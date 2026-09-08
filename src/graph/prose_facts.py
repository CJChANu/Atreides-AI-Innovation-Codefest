"""Reading a stated attribute out of a sentence, when no table holds it.

The fact store is built from key/value grids — infoboxes and codex tables — which
is what makes it precise. But the archive does not always use a table. The
Cinder-Wrought Aegis' forging year appears exactly once, in the prose of a
quartermaster's contract:

    Its forged year is **354 AS**.

The wiki's own article says the date is contested and directs the reader to
another source; the table extractor sees nothing, and the question came back
"not established" while the answer sat in the corpus. Retrieval found the right
passage every time — nothing was missing but the last step of reading it.

So this module is that last step, and it is deliberately the narrowest thing
that works: a small set of patterns, one per attribute, each requiring the
subject to be named in the same passage, each returning the span it matched so
the claim can be cited to a real chunk. It is a *fallback*. A value in a table
always wins, because a table is a stated record and a sentence is a sentence.

What it will not do is guess. No pattern here matches a bare number or a bare
name; every one of them requires the archive's own phrasing around the value.
That is the difference between reading a source and mining it for anything that
looks like an answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# In-world dates are always "<number> AS".
_YEAR = r"(\d{1,4}\s*AS)"
# A place or entity name: wikilinked, bolded, or plain title case. Kept tight —
# a loose name pattern is how a prose reader starts inventing entities.
_NAME = r"(?:\[\[)?\*{0,2}([A-Z][\w'’-]*(?:\s+[A-Z][\w'’-]*){0,3})\*{0,2}(?:\]\])?"
_NUMBER = r"([\d][\d,]*)"

# attribute -> patterns that state it. Each pattern must capture the value in
# group 1 and must include enough of the archive's phrasing that it cannot fire
# on unrelated text.
ATTRIBUTE_PATTERNS: dict[str, tuple[str, ...]] = {
    "forging_date": (
        rf"\bforged\s+year\s+is\s+\*{{0,2}}{_YEAR}",
        rf"\bwas\s+forged\s+in\s+\*{{0,2}}{_YEAR}",
        rf"\bforged\s+in\s+the\s+year\s+\*{{0,2}}{_YEAR}",
        rf"\bforging\s+year\s+(?:is|was)\s+\*{{0,2}}{_YEAR}",
    ),
    "forging_site": (
        rf"\bwas\s+forged\s+at\s+{_NAME}",
        rf"\bforged\s+at\s+{_NAME}",
        rf"\bplace\s+of\s+forging\s+is\s+{_NAME}",
    ),
    "housed_in": (
        rf"\bis\s+housed\s+in\s+{_NAME}",
        rf"\bhoused\s+in\s+{_NAME}",
        rf"\bcurrently\s+kept\s+at\s+{_NAME}",
    ),
    "founded": (
        rf"\bwas\s+founded\s+in\s+\*{{0,2}}{_YEAR}",
        rf"\bfounding\s+year\s+is\s+\*{{0,2}}{_YEAR}",
    ),
    "attunement_cost": (
        rf"\battunement\s+cost\s+(?:is|of)\s+\*{{0,2}}{_NUMBER}",
    ),
    "threat_rating": (
        rf"\bthreat\s+rating\s+(?:is|of)\s+\*{{0,2}}{_NUMBER}",
    ),
    "garrison_strength": (
        rf"\bgarrison\s+strength\s+(?:is|of)\s+\*{{0,2}}{_NUMBER}",
        rf"\bgarrison\s+of\s+\*{{0,2}}{_NUMBER}",
    ),
    "recorded_casualties": (
        rf"\brecorded\s+casualties\s+(?:are|is|of)\s+\*{{0,2}}{_NUMBER}",
        rf"\bcasualties\s+(?:are|is|of)\s+\*{{0,2}}{_NUMBER}",
    ),
}

# How the *archive* says each attribute, for building a retrieval query. The
# canonical names are ours, not the corpus's: searching "forging date" ranks the
# infobox pages that do not state it, while "forged year" — the archive's own
# wording — puts the sentence that does state it in the first few hits. The
# difference decided whether the Aegis' forging year was findable at all.
SEARCH_PHRASES: dict[str, tuple[str, ...]] = {
    "forging_date": ("forged year", "was forged in"),
    "forging_site": ("forged at", "place of forging"),
    "housed_in": ("housed in", "current repository"),
    "founded": ("was founded in", "founding year"),
    "attunement_cost": ("attunement cost",),
    "threat_rating": ("threat rating",),
    "garrison_strength": ("garrison strength", "souls under arms"),
    "recorded_casualties": ("recorded casualties", "souls lost"),
}


def search_queries(subject: str, attribute: str) -> list[str]:
    """Retrieval queries most likely to surface a sentence stating this value."""
    phrases = SEARCH_PHRASES.get(attribute, ())
    queries = [f"{subject} {phrase}" for phrase in phrases]
    queries.append(subject)
    return queries


_COMPILED: dict[str, tuple[re.Pattern[str], ...]] = {
    attribute: tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)
    for attribute, patterns in ATTRIBUTE_PATTERNS.items()
}

# Sentences that mention the value only to say it is disputed or absent. Reading
# a year out of "the forged year is contested" would turn a documented
# disagreement into a false certainty.
_HEDGE = re.compile(
    r"\b(contested|disputed|uncertain|no single account|not recorded|unrecorded|"
    r"remains? unclear|cannot be established)\b", re.IGNORECASE
)


@dataclass
class ProseFact:
    """A value read from a sentence, with the text that justifies it."""

    attribute: str
    value_text: str
    sentence: str

    def quote(self, limit: int = 160) -> str:
        cleaned = " ".join(self.sentence.split())
        return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


def _sentences(text: str) -> list[str]:
    return [part for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def _fold(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower())


# "Its forged year is 354 AS." — the archive names the subject in one sentence
# and states the value in the next. A pronoun opener is only trusted when the
# subject was named in the sentence immediately before it.
_PRONOUN_OPENER = re.compile(r"^\s*(its|it|this|the artifact|the relic|the regalia)\b",
                             re.IGNORECASE)


def extract(text: str, subject: str, attribute: str) -> ProseFact | None:
    """Read `attribute` for `subject` out of `text`, or return None.

    Scans sentence by sentence, so a value can never be paired with a subject
    named three sentences away, and so the sentence itself can be quoted as the
    evidence for the claim.
    """
    patterns = _COMPILED.get(attribute)
    if not patterns or not text:
        return None

    target = _fold(subject).strip()
    if not target:
        return None

    subject_named_previously = False
    for sentence in _sentences(text):
        names_subject = target in _fold(sentence)
        about = names_subject or (subject_named_previously and _PRONOUN_OPENER.match(sentence))

        if about and not _HEDGE.search(sentence):
            for pattern in patterns:
                match = pattern.search(sentence)
                if match:
                    value = " ".join(match.group(1).split()).strip(" .,;*")
                    if value:
                        return ProseFact(attribute=attribute, value_text=value,
                                         sentence=sentence)

        # A sentence that says nothing about the subject breaks the chain, so a
        # later "Its ..." cannot attach to a subject from a different paragraph.
        subject_named_previously = names_subject or (
            subject_named_previously and bool(_PRONOUN_OPENER.match(sentence))
        )
    return None
