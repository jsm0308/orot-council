"""Google Calendar API integration with OAuth 2.0.

Full read/write access to Google Calendar. Syncs with local calendar.json.
First run opens a browser for OAuth consent; subsequent runs use cached token.

References:
  https://developers.google.com/calendar/api/v3/reference
"""

import json
import os
import pickle
import ssl
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# Bypass corporate SSL certificate verification issue on Windows
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
os.environ["CURL_CA_BUNDLE"] = ""
os.environ["REQUESTS_CA_BUNDLE"] = ""

import requests as _requests
_requests.packages.urllib3.disable_warnings()

# Monkey-patch requests to skip SSL verification globally
_original_session_request = _requests.Session.request

def _patched_request(self, method, url, **kwargs):
    kwargs["verify"] = False
    return _original_session_request(self, method, url, **kwargs)

_requests.Session.request = _patched_request

# Also patch google.auth.transport.requests
import google.auth.transport.requests as _gatr
_original_gatr_request = _gatr.Request.__init__

def _patched_gatr_init(self, session=None):
    if session is None:
        session = _requests.Session()
        session.verify = False
    _original_gatr_request(self, session=session)

_gatr.Request.__init__ = _patched_gatr_init

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from core.config import BASE_DIR, DATA_DIR, CALENDAR_FILE

KST = timezone(timedelta(hours=9))
SCOPES = ["https://www.googleapis.com/auth/calendar"]
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = DATA_DIR / "google_token.pickle"
SYNC_STATE_FILE = DATA_DIR / "google_sync_state.json"


