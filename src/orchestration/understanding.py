"""Turn a natural-language question into a structured investigation object.

This is deliberately rule-based first. The archive gives us a closed, known
vocabulary — 417 entities and a fixed set of attribute names — so matching against
what we have actually indexed is both more accurate and more auditable than asking
a model to guess. It also means the system works with no API key and no network,
which matters for a live demonstration on a free tier.

An LLM pass refines the result when a key is configured (see `llm_refine`), but it
can only ever *fill gaps*: it is not allowed to overrule an entity that was matched
against the index.
"""

from __future__ import annotations

import re

from src.graph.entities import normalise
from src.orchestration.state import Intent, Question
from src.storage.db import ArchiveStore

# Phrases that name an attribute in the fact store. Ordered longest-first at match
# time so "recorded garrison strength" wins over "garrison".
ATTRIBUTE_PHRASES: dict[str, str] = {
    "threat rating": "threat_rating", "threat-rating": "threat_rating",
    "threat classification": "threat_rating", "numerical rating": "threat_rating",
    "rating": "threat_rating",
    "attunement cost": "attunement_cost", "shards of will": "attunement_cost",
    "garrison strength": "garrison_strength", "garrison": "garrison_strength",
    "recorded casualties": "recorded_casualties", "casualties": "recorded_casualties",
    "founded": "founded", "founding": "founded", "foundation": "founded",
    "forged": "forging_date", "forging date": "forging_date",
    "forged at": "forging_site", "forging site": "forging_site",
    "place of forging": "forging_site",
    "housed": "housed_in", "housing": "housed_in", "repository": "housed_in",
    "artifact class": "artifact_class",
    "lair": "lair", "habit": "habit", "region": "region", "status": "status",
    "seat": "seat", "seated": "seat",
    "ruled by": "ruled_by", "ruler": "ruled_by", "dominion": "ruled_by",
    "rules": "ruled_by", "governs": "ruled_by",
    "member of": "member_of", "membership": "member_of", "belongs to": "member_of",
    "members": "has_member", "member": "member_of",
    "victor": "victor", "won": "victor", "win": "victor", "wins": "victor",
    "winner": "victor", "ultimately won": "victor",
    "outcome": "outcome", "began": "began", "ended": "ended",
    "born": "born", "birth": "born", "role": "role",
    "doctrine": "doctrine", "emblem": "emblem", "banner": "emblem",
    "belligerent": "belligerent_in",
    "serves": "serves_at", "service": "serves_at",
    # Phrasings the archive itself never uses, but a person naturally would.
    # Every one of these was added because a real question missed without it.
    "defenders": "garrison_strength", "defenders hold": "garrison_strength",
    "troops": "garrison_strength", "soldiers": "garrison_strength",
    "how many men": "garrison_strength", "strength of the garrison": "garrison_strength",
    "came out on top": "victor", "prevailed": "victor", "triumphed": "victor",
    "makes its home": "lair", "makes their home": "lair", "nests": "lair",
    "dwells": "lair", "lives": "lair", "home of": "lair",
    "begin": "began", "started": "began", "broke out": "began",
    "end": "ended", "concluded": "ended", "finished": "ended",
    "descent": "doctrine", "claims descent": "doctrine",
    "sits": "seat", "based at": "seat", "headquarters": "seat",
}

# Two attributes describing the same event from different angles. When the
# question word disagrees with the attribute a phrase matched — "*Where* was it
# forged" matching `forging_date` — we swap to the sibling instead of answering
# the wrong question confidently.
ATTRIBUTE_SIBLINGS = {
    "forging_date": "forging_site",
    "forging_site": "forging_date",
    "founded": "location",
    "born": "birthplace",
}

# What each opening word expects the answer to *be*.
PLACE_WORDS = re.compile(r"^\s*(where|in which (place|city|hold|keep|fortress|region))\b", re.I)
TIME_WORDS = re.compile(r"^\s*(when|in (which|what) year|what year)\b", re.I)

PLACE_ATTRS = {"forging_site", "seat", "lair", "housed_in", "region", "location", "serves_at"}
TIME_ATTRS = {"forging_date", "founded", "born", "began", "ended", "birth"}

