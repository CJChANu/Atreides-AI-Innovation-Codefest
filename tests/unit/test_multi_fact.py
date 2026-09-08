"""A question that asks for several things must ask for all of them.

Two failures are pinned here, both of which used to end with the loop reporting
"all sub-questions supported" having answered a fraction of the question:

* a comparison of two subjects answered about the first one only;
* a four-part question decomposed into a single lookup.
"""

import pytest

from src.orchestration.planner import decompose, next_action
from src.orchestration.state import Intent, Operand, Question


def _multi(operands: list[Operand]) -> Question:
    return Question(
        text="q", intent=Intent.MULTI_FACT,
        entities=[(o.subject_id, o.subject_name) for o in operands],
        operands=operands,
    )


def _two_subjects() -> list[Operand]:
    return [
        Operand("weeping_lurker", "Weeping Lurker", "threat_rating"),
        Operand("marsh_revenant", "Marsh Revenant", "threat_rating"),
    ]


def test_every_requested_fact_becomes_its_own_sub_question():
    subs = decompose(_multi(_two_subjects()))
    assert [s.key for s in subs].count("operand:0") == 1
    assert "operand:1" in [s.key for s in subs]


def test_the_assembly_step_comes_after_every_lookup():
    subs = decompose(_multi(_two_subjects()))
    keys = [s.key for s in subs]
    assert keys.index("operand:1") < keys.index("assemble")


def test_a_second_subject_is_looked_up_against_itself():
    """The bug: the second entity was never searched for at all."""
    question = _multi(_two_subjects())
    second = next(s for s in decompose(question) if s.key == "operand:1")
    action, query, _ = next_action(question, [second], {})
    assert action == "operand_lookup"
    assert "Marsh Revenant" in query


def test_assembly_is_blocked_while_any_fact_is_missing():
    operands = _two_subjects()
    operands[0].value_text = "3"
    question = _multi(operands)
    assemble = next(s for s in decompose(question) if s.key == "assemble")

    action, query, _ = next_action(question, [assemble], {})
    assert action == "report_gap"
    assert "Marsh Revenant" in query


def test_assembly_runs_once_every_fact_is_established():
    operands = _two_subjects()
    operands[0].value_text = "3"
    operands[1].value_text = "4"
    question = _multi(operands)
    assemble = next(s for s in decompose(question) if s.key == "assemble")

    action, _, _ = next_action(question, [assemble], {})
    assert action == "assemble"


def test_a_non_numeric_value_still_grounds_a_plain_lookup():
    """A forging site is a fine answer; only arithmetic insists on a number."""
    place = Operand("x", "X", "forging_site", value_text="Hollowreach")
    assert place.grounded

    number = Operand("x", "X", "attunement_cost", value_text="none recorded",
                     must_be_numeric=True)
    assert not number.grounded


@pytest.mark.parametrize("key", ["operand:0", "operand:1", "assemble", "conflict"])
def test_every_sub_question_states_its_completion_condition(key):
    subs = {s.key: s for s in decompose(_multi(_two_subjects()))}
    assert subs[key].completion
