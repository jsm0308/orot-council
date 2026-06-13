"""iCal Calendar Sync - fetches Google Calendar via secret iCal URL.

Simpler than OAuth. Fetches .ics file, parses events, syncs to local calendar.json.
"""
import json
import ssl
from datetime import datetime, timezone, timedelta
from pathlib import Path

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import requests
from icalendar import Calendar as ICalCalendar

from core.config import BASE_DIR, DATA_DIR, CALENDAR_FILE

KST = timezone(timedelta(hours=9))
ICAL_URL_FILE = DATA_DIR / "ical_url.txt"
ICAL_SYNC_STATE = DATA_DIR / "ical_sync_state.json"


class ICalSync:
    """Fetches Google Calendar iCal feed and syncs to local calendar.json."""

    def __init__(self, local_calendar=None, ical_url: str = None):
        self.local_calendar = local_calendar
        self._ical_url = ical_url

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if ical_url and not ICAL_URL_FILE.exists():
            self._save_url(ical_url)

    @property
    def ical_url(self) -> str:
        if self._ical_url:
            return self._ical_url
        if ICAL_URL_FILE.exists():
            with open(ICAL_URL_FILE, "r", encoding="utf-8") as f:
                self._ical_url = f.read().strip()
        return self._ical_url

    def _save_url(self, url: str):
        with open(ICAL_URL_FILE, "w", encoding="utf-8") as f:
            f.write(url.strip())

    def fetch_events(self) -> list[dict]:
        """Fetch and parse iCal feed, return list of events in local format."""
        if not self.ical_url:
            return []

        try:
            resp = requests.get(self.ical_url, verify=False, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            print(f"  [iCal] Fetch error: {e}")
            return []

        try:
            cal = ICalCalendar.from_ical(resp.text)
        except Exception as e:
            print(f"  [iCal] Parse error: {e}")
            return []

        events = []
        for component in cal.walk("VEVENT"):
            uid = str(component.get("uid", ""))
            summary = str(component.get("summary", "(no title)"))
            description = str(component.get("description", ""))
            location = str(component.get("location", ""))

            dtstart = component.get("dtstart")
            dtend = component.get("dtend")

            if not dtstart:
                continue

            start_dt = dtstart.dt if dtstart.dt else None
            end_dt = dtend.dt if dtend and dtend.dt else start_dt

            if isinstance(start_dt, datetime):
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
                start_dt_kst = start_dt.astimezone(KST)
                start_str = start_dt_kst.isoformat()

                if isinstance(end_dt, datetime):
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=timezone.utc)
                    end_dt_kst = end_dt.astimezone(KST)
                    end_str = end_dt_kst.isoformat()
                else:
                    end_str = start_str
            else:
                # All-day event
                start_str = f"{start_dt.isoformat()}T00:00:00+09:00"
                end_str = f"{start_dt.isoformat()}T23:59:59+09:00"

            event = {
                "id": uid[:16] if uid else f"ical-{hash(summary + start_str)}",
                "summary": summary,
                "start": {"dateTime": start_str, "timeZone": "Asia/Seoul"},
                "end": {"dateTime": end_str, "timeZone": "Asia/Seoul"},
                "description": description,
                "location": location,
                "source": "ical",
                "ical_uid": uid,
            }
            events.append(event)

        return events

    def pull_to_local(self) -> dict:
        """Fetch iCal events and merge into local calendar.json. Returns sync report."""
        if not self.local_calendar:
            return {"error": "No local calendar instance"}

        ical_events = self.fetch_events()
        if not ical_events:
            return {"added": 0, "updated": 0, "total_ical": 0, "error": "No events fetched"}

        local_events = self.local_calendar._load()

        # Build lookup by ical_uid
        local_by_uid = {}
        for e in local_events:
            uid = e.get("ical_uid", "")
            if uid:
                local_by_uid[uid] = e

        # Keep non-iCal events
        merged = [e for e in local_events if not e.get("ical_uid")]

        added = 0
        updated = 0

        for ie in ical_events:
            uid = ie.get("ical_uid", "")
            if uid in local_by_uid:
                # Update existing
                updated += 1
            else:
                added += 1
            merged.append(ie)

        self.local_calendar._save(merged)

        state = {
            "last_sync": datetime.now(KST).isoformat(),
            "added": added,
            "updated": updated,
            "total_ical": len(ical_events),
            "total_local": len(merged),
        }
        with open(ICAL_SYNC_STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

        return state

    def status(self) -> dict:
        """Get iCal sync status."""
        synced = ICAL_SYNC_STATE.exists()
        state = {}
        if synced:
            with open(ICAL_SYNC_STATE, "r", encoding="utf-8") as f:
                state = json.load(f)
        return {
            "configured": bool(self.ical_url),
            "synced": synced,
            "last_sync": state.get("last_sync"),
            "total_ical": state.get("total_ical", 0),
            "total_local": state.get("total_local", 0),
        }
