"""PDF parser (page-accurate).

PDFs are the only format in this archive that carry real page numbers, which is
why we prefer them over their DOCX twins for citation (see docs/decisions.md).
Three things are extracted per page and kept linked to that page number:

* text blocks, with a heading heuristic that rebuilds a section path;
* tables, via PyMuPDF's table finder — in the codexes these hold the exact
  numeric facts (threat rating, attunement cost, garrison strength) that figure
  and table questions ask for;
* embedded images, written to the derived-assets directory so the UI can embed
  the actual figure instead of describing it.

A page with no extractable text is flagged for OCR rather than silently dropped.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from src.common.ids import figure_id as make_figure_id
from src.common.ids import table_id as make_table_id
from src.common.models import Block, Figure, Table
from src.ingestion.parsers.base import ParseResult

# Below this many characters a page is treated as image-only and routed to OCR.
MIN_TEXT_CHARS_PER_PAGE = 20
# Images smaller than this are decorative rules/bullets, not figures worth storing.
MIN_FIGURE_PIXELS = 100


def _looks_like_heading(text: str) -> bool:
    """Heuristic heading test for PDFs that carry no structure tags.

    Short, title-cased, punctuation-free lines act as headings in both the codexes
    ("Chalice of Ashdeep") and the chronicles ("Chapter Four"). Getting this
    slightly wrong costs us a section label, never a page citation.
    """
    stripped = text.strip()
    if not stripped or len(stripped) > 80 or "\n" in stripped:
        return False
    if stripped.endswith((".", ",", ";", ":", "?", "!")):
        return False
    words = stripped.split()
    return 1 <= len(words) <= 10 and sum(w[:1].isupper() for w in words) >= max(1, len(words) - 2)


class PdfParser:
    def __init__(self, ocr=None) -> None:
        # Injected rather than imported so the pipeline can run with OCR disabled
        # or unavailable, and say so, instead of failing.
        self.ocr = ocr

    def parse(self, path: Path, document_id: str, assets_dir: Path) -> ParseResult:
        result = ParseResult()
        document = pymupdf.open(str(path))
        result.page_count = document.page_count
        figure_ordinal = 0
        scanned_pages = 0

        for page_index in range(document.page_count):
            page = document[page_index]
            page_no = page_index + 1

            raw_text = page.get_text("text") or ""

            # Text first, tables second. In the codexes the entity name is a
            # heading directly above its table; emitting the table first would
            # orphan it from the only thing that says what it describes.
            if len(raw_text.strip()) < MIN_TEXT_CHARS_PER_PAGE:
                scanned_pages += 1
                self._ocr_page(page, page_no, result)
            else:
                self._emit_text_blocks(raw_text, page_no, result)

            self._extract_tables(page, document_id, page_no, result,
                                 heading=self._page_heading(raw_text))

            figure_ordinal = self._extract_images(
                page, document, document_id, page_no, assets_dir, result, figure_ordinal
            )

        document.close()
        if scanned_pages:
            result.warnings.append(
                f"{scanned_pages}/{result.page_count} pages had no text layer (scan path)"
            )
        return result

    # -- pieces -------------------------------------------------------------

    @staticmethod
    def _page_heading(raw_text: str) -> str:
        """First heading-like line on the page — the subject its tables describe."""
        for line in raw_text.splitlines():
            if _looks_like_heading(line):
                return line.strip()
        return ""

    def _extract_tables(self, page, document_id: str, page_no: int, result: ParseResult,
                        heading: str = "") -> int:
        try:
            found = page.find_tables()
        except Exception as exc:  # PyMuPDF raises on some malformed pages
            result.warnings.append(f"table detection failed on p.{page_no}: {exc}")
            return 0

        for ordinal, table in enumerate(found.tables):
            try:
                matrix = table.extract()
            except Exception as exc:
                result.warnings.append(f"table extraction failed on p.{page_no}: {exc}")
                continue
            matrix = [[(cell or "").strip() for cell in row] for row in matrix if any(row)]
            if len(matrix) < 2:
                continue
            table_obj = Table(
                table_id=make_table_id(document_id, page_no, ordinal),
                document_id=document_id,
                page=page_no,
                section_path=(heading,) if heading else (),
                caption=heading or f"Table on page {page_no}",
                columns=matrix[0],
                rows=matrix[1:],
            )
            result.tables.append(table_obj)
            result.blocks.append(
                Block(text=table_obj.as_retrieval_text(), content_type="table",
                      page=page_no, table_id=table_obj.table_id,
                      section_path=(heading,) if heading else ())
            )
        return len(found.tables)

    def _emit_text_blocks(self, raw_text: str, page_no: int, result: ParseResult) -> None:
        for paragraph in (p.strip() for p in raw_text.split("\n\n")):
            if not paragraph:
                continue
            content_type = "heading" if _looks_like_heading(paragraph) else "paragraph"
            result.blocks.append(Block(text=paragraph, content_type=content_type, page=page_no))

    def _ocr_page(self, page, page_no: int, result: ParseResult) -> None:
        if self.ocr is None or not self.ocr.available:
            result.blocks.append(
                Block(text="", content_type="page", page=page_no, ocr_confidence=0.0)
            )
            return
        text, confidence = self.ocr.read_page(page)
        if text.strip():
            result.blocks.append(
                Block(text=text.strip(), content_type="paragraph", page=page_no,
                      ocr_confidence=confidence)
            )

    def _extract_images(self, page, document, document_id, page_no, assets_dir,
                        result: ParseResult, ordinal: int) -> int:
        for xref, *_ in page.get_images(full=True):
            try:
                info = document.extract_image(xref)
            except Exception as exc:
                result.warnings.append(f"image extract failed p.{page_no}: {exc}")
                continue
            if info["width"] < MIN_FIGURE_PIXELS or info["height"] < MIN_FIGURE_PIXELS:
                continue
            fig_id = make_figure_id(document_id, page_no, ordinal)
            asset = assets_dir / f"{fig_id}.{info['ext']}"
            asset.parent.mkdir(parents=True, exist_ok=True)
            asset.write_bytes(info["image"])
            result.figures.append(
                Figure(
                    figure_id=fig_id,
                    document_id=document_id,
                    page=page_no,
                    caption=f"Figure on page {page_no}",
                    asset_path=str(asset),
                    nearby_text=(page.get_text("text") or "")[:400],
                    width=info["width"],
                    height=info["height"],
                )
            )
            ordinal += 1
        return ordinal
