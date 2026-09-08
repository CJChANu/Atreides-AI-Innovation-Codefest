"""Entity naming and normalisation.

The archive names the same thing several ways — "Weeping Lurker" as a wiki title,
"[[Weeping Lurker]]" as a link, "Weeping Lurker (creature)" as a heading. All must
collapse to one node, or multi-hop expansion silently splits in two.
"""

from __future__ import annotations

import re

_PARENTHETICAL = re.compile(r"\s*\([^)]*\)\s*$")
_NON_WORD = re.compile(r"[^\w\s]+", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")

# Wiki titles append a type in brackets; that bracket is a free type label.
_TYPE_HINTS = {
    "creature": "creature", "location": "place", "artifact": "artifact",
    "person": "person", "faction": "faction", "conflict": "event",
    "organization": "faction", "event": "event",
}


def normalise(name: str) -> str:
    """Return the canonical entity_id for a display name."""
    stripped = _PARENTHETICAL.sub("", name.strip())
    cleaned = _NON_WORD.sub(" ", stripped)
    return _WHITESPACE.sub("_", cleaned.strip().lower())


def type_hint(name: str) -> str:
    """Infer an entity type from a parenthetical suffix, e.g. 'X (creature)'."""
    match = re.search(r"\(([^)]*)\)\s*$", name.strip())
    if not match:
        return "unknown"
    return _TYPE_HINTS.get(match.group(1).strip().lower(), "unknown")


def display_name(name: str) -> str:
    return _PARENTHETICAL.sub("", name.strip()).strip()
