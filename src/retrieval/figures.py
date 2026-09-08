"""Figure evidence lookup.

Some values in this archive are only ever *drawn*. When the text record says
"None recorded" for an artifact's attunement cost, that is not an omission — the
archive is pointing at the plate. This module finds the plate so the answer can
show it, and reports honestly when the value on it is a bar rather than a printed
number.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.graph.plate_facts import PLATE_LABELS, is_chart_plate
from src.storage.db import ArchiveStore

# Heraldry paintings and portraits carry no printed labels, so OCR over them
# returns noise ("f ti teh Walia i { =| | eee"). Generic "does this look like
# language" heuristics do not reliably separate that from real text — we tried,
# and three-letter garbage passes them.
#
# The rule we use instead is the one the rest of the system already follows: quote
# a plate only when we can say *what* its text is labelling. A known label phrase
# is that proof. Everything else is a picture we can show but must not paraphrase.
_LABEL_PHRASES = tuple(PLATE_LABELS) + ("souls under arms", "per the", "as entered into")


def has_readable_label(value: str) -> bool:
    """True when the OCR text contains a recognised plate label."""
    lowered = " ".join(value.lower().split())
    return any(phrase in lowered for phrase in _LABEL_PHRASES)


@dataclass
class FigureHit:
    figure_id: str
    document_id: str
    caption: str
    asset_path: str
    ocr_text: str
    page: int | None
    is_chart: bool

    @property
    def readable(self) -> bool:
        """True when the plate prints a legible value rather than plotting it.

        Three ways a plate can fail to answer, all reported differently from
        "no evidence": it has no text, its text is OCR noise from artwork, or its
        value is drawn on a scale.
        """
        return has_readable_label(self.ocr_text) and not self.is_chart

    @property
    def pictorial(self) -> bool:
        """A plate whose meaning is the image itself — heraldry, a portrait."""
        return not has_readable_label(self.ocr_text)


class FigureIndex:
    def __init__(self, store: ArchiveStore) -> None:
        self.store = store

    def for_subject(self, name: str, limit: int = 4) -> list[FigureHit]:
        """Plates whose caption or OCR text names this subject."""
        pattern = f"%{name}%"
        rows = self.store.connection.execute(
            """SELECT f.figure_id, f.document_id, f.caption, f.asset_path,
                      f.ocr_text, f.page
               FROM figures f
               WHERE f.caption LIKE ? OR f.ocr_text LIKE ?
               ORDER BY length(f.ocr_text) DESC
               LIMIT ?""",
            (pattern, pattern, limit),
        ).fetchall()
        return [
            FigureHit(
                figure_id=r["figure_id"], document_id=r["document_id"],
                caption=r["caption"], asset_path=r["asset_path"],
                ocr_text=r["ocr_text"], page=r["page"],
                is_chart=is_chart_plate(f"{r['caption']} {r['ocr_text']}"),
            )
            for r in rows
        ]
