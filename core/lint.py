"""Lint Engine - Wiki health check.

v3: Schema validation, domains cache, prose relations, manifest/dependencies generation.
Scans all wiki pages for mechanical and qualitative issues.
"""
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from core.config import (
    MODEL_FAST, MODEL_PRO, WIKI_PATH, MANIFEST_FILE, DEPENDENCIES_FILE,
    SUBJECT_TREE_FILE, TOPICS_FILE,
)

VALID_KINDS = {"concept", "entity", "source-record", "project", "decision", "insight", "comparison"}
VALID_FORMS = {"prose", "index"}
VALID_SOURCE_TYPES = {"course", "conversation", "paper", "article", "docs", "book", "video", "podcast", "external"}
VALID_CONFIDENCES = {"high", "medium", "low"}


@dataclass
class LintIssue:
    category: str        # contradiction, stale, orphan, missing_concept,
                         # missing_crossref, data_gap, schema_validation,
                         # domains_cache, prose_relation, topic_vocabulary,
                         # subject_path, binary_creep
    severity: str        # critical, warning, info
    description: str
    pages: list[str] = field(default_factory=list)
    suggestion: str = ""


@dataclass
class LintReport:
    timestamp: str
    total_pages: int
    issues: list[LintIssue] = field(default_factory=list)
    summary: str = ""

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "critical")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    @property
    def info_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "info")


