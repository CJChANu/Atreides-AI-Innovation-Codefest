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
from src.orchestration.state import Calculation, Intent, Operand, Question
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

# Attributes whose values are numbers. A calculation can only be built over
# these, which is also what stops "what percentage of the wars did X win" from
# being parsed as arithmetic over two names.
NUMERIC_ATTRIBUTES = {
    "threat_rating", "attunement_cost", "garrison_strength", "recorded_casualties",
    "shards_of_will",
}

# Question shapes that ask for arithmetic rather than a lookup. Each maps to the
# formula kind; the operand *order* is worked out separately, because "what
# percentage of A is B" and "B as a percentage of A" put the same operand in the
# denominator despite naming them in opposite orders.
CALCULATION_MARKERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bwhat\s+percent(age)?\b|\bas\s+a\s+percent(age)?\s+of\b|"
                r"\bpercent(age)?\s+of\b", re.IGNORECASE), "percentage"),
    (re.compile(r"\bratio\s+of\b|\bhow\s+many\s+times\b|\btimes\s+(larger|greater|"
                r"bigger|smaller|as\s+many|as\s+large)\b", re.IGNORECASE), "ratio"),
    (re.compile(r"\bdifference\s+between\b|\bhow\s+much\s+(larger|greater|smaller|"
                r"more|less)\b|\bhow\s+many\s+(more|fewer|less)\b", re.IGNORECASE), "difference"),
    (re.compile(r"\bcombined\b|\btotal\s+of\b|\bsum\s+of\b|\btogether\b|"
                r"\badded\s+together\b", re.IGNORECASE), "total"),
    (re.compile(r"\baverage\b|\bmean\s+of\b", re.IGNORECASE), "average"),
]

