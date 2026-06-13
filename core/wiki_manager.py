"""Wiki Manager - Core wiki CRUD operations with index and log management.

Manages the persistent, structured wiki in the Obsidian vault.
v3: Flat directory, 5+1 frontmatter model, prose relations.
"""
import re
import json
import yaml
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from core.config import (
    WIKI_PATH, SOURCES_PATH, DAILY_LOG_PATH, DECISIONS_PATH, VAULT_FOLDER,
    ONTOLOGY_PATH, RAW_PATH, SUBJECT_TREE_FILE, TOPICS_FILE,
    MANIFEST_FILE, DEPENDENCIES_FILE,
)

VALID_KINDS = {"concept", "entity", "source-record", "project", "decision", "insight", "comparison"}
VALID_FORMS = {"prose", "index"}
VALID_SOURCE_TYPES = {"course", "conversation", "paper", "article", "docs", "book", "video", "podcast", "external"}
VALID_CONFIDENCES = {"high", "medium", "low"}


@dataclass
class WikiPage:
    path: str
    title: str
    kind: str                  # concept, entity, source-record, project, decision, insight, comparison
    form: str = "prose"        # prose, index
    topics: list[str] = field(default_factory=list)
    subject: list[str] = field(default_factory=list)
    source_types: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    confidence: str = "medium"
    created: str = ""
    updated: str = ""


