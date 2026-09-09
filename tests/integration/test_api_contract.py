"""The contract the UI depends on.

Two properties matter more than the shape of any single field:

* **The UI must not decide completeness.** It reads `status` and `partial` from
  the backend, which derive from one evaluation. When the UI formed its own view,
  the same response could be labelled complete in one panel and partial in
  another.
* **Every citation must be openable.** A reference the reader cannot follow is a
  promise, not evidence — so the endpoints behind them are tested, not assumed.

These run against the real index, and skip cleanly when it has not been built.
"""

import pytest

from src.common.config import SETTINGS

pytestmark = pytest.mark.skipif(
    not SETTINGS.db_path.exists(), reason="archive index not built")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.api.app import app

    return TestClient(app)


def _ask(client, question: str, **options):
    payload = {"question": question, "options": {"allow_llm": False, **options}}
    response = client.post("/api/questions", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


# -- the completion contract ------------------------------------------------

def test_partial_always_agrees_with_status(client):
    """The contradiction this prevents: 'complete' and 'partial' in one response."""
    for question in ("What is the threat rating of the Marsh Revenant?",
                     "What emblem appears on the banner of House Morvain?",
                     "How many airships does the Ashen Vanguard operate?"):
        data = _ask(client, question)
        assert data["partial"] is (data["status"] != "completed"), question


def test_a_completed_answer_has_no_unsupported_claim(client):
    data = _ask(client, "What is the threat rating of the Marsh Revenant?")
    assert data["status"] == "completed"
    assert all(c["claim_type"] != "unsupported" for c in data["claims"])


def test_a_partial_answer_says_what_is_still_open(client):
    data = _ask(client, "What emblem appears on the banner of House Morvain?")
    assert data["partial"]
    assert data["status_headline"]
    assert data["status_reasons"] or data["unmet_requirements"]


# -- provenance -------------------------------------------------------------

def test_every_supported_claim_quotes_its_source(client):
    data = _ask(client, "Where is the Cinder-Wrought Aegis housed?")
    supported = [c for c in data["claims"] if c["claim_type"] != "unsupported"]
    assert supported
    for claim in supported:
        assert claim["evidence"], claim["text"]
        assert any(e["excerpt"] for e in claim["evidence"]), claim["text"]


def test_confidence_is_explained_not_just_scored(client):
    data = _ask(client, "What is the threat rating of the Marsh Revenant?")
    claim = data["claims"][0]
    assert claim["confidence_reasons"]
    assert any("reliab" in reason for reason in claim["confidence_reasons"])


def test_a_citation_opens_the_chunk_it_names(client):
    data = _ask(client, "What is the garrison strength of Marrowwatch?")
    evidence = data["claims"][0]["evidence"][0]
    response = client.get(f"/api/chunks/{evidence['chunk_id']}")
    assert response.status_code == 200


def test_a_visual_claim_can_show_its_plate(client):
    """A figure-backed answer must be able to display the figure."""
    data = _ask(client, "What is the threat rating of the Marsh Revenant?")
    figures = [e["figure_id"] for c in data["claims"] for e in c["evidence"]
               if e["figure_id"]]
    assert figures, "a plate-derived claim should carry its figure id"
    response = client.get(f"/api/figures/{figures[0]}/asset")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")


# -- isolation --------------------------------------------------------------

def test_each_request_gets_its_own_investigation_id(client):
    first = _ask(client, "What is the garrison strength of Marrowwatch?")
    second = _ask(client, "What is the threat rating of the Thorn Wraith?")
    assert first["investigation_id"] != second["investigation_id"]


def test_no_evidence_leaks_between_requests(client):
    """A previous question's numbers must not appear in the next answer."""
    _ask(client, "What percentage of Embermarch's garrison strength is "
                 "the Cinder-Wrought Aegis's attunement cost?")
    second = _ask(client, "What is the threat rating of the Thorn Wraith?")
    blob = str(second)
    assert "4063" not in blob
    assert "Embermarch" not in blob


def test_repeating_a_question_gives_the_same_answer(client):
    """Reproducibility: the deterministic path must not drift between runs."""
    question = "What is the recorded garrison strength of Crookgate Keep?"
    first, second = _ask(client, question), _ask(client, question)
    assert first["answer"] == second["answer"]
    assert first["status"] == second["status"]
    assert first["investigation_id"] != second["investigation_id"]


# -- calculations -----------------------------------------------------------

def test_a_calculation_shows_its_formula_and_operands(client):
    data = _ask(client, "How long did the Winter Reckoning last?")
    calculation = data["calculation"]
    assert calculation.get("formula")
    assert calculation.get("result_text")
    assert len(calculation.get("operands", [])) >= 2