# The word that introduces the denominator in a percentage or ratio question.
_DENOMINATOR_CUE = re.compile(r"\bpercent(?:age)?\s+of\b|\bratio\s+of\b|\bof\b", re.IGNORECASE)


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

    def locate_entities(self, text: str) -> list[tuple[tuple[str, str], int, int]]:
        """Every known entity in the text, as ``(entity, start, end)``.

        Same longest-match-wins scan as `match_entities`, but it keeps the spans.
        A question that names two subjects needs to know *where* each one sits in
        order to work out which attribute belongs to which — "Embermarch's
        garrison strength" and "the Aegis' attunement cost" are only separable by
        position.
        """
        lowered = text.lower()
        consumed = [False] * len(lowered)
        found: list[tuple[tuple[str, str], int, int]] = []

        for surface in self._surfaces:
            start = lowered.find(surface)
            while start >= 0:
                end = start + len(surface)
                before_ok = start == 0 or not lowered[start - 1].isalnum()
                after_ok = end >= len(lowered) or not lowered[end].isalnum()
                if before_ok and after_ok and not any(consumed[start:end]):
                    for index in range(start, end):
                        consumed[index] = True
                    found.append((self._by_surface[surface], start, end))
                    break
                start = lowered.find(surface, start + 1)

        found.sort(key=lambda item: item[1])
        return found

    def match_entities(self, text: str) -> list[tuple[str, str]]:
        """Longest-match known entity names against the question text.

        Matching against the index rather than running a general NER model is the
        whole point: the vocabulary is invented, so "Vharencrag Fortress" is only
        recognisable because we have it, and a name we do not have is a name we
        could not have cited anyway.
        """
        return [entity for entity, _, _ in self.locate_entities(text)]

    def locate_attributes(self, text: str) -> list[tuple[str, int, int]]:
        """Every attribute phrase in the text, as ``(attribute, start, end)``.

        `match_attribute` answers "what is this question about"; this answers
        "what does it mention", which is what a two-operand question needs. Longer
        phrases win over shorter ones covering the same span, and each attribute
        is reported once per position rather than once overall.
        """
        lowered = text.lower()
        consumed = [False] * len(lowered)
        found: list[tuple[str, int, int]] = []

        for phrase in sorted(ATTRIBUTE_PHRASES, key=len, reverse=True):
            attribute = ATTRIBUTE_PHRASES[phrase]
            start = lowered.find(phrase)
            while start >= 0:
                end = start + len(phrase)
                before_ok = start == 0 or not lowered[start - 1].isalnum()
                after_ok = end >= len(lowered) or not lowered[end].isalnum()
                # A comparison asks for "the threat rating*s* of A and B". The
                # vocabulary is singular, so without this the plural form matches
                # nothing and the question silently loses its attribute — which
                # is how comparing two creatures ended up answering about one.
                if not after_ok and lowered[end] == "s":
                    plural_end = end + 1
                    if plural_end >= len(lowered) or not lowered[plural_end].isalnum():
                        after_ok, end = True, plural_end
                if before_ok and after_ok and not any(consumed[start:end]):
                    for index in range(start, end):
                        consumed[index] = True
                    found.append((attribute, start, end))
                start = lowered.find(phrase, end if after_ok else start + 1)

        found.sort(key=lambda item: item[1])
        return found

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

    # -- calculations -------------------------------------------------------

    @staticmethod
    def match_calculation(text: str) -> str | None:
        """The kind of arithmetic the question asks for, if any."""
        for pattern, kind in CALCULATION_MARKERS:
            if pattern.search(text):
                return kind
        return None

    def _corrected_attributes(self, text: str) -> list[tuple[str, int, int]]:
        """Attribute spans, with place/time siblings resolved from the question.

        The archive uses one word, "forged", for two attributes: where and when.
        `match_attribute` already reads the question word to pick the right one
        for a single lookup; the same reasoning has to be applied here, or
        "Where were the Edge and the Lantern forged" compares forging *years*.

        A question can also ask for both at once — "Where *and in which year* was
        it forged" — in which case both siblings are required, not one of them.
        """
        found = self.locate_attributes(text)
        wants_place = bool(PLACE_WORDS.match(text)) or bool(
            re.search(r"\bwhere\b|\bin which (place|city|hold|keep|fortress|region)\b",
                      text, re.IGNORECASE))
        wants_time = bool(TIME_WORDS.match(text)) or bool(
            re.search(r"\bwhen\b|\bin (which|what) year\b|\bwhat year\b",
                      text, re.IGNORECASE))

        corrected: list[tuple[str, int, int]] = []
        for attribute, start, end in found:
            sibling = ATTRIBUTE_SIBLINGS.get(attribute)
            if sibling is None:
                corrected.append((attribute, start, end))
                continue

            pair = {attribute, sibling}
            place = next((item for item in pair if item in PLACE_ATTRS), None)
            time = next((item for item in pair if item in TIME_ATTRS), None)

            # Both asked for: the one word carries two requirements.
            if wants_place and wants_time and place and time:
                corrected.append((place, start, end))
                corrected.append((time, start, end))
                continue
            if wants_place and place:
                corrected.append((place, start, end))
                continue
            if wants_time and time:
                corrected.append((time, start, end))
                continue
            corrected.append((attribute, start, end))

        corrected.sort(key=lambda item: (item[1], item[0]))
        return corrected

    def build_requirements(self, text: str) -> list[Operand]:
        """Every (subject, attribute) this question asks to be established.

        A long question is a list of small ones. "Where and in which year was the
        Aegis forged, and where is it housed" asks for three separate facts about
        one subject; "compare the threat ratings of A and B" asks for the same
        fact about two subjects. Both used to collapse to whichever single
        attribute matched first, and the rest of the question was silently
        dropped — the loop reported "all sub-questions supported" having answered
        a third of what was asked.

        Unlike `build_operands` this accepts non-numeric attributes, because a
        forging site is a perfectly good thing to be asked for.
        """
        entities = self.locate_entities(text)
        attributes = self._corrected_attributes(text)
        if not entities or not attributes:
            return []

        requirements: list[Operand] = []
        seen: set[tuple[str, str]] = set()

        distinct = {attribute for attribute, _, _ in attributes}
        # One attribute, several subjects: a comparison. The attribute applies to
        # each of them ("the threat ratings of the Lurker and the Revenant").
        if len(distinct) == 1 and len(entities) > 1:
            attribute = next(iter(distinct))
            for (subject_id, name), _, _ in entities:
                if (subject_id, attribute) not in seen:
                    seen.add((subject_id, attribute))
                    requirements.append(
                        Operand(subject_id=subject_id, subject_name=name, attribute=attribute))
            return requirements

        # Otherwise attach each attribute to its own subject by position, exactly
        # as a reader would: the nearest name before it, else the nearest after.
        for attribute, start, end in attributes:
            before = [item for item in entities if item[2] <= start]
            after = [item for item in entities if item[1] >= end]
            chosen = before[-1] if before else (after[0] if after else None)
            if chosen is None:
                continue
            (subject_id, name), _, _ = chosen
            if (subject_id, attribute) in seen:
                continue
            seen.add((subject_id, attribute))
            requirements.append(
                Operand(subject_id=subject_id, subject_name=name, attribute=attribute))
        return requirements

    def build_operands(self, text: str) -> list[Operand]:
        """Pair every numeric attribute in the question with its own subject.

        The pairing is positional: an attribute belongs to the nearest entity
        *before* it ("Embermarch's garrison strength"), falling back to the
        nearest one after ("the garrison strength of Embermarch"). Attributes
        that no entity can be attached to are dropped rather than guessed at —
        an operand without a subject cannot be looked up, and inventing one is
        exactly the failure this whole path exists to prevent.
        """
        entities = self.locate_entities(text)
        if not entities:
            return []

        operands: list[Operand] = []
        seen: set[tuple[str, str]] = set()
        for attribute, start, end in self.locate_attributes(text):
            if attribute not in NUMERIC_ATTRIBUTES:
                continue
            before = [item for item in entities if item[2] <= start]
            after = [item for item in entities if item[1] >= end]
            chosen = before[-1] if before else (after[0] if after else None)
            if chosen is None:
                continue
            (subject_id, name), _, _ = chosen
            if (subject_id, attribute) in seen:
                continue
            seen.add((subject_id, attribute))
            operands.append(Operand(subject_id=subject_id, subject_name=name,
                                    attribute=attribute, must_be_numeric=True))

        # "the difference between the garrison strength of Marrowwatch and
        # Thorncairn" names the attribute once and the subjects twice. The
        # positional pass can only attach it to one of them, so when a single
        # numeric attribute is shared across several named subjects, read it as
        # applying to each — that is what the sentence means.
        numeric = {attribute for attribute, _, _ in self.locate_attributes(text)
                   if attribute in NUMERIC_ATTRIBUTES}
        if len(operands) < 2 and len(numeric) == 1 and len(entities) >= 2:
            shared = next(iter(numeric))
            operands = [
                Operand(subject_id=subject_id, subject_name=name, attribute=shared,
                        must_be_numeric=True)
                for (subject_id, name), _, _ in entities
            ]
        return operands

    @staticmethod
    def order_calculation(kind: str, text: str, operands: list[Operand],
                          spans: list[tuple[str, int, int]]) -> Calculation:
        """Decide which operand is the numerator and which the denominator.

        Both "what percentage of A is B" and "B as a percentage of A" mean
        B ÷ A: in each the denominator is the operand named after the word "of".
        Reading the cue word rather than the surface order is what keeps the two
        phrasings from producing reciprocal answers.
        """
        calculation = Calculation(kind=kind)
        if not calculation.is_pairwise or len(operands) < 2:
            return calculation

        # When both operands carry the *same* attribute the cue word cannot tell
        # them apart ("the ratio of the threat rating of A to that of B" puts
        # "of" before both). Source order is the reading a person would take.
        if len({operand.attribute for operand in operands}) < 2:
            return calculation

        cue = _DENOMINATOR_CUE.search(text)
        if cue is None:
            return calculation

        # Which attribute phrase is the first one after the cue word?
        following = [span for span in spans
                     if span[1] >= cue.end() and span[0] in NUMERIC_ATTRIBUTES]
        if not following:
            return calculation
        denominator_attribute = following[0][0]
        for index, operand in enumerate(operands):
            if operand.attribute == denominator_attribute:
                calculation.denominator = index
                calculation.numerator = 1 - index if len(operands) == 2 else 0
                break
        return calculation

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

        # A calculation question is the one case where a single attribute slot is
        # not enough: it needs a value for *each* named subject, and answering it
        # from whichever one the rules happened to match first is how a system
        # ends up ignoring half the question.
        calculation_kind = self.match_calculation(text)
        operands: list[Operand] = []
        calculation: Calculation | None = None
        if calculation_kind:
            # Every supported formula needs at least two numbers, pairwise or not.
            operands = self.build_operands(text)
            if len(operands) >= 2:
                calculation = self.order_calculation(
                    calculation_kind, text, operands, self.locate_attributes(text)
                )
            else:
                # Not enough grounded operands to compute anything. Fall through
                # to the ordinary lookup path rather than promising arithmetic we
                # cannot perform.
                operands = []

        if calculation is not None:
            return Question(
                text=text, intent=Intent.CALCULATION, entities=entities,
                attribute=attribute, bridge_attribute=None, answer_type="number",
                expects_conflict=expects_conflict,
                filter_terms=sorted(FILTER_WORDS & set(re.findall(r"[a-z]+", text.lower()))),
                operands=operands, calculation=calculation,
            )

        # A question asking for several distinct facts is several questions. This
        # is checked *after* the hop test on purpose: "the faction of which X is a
        # member, and what it won" also names two attributes, but it is one chain,
        # not two independent lookups, and splitting it would break the hop.
        if not (bridge and attribute and attribute != bridge):
            requirements = self.build_requirements(text)
            if len(requirements) > 1:
                return Question(
                    text=text, intent=Intent.MULTI_FACT, entities=entities,
                    attribute=attribute, answer_type=self._answer_type(text, attribute),
                    expects_conflict=expects_conflict,
                    filter_terms=sorted(FILTER_WORDS & set(re.findall(r"[a-z]+", text.lower()))),
                    operands=requirements,
                )

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
