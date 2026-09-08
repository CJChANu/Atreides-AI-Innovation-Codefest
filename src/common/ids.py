"""Deterministic identifiers.

Re-running ingestion on an unchanged archive must produce identical IDs, or every
stored citation and cached investigation becomes invalid. All IDs are therefore
derived from content and normalised paths, never from insertion order or time.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_HASH_PREFIX_LEN = 12


def file_hash(path: Path, chunk_bytes: int = 1 << 20) -> str:
    """SHA-256 of a file's bytes, streamed so large PDFs do not load into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk_bytes):
            digest.update(block)
    return digest.hexdigest()


def document_id(relative_path: Path, file_size: int, content_hash: str) -> str:
    """Stable document ID: sha256(normalised path + size + hash prefix).

    Including the size and hash means an edited file yields a *new* ID, which is
    what lets ingestion be idempotent for unchanged files and versioned for
    changed ones.
    """
    normalised = relative_path.as_posix().lower()
    seed = f"{normalised}|{file_size}|{content_hash[:_HASH_PREFIX_LEN]}"
    return "doc-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def chunk_id(doc_id: str, page: int | None, section_index: int, ordinal: int) -> str:
    page_part = f"p{page:04d}" if page is not None else "pxxx"
    return f"{doc_id}-{page_part}-s{section_index:02d}-c{ordinal:03d}"


def table_id(doc_id: str, page: int | None, ordinal: int) -> str:
    page_part = f"{page:04d}" if page is not None else "xxxx"
    return f"{doc_id}-table-{page_part}-{ordinal:02d}"


def figure_id(doc_id: str, page: int | None, ordinal: int) -> str:
    page_part = f"{page:04d}" if page is not None else "xxxx"
    return f"{doc_id}-figure-{page_part}-{ordinal:02d}"
