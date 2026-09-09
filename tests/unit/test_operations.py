"""Operation detection is about question *shape*, never about the subject.

The property under test is generality. A rule that fires on "the Cinder-Wrought
Aegis" answers one question; a rule that fires on "how long did it last" answers
every question of that shape, including ones nobody has written yet. So these
tests deliberately use entities the archive does not contain — if detection
depends on recognising the subject, they fail.
"""

import re

import pytest

from src.reasoning.operations import REGISTRY, OperationKind, detect


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("How long did the Siege of Nowhere last?", OperationKind.DURATION),
        ("Which came first, the Fall of Nothing or the Rise of Nobody?",
         OperationKind.DATE_ORDERING),
        ("Which fortress had the most defenders?", OperationKind.SORTING),
        ("What percentage of A's total is B's total?", OperationKind.PERCENTAGE),
        ("What is the ratio of X to Y?", OperationKind.RATIO),
        ("What is the difference between P and Q?", OperationKind.DIFFERENCE),
        ("What is the combined strength of M and N?", OperationKind.TOTAL),
        ("What is the average rating of J and K?", OperationKind.AVERAGE),
        ("Is Alpha larger than Beta?", OperationKind.NUMERIC_COMPARISON),
        ("Do the sources disagree about Zeta?", OperationKind.CONFLICT_DETECTION),
        ("Why did the Blight of Elsewhere happen?", OperationKind.CAUSE_EFFECT),
        ("What was the impact of the Quiet Accord?", OperationKind.IMPACT_ANALYSIS),
        ("Give me a timeline of the Hollow Age.", OperationKind.TIMELINE),
        ("Could the Sunken Crown have existed during the Long Dark?",
         OperationKind.EXISTENCE_CHECK),
        ("How many years between the Founding and the Sundering?",
         OperationKind.DATE_DIFFERENCE),
    ],
)
def test_the_shape_of_a_question_selects_the_operation(question, expected):
    assert expected in detect(question).kinds, question


def test_a_plain_lookup_needs_no_special_operation():
    assert detect("What is the garrison strength of Nowhere Keep?").kinds == set()


def test_several_operations_can_apply_at_once():
    """Answering only one of them answers half the question."""
    plan = detect("How many years after the Long Dark was the Sunken Crown forged?")
    assert OperationKind.DATE_DIFFERENCE in plan.kinds


def test_arithmetic_and_temporal_are_distinguishable():
    assert detect("What percentage of A is B?").is_arithmetic
    assert not detect("What percentage of A is B?").is_temporal
    assert detect("How long did it last?").is_temporal
    assert not detect("How long did it last?").is_arithmetic


def test_every_operation_states_what_evidence_it_needs():
    """A gap can only be reported specifically if the need was declared."""
    for spec in REGISTRY:
        assert spec.needs, spec.kind
        assert spec.describes, spec.kind


def test_no_cue_names_an_entity():
    """The guard against overfitting: cues are question words, not proper nouns.

    A capitalised word inside a cue would mean the registry had learned one
    archive's vocabulary instead of the shape of a question.
    """
    for spec in REGISTRY:
        for cue in spec.cues:
            letters = re.sub(r"\\[a-zA-Z]|[^A-Za-z ]", " ", cue)
            assert letters == letters.lower(), f"{spec.kind}: {cue}"


def test_detection_explains_itself():
    plan = detect("How long did the Quiet War last?")
    assert plan.operations[0].trigger
    assert "how long" in plan.operations[0].to_dict()["why"].lower()
