"""Standalone figure plates (images/, wiki/images/, codex/images/).

These carry answers that exist nowhere in prose — garrison strengths, threat
ratings, attunement costs are printed *on the plate*. We record the asset and its
filename-derived subject now; OCR of the plate labels is applied when available.
"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from src.common.ids import figure_id as make_figure_id
from src.common.models import Block, Figure
from src.ingestion.parsers.base import ParseResult

# Plate filenames encode their own metadata, e.g.
# plate_08_creature_weeping_lurker.png -> kind "creature", subject "Weeping Lurker".
_PLATE_NAME = re.compile(
    r"^(?:plate_(?P<num>\d+)_)?(?P<kind>creature|location|artifact|conflict|heraldry|portrait|faction)?_?(?P<subject>.+)$"
)


def describe_plate(stem: str) -> tuple[str, str]:
    """Return (kind, human subject) parsed from a plate filename."""
    cleaned = stem.replace("atmo_", "").replace("battle_painting_", "")
    match = _PLATE_NAME.match(cleaned)
    if not match:
        return "", stem.replace("_", " ").title()
    kind = match.group("kind") or ""
    subject = match.group("subject").replace("_", " ").strip().title()
    return kind, subject


class ImageParser:
    def __init__(self, ocr=None) -> None:
        self.ocr = ocr

    def parse(self, path: Path, document_id: str, assets_dir: Path) -> ParseResult:
        result = ParseResult(page_count=1)
        kind, subject = describe_plate(path.stem)
        caption = f"{kind.title()} plate: {subject}".strip(": ").strip()

        ocr_text, confidence = "", None
        if self.ocr is not None and self.ocr.available:
            ocr_text, confidence = self._ocr_image(path)

        result.figures.append(
            Figure(
                figure_id=make_figure_id(document_id, 1, 0),
                document_id=document_id,
                page=1,
                caption=caption,
                asset_path=str(path),  # corpus is read-only; reference in place
                nearby_text=subject,
                ocr_text=ocr_text,
            )
        )
        # The plate must also be *findable* by text search, so we index its caption
        # plus whatever labels OCR recovered.
        result.blocks.append(
            Block(
                text=f"{caption}\n{ocr_text}".strip(),
                content_type="figure",
                page=1,
                figure_id=result.figures[0].figure_id,
                ocr_confidence=confidence,
            )
        )
        if not ocr_text:
            result.warnings.append("plate indexed by caption only; OCR unavailable or empty")
        return result

    def _ocr_image(self, path: Path) -> tuple[str, float]:
        """Wrap the raster in a one-page PDF so the OCR adapter has a single input type."""
        try:
            document = pymupdf.open(str(path))
            pdf = pymupdf.open("pdf", document.convert_to_pdf())
            text, confidence = self.ocr.read_page(pdf[0])
            document.close()
            pdf.close()
            return text, confidence
        except Exception:
            return "", 0.0
