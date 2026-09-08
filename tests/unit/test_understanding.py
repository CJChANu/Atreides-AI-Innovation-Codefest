"""Question analysis drives every later step, so its classification is pinned."""

import pytest

from src.orchestration.understanding import CONFLICT_MARKERS, QuestionAnalyzer
from src.orchestration.state import Intent


class _FakeStore:
    """Minimal stand-in: the analyzer only needs entity and subject surfaces."""

    def __init__(self, names):
        self._names = names

    class _Cursor:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    @property
    def connection(self):
        return self

    def execute(self, sql, params=()):
        if "FROM entities" in sql:
            return self._Cursor([{"entity_id": n.lower().replace(" ", "_"), "name": n}
                                 for n in self._names])
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
