# ai_intelligence/rag/chunking.py
"""Text normalisation, file extraction and chunking for the knowledge base."""
from __future__ import annotations

import re
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ai_intelligence.conf import ai_int
from ai_intelligence.domain.exceptions import IngestionError

SUPPORTED_SUFFIXES = {".md", ".txt", ".pdf"}


def normalize_text(text: str) -> str:
    """Unify line endings, drop NUL bytes (Postgres rejects them in text), trim
    trailing spaces and collapse runs of blank lines."""
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_text(text: str) -> list[str]:
    """Paragraph/heading-aware chunks (chunk size and overlap from settings)."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=ai_int("AI_RAG_CHUNK_SIZE"),
        chunk_overlap=ai_int("AI_RAG_CHUNK_OVERLAP"),
        separators=["\n## ", "\n# ", "\n\n", "\n", ". ", " ", ""],
    )
    return [c.strip() for c in splitter.split_text(text) if c.strip()]


def extract_text(path: str | Path) -> str:
    """Read .md / .txt / .pdf into plain text. Raises IngestionError for anything else."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise IngestionError(f"Unsupported file type {suffix!r}; supported: {sorted(SUPPORTED_SUFFIXES)}")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise IngestionError("pypdf is not installed: pip install pypdf") from exc
        try:
            return "\n\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
        except Exception as exc:                              # noqa: BLE001 - corrupt/encrypted PDF
            raise IngestionError(f"Could not read PDF {path.name}: {exc}") from exc
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise IngestionError(f"Could not read {path.name}: {exc}") from exc