class LintEngine:
    """Scans the wiki and reports health issues. v3: extended checks."""

    def __init__(self, llm_client, wiki_manager, obsidian_client):
        self.llm = llm_client
        self.wiki = wiki_manager
        self.obs = obsidian_client

    def run_full_check(self) -> LintReport:
        """Run all lint checks and return a structured report."""
        today = datetime.now().astimezone().strftime("%Y-%m-%d")
        report = LintReport(timestamp=today, total_pages=0)

        all_pages = self.wiki.list_pages()
        report.total_pages = len(all_pages)

        if not all_pages:
            report.summary = "No wiki pages found."
            return report

        page_data = {}
        for path in all_pages:
            try:
                data = self.wiki.read_page(path)
                page_data[path] = data
            except Exception:
                continue

        report.issues = []

        # Mechanical checks
        report.issues.extend(self._check_schema_validation(page_data))
        report.issues.extend(self._check_domains_cache(page_data))
        report.issues.extend(self._check_subject_paths(page_data))
        report.issues.extend(self._check_topic_vocabulary(page_data))
        report.issues.extend(self._check_staleness(page_data))
        report.issues.extend(self._check_orphans(all_pages))

        # Generate manifest and dependencies
        self._generate_manifest(page_data)
        self._generate_dependencies(page_data)

        # LLM-based checks
        if len(page_data) >= 2:
            try:
                report.issues.extend(self._llm_contradiction_check(page_data, all_pages))
            except Exception:
                report.issues.append(LintIssue(
                    category="system", severity="warning",
                    description="LLM contradiction check failed",
                ))
            try:
                report.issues.extend(self._llm_missing_check(page_data, all_pages))
            except Exception:
                pass

        severity_order = {"critical": 0, "warning": 1, "info": 2}
        report.issues.sort(key=lambda i: severity_order.get(i.severity, 3))

        report.summary = (
            f"{report.total_pages} pages scanned. "
            f"{report.critical_count} critical, "
            f"{report.warning_count} warnings, "
            f"{report.info_count} info."
        )
        return report

    def _check_schema_validation(self, page_data: dict) -> list[LintIssue]:
        """Validate frontmatter fields have valid values."""
        issues = []
        for path, data in page_data.items():
            fm = data.get("frontmatter", {})

            kind = fm.get("kind", "")
            if kind and kind not in VALID_KINDS:
                issues.append(LintIssue(
                    category="schema_validation", severity="critical",
                    description=f"Invalid kind '{kind}'. Valid: {', '.join(sorted(VALID_KINDS))}",
                    pages=[path], suggestion=f"Set kind to one of the valid values.",
                ))

            form = fm.get("form", "")
            if form and form not in VALID_FORMS:
                issues.append(LintIssue(
                    category="schema_validation", severity="critical",
                    description=f"Invalid form '{form}'. Valid: {', '.join(sorted(VALID_FORMS))}",
                    pages=[path],
                ))

            source_types = fm.get("source-types", [])
            if isinstance(source_types, str):
                source_types = [source_types]
            for st in source_types:
                if st and st not in VALID_SOURCE_TYPES:
                    issues.append(LintIssue(
                        category="schema_validation", severity="warning",
                        description=f"Invalid source-type '{st}'",
                        pages=[path],
                    ))

            confidence = fm.get("confidence", "")
            if confidence and confidence not in VALID_CONFIDENCES:
                issues.append(LintIssue(
                    category="schema_validation", severity="warning",
                    description=f"Invalid confidence '{confidence}'",
                    pages=[path],
                ))

        return issues

    def _check_domains_cache(self, page_data: dict) -> list[LintIssue]:
        """Verify domains field matches subject's top-level."""
        issues = []
        for path, data in page_data.items():
            fm = data.get("frontmatter", {})
            subject = fm.get("subject", [])
            if isinstance(subject, str):
                subject = [subject]
            expected_domains = []
            for s in subject:
                parts = s.split("/")
                if parts:
                    expected_domains.append(parts[0])
            expected_domains = list(set(expected_domains))

            domains = fm.get("domains", [])
            if isinstance(domains, str):
                domains = [domains]

            if set(domains) != set(expected_domains) and expected_domains:
                issues.append(LintIssue(
                    category="domains_cache", severity="warning",
                    description=f"domains mismatch. Expected {expected_domains}, got {domains}",
                    pages=[path],
                    suggestion="Lint will auto-fix on next run. Do not edit domains manually.",
                ))

        return issues

    def _check_subject_paths(self, page_data: dict) -> list[LintIssue]:
        """Verify subject paths exist in the subject tree."""
        issues = []
        try:
            tree_content = SUBJECT_TREE_FILE.read_text(encoding="utf-8") if SUBJECT_TREE_FILE.exists() else ""
        except Exception:
            tree_content = ""

        valid_paths = set()
        for line in tree_content.split("\n"):
            path = line.strip().rstrip("/")
            if path and not path.startswith("#") and "/" in path:
                valid_paths.add(path)

        for path, data in page_data.items():
            fm = data.get("frontmatter", {})
            subject = fm.get("subject", [])
            if isinstance(subject, str):
                subject = [subject]
            for s in subject:
                if s and s not in valid_paths and valid_paths:
                    issues.append(LintIssue(
                        category="subject_path", severity="warning",
                        description=f"Subject path '{s}' not found in subject-tree.md",
                        pages=[path],
                        suggestion="Add the path to ontology/subject-tree.md or fix the subject.",
                    ))

        return issues

    def _check_topic_vocabulary(self, page_data: dict) -> list[LintIssue]:
        """Warn on unfamiliar topics."""
        try:
            topics_content = TOPICS_FILE.read_text(encoding="utf-8") if TOPICS_FILE.exists() else ""
        except Exception:
            topics_content = ""

        known_topics = set()
        for line in topics_content.split("\n"):
            line = line.strip()
            if line.startswith("- ") and not line.startswith("- #"):
                topic = line[2:].strip()
                known_topics.add(topic)

        # Also collect from aliases
        alias_section = False
        for line in topics_content.split("\n"):
            if "## Aliases" in line:
                alias_section = True
                continue
            if alias_section and ": " in line:
                known_topics.add(line.split(":")[0].strip())

        issues = []
        for path, data in page_data.items():
            fm = data.get("frontmatter", {})
            topics = fm.get("topics", [])
            if isinstance(topics, str):
                topics = [topics]
            for topic in topics:
                if topic and topic not in known_topics and known_topics:
                    issues.append(LintIssue(
                        category="topic_vocabulary", severity="info",
                        description=f"Unfamiliar topic '{topic}'. Topics vocabulary is allowed to grow.",
                        pages=[path],
                    ))

        return issues

    def _check_staleness(self, page_data: dict) -> list[LintIssue]:
        """Detect pages not updated in 90+ days. Skips index pages."""
        from datetime import date as date_type
        issues = []
        cutoff_date = (datetime.now().astimezone() - timedelta(days=90)).date()

        for path, data in page_data.items():
            fm = data.get("frontmatter", {})
            form = fm.get("form", "")
            if form == "index":
                continue
            updated = fm.get("updated", fm.get("last_updated", None))
            if updated is None:
                continue
            # YAML may parse dates as datetime.date objects
            updated_date = updated if isinstance(updated, date_type) else None
            if updated_date is None:
                try:
                    updated_date = datetime.strptime(str(updated)[:10], "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    continue
            if updated_date < cutoff_date:
                issues.append(LintIssue(
                    category="stale", severity="warning",
                    description=f"Page last updated {updated_date} (>90 days ago)",
                    pages=[path],
                    suggestion="Consider updating with new sources.",
                ))
        return issues

    def _check_orphans(self, all_pages: list[str]) -> list[LintIssue]:
        """Detect pages with no inbound links."""
        issues = []
        try:
            orphans = self.wiki.find_orphans()
            if orphans:
                issues.append(LintIssue(
                    category="orphan", severity="info",
                    description=f"{len(orphans)} pages have no inbound links",
                    pages=orphans,
                    suggestion="Add cross-references from related pages.",
                ))
        except Exception:
            pass
        return issues

    def _generate_manifest(self, page_data: dict):
        """Generate and save wiki manifest JSON."""
        from datetime import date as date_type
        def _str(val):
            if isinstance(val, (date_type, datetime)):
                return val.strftime("%Y-%m-%d") if isinstance(val, date_type) and not isinstance(val, datetime) else val.strftime("%Y-%m-%d")
            return str(val) if val else ""

        manifest = {
            "generated": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
            "description": "Auto-generated page manifest.",
            "pages": []
        }
        for path, data in page_data.items():
            fm = data.get("frontmatter", {})
            topics = fm.get("topics", [])
            if isinstance(topics, str):
                topics = [topics]
            subject = fm.get("subject", [])
            if isinstance(subject, str):
                subject = [subject]
            domains = fm.get("domains", [])
            if isinstance(domains, str):
                domains = [domains]
            entry = {
                "path": path,
                "kind": fm.get("kind", ""),
                "form": fm.get("form", ""),
                "topics": topics,
                "subject": subject,
                "domains": domains,
                "confidence": fm.get("confidence", ""),
                "created": _str(fm.get("created", "")),
                "updated": _str(fm.get("updated", fm.get("last_updated", ""))),
            }
            manifest["pages"].append(entry)

        MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

    def _generate_dependencies(self, page_data: dict):
        """Generate and save wiki dependencies (wikilinks + prose relations)."""
        deps = {
            "generated": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
            "description": "Auto-generated wikilink and prose relation map.",
            "relations": []
        }
        for path, data in page_data.items():
            body = data.get("body", "")
            # Extract wikilinks
            wikilinks = re.findall(r'\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]', body)
            # Extract prose relations
            prose_patterns = [
                (r'builds on \[\[([^\]]+)\]\]', 'builds_on'),
                (r'contradicts \[\[([^\]]+)\]\]', 'contradicts'),
                (r'instance of \[\[([^\]]+)\]\]', 'instance_of'),
                (r'applies to \[\[([^\]]+)\]\]', 'applies_to'),
                (r'decided \[\[([^\]]+)\]\] over \[\[([^\]]+)\]\]', 'decided_over'),
                (r'failed when \[\[([^\]]+)\]\]', 'failed_when'),
                (r'trade-off: \[\[([^\]]+)\]\] vs \[\[([^\]]+)\]\]', 'tradeoff'),
            ]
            for pattern, rel_type in prose_patterns:
                for match in re.finditer(pattern, body):
                    targets = match.groups()
                    deps["relations"].append({
                        "from": path,
                        "to": list(targets),
                        "type": rel_type,
                    })

        DEPENDENCIES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(DEPENDENCIES_FILE, "w", encoding="utf-8") as f:
            json.dump(deps, f, ensure_ascii=False, indent=2)

    def _llm_contradiction_check(self, page_data: dict, all_pages: list[str]) -> list[LintIssue]:
        """Use LLM to detect contradictions between pages."""
        page_summaries = []
        for path in all_pages[:20]:
            data = page_data.get(path, {})
            fm = data.get("frontmatter", {})
            body = data.get("body", "")[:500]
            page_summaries.append(
                f"[[{path}]] (kind={fm.get('kind', '?')}, "
                f"confidence={fm.get('confidence', '?')})\n{body}\n"
            )

        if len(page_summaries) < 2:
            return []

        prompt = f"""Review these wiki pages for contradictions.

Pages:
{chr(10).join(page_summaries[:10])}

Respond in JSON only:
{{"contradictions": [{{"description": "Korean description", "pages": ["page1.md", "page2.md"], "suggestion": "Korean suggestion"}}]}}
If no contradictions: {{"contradictions": []}}"""
        try:
            result = self.llm.chat_sync(
                messages=[{"role": "user", "content": prompt}],
                model=MODEL_PRO, temperature=0.0, max_tokens=1500,
            )
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            data = json.loads(json_match.group() if json_match else result)
        except Exception:
            return []

        issues = []
        for c in data.get("contradictions", []):
            issues.append(LintIssue(
                category="contradiction", severity="critical",
                description=c.get("description", ""),
                pages=c.get("pages", []),
                suggestion=c.get("suggestion", "Resolve the inconsistency."),
            ))
        return issues

    def _llm_missing_check(self, page_data: dict, all_pages: list[str]) -> list[LintIssue]:
        """Use LLM to detect missing concepts and cross-references."""
        page_summaries = []
        for path in all_pages[:15]:
            data = page_data.get(path, {})
            fm = data.get("frontmatter", {})
            page_summaries.append(
                f"[[{path}]] - title={body.split(chr(10))[0].replace('# ','') if (body := data.get('body','')) else '?'} ({fm.get('topics', '')})"
            )

        prompt = f"""Review this wiki for:
1. Missing concept pages
2. Missing cross-references
3. Data gaps

Existing pages:
{chr(10).join(page_summaries[:15])}

Respond in JSON only:
{{"missing_concepts": [{{"description": "...", "mentioned_in": ["p1.md"], "suggestion": "..."}}],
 "missing_crossrefs": [{{"description": "...", "pages": ["p1.md", "p2.md"], "suggestion": "..."}}],
 "data_gaps": [{{"description": "...", "page": "p.md", "suggestion": "..."}}]}}"""
        try:
            result = self.llm.chat_sync(
                messages=[{"role": "user", "content": prompt}],
                model=MODEL_FAST, temperature=0.0, max_tokens=1500,
            )
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            data = json.loads(json_match.group() if json_match else result)
        except Exception:
            return []

        issues = []
        for mc in data.get("missing_concepts", []):
            issues.append(LintIssue(
                category="missing_concept", severity="info",
                description=mc.get("description", ""),
                pages=mc.get("mentioned_in", []),
                suggestion=mc.get("suggestion", ""),
            ))
        for mc in data.get("missing_crossrefs", []):
            issues.append(LintIssue(
                category="missing_crossref", severity="warning",
                description=mc.get("description", ""),
                pages=mc.get("pages", []),
                suggestion=mc.get("suggestion", ""),
            ))
        for dg in data.get("data_gaps", []):
            issues.append(LintIssue(
                category="data_gap", severity="info",
                description=dg.get("description", ""),
                pages=[dg.get("page", "")],
                suggestion=dg.get("suggestion", ""),
            ))
        return issues

    def save_report(self, report: LintReport) -> str:
        """Save lint report to 2_Wiki/lint_reports/. Returns the path."""
        report_path = f"lint_reports/{report.timestamp}_lint.md"

        lines = [f"# Wiki Lint Report -- {report.timestamp}",
                 f"",
                 f"**{report.total_pages}** pages scanned.",
                 f"**{report.critical_count}** critical, "
                 f"**{report.warning_count}** warnings, "
                 f"**{report.info_count}** info.",
                 f""]

        for issue in report.issues:
            icon = {"critical": "x", "warning": "!", "info": "i"}.get(issue.severity, "?")
            lines.append(f"## [{icon}] {issue.category}")
            lines.append(f"- **Severity**: {issue.severity}")
            lines.append(f"- **Description**: {issue.description}")
            if issue.pages:
                pages_str = ", ".join(f"[[{p}]]" for p in issue.pages)
                lines.append(f"- **Pages**: {pages_str}")
            if issue.suggestion:
                lines.append(f"- **Suggestion**: {issue.suggestion}")
            lines.append("")

        content = "\n".join(lines)
        self.obs.write_note(f"{WIKI_PATH}/{report_path}", content)
        self.wiki.append_log("lint", report.timestamp, report.summary)
        return report_path
