"""Cross-reference Manager - Wiki link analysis and maintenance.

v3: Prose relation patterns + flat directory support.
Finds broken links, validates prose relations, suggests cross-references,
and provides graph statistics for the wiki.
"""
import re
import json
from core.config import MODEL_FAST, WIKI_PATH


# Prose relation patterns — recognized phrases that contain wikilinks
PROSE_RELATION_PATTERNS = [
    (r'builds on \[\[([^\]]+)\]\]', 'builds_on'),
    (r'contradicts \[\[([^\]]+)\]\]', 'contradicts'),
    (r'instance of \[\[([^\]]+)\]\]', 'instance_of'),
    (r'applies to \[\[([^\]]+)\]\]', 'applies_to'),
    (r'decided \[\[([^\]]+)\]\] over \[\[([^\]]+)\]\]', 'decided_over'),
    (r'failed when \[\[([^\]]+)\]\]', 'failed_when'),
    (r'trade-off: \[\[([^\]]+)\]\] vs \[\[([^\]]+)\]\]', 'tradeoff'),
]

# Pattern to find any wikilink
WIKILINK_PATTERN = re.compile(r'\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]')


class CrossrefManager:
    """Manages wiki cross-references. v3: prose relations + flat directory."""

    def __init__(self, wiki_manager, obsidian_client):
        self.wiki = wiki_manager
        self.obs = obsidian_client

    def extract_links(self, text: str) -> list[str]:
        """Extract all wikilink targets from text."""
        return WIKILINK_PATTERN.findall(text)

    def extract_prose_relations(self, text: str) -> list[dict]:
        """Extract structured prose relations from text.

        Returns list of {type, source, target} dicts.
        """
        relations = []
        for pattern, rel_type in PROSE_RELATION_PATTERNS:
            for match in re.finditer(pattern, text):
                if rel_type in ('decided_over', 'tradeoff'):
                    # These have two targets
                    rel = {
                        'type': rel_type,
                        'targets': list(match.groups()),
                    }
                else:
                    rel = {
                        'type': rel_type,
                        'target': match.group(1),
                    }
                relations.append(rel)
        return relations

    def find_broken_links(self, page_path: str = None) -> dict[str, list[str]]:
        """Find [[links]] that point to non-existent pages.

        If page_path is None, scans all wiki pages.
        Returns {page_path: [broken_link1, broken_link2]} dict.
        """
        broken = {}

        if page_path:
            pages_to_check = [page_path]
        else:
            pages_to_check = self.wiki.list_pages()

        for page in pages_to_check:
            try:
                data = self.wiki.read_page(page)
            except Exception:
                continue

            body = data.get("body", "")
            links = self.extract_links(body)
            broken_for_page = []

            for link in links:
                if not self._page_exists(link):
                    broken_for_page.append(link)

            if broken_for_page:
                broken[page] = broken_for_page

        return broken

    def find_broken_prose_links(self, page_path: str = None) -> dict[str, list[dict]]:
        """Check prose relations for broken wikilinks.

        Returns {page_path: [{type, target, broken}]} dict.
        """
        broken = {}

        if page_path:
            pages_to_check = [page_path]
        else:
            pages_to_check = self.wiki.list_pages()

        for page in pages_to_check:
            try:
                data = self.wiki.read_page(page)
            except Exception:
                continue

            body = data.get("body", "")
            relations = self.extract_prose_relations(body)
            broken_rels = []

            for rel in relations:
                targets = rel.get('targets', [rel.get('target', '')])
                for target in targets:
                    if target and not self._page_exists(target):
                        broken_rels.append({
                            'type': rel['type'],
                            'target': target,
                            'broken': True,
                        })

            if broken_rels:
                broken[page] = broken_rels

        return broken

    def _page_exists(self, page_slug: str) -> bool:
        """Check if a wiki page exists in the flat directory."""
        slug = page_slug.replace(".md", "")
        # Try exact match in flat directory
        if self.wiki.page_exists(slug):
            return True
        if self.wiki.page_exists(f"{slug}.md"):
            return True
        return False

    def suggest_links(self, page_path: str, top_k: int = 5) -> list[str]:
        """Suggest pages that should be linked from the given page.

        Uses keyword overlap in titles and content.
        """
        try:
            data = self.wiki.read_page(page_path)
        except Exception:
            return []

        body = data.get("body", "")
        fm = data.get("frontmatter", {})
        title = body.split("\n")[0].replace("# ", "") if body else ""

        # Extract keywords from the page
        words = set(re.findall(r'[가-힣a-zA-Z0-9_]+', title + " " + body[:1000]))
        words = {w for w in words if len(w) > 2}

        # Search for pages with similar keywords
        suggestions = set()
        all_pages = self.wiki.list_pages()
        for p in all_pages:
            if p == page_path:
                continue
            try:
                other = self.wiki.read_page(p)
                other_body = other.get("body", "")
                other_fm = other.get("frontmatter", {})
                other_text = str(other_fm.get("topics", "")) + " " + other_body[:500]
                overlap = sum(1 for w in words if w in other_text)
                if overlap >= 2:
                    suggestions.add(p)
            except Exception:
                continue

        return list(suggestions)[:top_k]

    def suggest_prose_relations(self, page_path: str) -> list[str]:
        """Suggest prose relation lines for a page."""
        suggestions = []
        all_pages = self.wiki.list_pages()
        fm = {}
        try:
            data = self.wiki.read_page(page_path)
            fm = data.get("frontmatter", {})
        except Exception:
            pass

        kind = fm.get("kind", "")
        subject = fm.get("subject", [])

        for p in all_pages:
            if p == page_path:
                continue
            try:
                other = self.wiki.read_page(p)
                other_fm = other.get("frontmatter", {})
                other_kind = other_fm.get("kind", "")
                other_subject = other_fm.get("subject", [])

                # Same subject => builds on or instance of
                if any(s in other_subject for s in subject):
                    if other_kind == "concept" and kind == "concept":
                        suggestions.append(f"builds on [[{p}]]")
                    elif other_kind == "concept" and kind != "concept":
                        suggestions.append(f"instance of [[{p}]]")
                    elif other_kind == "project" and kind != "project":
                        suggestions.append(f"applies to [[{p}]]")
            except Exception:
                continue

        return suggestions[:5]

    def get_graph_stats(self) -> dict:
        """Get basic wiki graph statistics (v3: flat directory)."""
        all_pages = self.wiki.list_pages()
        total_wikilinks = 0
        total_prose_rels = 0
        pages_with_links = 0

        for page in all_pages:
            try:
                data = self.wiki.read_page(page)
                body = data.get("body", "")
                links = self.extract_links(body)
                rels = self.extract_prose_relations(body)
                if links or rels:
                    pages_with_links += 1
                    total_wikilinks += len(links)
                    total_prose_rels += len(rels)
            except Exception:
                continue

        return {
            "total_pages": len(all_pages),
            "total_wikilinks": total_wikilinks,
            "total_prose_relations": total_prose_rels,
            "pages_with_links": pages_with_links,
            "pages_without_links": len(all_pages) - pages_with_links,
            "orphans": len(self.wiki.find_orphans()) if all_pages else 0,
        }

    def validate_all_links(self) -> dict[str, list[str]]:
        """Validate all cross-references across the entire wiki."""
        return self.find_broken_links()

    def fix_wiki_link(self, text: str, page_title: str,
                       target_path: str) -> str:
        """Convert a plain page title into a proper [[wiki-link]].

        e.g. fix_wiki_link("See Attention Mechanism", "Attention Mechanism",
                           "attention-mechanism")
        -> "See [[attention-mechanism|Attention Mechanism]]"
        """
        return text.replace(
            page_title,
            f"[[{target_path}|{page_title}]]",
        )
