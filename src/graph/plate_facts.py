"""Attribute extraction from figure-plate OCR.

Some facts in this archive exist *only* as printed labels on an illustration.
The Weeping Lurker's threat rating, for example, appears in no table and no
sentence — only on ``plate_08_creature_weeping_lurker.png``. A text-only pipeline
cannot answer that question at all, which is why plate OCR is a correctness
requirement here rather than a flourish.

Plates follow a rigid house style: a subject line, an upper-case label, then the
value ("Marrowwatch RECORDED GARRISON STRENGTH 3,107 souls under arms"). A small
labelled-number grammar is therefore more accurate *and* more auditable than
asking a model to read the plate, and it costs no API calls.
"""

from __future__ import annotations

import re

# Label phrase (as printed on the plate) -> canonical attribute name.
PLATE_LABELS = {
    "recorded garrison strength": "garrison_strength",
    "garrison strength": "garrison_strength",
    "threat rating": "threat_rating",
    "attunement cost": "attunement_cost",
    "recorded casualties": "recorded_casualties",
    "casualties": "recorded_casualties",
    "shards of will": "shards_of_will",
}

# Matches "3,107", "20", "67,349" — the value always follows its label.
_NUMBER_AFTER = re.compile(r"[^\d]{0,40}?(\d[\d,]*)")

# Some plates are *charts*: the label names an axis and the real value is drawn as
# a bar, with these words printed as scale reference marks. OCR reads the axis
# ticks perfectly and the bar not at all, so a number pulled from such a plate is
# as likely to be an axis maximum as the answer. We refuse to assert those rather
# than publish a number we cannot justify — see docs/limitations.md.
_CHART_LEGEND = re.compile(
    r"\b(tolerance|minimum|standard|measured in|per the .{0,20}scale)\b", re.IGNORECASE
)


def is_chart_plate(text: str) -> bool:
    """True when the plate draws its value on a scale rather than printing it."""
    return len(_CHART_LEGEND.findall(text)) >= 2


def extract_plate_facts(caption: str, ocr_text: str) -> list[tuple[str, str, float | None]]:
    """Return ``(attribute, value_text, value_number)`` for each labelled number.

    Only the *first* number after a label is taken, and chart-style plates yield
    nothing at all: on those the printed numbers are scale ticks, not the value.
    """
    haystack = " ".join(f"{caption} {ocr_text}".split())
    if is_chart_plate(haystack):
        return []
    lowered = haystack.lower()
    found: list[tuple[str, str, float | None]] = []
    seen: set[str] = set()

    for phrase, attribute in PLATE_LABELS.items():
        if attribute in seen:
            continue
        position = lowered.find(phrase)
        if position < 0:
            continue
        match = _NUMBER_AFTER.match(haystack, position + len(phrase))
        if not match:
            continue
        raw = match.group(1)
        found.append((attribute, raw, float(raw.replace(",", ""))))
        seen.add(attribute)
    return found


def subject_from_caption(caption: str) -> str:
    """'Creature plate: Weeping Lurker' -> 'Weeping Lurker'."""
    _, _, tail = caption.partition(":")
    return (tail or caption).strip()
