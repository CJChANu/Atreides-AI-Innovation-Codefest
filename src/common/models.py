"""Canonical data model shared by ingestion, retrieval and the answer generator.

The single rule that shapes everything here: **every answerable unit keeps its
source location**. A citation is generated from metadata we recorded at parse
time, never guessed by a language model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ContentType = Literal["paragraph", "heading", "table", "figure", "list", "verse", "page"]
SourceFormat = Literal["pdf", "pdf_scan", "docx", "markdown", "text", "image"]


@dataclass
class Document:
    """One physical file in the archive."""

    document_id: str
    relative_path: str
    title: str
    source_format: SourceFormat
    source_class: str
    reliability: float
    file_hash: str
    file_size: int
    page_count: int | None
    version: int = 1
    ingested_at: str = ""
    # Set when a sibling file holds the same content in another format (e.g. the
    # DOCX twin of a PDF). We ingest one and record the other for traceability.
    superseded_by: str | None = None
    notes: str = ""


@dataclass
class Block:
    """A raw unit emitted by a parser, before chunking.

    Parsers are responsible for provenance (page, section, line range); the
    chunker is responsible only for sizing. Keeping those concerns apart means a
    chunking change can never silently corrupt a citation.
    """

    text: str
    content_type: ContentType = "paragraph"
    page: int | None = None
    section_path: tuple[str, ...] = ()
    line_start: int | None = None
    line_end: int | None = None
    table_id: str | None = None
    figure_id: str | None = None
    ocr_confidence: float | None = None


@dataclass
class Chunk:
    """A retrievable, citable unit of text."""

    chunk_id: str
    document_id: str
    document_version: int
    source_format: SourceFormat
    source_class: str
    content: str
    content_type: ContentType
    page_start: int | None = None
    page_end: int | None = None
    section_path: tuple[str, ...] = ()
    char_start: int = 0
    char_end: int = 0
    table_ids: list[str] = field(default_factory=list)
    figure_ids: list[str] = field(default_factory=list)
    ocr_confidence: float | None = None

    def citation(self) -> str:
        """Human-readable citation string built purely from recorded metadata."""
        where = f"p.{self.page_start}" if self.page_start else " > ".join(self.section_path) or "—"
        return f"[{self.document_id} · {where}]"


@dataclass
class Table:
    """A table kept as both a cell matrix and a flat retrieval text."""

    table_id: str
    document_id: str
    page: int | None
    section_path: tuple[str, ...]
    caption: str
    columns: list[str]
    rows: list[list[str]]

    def as_retrieval_text(self) -> str:
        header = " | ".join(self.columns)
        body = "\n".join(" | ".join(r) for r in self.rows)
        return f"{self.caption}\nColumns: {header}\n{body}".strip()


@dataclass
class Figure:
    """An image or figure plate, linked back to the page it appeared on."""

    figure_id: str
    document_id: str
    page: int | None
    caption: str
    asset_path: str
    nearby_text: str = ""
    ocr_text: str = ""
    width: int | None = None
    height: int | None = None