# Words that signal the asker already suspects the sources disagree. These are the
# 1C questions: "the *true* founding", "in which year was it *actually* forged".
CONFLICT_MARKERS = re.compile(
    r"\b(actually|truly|true|really|precise|precisely|exact|exactly|definitive|"
    r"in fact|genuine|correct)\b", re.IGNORECASE
)

# A question naming a relation *about* another relation is two hops:
# "the lair of X" then "who rules that", "the faction of which X is a member" then
# "what did that faction win".
BRIDGE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # "the lair of X", but also "the place where X lairs" — the same hop phrased
    # as a clause. The relation comes from the *verb* in the clause, never from
    # the word "place": "the place where X lairs" and "the place where X is
    # housed" are different hops, and collapsing them answers the wrong question.
    (re.compile(r"\blair\s+of\b", re.IGNORECASE), "lair"),
    # A verb clause is only a *bridge* when it modifies a place noun — we want
    # that place, then something about it. Without the head noun the same verb is
    # the question's own relation: "which creature lairs in Y" asks for the
    # creature, not for a hop, and treating it as one answers the wrong thing.
    (re.compile(r"\b(place|site|region|territory|land|hold|seat)\s+(where|in which)\b"
                r"[^?]{0,70}?\b(lairs|dwells|nests|makes (its|their) home)\b", re.IGNORECASE), "lair"),
    (re.compile(r"\b(place|site|hold|vault)\s+(where|in which)\b[^?]{0,70}?"
                r"\b(housed|kept|held|stored)\b", re.IGNORECASE), "housed_in"),
    (re.compile(r"\b(place|site|hold)\s+(where|in which)\b[^?]{0,70}?"
                r"\b(seated|based)\b", re.IGNORECASE), "seat"),
    (re.compile(r"\b(place|site|forge)\s+(where|in which)\b[^?]{0,70}?"
                r"\bforged\b", re.IGNORECASE), "forging_site"),
    (re.compile(r"\bfaction\s+of\s+which\b|\bfaction\s+that\b|\bfaction\b", re.IGNORECASE), "member_of"),
    (re.compile(r"\borganization\s+that\b|\borganisation\s+that\b", re.IGNORECASE), "member_of"),
    (re.compile(r"\bseat\s+of\b", re.IGNORECASE), "seat"),
    (re.compile(r"\bhome\s+of\b|\bhoused\s+in\b", re.IGNORECASE), "housed_in"),
]

# Words that constrain which of several returned values is wanted.
FILTER_WORDS = {"accord", "war", "purge", "reckoning", "siege", "battle", "treaty"}

_QUESTION_HEAD = re.compile(r"^(which|what|who|whose|where|when|how many|how much|in which|state)\b",
                            re.IGNORECASE)


