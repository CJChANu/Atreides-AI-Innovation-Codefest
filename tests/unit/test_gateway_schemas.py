"""The schema layer is the boundary between 'a model said something' and 'we act'."""

import pytest

from src.ai_gateway.errors import SchemaViolation
from src.ai_gateway.schemas import (
    extract_json,
    validate_extracted_claims,
    validate_query_suggestions,
    validate_question_understanding,
)


def test_json_is_recovered_from_a_fenced_response():
    assert extract_json('```json\n{"intent":"open_question"}\n```') == {"intent": "open_question"}


def test_json_is_recovered_from_surrounding_prose():
    raw = 'Sure! Here is the analysis:\n{"intent":"open_question"}\nHope that helps.'
    assert extract_json(raw)["intent"] == "open_question"


def test_unparseable_output_is_a_violation_not_a_repair():
    """We never heuristically 'fix' malformed output — that is how it gets trusted."""
    with pytest.raises(SchemaViolation):
        extract_json("I think the answer is probably Marrowwell Abbey.")


def test_a_json_array_is_rejected():
    with pytest.raises(SchemaViolation):
        extract_json("[1, 2, 3]")


def test_an_unknown_intent_is_rejected():
    with pytest.raises(SchemaViolation):
        validate_question_understanding({"intent": "please_just_answer"})


def test_unsupported_relations_are_quarantined_not_traversed():
    result = validate_question_understanding({
        "intent": "relation_hop",
        "relations": ["lair", "secretly_controls"],
    })
    assert result["relations"] == ["lair"]
    assert result["candidate_relations"] == ["secretly_controls"]


def test_unknown_keys_are_dropped():
    """A model must not be able to smuggle a field into our state."""
    result = validate_question_understanding({"intent": "open_question", "run_shell": "rm -rf /"})
    assert "run_shell" not in result


def test_query_suggestions_must_be_non_empty():
    with pytest.raises(SchemaViolation):
        validate_query_suggestions({"queries": ["", "   "]})


def test_claims_without_an_evidence_id_are_dropped():
    """A claim that cannot name its source can never be cited, so it cannot count."""
    claims = validate_extracted_claims({"claims": [
        {"subject": "A", "predicate": "ruled_by", "value": "B", "evidence_id": "chunk-1"},
        {"subject": "C", "predicate": "ruled_by", "value": "D"},
    ]})
    assert len(claims) == 1
    assert claims[0]["evidence_id"] == "chunk-1"


def test_missing_claims_key_is_not_an_error():
    assert validate_extracted_claims({}) == []
