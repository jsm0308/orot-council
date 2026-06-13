"""Ingest Pipeline - Source document ingestion into the Wiki.

Reads a source (PDF/markdown/word/etc), extracts key knowledge via LLM,
discusses with user, and creates/updates wiki pages.
v3: 5+1 frontmatter model, prose relations, flat directory.
"""
import json
import re
from dataclasses import dataclass, field
from datetime import datetime

from core.config import MODEL_FAST, MODEL_PRO, WIKI_PATH, VAULT_FOLDER


@dataclass
class IngestReport:
    source_path: str
    source_title: str
    summary_page: str = ""
    updated_pages: list[str] = field(default_factory=list)
    new_pages: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    total_touched: int = 0
    errors: list[str] = field(default_factory=list)


class IngestPipeline:
    """Process a source document into wiki pages."""

    def __init__(self, llm_client, wiki_manager, obsidian_client, converter):
        self.llm = llm_client
        self.wiki = wiki_manager
        self.obs = obsidian_client
        self.converter = converter

    def extract_and_discuss(self, source_path: str) -> dict:
        """Phase 1 of ingest: read, extract, return summary for user discussion.

        Returns dict with 'report', 'takeaways', 'content', 'source_title'.
        """
        report = IngestReport(source_path=source_path)

        try:
            content = self.converter.read_text(source_path)
            info = self.converter.file_info(source_path)
        except Exception as e:
            report.errors.append(str(e))
            return {"report": report, "takeaways": None, "content": "", "source_title": source_path}

        if len(content) > 30000:
            content = content[:30000] + "\n\n[...truncated...]"

        takeaways = self._extract_takeaways(content, source_path)
        if not takeaways:
            report.errors.append("LLM failed to extract takeaways")
            return {"report": report, "takeaways": None, "content": content, "source_title": source_path}

        report.source_title = takeaways.get("title", source_path)
        return {
            "report": report,
            "takeaways": takeaways,
            "content": content,
            "source_title": takeaways.get("title", source_path),
        }

    def execute_ingest(self, report: IngestReport, takeaways: dict,
                       content: str, user_emphasis: str = "") -> IngestReport:
        """Phase 2 of ingest: create wiki pages based on extracted knowledge."""
        title = report.source_title

        existing_context = self._gather_wiki_context(title, takeaways)

        print(f"  Planning wiki updates...")
        page_plan = self._plan_pages(takeaways, content, existing_context, user_emphasis)
        if not page_plan:
            report.errors.append("LLM failed to plan pages")
            return report

        created = []
        updated = []

        # Create source-record page
        try:
            source_content = self._build_source_summary(takeaways, content)
            safe_name = re.sub(r'[\\/:*?"<>|\s]+', '-', title)[:60]
            source_page = f"{safe_name}.md"
            ok = self.wiki.create_page(
                path=source_page,
                title=title,
                content=source_content,
                kind="source-record",
                form="prose",
                topics=takeaways.get("topics", []),
                subject=takeaways.get("subject", ["general"]),
                source_types=takeaways.get("source_types", ["article"]),
                confidence=takeaways.get("confidence", "medium"),
            )
            if ok:
                created.append(source_page)
                report.summary_page = source_page
        except Exception as e:
            report.errors.append(f"Source summary: {e}")

        # Create/update entity and concept pages
        for entity in page_plan.get("entities", []):
            try:
                page = self._create_or_update_page(entity, content)
                if page and entity.get("is_new", True):
                    created.append(page)
                elif page:
                    updated.append(page)
            except Exception as e:
                report.errors.append(f"Entity '{entity.get('title','?')}': {e}")

        for concept in page_plan.get("concepts", []):
            try:
                page = self._create_or_update_page(concept, content)
                if page and concept.get("is_new", True):
                    created.append(page)
                elif page:
                    updated.append(page)
            except Exception as e:
                report.errors.append(f"Concept '{concept.get('title','?')}': {e}")

        for contradiction in page_plan.get("contradictions", []):
            report.contradictions.append(contradiction)

        report.new_pages = created
        report.updated_pages = updated
        report.total_touched = len(created) + len(updated)

        summary = f"Updated {report.total_touched} pages"
        if report.contradictions:
            summary += f", {len(report.contradictions)} contradictions"
        self.wiki.append_log("ingest", title, summary)

        return report

    def _extract_takeaways(self, content: str, source_path: str) -> dict:
        """LLM extracts structured takeaways from source content."""
        prompt = f"""Analyze this document and extract key information for a personal wiki.

Source path: {source_path}

Document content:
{content[:15000]}

Respond in valid JSON only (no markdown, no code fences):
{{
    "title": "Concise title in Korean (max 40 chars)",
    "source_type": "paper|article|book|video|podcast|course|conversation|docs|external",
    "summary": "One-paragraph Korean summary (2-3 sentences)",
    "key_claims": ["claim1", "claim2", "claim3"],
    "methodology": "Brief methodology description",
    "main_concepts": ["concept1", "concept2", "concept3"],
    "key_entities": ["entity1", "entity2"],
    "topics": ["topic1", "topic2"],
    "subject": ["path/to/subject"],
    "confidence": "high|medium|low"
}}"""
        try:
            result = self.llm.chat_sync(
                messages=[{"role": "user", "content": prompt}],
                model=MODEL_PRO, temperature=0.3, max_tokens=1000,
            )
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(result)
            # Map source_type to source_types list
            st = data.get("source_type", "article")
            data["source_types"] = [st] if isinstance(st, str) else st
            return data
        except Exception:
            return {}

    def _gather_wiki_context(self, title: str, takeaways: dict) -> str:
        """Gather existing wiki context relevant to this source."""
        index = self.wiki.read_index()
        if not index:
            return "(No existing wiki pages)"
        log = self.wiki.read_log(10)
        return f"""Existing Wiki Index:
{index}

Recent Activity:
{log}"""

    def _plan_pages(self, takeaways: dict, content: str,
                    existing_context: str, user_emphasis: str) -> dict:
        """LLM determines what wiki pages to create or update."""
        emphasis_text = f"\nUser's emphasis: {user_emphasis}" if user_emphasis else ""

        prompt = f"""You are a wiki curator. Given this source document analysis,
determine exactly which wiki pages should be created or updated.

Source Analysis:
Title: {takeaways.get('title', 'Unknown')}
Type: {takeaways.get('source_type', 'unknown')}
Summary: {takeaways.get('summary', '')}
Key Claims: {json.dumps(takeaways.get('key_claims', []))}
Main Concepts: {json.dumps(takeaways.get('main_concepts', []))}
Key Entities: {json.dumps(takeaways.get('key_entities', []))}
Topics: {json.dumps(takeaways.get('topics', []))}
Subject: {json.dumps(takeaways.get('subject', []))}
{emphasis_text}

Existing Wiki Context:
{existing_context[:2000]}

Respond in JSON only:
{{
    "entities": [
        {{
            "title": "Entity name in Korean",
            "filename": "entity-name.md",
            "is_new": true,
            "kind": "entity",
            "form": "prose",
            "content": "Wiki page content in Korean markdown (use prose relations like 'builds on [[x]]', 'instance of [[y]]')",
            "topics": ["topic1"],
            "subject": ["path/to/subject"],
            "source_types": ["paper"],
            "confidence": "high|medium|low"
        }}
    ],
    "concepts": [
        {{
            "title": "Concept name in Korean",
            "filename": "concept-name.md",
            "is_new": true,
            "kind": "concept",
            "form": "prose",
            "content": "Wiki page content in Korean markdown (use prose relations)",
            "topics": ["topic1"],
            "subject": ["path/to/subject"],
            "source_types": ["paper"],
            "confidence": "high|medium|low"
        }}
    ],
    "contradictions": [
        "Description of any contradiction found with existing wiki pages"
    ]
}}

Rules:
- Use Korean for all titles and content
- Use [[wikilinks]] in flat format (no subdirectory prefix)
- Use prose relations: 'builds on [[x]]', 'instance of [[y]]', 'applies to [[z]]', 'trade-off: [[a]] vs [[b]]'
- A single source typically touches 5-15 pages
- kind: 'entity' for specific things/people/models, 'concept' for ideas/methods/theories, 'comparison' for A vs B
- subject must be from the subject tree (study/ml, study/fp, fitness/routine, economy/investment, etc.)
- Mark is_new=false if the page already exists and should be updated"""
        try:
            result = self.llm.chat_sync(
                messages=[{"role": "user", "content": prompt}],
                model=MODEL_PRO, temperature=0.3, max_tokens=4000,
            )
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return json.loads(result)
        except Exception:
            return {}

    def _build_source_summary(self, takeaways: dict, content: str) -> str:
        """Build a source-record page content with prose relations."""
        claims = "\n".join(f"- {c}" for c in takeaways.get("key_claims", []))
        concepts = ", ".join(f"[[{c}]]" for c in takeaways.get("main_concepts", []))

        return f"""## Summary
{takeaways.get('summary', '')}

## Key Claims
{claims}

builds on {concepts if concepts else 'N/A'}

## Methodology
{takeaways.get('methodology', 'N/A')}

## Domain
- **Source type**: {takeaways.get('source_type', 'other')}
"""

    def _create_or_update_page(self, page_info: dict, source_content: str) -> str:
        """Create or update a wiki page. Returns the page path, or empty string."""
        title = page_info.get("title", "Untitled")
        safe_title = re.sub(r'[\\/:*?"<>|]+', '-', title).strip()[:60]
        filename = page_info.get("filename", f"{safe_title}.md")
        content = page_info.get("content", "")
        kind = page_info.get("kind", "concept")
        form = page_info.get("form", "prose")
        topics = page_info.get("topics", [])
        subject = page_info.get("subject", [])
        source_types = page_info.get("source_types", ["article"])
        confidence = page_info.get("confidence", "medium")
        is_new = page_info.get("is_new", True)

        if not content:
            return ""

        if is_new:
            ok = self.wiki.create_page(
                path=filename,
                title=title,
                content=content,
                kind=kind,
                form=form,
                topics=topics,
                subject=subject,
                source_types=source_types,
                confidence=confidence,
            )
            return filename if ok else ""
        else:
            ok = self.wiki.update_page(filename, content)
            return filename if ok else ""
