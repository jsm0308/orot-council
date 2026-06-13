"""Local JSON Calendar - standalone, no Google API dependency.

Migrated from local_calendar.py. Stores events in data/calendar.json.
Phase 3: Wiki-linked calendar events.
"""
import json
import re
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from core.config import DATA_DIR, CALENDAR_FILE

KST = timezone(timedelta(hours=9))


class Calendar:
    def __init__(self, file_path: Path = None, search_engine=None):
        self.file_path = file_path or CALENDAR_FILE
        self.search_engine = search_engine  # Optional SearchEngine for Wiki linking
        self._ensure_file()

    def _ensure_file(self):
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump([], f)

    def _load(self) -> list[dict]:
        self._ensure_file()
        with open(self.file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self, events: list[dict]):
        self._ensure_file()
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(events, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(KST)

    def list_events(self, max_results: int = 20, time_min: str = None, time_max: str = None) -> list[dict]:
        events = self._load()
        now = self._now()
        min_dt = datetime.fromisoformat(time_min).replace(tzinfo=KST) if time_min else now
        max_dt = datetime.fromisoformat(time_max).replace(tzinfo=KST) if time_max else None

        def parse_start(event: dict) -> datetime:
            start_str = event.get("start", {}).get("dateTime", "")
            if not start_str:
                return datetime.max.replace(tzinfo=KST)
            return datetime.fromisoformat(start_str).replace(tzinfo=KST)

        filtered = [e for e in events if parse_start(e) >= min_dt and (max_dt is None or parse_start(e) <= max_dt)]
        filtered.sort(key=parse_start)
        return filtered[:max_results]

    def list_today(self, max_results: int = 20) -> list[dict]:
        now = self._now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()
        return self.list_events(max_results=max_results, time_min=today_start, time_max=today_end)

    def create_event(self, summary: str, start_time: str, end_time: str,
                     description: str = None, location: str = None) -> dict:
        events = self._load()
        event_id = str(uuid.uuid4())[:8]
        event = {
            "id": event_id,
            "summary": summary,
            "start": {"dateTime": start_time, "timeZone": "Asia/Seoul"},
            "end": {"dateTime": end_time, "timeZone": "Asia/Seoul"},
        }
        if description:
            event["description"] = description
        if location:
            event["location"] = location
        events.append(event)
        self._save(events)
        return event

    def delete_event(self, event_id: str) -> dict:
        events = self._load()
        for e in events:
            if e.get("id") == event_id:
                events.remove(e)
                self._save(events)
                return {"status": "deleted", "id": event_id}
        return {"error": f"Event ID '{event_id}' not found."}

    @staticmethod
    def format_event(event: dict) -> str:
        summary = event.get("summary", "(no title)")
        start = event.get("start", {}).get("dateTime", "?")
        end = event.get("end", {}).get("dateTime", "?")

        try:
            start_dt = datetime.fromisoformat(start)
            start_str = start_dt.strftime("%m/%d(%a) %H:%M")
        except Exception:
            start_str = start

        try:
            end_dt = datetime.fromisoformat(end)
            end_str = end_dt.strftime("%H:%M")
        except Exception:
            end_str = end

        eid = event.get("id", "?")
        lines = [f"  - **{summary}**  `{eid}`  ({start_str} ~ {end_str})"]

        location = event.get("location")
        if location:
            lines.append(f"    Location: {location}")

        description = event.get("description", "")
        if description:
            lines.append(f"    {description[:100]}")

        return "\n".join(lines)

    def parse_and_execute(self, action_block: str) -> str:
        """Execute a calendar-action JSON block from LLM output."""
        try:
            action = json.loads(action_block.strip())
        except json.JSONDecodeError as e:
            return f"  [Calendar] JSON error: {e}"

        action_type = action.get("action")
        params = action.get("params", {})

        if action_type == "list_today":
            events = self.list_today(max_results=params.get("max_results", 20))
            if not events:
                today = self._now().strftime("%m/%d")
                return f"  [Calendar] No events for {today}."
            lines = [f"  [Calendar] Today ({len(events)} events):"]
            for e in events:
                lines.append(self.format_event(e))
            return "\n".join(lines)

        elif action_type == "list_events":
            max_results = params.get("max_results", 10)
            time_min = params.get("time_min")
            time_max = params.get("time_max")
            events = self.list_events(max_results=max_results, time_min=time_min, time_max=time_max)
            if not events:
                return "  [Calendar] No events in range."
            lines = [f"  [Calendar] Events ({len(events)}):"]
            for e in events:
                lines.append(self.format_event(e))
            return "\n".join(lines)

        elif action_type == "create_event":
            summary = params.get("summary", "")
            start_time = params.get("start_time", "")
            end_time = params.get("end_time", "")
            description = params.get("description")
            location = params.get("location")
            if not summary or not start_time or not end_time:
                return "  [Calendar] Create failed: summary, start_time, end_time required."
            result = self.create_event(summary, start_time, end_time, description, location)
            return f"  [Calendar] Created: {result['summary']} ({result['start']['dateTime']} ~ {result['end']['dateTime']}) ID: `{result['id']}`"

        elif action_type == "delete_event":
            event_id = params.get("event_id", "")
            if not event_id:
                return "  [Calendar] Delete failed: event_id required."
            result = self.delete_event(event_id)
            if "error" in result:
                return f"  [Calendar] {result['error']}"
            return f"  [Calendar] Deleted (ID: {event_id})"

        elif action_type == "create_from_wiki":
            wiki_path = params.get("wiki_path", "")
            date = params.get("date", "")
            time = params.get("time", "09:00")
            duration = params.get("duration_minutes", 60)
            desc = params.get("description")
            if not wiki_path or not date:
                return "  [Calendar] create_from_wiki failed: wiki_path and date required."
            result = self.create_event_from_wiki(wiki_path, date, time, duration, desc)
            return (f"  [Calendar] Created from wiki: {result['summary']} "
                    f"({result['start']['dateTime']} ~ {result['end']['dateTime']}) ID: `{result['id']}`")

        return f"  [Calendar] Unknown action: {action_type}"

    def process_actions(self, response_text: str) -> list[str]:
        """Find and execute all calendar-action blocks in the AI response."""
        pattern = r"```calendar-action\s*\n(.*?)```"
        blocks = re.findall(pattern, response_text, re.DOTALL)
        results = []
        for block in blocks:
            result = self.parse_and_execute(block.strip())
            results.append(result)
        return results

    # --- Phase 3: Calendar ↔ Wiki Integration ---

    def link_to_wiki(self, event: dict) -> list[str]:
        """Find wiki pages related to this event, return [[links]]."""
        if not self.search_engine:
            return []
        keywords = event.get("summary", "")
        desc = event.get("description", "")
        query = f"{keywords} {desc}".strip()
        if not query:
            return []
        try:
            results = self.search_engine.search(query, top_k=3)
            return [f"[[{r['path']}]]" for r in results if r.get("path")]
        except Exception:
            return []

    def create_event_from_wiki(self, wiki_path: str, date: str, time: str = "09:00",
                                duration_minutes: int = 60, description: str = None) -> dict:
        """Create a calendar event from a wiki page, using page title as event name."""
        from datetime import timedelta
        try:
            start_dt = datetime.fromisoformat(f"{date}T{time}:00")
        except ValueError:
            start_dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        start_dt = start_dt.replace(tzinfo=KST)
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        # Extract page title from wiki path
        page_title = wiki_path.replace(".md", "").split("/")[-1].replace("_", " ")
        full_desc = description or ""
        if full_desc:
            full_desc += "\n"
        full_desc += f"Wiki page: [[{wiki_path}]]"

        return self.create_event(
            summary=f"[Wiki] {page_title}",
            start_time=start_dt.isoformat(),
            end_time=end_dt.isoformat(),
            description=full_desc,
        )

    def enrich_events_with_wiki(self, events: list[dict]) -> list[dict]:
        """Attach wiki links to each event in a list."""
        enriched = []
        for e in events:
            e = dict(e)
            links = self.link_to_wiki(e)
            if links:
                existing = e.get("wiki_links", [])
                e["wiki_links"] = list(set(existing + links))
            enriched.append(e)
        return enriched
