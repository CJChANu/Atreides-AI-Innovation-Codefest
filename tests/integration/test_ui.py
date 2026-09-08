"""The served UI: shape, wiring and the guarantees the page depends on.

These are cheap structural checks rather than visual ones, but they catch the
failures that actually happen — a renamed API field the UI still reads, a script
that stopped being served, or an escaping regression.
"""

import re

import pytest
from fastapi.testclient import TestClient

from src.api.app import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def page(client):
    return client.get("/").text


def test_the_page_is_served(page):
    assert page.startswith("<!doctype html>")
    assert "Atreides Archive" in page


def test_the_wordmark_is_not_duplicated_beside_the_crest(page):
    """The supplied mark already carries the wordmark and tagline.

    Repeating them in HTML beside the image reads as a mistake, so the heading is
    present for assistive technology only.
    """
    assert 'class="visually-hidden"' in page
    assert page.count("<h1") == 1


def test_the_sandstorm_script_is_served_and_exposes_its_control_api(client, page):
    assert '<script src="/static/sandstorm.js">' in page
    script = client.get("/static/sandstorm.js")
    assert script.status_code == 200
    # The page drives the storm from the request lifecycle; these three must exist.
    for method in ("surge", "settle", "gust"):
        assert re.search(rf"\b{method}\s*\(", script.text), method


def test_the_storm_reacts_to_the_pointer(client):
    """The sand must be a field the cursor disturbs, not a looping backdrop."""
    script = client.get("/static/sandstorm.js").text
    # Grains are shoved aside, curled into the wake and carried along.
    for knob in ("pushStrength", "dragStrength", "swirl", "pointerRadius"):
        assert knob in script, knob
    assert "applyPointer" in script
    # Fast movement throws sand up, and touch drives the same field.
    assert "kickSpeed" in script and "makeSpark" in script
    assert "touchmove" in script and "pointermove" in script


def test_the_storm_respects_reduced_motion_and_hidden_tabs(client):
    """Ambient motion must never be mandatory, and must not run in a background tab."""
    script = client.get("/static/sandstorm.js").text
    assert "prefers-reduced-motion" in script
    assert "visibilitychange" in script


def test_the_installed_crest_is_served(client):
    """The real mark is installed via scripts/set_logo.py and served as-is."""
    response = client.get("/static/logo.png")
    if response.status_code == 404:
        pytest.skip("no crest installed; the inline SVG fallback is in use")
    assert response.headers["content-type"].startswith("image/")
    assert len(response.content) > 1000


def test_the_page_still_carries_the_inline_crest_fallback(page):
    """The UI must never depend on an asset being present."""
    assert 'id="crest"' in page and "<svg" in page
    # It probes several formats before giving up and keeping the SVG.
    for candidate in ("logo.png", "logo.svg", "logo.webp", "logo.jpg"):
        assert candidate in page, candidate


def test_the_installed_crest_has_transparent_corners():
    """The mark must sit in the scene, not as an opaque square over the desert.

    A blend mode only hides a square background when it is exactly black; this
    artwork's is a textured near-black, so it showed as a lighter rectangle.
    set_logo.py masks the asset to its circle instead, which is checkable here.
    """
    from src.common.config import REPO_ROOT

    logo = REPO_ROOT / "src" / "api" / "static" / "logo.png"
    if not logo.is_file():
        pytest.skip("no crest installed")
    from PIL import Image

    with Image.open(logo) as image:
        image = image.convert("RGBA")
        corners = [(2, 2), (image.width - 3, 2), (2, image.height - 3),
                   (image.width - 3, image.height - 3)]
        assert all(image.getpixel(c)[3] == 0 for c in corners), "corners are not transparent"
        assert image.getpixel((image.width // 2, image.height // 2))[3] > 0, "centre was masked away"


def test_the_page_reads_only_fields_the_api_actually_returns(client, page):
    """Guards the UI against a silently renamed response field."""
    body = client.post("/api/questions", json={
        "question": "Whose dominion encompasses the lair of the Gravemaw Wyrm?"
    }).json()
    for field in ("answer", "partial", "ai_mode", "claims", "evidence_chain",
                  "graph_path", "conflicts", "sub_questions", "trace",
                  "stop_reason", "fallback_events", "stats"):
        assert field in body, field
        assert f"d.{field}" in page or f'"{field}"' in page, field


def test_untrusted_values_are_escaped_before_rendering(page):
    """Document titles and claim text come from the archive, so they are escaped."""
    assert "const esc =" in page
    for call in ("esc(d.answer)", "esc(d.stop_reason)", "esc(e.document)"):
        assert call in page, call


def test_the_ui_offers_the_deterministic_toggle(page):
    """The demo has to be able to show the fallback path on the same question."""
    assert 'id="llm"' in page
    assert "allow_llm" in page
