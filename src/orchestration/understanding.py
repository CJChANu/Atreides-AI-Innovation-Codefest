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
}

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
    (re.compile(r"\blair\s+of\b", re.IGNORECASE), "lair"),
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
        subjects = store.connection.execute(
            "SELECT DISTINCT subject_id, subject_name FROM facts"
        ).fetchall()
        for row in subjects:
            self._by_surface.setdefault(row["subject_name"].lower(),
                                        (row["subject_id"], row["subject_name"]))
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
        return best[1] if best else None

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
