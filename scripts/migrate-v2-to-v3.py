#!/usr/bin/env python3
"""Migrate JSM Wiki v2 pages to v3 schema.

Converts:
- category -> kind
- tags -> topics + subject (best effort)
- source_count -> source-types
- related -> prose relations section in body
- Subdirectory paths -> flat filenames
- Wikilink paths updated

Usage: python scripts/migrate-v2-to-v3.py [--dry-run]
"""

import re
import sys
import json
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Try to import obsidian client
try:
    from core.obsidian_api import ObsidianClient
    from core.config import WIKI_PATH, VAULT_FOLDER
    OBSIDIAN_AVAILABLE = True
except ImportError:
    OBSIDIAN_AVAILABLE = False
    print("Warning: Obsidian client not available. Running in dry-run-only mode.")

DRY_RUN = "--dry-run" in sys.argv or not OBSIDIAN_AVAILABLE

OLD_TO_KIND = {
    "entities": "entity",
    "concepts": "concept",
    "comparisons": "comparison",
    "synthesis": "concept",  # synthesis pages become concepts
    "sources": "source-record",
}

DOMAIN_TO_SUBJECT = {
    "study": ["study"],
    "fitness": ["fitness"],
    "economy": ["economy"],
    "general": ["general"],
}


def parse_old_frontmatter(text: str) -> tuple[dict, str]:
    """Parse v2 frontmatter (line-by-line flat format)."""
    fm_match = re.match(r'^---\n(.*?)\n---\n', text, re.DOTALL)
    if not fm_match:
        return {}, text
    body = text[fm_match.end():]
    fm = {}
    for line in fm_match.group(1).split("\n"):
        parts = line.split(":", 1)
        if len(parts) == 2:
            key = parts[0].strip()
            val = parts[1].strip()
            fm[key] = val
    return fm, body


def build_new_frontmatter(kind: str, form: str, topics: list, subject: list,
                          source_types: list, confidence: str, created: str, updated: str) -> str:
    """Build v3 YAML frontmatter."""
    lines = ["---"]
    lines.append(f"kind: {kind}")
    lines.append(f"form: {form}")
    lines.append(f"topics: [{', '.join(topics)}]" if topics else "topics: []")
    lines.append(f"subject: [{', '.join(subject)}]" if subject else "subject: []")
    lines.append(f"source-types: [{', '.join(source_types)}]" if source_types else "source-types: []")
    lines.append(f"domains: []")
    lines.append(f"confidence: {confidence}")
    lines.append(f"created: {created}")
    lines.append(f"updated: {updated}")
    lines.append("---")
    return "\n".join(lines)


def extract_filename(path: str) -> str:
    """Convert a subdirectory path to a flat filename."""
    # e.g. "entities/Transformer.md" -> "transformer.md"
    filename = path.split("/")[-1] if "/" in path else path
    # Convert underscores to hyphens
    filename = filename.replace("_", "-").replace(".md", ".md")
    return filename


def extract_tags_from_line(tags_line: str) -> list[str]:
    """Parse a tags line like '[tag1, tag2, tag3]' to list."""
    tags_line = tags_line.strip("[]").strip("'\"")
    if not tags_line:
        return []
    return [t.strip().strip("'\"") for t in tags_line.split(",") if t.strip()]


def extract_related_from_line(related_line: str) -> list[str]:
    """Parse a related line with [[links]]."""
    links = re.findall(r'\[\[([^\]]+)\]\]', related_line)
    return links


