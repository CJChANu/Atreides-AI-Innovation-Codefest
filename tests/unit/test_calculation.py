"""Calculation questions need every operand, or no answer at all.

The failure these tests pin down is a specific one: asked to compare two
quantities, the system used to find the first, ignore the second, and answer
anyway. A calculation is the one question shape where a partial result is worse
than none — it looks like an answer.
"""

import pytest

from src.orchestration.planner import decompose, next_action
from src.orchestration.state import Calculation, Intent, Operand, Question


def _calculation(kind: str, operands: list[Operand], numerator=0, denominator=1) -> Question:
    return Question(
        text="q", intent=Intent.CALCULATION,
        entities=[(o.subject_id, o.subject_name) for o in operands],
        answer_type="number", operands=operands,
        calculation=Calculation(kind=kind, numerator=numerator, denominator=denominator),
    )


def _pair() -> list[Operand]:
    # Calculation operands demand a number: "None recorded" must not satisfy one.
    return [
        Operand("embermarch", "Embermarch", "garrison_strength", must_be_numeric=True),
        Operand("the_cinder_wrought_aegis", "The Cinder-Wrought Aegis", "attunement_cost",
                must_be_numeric=True),
    ]


# -- decomposition ---------------------------------------------------------

def test_each_operand_gets_its_own_sub_question():
    """One sub-question per operand is what makes a missing one visible."""
    subs = decompose(_calculation("percentage", _pair()))
    keys = [s.key for s in subs]
    assert "operand:0" in keys and "operand:1" in keys


def test_the_computation_step_comes_after_every_operand():
    subs = decompose(_calculation("percentage", _pair()))
    keys = [s.key for s in subs]
    assert keys.index("operand:0") < keys.index("compute")
    assert keys.index("operand:1") < keys.index("compute")


def test_every_sub_question_states_its_completion_condition():
    for sub in decompose(_calculation("ratio", _pair())):
        assert sub.completion


# -- operand validation ----------------------------------------------------

def test_an_ungrounded_operand_blocks_the_arithmetic():
    """The whole point: no value, no answer — and the gap is named."""
    operands = _pair()
    operands[0].value = 4063.0
    question = _calculation("percentage", operands)
    subs = decompose(question)
    compute = next(s for s in subs if s.key == "compute")

    action, query, reason = next_action(question, [compute], {})
    assert action == "report_gap"
    assert "The Cinder-Wrought Aegis" in query
    assert "attunement cost" in reason


def test_the_arithmetic_runs_once_every_operand_is_grounded():
    operands = _pair()
    operands[0].value = 4063.0
    operands[1].value = 34.0
    question = _calculation("percentage", operands)
    compute = next(s for s in decompose(question) if s.key == "compute")

    action, _, _ = next_action(question, [compute], {})
    assert action == "compute"


def test_an_operand_step_asks_for_that_operands_subject():
    """The second operand must not be looked up against the first one's subject."""
    question = _calculation("percentage", _pair())
    subs = decompose(question)
    second = next(s for s in subs if s.key == "operand:1")

    action, query, _ = next_action(question, [second], {})
    assert action == "operand_lookup"
    assert "Cinder-Wrought Aegis" in query
    assert "attunement cost" in query


# -- the formulas ----------------------------------------------------------

@pytest.mark.parametrize(
    ("kind", "values", "expected"),
    [
        ("percentage", [4063.0, 34.0], 4063.0 / 34.0 * 100),
        ("ratio", [4.0, 9.0], 4.0 / 9.0),
        ("difference", [3107.0, 7748.0], 3107.0 - 7748.0),
        ("total", [3107.0, 1306.0], 4413.0),
        ("average", [4.0, 9.0], 6.5),
    ],
)
def test_each_formula_computes_what_it_says(kind, values, expected):
    assert Calculation(kind=kind).apply(values) == pytest.approx(expected)


def test_a_zero_denominator_yields_no_result_rather_than_an_exception():
    assert Calculation(kind="ratio").apply([4.0, 0.0]) is None


def test_the_formula_is_written_out_for_the_trace():
    operands = _pair()
    formula = Calculation(kind="percentage", numerator=1, denominator=0).formula(operands)
    assert "attunement cost" in formula
    assert "garrison strength" in formula
    assert "× 100" in formula