class GoogleCalendarClient:
    """Google Calendar API client with OAuth 2.0 authentication."""

    def __init__(self, local_calendar=None):
        self._service = None
        self.local_calendar = local_calendar
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ── Auth ──────────────────────────────────────────────────────────

    @property
    def service(self):
        """Lazily build and authenticate the Calendar API service."""
        if self._service is None:
            self._service = self._authenticate()
        return self._service

    def is_authenticated(self) -> bool:
        """Check if a valid token already exists (no browser needed)."""
        if not TOKEN_FILE.exists():
            return False
        try:
            with open(TOKEN_FILE, "rb") as f:
                creds = pickle.load(f)
            if creds and creds.valid:
                return True
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(_gatr.Request())
                with open(TOKEN_FILE, "wb") as f:
                    pickle.dump(creds, f)
                return True
        except Exception:
            pass
        return False

    def _authenticate(self):
        """Run OAuth 2.0 flow (opens browser on first run)."""
        if not CREDENTIALS_FILE.exists():
            raise FileNotFoundError(
                f"credentials.json not found at {CREDENTIALS_FILE}. "
                "Download it from Google Cloud Console → APIs & Services → Credentials."
            )

        creds = None
        if TOKEN_FILE.exists():
            with open(TOKEN_FILE, "rb") as f:
                creds = pickle.load(f)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(_gatr.Request())
            else:
                print("", flush=True)
                print("  *************************************************", flush=True)
                print("  Go to this URL in your browser:", flush=True)
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(CREDENTIALS_FILE), SCOPES
                )
                flow.redirect_uri = "http://localhost"
                auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
                print(f"  {auth_url}", flush=True)
                print("", flush=True)
                print("  Authorize the app, then paste the code here.", flush=True)
                print("  *************************************************", flush=True)
                print("", flush=True)
                code = input("  Paste authorization code: ").strip()
                flow.fetch_token(code=code)
                creds = flow.credentials
                print("  Authorization successful!", flush=True)
            with open(TOKEN_FILE, "wb") as f:
                pickle.dump(creds, f)

        return build("calendar", "v3", credentials=creds)

    def revoke_auth(self):
        """Revoke the stored token. Next call will require re-auth."""
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
        self._service = None

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _to_rfc3339(dt_str: str) -> str:
        """Convert ISO datetime string to RFC 3339 (Google's format)."""
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        return dt.isoformat()

    @staticmethod
    def _from_google_event(gevent: dict) -> dict:
        """Convert a Google Calendar event dict to local calendar format."""
        return {
            "id": gevent.get("id", ""),
            "summary": gevent.get("summary", "(no title)"),
            "start": gevent.get("start", {}),
            "end": gevent.get("end", {}),
            "description": gevent.get("description", ""),
            "location": gevent.get("location", ""),
            "source": "google",
            "google_id": gevent.get("id", ""),
            "html_link": gevent.get("htmlLink", ""),
            "status": gevent.get("status", ""),
            "created": gevent.get("created", ""),
            "updated": gevent.get("updated", ""),
        }

    @staticmethod
    def _to_google_body(summary: str, start_time: str, end_time: str,
                        description: str = None, location: str = None) -> dict:
        """Build a Google Calendar event body dict."""
        body = {
            "summary": summary,
            "start": {
                "dateTime": GoogleCalendarClient._to_rfc3339(start_time),
                "timeZone": "Asia/Seoul",
            },
            "end": {
                "dateTime": GoogleCalendarClient._to_rfc3339(end_time),
                "timeZone": "Asia/Seoul",
            },
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        return body

    # ── Read ──────────────────────────────────────────────────────────

    def list_events(self, max_results: int = 50,
                    time_min: str = None, time_max: str = None) -> list[dict]:
        """List events from Google Calendar."""
        params = {
            "calendarId": "primary",
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
            "timeZone": "Asia/Seoul",
        }
        if time_min:
            params["timeMin"] = self._to_rfc3339(time_min)
        else:
            params["timeMin"] = datetime.now(KST).isoformat()
        if time_max:
            params["timeMax"] = self._to_rfc3339(time_max)

        try:
            result = self.service.events().list(**params).execute()
            items = result.get("items", [])
            return [self._from_google_event(e) for e in items]
        except HttpError as e:
            print(f"  [Google Calendar] API error: {e}")
            return []

    def list_today(self, max_results: int = 50) -> list[dict]:
        """List today's events from Google Calendar."""
        now = datetime.now(KST)
        t_min = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        t_max = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()
        return self.list_events(max_results=max_results, time_min=t_min, time_max=t_max)

    def get_event(self, event_id: str) -> Optional[dict]:
        """Get a single event by Google Calendar event ID."""
        try:
            gevent = self.service.events().get(
                calendarId="primary", eventId=event_id
            ).execute()
            return self._from_google_event(gevent)
        except HttpError:
            return None

    # ── Write ─────────────────────────────────────────────────────────

    def create_event(self, summary: str, start_time: str, end_time: str,
                     description: str = None, location: str = None) -> dict:
        """Create an event on Google Calendar."""
        body = self._to_google_body(summary, start_time, end_time, description, location)
        try:
            gevent = self.service.events().insert(
                calendarId="primary", body=body
            ).execute()
            return self._from_google_event(gevent)
        except HttpError as e:
            return {"error": str(e), "summary": summary}

    def update_event(self, event_id: str, summary: str = None,
                     start_time: str = None, end_time: str = None,
                     description: str = None, location: str = None) -> dict:
        """Update an existing event on Google Calendar."""
        try:
            existing = self.service.events().get(
                calendarId="primary", eventId=event_id
            ).execute()
        except HttpError as e:
            return {"error": f"Event not found: {e}"}

        if summary is not None:
            existing["summary"] = summary
        if start_time is not None:
            existing["start"] = {
                "dateTime": self._to_rfc3339(start_time),
                "timeZone": "Asia/Seoul",
            }
        if end_time is not None:
            existing["end"] = {
                "dateTime": self._to_rfc3339(end_time),
                "timeZone": "Asia/Seoul",
            }
        if description is not None:
            existing["description"] = description
        if location is not None:
            existing["location"] = location

        try:
            gevent = self.service.events().update(
                calendarId="primary", eventId=event_id, body=existing
            ).execute()
            return self._from_google_event(gevent)
        except HttpError as e:
            return {"error": str(e)}

    def delete_event(self, event_id: str) -> dict:
        """Delete an event from Google Calendar."""
        try:
            self.service.events().delete(
                calendarId="primary", eventId=event_id
            ).execute()
            return {"status": "deleted", "id": event_id}
        except HttpError as e:
            return {"error": str(e)}

    # ── Sync ──────────────────────────────────────────────────────────

    def _load_sync_state(self) -> dict:
        """Load last sync timestamp from disk."""
        if SYNC_STATE_FILE.exists():
            with open(SYNC_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"last_sync": None}

    def _save_sync_state(self, state: dict):
        """Save sync timestamp to disk."""
        with open(SYNC_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

    def pull_from_google(self, days_ahead: int = 90) -> dict:
        """Pull events from Google Calendar into local calendar.json.

        Merges by google_id to avoid duplicates. Returns sync report.
        """
        if not self.local_calendar:
            return {"error": "No local calendar instance provided"}

        now = datetime.now(KST)
        t_min = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        t_max = (now + timedelta(days=days_ahead)).replace(
            hour=23, minute=59, second=59
        ).isoformat()

        google_events = self.list_events(max_results=250, time_min=t_min, time_max=t_max)
        local_events = self.local_calendar._load()

        # Build lookup by google_id
        local_by_google_id = {}
        local_only = []
        for e in local_events:
            gid = e.get("google_id", "")
            if gid:
                local_by_google_id[gid] = e
            else:
                local_only.append(e)

        added = 0
        updated = 0

        for ge in google_events:
            gid = ge.get("google_id", "")
            if gid in local_by_google_id:
                # Update existing
                idx = local_events.index(local_by_google_id[gid])
                local_events[idx] = ge
                updated += 1
            else:
                # New event
                local_events.append(ge)
                added += 1

        # Keep local-only events (not from Google)
        merged = []
        seen_gids = set()
        for e in local_events:
            gid = e.get("google_id", "")
            if gid:
                if gid not in seen_gids:
                    merged.append(e)
                    seen_gids.add(gid)
            else:
                merged.append(e)

        self.local_calendar._save(merged)

        state = {
            "last_sync": now.isoformat(),
            "added": added,
            "updated": updated,
            "total_google": len(google_events),
            "total_local": len(merged),
        }
        self._save_sync_state(state)
        return state

    def push_to_google(self, event: dict) -> dict:
        """Push a local calendar event to Google Calendar."""
        summary = event.get("summary", "Untitled")
        start = event.get("start", {}).get("dateTime", "")
        end = event.get("end", {}).get("dateTime", "")
        desc = event.get("description", "")
        loc = event.get("location", "")

        if not start or not end:
            return {"error": "start_time and end_time required"}

        result = self.create_event(summary, start, end, desc, loc)
        if "error" not in result and self.local_calendar:
            # Update local event with google_id
            events = self.local_calendar._load()
            for e in events:
                if e.get("id") == event.get("id"):
                    e["google_id"] = result.get("google_id", "")
                    e["html_link"] = result.get("html_link", "")
                    e["source"] = "google"
                    break
            self.local_calendar._save(events)

        return result

    # ── Format ────────────────────────────────────────────────────────

    @staticmethod
    def format_event(event: dict) -> str:
        """Format an event for CLI display (same format as local Calendar)."""
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
        source_tag = "[G]" if event.get("source") == "google" else "[L]"
        lines = [f"  - {source_tag} **{summary}**  `{eid[:8]}`  ({start_str} ~ {end_str})"]

        location = event.get("location")
        if location:
            lines.append(f"    Location: {location}")

        description = event.get("description", "")
        if description:
            lines.append(f"    {description[:100]}")

        return "\n".join(lines)

    # ── Status ────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Get authentication and sync status."""
        state = self._load_sync_state()
        return {
            "authenticated": self.is_authenticated(),
            "last_sync": state.get("last_sync"),
            "credentials": CREDENTIALS_FILE.exists(),
            "token": TOKEN_FILE.exists(),
        }