def migrate_page(path: str, raw_content: str) -> tuple[str, str]:
    """Migrate a single page. Returns (new_filename, new_content) or (None, None) if no change."""
    fm, body = parse_old_frontmatter(raw_content)
    if not fm:
        return (None, None)

    old_category = fm.get("category", "").strip().strip("'\"")
    tags_raw = fm.get("tags", "")
    related_raw = fm.get("related", "")
    confidence = fm.get("confidence", "medium").strip().strip("'\"")
    last_updated = fm.get("last_updated", datetime.now().strftime("%Y-%m-%d")).strip().strip("'\"")
    old_source_count = fm.get("source_count", "0").strip().strip("'\"")

    # Map category -> kind
    kind = OLD_TO_KIND.get(old_category, "concept")
    form = "prose"

    # Parse tags -> topics + subject
    all_tags = extract_tags_from_line(tags_raw)
    topics = []
    subject = []
    domains = set()

    domain_keywords = ["study", "fitness", "economy", "general"]
    for tag in all_tags:
        if tag in domain_keywords:
            domains.add(tag)
        else:
            topics.append(tag)

    # Map domains to subject paths
    for domain in domains:
        if domain in DOMAIN_TO_SUBJECT:
            subject.extend(DOMAIN_TO_SUBJECT[domain])
        else:
            subject.append("general")

    if not subject:
        subject = ["general"]

    # Map source_count -> source-types
    try:
        count = int(old_source_count)
    except ValueError:
        count = 0
    source_types = ["article"] if count > 0 else []

    # Parse related -> prose relations in body
    related_links = extract_related_from_line(related_raw)
    if related_links:
        prose_section = "\n\n## Relations\n"
        for link in related_links:
            # Convert old link path to flat filename
            flat_link = extract_filename(link).replace(".md", "")
            prose_section += f"builds on [[{flat_link}]]\n"
        body = body.rstrip() + prose_section

    # Fix wikilinks in body: convert subdirectory paths to flat
    def fix_wikilink(match):
        link = match.group(1)
        label = match.group(2) if len(match.groups()) > 1 and match.group(2) else ""
        flat = extract_filename(link).replace(".md", "")
        if label:
            return f"[[{flat}|{label}]]"
        return f"[[{flat}]]"

    body = re.sub(r'\[\[([^\]|#]+)\|([^\]]+)\]\]', fix_wikilink, body)
    body = re.sub(r'\[\[([^\]|#]+)\]\]', fix_wikilink, body)

    # Build new frontmatter
    today = datetime.now().strftime("%Y-%m-%d")
    new_fm = build_new_frontmatter(
        kind=kind,
        form=form,
        topics=topics,
        subject=subject if isinstance(subject, list) else [subject],
        source_types=source_types,
        confidence=confidence,
        created=last_updated,  # Use old last_updated as created (best guess)
        updated=today,
    )

    new_filename = extract_filename(path)
    new_content = new_fm + "\n" + body

    return (new_filename, new_content)


def main():
    global DRY_RUN
    print(f"JSM Wiki v2 -> v3 Migration")
    print(f"{'DRY RUN (no changes made)' if DRY_RUN else 'LIVE MIGRATION'}")
    print()

    if not OBSIDIAN_AVAILABLE:
        print("Cannot connect to Obsidian. Dry run only.")
        return

    obs = ObsidianClient()
    if not obs.check_connection():
        print("Obsidian not connected. Dry run only.")
        DRY_RUN = True

    # Scan old wiki directories
    old_dirs = ["entities", "concepts", "comparisons", "synthesis"]
    migrated = 0
    errors = 0
    skipped = 0

    for old_dir in old_dirs:
        dir_path = f"{WIKI_PATH}/{old_dir}"
        try:
            files = obs.list_notes(dir_path)
        except Exception:
            print(f"  Skipping {old_dir}/ (not found)")
            continue

        for fname in files:
            if not fname.endswith(".md"):
                continue
            old_path = f"{old_dir}/{fname}"
            try:
                raw = obs.read_note(f"{WIKI_PATH}/{old_path}")
            except Exception as e:
                print(f"  Error reading {old_path}: {e}")
                errors += 1
                continue

            new_filename, new_content = migrate_page(old_path, raw)
            if new_filename is None:
                skipped += 1
                continue

            new_path = f"{WIKI_PATH}/{new_filename}"

            if DRY_RUN:
                fm = parse_old_frontmatter(raw)[0]
                old_kind = fm.get("category", "?")
                new_kind = OLD_TO_KIND.get(old_kind, "concept")
                print(f"  {old_path} -> {new_filename}  [{old_kind} -> {new_kind}]")
                migrated += 1
            else:
                try:
                    obs.write_note(new_path, new_content)
                    print(f"  + {new_filename}")
                    migrated += 1
                except Exception as e:
                    print(f"  Error writing {new_filename}: {e}")
                    errors += 1

    print(f"\nMigrated: {migrated}, Errors: {errors}, Skipped: {skipped}")


if __name__ == "__main__":
    main()
