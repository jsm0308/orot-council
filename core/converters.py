"""Document converter using Microsoft markitdown.

Converts PDF, Word, PPT, Excel, and other formats to markdown text.
Resolves Obsidian vault API paths to actual filesystem paths for reading.
"""
import os
from pathlib import Path
from core.config import OBSIDIAN_VAULT_PATH, VAULT_FOLDER


class DocumentConverter:
    """Convert source documents to markdown text for LLM processing."""

    def __init__(self, vault_path: Path = None):
        self.vault_path = vault_path or OBSIDIAN_VAULT_PATH

    def _resolve_path(self, source_path: str) -> Path:
        """Resolve an API-relative path to an absolute filesystem path.

        e.g. '1_Sources/papers/paper.pdf' ->
             C:/Users/Gram/Desktop/jsm obsidian/jsm personal agents (obsidian files)/Agents/1_Sources/papers/paper.pdf
        """
        # If already absolute, use as-is
        p = Path(source_path)
        if p.is_absolute():
            return p

        # Resolve relative to vault's Agents folder
        full = self.vault_path / VAULT_FOLDER / source_path
        return full

    def read_text(self, source_path: str) -> str:
        """Read a source file and return its markdown text content.

        Supports: .pdf, .docx, .pptx, .xlsx, .md, .txt, .html
        Uses markitdown for complex formats, direct read for plain text.
        Falls back to pdfplumber if markitdown fails on PDFs.
        """
        disk_path = self._resolve_path(source_path)

        if not disk_path.exists():
            raise FileNotFoundError(f"Source not found: {disk_path}")

        suffix = disk_path.suffix.lower()

        # Plain text formats -- direct read
        if suffix in (".md", ".txt", ".markdown"):
            return disk_path.read_text(encoding="utf-8", errors="replace")

        # Complex formats -- use markitdown
        if suffix in (".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm"):
            return self._markitdown_convert(str(disk_path), suffix)

        # Unknown format -- try markitdown anyway
        return self._markitdown_convert(str(disk_path), suffix)

    def _markitdown_convert(self, disk_path: str, suffix: str) -> str:
        """Convert using markitdown. Falls back to pdfplumber for PDFs."""
        try:
            from markitdown import MarkItDown
            md = MarkItDown()
            result = md.convert(disk_path)
            return result.text_content
        except ImportError:
            if suffix == ".pdf":
                return self._pdfplumber_fallback(disk_path)
            raise RuntimeError(
                "markitdown not installed. Run: pip install markitdown"
            )
        except Exception as e:
            if suffix == ".pdf":
                try:
                    return self._pdfplumber_fallback(disk_path)
                except Exception:
                    pass
            raise RuntimeError(
                f"Failed to convert {disk_path}: {e}"
            )

    def _pdfplumber_fallback(self, disk_path: str) -> str:
        """Fallback PDF text extraction using pdfplumber."""
        try:
            import pdfplumber
            text_parts = []
            with pdfplumber.open(disk_path) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        text_parts.append(t)
            return "\n\n".join(text_parts)
        except ImportError:
            raise RuntimeError(
                "Neither markitdown nor pdfplumber is installed. "
                "Run: pip install markitdown pdfplumber"
            )

    def file_info(self, source_path: str) -> dict:
        """Get basic file information for display."""
        disk_path = self._resolve_path(source_path)
        return {
            "path": source_path,
            "disk_path": str(disk_path),
            "exists": disk_path.exists(),
            "size_kb": round(disk_path.stat().st_size / 1024, 1) if disk_path.exists() else 0,
            "format": disk_path.suffix.lower() if disk_path.exists() else "unknown",
        }
