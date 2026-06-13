"""Obsidian Local REST API client.

Unified client for all Obsidian vault operations.
The Obsidian Local REST API plugin must be running on port 27124.
Phase 3: Added local cache fallback for offline resilience.
"""
import json
import os
import requests
import urllib3
from datetime import datetime
from pathlib import Path
from core.config import OBSIDIAN_API_URL, OBSIDIAN_API_KEY, BASE_DIR

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TIMEOUT = 5
CACHE_DIR = BASE_DIR / "data" / "obsidian_cache"


class ObsidianClient:
    """HTTP client for Obsidian Local REST API.
    
    When Obsidian is offline, write operations are cached locally
    and replayed when the connection is restored.
    """

    def __init__(self, base_url: str = None, api_key: str = None):
        self.base_url = base_url or OBSIDIAN_API_URL
        self.api_key = api_key or OBSIDIAN_API_KEY
        self._online: bool | None = None
        self._cache_dir = CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def online(self) -> bool:
        if self._online is None:
            self._online = self.check_connection()
        return self._online

    def _headers_read(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "text/markdown"}

    def _headers_write(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "text/markdown"}

    def check_connection(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/", headers=self._headers_read(), verify=False, timeout=TIMEOUT)
            return resp.ok
        except Exception:
            return False

    def read_note(self, path: str) -> str:
        """Read a note from the vault. Raises on failure."""
        resp = requests.get(f"{self.base_url}/{path}", headers=self._headers_read(), verify=False, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.text

    def note_exists(self, path: str) -> bool:
        try:
            self.read_note(path)
            return True
        except Exception:
            return False

    def _cache_operation(self, op_type: str, path: str, content: str = ""):
        """Cache a write operation for later replay when Obsidian comes back online."""
        safe_name = path.replace("/", "_").replace("\\", "_").replace(" ", "_")[:80]
        cache_file = self._cache_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_name}.json"
        entry = {
            "type": op_type,
            "path": path,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False)
        return cache_file

    def _replay_cache(self) -> int:
        """Replay all cached write operations. Returns number of successful replays."""
        if not self.check_connection():
            return 0
        cache_files = sorted(self._cache_dir.glob("*.json"))
        replayed = 0
        for cf in cache_files:
            try:
                with open(cf, "r", encoding="utf-8") as f:
                    entry = json.load(f)
                op_type = entry.get("type")
                path = entry.get("path")
                content = entry.get("content", "")
                success = False
                if op_type == "write":
                    success = self._write_direct(path, content)
                elif op_type == "append":
                    success = self._append_direct(path, content)
                elif op_type == "delete":
                    success = self._delete_direct(path)
                if success:
                    cf.unlink()
                    replayed += 1
            except Exception:
                continue
        if replayed:
            self._online = True
        return replayed

    def _write_direct(self, path: str, content: str) -> bool:
        """Direct write without cache fallback."""
        try:
            resp = requests.put(
                f"{self.base_url}/{path}",
                data=content.encode("utf-8"),
                headers=self._headers_write(),
                verify=False,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            return True
        except Exception:
            return False

    def write_note(self, path: str, content: str) -> bool:
        """Create or overwrite a note. Caches locally if Obsidian is offline."""
        try:
            if self._write_direct(path, content):
                return True
        except Exception:
            pass
        self._online = False
        self._cache_operation("write", path, content)
        return False

    def _append_direct(self, path: str, content: str) -> bool:
        """Direct append without cache fallback."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "text/markdown",
            "Content-Insertion-Position": "end",
        }
        try:
            resp = requests.post(
                f"{self.base_url}/{path}",
                data=content.encode("utf-8"),
                headers=headers,
                verify=False,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            return True
        except Exception:
            return False

    def append_note(self, path: str, content: str) -> bool:
        """Append content to end of a note. Caches locally if Obsidian is offline."""
        try:
            if self._append_direct(path, content):
                return True
        except Exception:
            pass
        self._online = False
        self._cache_operation("append", path, content)
        return False

    def _delete_direct(self, path: str) -> bool:
        try:
            resp = requests.delete(f"{self.base_url}/{path}", headers=self._headers_read(), verify=False, timeout=TIMEOUT)
            resp.raise_for_status()
            return True
        except Exception:
            return False

    def delete_note(self, path: str) -> bool:
        try:
            if self._delete_direct(path):
                return True
        except Exception:
            pass
        self._online = False
        self._cache_operation("delete", path)
        return False

    def list_notes(self, dir_path: str) -> list[str]:
        """List all markdown files in a vault directory."""
        try:
            resp = requests.get(f"{self.base_url}/{dir_path}/", headers=self._headers_read(), verify=False, timeout=TIMEOUT)
            resp.raise_for_status()
            files = resp.json().get("files", [])
            return [f for f in files if f.endswith(".md")]
        except Exception:
            self._online = False
            return []

    def search_notes(self, query: str) -> list[dict]:
        """Simple search via Obsidian REST API. Returns list of {path, score} dicts."""
        try:
            resp = requests.get(
                f"{self.base_url}/{VAULT_FOLDER}",
                headers=self._headers_read(),
                params={"query": query},
                verify=False,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json().get("files", [])
        except Exception:
            self._online = False
            return []


# Back-compat import for config
from core.config import VAULT_FOLDER
