"""Vision degrades honestly, and every provider failure has a named status.

The rule this protects: a provider being unavailable must never turn into an
invented answer. The free tier here is 50 requests per day and returns 429 for
the rest of it, so the unavailable path is the *common* path and has to be as
correct as the working one.
"""

from dataclasses import dataclass

import pytest

from src.ai_gateway.vision import VisionReader, VisualObservation, VisualStatus


@dataclass
class _Settings:
    vision_model: str = ""
    llm_base_url: str = "https://example.invalid/v1"
    llm_api_key: str = "k"


def test_vision_is_disabled_when_no_model_is_configured():
    reader = VisionReader(_Settings())
    assert not reader.available
    observation = reader.describe("f1", "/tmp/whatever.png", "what is this?")
    assert observation.status is VisualStatus.VISION_UNAVAILABLE
    assert "AEA_VISION_MODEL" in observation.note


def test_a_missing_asset_is_reported_not_guessed(tmp_path):
    reader = VisionReader(_Settings(vision_model="some/model:free"))
    observation = reader.describe("f1", str(tmp_path / "absent.png"), "q")
    assert observation.status is VisualStatus.VISION_UNAVAILABLE
    assert not observation.description


def test_an_unreachable_provider_degrades_to_a_status(tmp_path):
    """A 429 or a dead host is normal here; it must not raise or invent."""
    from PIL import Image

    path = tmp_path / "plate.png"
    Image.new("RGB", (40, 40), (200, 190, 170)).save(path)

    reader = VisionReader(_Settings(vision_model="some/model:free"), timeout=1.0)
    observation = reader.describe("f1", str(path), "q")
    assert observation.status is VisualStatus.VISION_UNAVAILABLE
    assert "unavailable" in observation.note
    assert not observation.usable


def test_a_hedging_answer_is_not_treated_as_an_observation():
    observation = VisualObservation(
        figure_id="f1", asset_path="p", status=VisualStatus.VISUAL_AMBIGUOUS,
        description="I cannot make out the emblem.")
    assert not observation.usable


@pytest.mark.parametrize(
    ("status", "usable"),
    [
        (VisualStatus.VERIFIED_VISUAL, True),
        (VisualStatus.PARTIAL_VISUAL, True),
        (VisualStatus.VISUAL_AMBIGUOUS, False),
        (VisualStatus.OCR_LOW_CONFIDENCE, False),
        (VisualStatus.VISION_UNAVAILABLE, False),
        (VisualStatus.NOT_ESTABLISHED, False),
    ],
)
def test_only_a_real_reading_counts_as_usable(status, usable):
    observation = VisualObservation(figure_id="f", asset_path="p", status=status)
    assert observation.usable is usable


def test_a_large_image_is_downscaled_before_sending(tmp_path):
    """Measured: 2.1MB artwork failed until resized; 29KB plates always worked."""
    from PIL import Image

    from src.ai_gateway.vision import INLINE_LIMIT, MAX_EDGE, _downscale

    path = tmp_path / "big.png"
    Image.new("RGB", (4000, 3000), (120, 90, 60)).save(path)
    encoded = _downscale(path)
    assert encoded is not None
    mime, payload = encoded
    assert mime == "image/jpeg"
    assert len(payload) < INLINE_LIMIT

    with Image.open(path) as original:
        assert max(original.size) > MAX_EDGE  # the input really was oversized


def test_an_observation_is_labelled_as_a_model_reading_not_an_archive_fact():
    observation = VisualObservation(
        figure_id="f", asset_path="p", status=VisualStatus.PARTIAL_VISUAL,
        description="crossed keys on black",
        note="a model's reading of an image, not a recorded archive fact")
    payload = observation.to_dict()
    assert payload["status"] == "partial_visual"
    assert "not a recorded archive fact" in payload["note"]
