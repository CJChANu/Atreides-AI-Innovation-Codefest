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


# What a figure plate can actually answer. Plates in this archive carry exactly
# one thing: a measured quantity about their subject. They never state where a
# relic is housed, when it was forged, or what class it is — those live in the
# codex tables and the wiki infoboxes.
#
# Routing on this rather than on "is there a plate for this entity" is what stops
# the system searching an artifact's portrait for its housing location and then
# reporting the answer as unavailable because the painting has no labels. A plate
# exists for nearly every entity; that is not a reason to consult it.
FIGURE_ATTRIBUTES = frozenset({
    "threat_rating",
    "attunement_cost",
    "garrison_strength",
    "recorded_casualties",
    "shards_of_will",
})


# Attributes whose answer is the *picture itself*: what a banner shows, what a
# portrait's subject is holding. No table states these and no OCR recovers them,
# because there is nothing written to recover — they are the one class of
# question that genuinely requires looking at the image.
VISUAL_ATTRIBUTES = frozenset({
    "emblem", "banner", "heraldry", "appearance", "visual_identity", "arms_and_regalia",
    "clothing", "armament", "symbol",
})


def is_figure_attribute(attribute: str | None) -> bool:
    """True when a figure plate is a plausible source for this attribute."""
    return bool(attribute) and attribute in FIGURE_ATTRIBUTES


def is_visual_attribute(attribute: str | None) -> bool:
    """True when only an image can answer this — a painted emblem, an object held."""
    return bool(attribute) and attribute in VISUAL_ATTRIBUTES


def routes_to_figure(attribute: str | None) -> bool:
    """True when a figure is worth consulting for this attribute at all."""
    return is_figure_attribute(attribute) or is_visual_attribute(attribute)


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
