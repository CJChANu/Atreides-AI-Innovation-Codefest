"""Question analysis drives every later step, so its classification is pinned."""

import pytest

from src.orchestration.understanding import CONFLICT_MARKERS, QuestionAnalyzer
from src.orchestration.state import Intent


class _FakeStore:
    """Minimal stand-in: the analyzer only needs entity and subject surfaces."""

    def __init__(self, names):
        self._names = names

    class _Cursor:
        """sqlite3 cursors are both iterable and fetchall-able; so is this."""

        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

        def __iter__(self):
            return iter(self._rows)

    @property
    def connection(self):
        return self

    def execute(self, sql, params=()):
        if "FROM entities" in sql:
            return self._Cursor([{"entity_id": n.lower().replace(" ", "_"), "name": n}
                                 for n in self._names])
        if "DISTINCT attribute" in sql:
            return self._Cursor([{"attribute": a} for a in
                                 ("lair", "ruled_by", "garrison_strength", "victor",
                                  "forging_date", "forging_site", "founded")])
        return self._Cursor([])


@pytest.fixture
def analyzer():
    return QuestionAnalyzer(_FakeStore([
        "Gravemaw Wyrm", "Gloamreach", "Greyfell Citadel", "Greyfell",
        "Ederon Fellgard", "Gauntlet of Sorrowfell",
    ]))


def test_longest_entity_name_wins(analyzer):
    """'Greyfell Citadel' must not be matched as the shorter 'Greyfell'."""
    names = [name for _, name in analyzer.analyze("garrison of Greyfell Citadel").entities]
    assert names == ["Greyfell Citadel"]


def test_entities_are_matched_on_whole_tokens(analyzer):
    assert analyzer.analyze("Gloamreachward marches").entities == []


def test_conflict_markers_flag_the_1c_questions(analyzer):
    q = analyzer.analyze("In which year was the Gauntlet of Sorrowfell actually forged?")
    assert q.expects_conflict
    assert q.intent is Intent.CONFLICT_RESOLUTION
    assert q.attribute == "forging_date"


@pytest.mark.parametrize("phrase", ["actually", "truly", "the precise year", "in fact"])
def test_conflict_marker_vocabulary(phrase):
    assert CONFLICT_MARKERS.search(f"what is {phrase} recorded")


def test_two_relations_are_recognised_as_a_hop(analyzer):
    q = analyzer.analyze("Whose dominion encompasses the lair of the Gravemaw Wyrm?")
    assert q.intent is Intent.RELATION_HOP
    assert q.bridge_attribute == "lair"
    assert q.attribute == "ruled_by"


def test_plain_attribute_question_is_a_lookup(analyzer):
    q = analyzer.analyze("What is the garrison strength of Greyfell Citadel?")
    assert q.intent is Intent.ATTRIBUTE_LOOKUP
    assert q.attribute == "garrison_strength"
    assert q.answer_type == "number"


def test_constraint_words_are_captured_for_narrowing(analyzer):
    q = analyzer.analyze("Which accord was won by the faction of Ederon Fellgard?")
    assert "accord" in q.filter_terms


def test_a_field_label_is_not_treated_as_an_entity(analyzer):
    """A mis-parsed table heading can leave a *subject* named "Region".

    Left in the surface index it matches the word "region" in "Which region
    contains…", shadows the entity the question is about, and the whole
    investigation runs against the wrong subject.
    """
    names = [name for _, name in
             analyzer.analyze("Which region contains the lair of the Gravemaw Wyrm?").entities]
    assert names == ["Gravemaw Wyrm"]


def test_the_question_word_picks_between_sibling_attributes(analyzer):
    """"Where was it forged" and "when was it forged" share a phrase."""
    assert analyzer.analyze("Where was the Gauntlet of Sorrowfell forged?").attribute == "forging_site"
    assert analyzer.analyze("In which year was the Gauntlet of Sorrowfell forged?").attribute == "forging_date"


def test_a_verb_clause_is_a_hop_only_when_it_modifies_a_place(analyzer):
    """"the place where X lairs" is a hop; "which creature lairs in Y" is not."""
    hop = analyzer.analyze("Which faction rules the place where the Gravemaw Wyrm lairs?")
    assert hop.bridge_attribute == "lair"

    inverse = analyzer.analyze("Which creature lairs in Gloamreach?")
    assert inverse.bridge_attribute is None