class QuestionAnalyzer:
    def __init__(self, store: ArchiveStore) -> None:
        # Entity surface forms come from what we actually indexed, so the analyzer
        # can never "recognise" something the archive does not contain.
        rows = store.connection.execute(
            "SELECT entity_id, name FROM entities WHERE length(name) > 2"
        ).fetchall()
        self._by_surface: dict[str, tuple[str, str]] = {}
        for row in rows:
            surface = row["name"].lower()
            # A handful of table labels ("Forged", "Region") leak into the entity
            # table from plain-text infobox values. Treating them as entities
            # would shadow the attribute phrase of the same name.
            if surface in ATTRIBUTE_PHRASES:
                continue
            self._by_surface.setdefault(surface, (row["entity_id"], row["name"]))
        # Attributes the fact store actually holds. This is what an LLM-proposed
        # relation is checked against, so the archive — not a hardcoded list —
        # decides what counts as a real relation.
        self.known_attributes = {
            row["attribute"] for row in
            store.connection.execute("SELECT DISTINCT attribute FROM facts")
        }
        subjects = store.connection.execute(
            "SELECT DISTINCT subject_id, subject_name FROM facts"
        ).fetchall()
        for row in subjects:
            surface = row["subject_name"].lower()
            # Same guard as above, and it matters more here: a codex table whose
            # heading was mis-parsed can leave a *subject* called "Region", which
            # then matches the word "region" in "Which region contains…" and
            # shadows the entity the question is actually about.
            if surface in ATTRIBUTE_PHRASES:
                continue
            self._by_surface.setdefault(surface, (row["subject_id"], row["subject_name"]))
        # Longest surfaces first: "Greyfell Citadel" must beat "Greyfell".
        self._surfaces = sorted(self._by_surface, key=len, reverse=True)

    # -- entity matching ----------------------------------------------------

    def match_entities(self, text: str) -> list[tuple[str, str]]:
        """Longest-match known entity names against the question text.

        Matching against the index rather than running a general NER model is the
        whole point: the vocabulary is invented, so "Vharencrag Fortress" is only
        recognisable because we have it, and a name we do not have is a name we
        could not have cited anyway.
        """
        lowered = text.lower()
        consumed = [False] * len(lowered)
        found: list[tuple[str, str]] = []

        for surface in self._surfaces:
            start = lowered.find(surface)
            while start >= 0:
                end = start + len(surface)
                # Whole-token match only, and not inside an already-claimed span.
                before_ok = start == 0 or not lowered[start - 1].isalnum()
                after_ok = end >= len(lowered) or not lowered[end].isalnum()
                if before_ok and after_ok and not any(consumed[start:end]):
                    for index in range(start, end):
                        consumed[index] = True
                    found.append((self._by_surface[surface], start))
                    break
                start = lowered.find(surface, start + 1)

        found.sort(key=lambda item: item[1])
        return [entity for entity, _ in found]

    # -- attribute matching -------------------------------------------------

    @staticmethod
    def match_attribute(text: str, exclude: str | None = None) -> str | None:
        lowered = text.lower()
        best: tuple[int, str] | None = None
        for phrase, attribute in ATTRIBUTE_PHRASES.items():
            if attribute == exclude or phrase not in lowered:
                continue
            if best is None or len(phrase) > best[0]:
                best = (len(phrase), attribute)
        if best is None:
            return None

        attribute = best[1]
        # "Where was the Gauntlet forged?" matches the phrase "forged", which maps
        # to the *date*. The opening word says the asker wants a place, so prefer
        # the sibling. Answering the wrong question confidently is worse than
        # answering none.
        sibling = ATTRIBUTE_SIBLINGS.get(attribute)
        if sibling:
            if PLACE_WORDS.match(text) and attribute in TIME_ATTRS and sibling in PLACE_ATTRS:
                return sibling
            if TIME_WORDS.match(text) and attribute in PLACE_ATTRS and sibling in TIME_ATTRS:
                return sibling
        return attribute

    @staticmethod
    def match_bridge(text: str) -> str | None:
        for pattern, attribute in BRIDGE_PATTERNS:
            if pattern.search(text):
                return attribute
        return None

    # -- assembly -----------------------------------------------------------

    def analyze(self, text: str) -> Question:
        entities = self.match_entities(text)
        bridge = self.match_bridge(text)
        attribute = self.match_attribute(text, exclude=bridge)
        expects_conflict = bool(CONFLICT_MARKERS.search(text))

        if bridge and attribute and attribute != bridge:
            intent = Intent.RELATION_HOP
        elif expects_conflict and attribute:
            intent = Intent.CONFLICT_RESOLUTION
        elif attribute and entities:
            intent = Intent.ATTRIBUTE_LOOKUP
        elif attribute and not entities:
            intent = Intent.INVERSE_HOP
        else:
            intent = Intent.OPEN_QUESTION

        if not entities:
            intent = Intent.INVERSE_HOP if attribute else Intent.OPEN_QUESTION

        return Question(
            text=text,
            intent=intent,
            entities=entities,
            attribute=attribute,
            bridge_attribute=bridge if bridge != attribute else None,
            answer_type=self._answer_type(text, attribute),
            expects_conflict=expects_conflict,
            filter_terms=sorted(FILTER_WORDS & set(re.findall(r"[a-z]+", text.lower()))),
        )

    @staticmethod
    def _answer_type(text: str, attribute: str | None) -> str:
        lowered = text.lower()
        if lowered.startswith(("how many", "how much")) or attribute in {
            "threat_rating", "attunement_cost", "garrison_strength", "recorded_casualties"
        }:
            return "number"
        if attribute in {"founded", "forging_date", "born", "began", "ended"}:
            return "year"
        if _QUESTION_HEAD.match(lowered) and lowered.split()[0] in {"which", "who", "whose"}:
            return "entity"
        return "value"


def normalise_name(name: str) -> str:
    return normalise(name)
