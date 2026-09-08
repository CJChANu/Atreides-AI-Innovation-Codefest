"""Structure-aware chunking.

Fixed-size windows would cut this archive in exactly the wrong places: a codex
infobox row separated from the entity name above it becomes an orphan number, and
a wiki infobox split mid-table stops answering the question it exists to answer.

The policy:

* **Headings bind downward.** A heading is prepended to the chunks beneath it, so
  every chunk carries the entity name even when the prose uses a pronoun.
* **Tables and figures are never split.** They are emitted whole, as their own
  chunk, however long they are — a half table is worse than no table.
* **Prose overlaps.** Narrative chunks carry a tail of the previous chunk so a
  fact stated across a paragraph boundary survives.
* **Provenance is inherited, never computed.** A chunk's page and section come
  from the blocks it contains.
"""

from __future__ import annotations

from src.common.ids import chunk_id as make_chunk_id
from src.common.models import Block, Chunk, SourceFormat

# Content types that must be emitted as a single, unsplit chunk.
ATOMIC_TYPES = {"table", "figure"}


def _pages(blocks: list[Block]) -> tuple[int | None, int | None]:
    pages = [b.page for b in blocks if b.page is not None]
    return (min(pages), max(pages)) if pages else (None, None)


def _ocr_confidence(blocks: list[Block]) -> float | None:
    values = [b.ocr_confidence for b in blocks if b.ocr_confidence is not None]
    return round(min(values), 3) if values else None


class Chunker:
    def __init__(self, target_chars: int = 1200, overlap_chars: int = 180) -> None:
        self.target_chars = target_chars
        self.overlap_chars = overlap_chars

    def chunk(
        self,
        blocks: list[Block],
        *,
        document_id: str,
        document_version: int,
        source_format: SourceFormat,
        source_class: str,
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        ordinal = 0
        section_index = 0
        cursor = 0  # running character offset within the document, for char_start/end

        pending: list[Block] = []
        pending_len = 0
        current_heading: str | None = None
        last_section: tuple[str, ...] = ()

        def emit() -> None:
            nonlocal pending, pending_len, ordinal, cursor
            if not pending:
                return
            body = "\n\n".join(b.text for b in pending if b.text.strip())
            if not body.strip():
                pending, pending_len = [], 0
                return
            # Bind the governing section so the chunk is self-identifying.
            #
            # The *full* path matters, not just the nearest heading: a wiki
            # infobox sits under 'Gauntlet of Sorrowfell > Infobox', and binding
            # only 'Infobox' would leave the article's own subject — the thing
            # every question names — absent from the chunk text entirely.
            section = pending[-1].section_path or last_section
            heading = " > ".join(section) if section else current_heading
            text = f"{heading}\n\n{body}" if heading and not body.startswith(heading) else body
            page_start, page_end = _pages(pending)
            chunks.append(
                Chunk(
                    chunk_id=make_chunk_id(document_id, page_start, section_index, ordinal),
                    document_id=document_id,
                    document_version=document_version,
                    source_format=source_format,
                    source_class=source_class,
                    content=text,
                    content_type=pending[0].content_type if len(pending) == 1 else "paragraph",
                    page_start=page_start,
                    page_end=page_end,
                    section_path=section,
                    char_start=cursor,
                    char_end=cursor + len(text),
                    table_ids=[b.table_id for b in pending if b.table_id],
                    figure_ids=[b.figure_id for b in pending if b.figure_id],
                    ocr_confidence=_ocr_confidence(pending),
                )
            )
            ordinal += 1
            cursor += len(text)
            # Carry a tail of prose forward as overlap; atomic blocks never overlap.
            tail = pending[-1]
            pending, pending_len = [], 0
            if self.overlap_chars and tail.content_type not in ATOMIC_TYPES and len(tail.text) > self.overlap_chars:
                carried = Block(
                    text=tail.text[-self.overlap_chars :],
                    content_type=tail.content_type,
                    page=tail.page,
                    section_path=tail.section_path,
                    ocr_confidence=tail.ocr_confidence,
                )
                pending.append(carried)
                pending_len = len(carried.text)

        for block in blocks:
            if not block.text.strip() and block.content_type != "page":
                continue
            if block.section_path:
                last_section = block.section_path

            if block.content_type == "heading":
                emit()
                section_index += 1
                current_heading = block.text.strip()
                continue

            if block.content_type in ATOMIC_TYPES:
                emit()
                pending = [block]
                pending_len = len(block.text)
                emit()
                continue

            if pending_len + len(block.text) > self.target_chars and pending:
                emit()

            pending.append(block)
            pending_len += len(block.text)

        emit()
        return chunks
