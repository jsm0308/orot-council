"""Search Engine wrapper for the Wiki.

Primarily uses the Obsidian API for search. qmd integration is available
as an optional enhancement.
"""
import subprocess
import shutil
import json
from core.config import OBSIDIAN_VAULT_PATH, WIKI_PATH
from typing import Optional

QMD_AVAILABLE = shutil.which("qmd") is not None


class SearchEngine:
    def __init__(self, obsidian_client, wiki_path: str = None):
        self.obs = obsidian_client
        self.wiki_path = wiki_path or f"{OBSIDIAN_VAULT_PATH}/Agents/2_Wiki"
        self.use_qmd = QMD_AVAILABLE

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        """Search the wiki. Uses qmd if available, falls back to Obsidian API."""
        if self.use_qmd:
            return self._qmd_search(query, top_k)
        return self._fallback_search(query, top_k)

    def _qmd_search(self, query: str, top_k: int) -> list[dict]:
        """Hybrid BM25 + vector search via qmd."""
        try:
            result = subprocess.run(
                ["qmd", "search", query, "--limit", str(top_k), "--dir", str(self.wiki_path)],
                capture_output=True, text=True, timeout=10, encoding="utf-8"
            )
            if result.returncode != 0:
                self.use_qmd = False
                return self._fallback_search(query, top_k)

            results = json.loads(result.stdout)
            return [
                {"path": r.get("path", r.get("filename", "")), "score": r.get("score", 0), "content": r.get("text", "")[:200]}
                for r in results[:top_k]
            ]
        except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
            self.use_qmd = False
            return self._fallback_search(query, top_k)

    def _fallback_search(self, query: str, top_k: int) -> list[dict]:
        """Fallback: search via Obsidian REST API."""
        try:
            results = self.obs.search_notes(query)
            return [
                {"path": r.get("path", ""), "score": r.get("score", 0), "content": r.get("content", "")[:200]}
                for r in results[:top_k]
            ]
        except Exception:
            return []

    def keyword_search(self, query: str, top_k: int = 5) -> list[dict]:
        """BM25-only keyword search."""
        return self.search(query, top_k)

    def re_rank(self, query: str, candidates: list[dict], top_k: int = 3) -> list[dict]:
        """Re-rank candidates by relevance. Basic: sort by score, return top_k."""
        sorted_candidates = sorted(candidates, key=lambda x: x.get("score", 0), reverse=True)
        return sorted_candidates[:top_k]