class WikiManager:
    def __init__(self, obsidian_client):
        self.obs = obsidian_client

    @staticmethod
    def _today() -> str:
        return datetime.now().astimezone().strftime("%Y-%m-%d")

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().strftime("%H:%M")

    # --- Vault Initialization ---

    def init_vault(self) -> list[str]:
        """Create the wiki directory structure in the vault. Returns list of created paths."""
        created = []
        dirs = [
            SOURCES_PATH,
            f"{SOURCES_PATH}/papers",
            f"{SOURCES_PATH}/articles",
            f"{SOURCES_PATH}/books",
            f"{SOURCES_PATH}/videos",
            f"{SOURCES_PATH}/podcasts",
            WIKI_PATH,
            f"{WIKI_PATH}/lint_reports",
            DAILY_LOG_PATH,
            DECISIONS_PATH,
        ]
        for d in dirs:
            if not self.obs.note_exists(f"{d}/.exists"):
                self.obs.write_note(f"{d}/.exists", "")
                created.append(d)

        if not self.obs.note_exists(f"{WIKI_PATH}/index.md"):
            self._create_index()
            created.append(f"{WIKI_PATH}/index.md")

        if not self.obs.note_exists(f"{WIKI_PATH}/log.md"):
            self._create_log()
            created.append(f"{WIKI_PATH}/log.md")

        if not self.obs.note_exists(f"{WIKI_PATH}/_stubs.md"):
            self.obs.write_note(f"{WIKI_PATH}/_stubs.md", "# Proposed Pages\n\n<!-- Auto-generated graph gap proposals -->\n")
            created.append(f"{WIKI_PATH}/_stubs.md")

        return created

    def _create_index(self) -> None:
        content = f"""---
kind: concept
form: index
topics: [wiki, index, navigation]
subject: [general/tools]
source-types: []
domains: [general]
confidence: high
created: {self._today()}
updated: {self._today()}
---

# Wiki Index

Curated entry points for the wiki. Not an exhaustive list -- full page catalog is in `ontology/wiki-manifest.json`.

"""
        self.obs.write_note(f"{WIKI_PATH}/index.md", content)

    def _create_log(self) -> None:
        content = f"""---
kind: entity
form: prose
topics: [wiki, log]
subject: [general/tools]
source-types: []
domains: [general]
confidence: high
created: {self._today()}
updated: {self._today()}
---

# Wiki Activity Log

## [{self._today()} {self._now()}] system | Wiki initialized (v3)
"""
        self.obs.write_note(f"{WIKI_PATH}/log.md", content)

    # --- Index Management ---

    def read_index(self) -> str:
        try:
            raw = self.obs.read_note(f"{WIKI_PATH}/index.md")
            fm, body = self._parse_frontmatter(raw)
            return body
        except Exception:
            return ""

    def update_index_entry(self, kind: str, title: str, page_path: str,
                           summary: str = "") -> bool:
        """Add or update an entry in the index under a kind-based domain section."""
        try:
            fm, body = self._parse_frontmatter(self.obs.read_note(f"{WIKI_PATH}/index.md"))
        except Exception:
            body = ""

        entry_line = f"- [[{page_path}|{title}]] — {summary}" if summary else f"- [[{page_path}|{title}]]"

        # Find or create section by kind
        section_header = f"## {kind.replace('-', ' ').title()}"
        section_pattern = re.compile(
            rf"({re.escape(section_header)}\n)(.*?)(?=\n## |\Z)", re.DOTALL
        )

        match = section_pattern.search(body)
        if not match:
            body += f"\n{section_header}\n{entry_line}\n"
        else:
            section_start = match.group(1)
            section_body = match.group(2)
            existing_pattern = re.compile(rf"- \[\[{re.escape(page_path)}\|.*?\]\].*?\n")
            if existing_pattern.search(section_body):
                section_body = existing_pattern.sub(entry_line + "\n", section_body)
            else:
                section_body += f"{entry_line}\n"
            body = body.replace(match.group(0), section_start + section_body)

        # Rebuild full file with frontmatter
        fm["updated"] = self._today()
        fm_str = self._build_frontmatter(fm)
        self.obs.write_note(f"{WIKI_PATH}/index.md", fm_str + "\n" + body)
        return True

    # --- Log Management ---

    def append_log(self, entry_type: str, title: str, summary: str = "") -> bool:
        """Append a log entry with a parsable prefix."""
        summary_suffix = f" -- {summary}" if summary else ""
        entry = f"\n## [{self._today()} {self._now()}] {entry_type} | {title}{summary_suffix}\n"
        return self.obs.append_note(f"{WIKI_PATH}/log.md", entry)

    def read_log(self, lines: int = 20) -> str:
        try:
            _, body = self._parse_frontmatter(self.obs.read_note(f"{WIKI_PATH}/log.md"))
            log_lines = body.split("\n")
            return "\n".join(log_lines[-lines:])
        except Exception:
            return ""

    # --- Page CRUD ---

    def create_page(self, path: str, title: str, content: str,
                    kind: str = "concept", form: str = "prose",
                    topics: list[str] = None,
                    subject: list[str] = None,
                    source_types: list[str] = None,
                    domains: list[str] = None,
                    confidence: str = "medium",
                    created: str = None) -> bool:
        """Create a new wiki page with v3 frontmatter."""
        # Normalize path: just the filename for flat directory
        filename = path.replace(".md", "") + ".md" if not path.endswith(".md") else path
        # Strip any subdirectory prefix (support both old "entities/X.md" and new "X.md")
        filename = filename.split("/")[-1]
        full_path = f"{WIKI_PATH}/{filename}"

        topics = topics or []
        subject = subject or []
        source_types = source_types or []
        domains_val = domains or []
        created_str = created or self._today()
        today = self._today()

        # Validate values
        if kind not in VALID_KINDS:
            kind = "concept"
        if form not in VALID_FORMS:
            form = "prose"
        if confidence not in VALID_CONFIDENCES:
            confidence = "medium"
        source_types = [st for st in source_types if st in VALID_SOURCE_TYPES]

        doc = self._build_frontmatter({
            "kind": kind,
            "form": form,
            "topics": topics,
            "subject": subject,
            "source-types": source_types,
            "domains": domains_val,
            "confidence": confidence,
            "created": created_str,
            "updated": today,
        })
        doc += f"\n# {title}\n\n{content}\n"

        success = self.obs.write_note(full_path, doc)
        if success:
            self.update_index_entry(kind, title, filename, content[:80])
            self.append_log("create", title)
        return success

    def read_page(self, path: str) -> dict:
        """Read a wiki page. Returns dict with 'frontmatter', 'body', and 'raw'."""
        # Normalize path
        path = path.split("/")[-1] if "/" in path else path
        full_path = f"{WIKI_PATH}/{path}" if not path.startswith(VAULT_FOLDER) else path
        content = self.obs.read_note(full_path)
        fm, body = self._parse_frontmatter(content)
        return {"frontmatter": fm, "body": body, "raw": content}

    def _parse_frontmatter(self, content: str) -> tuple[dict, str]:
        """Parse YAML frontmatter from content. Returns (frontmatter_dict, body)."""
        fm_match = re.match(r'^---\n(.*?)\n---\n', content, re.DOTALL)
        if not fm_match:
            return {}, content
        body = content[fm_match.end():]
        try:
            fm = yaml.safe_load(fm_match.group(1)) or {}
        except yaml.YAMLError:
            # Fallback: line-by-line parse for malformed YAML
            fm = {}
            for line in fm_match.group(1).split("\n"):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip()
                    fm[key] = val
        return fm, body

    def _build_frontmatter(self, fm: dict) -> str:
        """Build YAML frontmatter string from a dict."""
        # Use yaml.dump for valid YAML output
        yaml_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False)
        return f"---\n{yaml_str.strip()}\n---"

    def update_page(self, path: str, new_body: str) -> bool:
        """Update the body of an existing wiki page, updating frontmatter updated date."""
        path = path.split("/")[-1] if "/" in path else path
        full_path = f"{WIKI_PATH}/{path}" if not path.startswith(VAULT_FOLDER) else path
        try:
            existing = self.read_page(path)
        except Exception:
            return False

        fm = existing.get("frontmatter", {})
        fm["updated"] = self._today()

        doc = self._build_frontmatter(fm)
        doc += f"\n{new_body}\n"
        return self.obs.write_note(full_path, doc)

    def list_pages(self) -> list[str]:
        """List all wiki page paths in the flat directory. Excludes meta pages."""
        try:
            files = self.obs.list_notes(WIKI_PATH)
            meta = {"index.md", "log.md", "_stubs.md", "lint_reports"}
            return [f for f in files if f.endswith(".md") and f not in meta]
        except Exception:
            return []

    def get_backlinks(self, page_path: str) -> list[str]:
        """Find pages that link to the given page. Searches for [[slug]] references."""
        slug = page_path.split("/")[-1].replace(".md", "")
        patterns = [
            f"[[{slug}]]",
            f"[[{slug}|",
        ]
        try:
            results = []
            for pat in patterns:
                found = self.obs.search_notes(pat)
                results.extend(r for r in found if r.get("path") != page_path)
            # Deduplicate by path
            seen = set()
            unique = []
            for r in results:
                p = r.get("path", "")
                if p not in seen:
                    seen.add(p)
                    unique.append(p)
            return unique
        except Exception:
            return []

    def find_orphans(self) -> list[str]:
        """Find pages with no inbound links."""
        all_pages = self.list_pages()
        orphans = []
        for page in all_pages:
            backlinks = self.get_backlinks(page)
            if len(backlinks) <= 1:
                orphans.append(page)
        return orphans

    def page_exists(self, path: str) -> bool:
        """Check if a wiki page exists."""
        path = path.split("/")[-1] if "/" in path else path
        full_path = f"{WIKI_PATH}/{path}"
        return self.obs.note_exists(full_path)
