"""Reading a value off a bar chart, and refusing to when the drawing disagrees.

These tests build their own plates rather than reading the archive's, so they
pin the *rule* — length calibrates value, and OCR is corroboration — instead of
re-measuring five specific images. The integration test over the real plates
lives in `tests/integration/test_pipeline.py`.
"""

import pytest

from src.graph.plate_chart import Bar, _attribute_of, _fit, _matches_subject


def _bar(length: int, printed: float | None, label: str = "", top: int = 0) -> Bar:
    return Bar(top=top, bottom=top + 40, left=285, right=285 + length - 1,
               colour=(122, 106, 82), label=label, printed=printed)


def test_the_scale_is_fitted_from_the_reference_bars():
    fitted = _fit([_bar(89, 20), _bar(249, 55), _bar(387, 85)])
    assert fitted is not None
    slope, intercept, inliers = fitted
    assert len(inliers) == 3
    # A bar of value zero has no length, so the line passes near the origin.
    assert abs(intercept) < 12
    assert (153 - intercept) / slope == pytest.approx(34, abs=0.5)


def test_a_misread_reference_is_dropped_rather_than_fitted():
    """Tesseract reads one plate's '55' as '95'. The drawing contradicts it.

    A 95 cannot sit on a bar shorter than the one labelled 85, so the fit must
    exclude it — otherwise it drags the scale and every value read off it.
    """
    fitted = _fit([_bar(80, 20), _bar(225, 95), _bar(349, 85)])
    assert fitted is not None
    slope, intercept, inliers = fitted
    assert [bar.printed for bar in inliers] == [20, 85]
    # The excluded bar's true value falls out of the corrected scale.
    assert (225 - intercept) / slope == pytest.approx(55, abs=1.0)


def test_a_scale_needs_at_least_two_references():
    assert _fit([_bar(89, 20)]) is None
    assert _fit([]) is None


def test_references_without_a_readable_number_are_unusable():
    assert _fit([_bar(89, None), _bar(387, None)]) is None


def test_a_negative_or_inverted_scale_is_rejected():
    """Longer bars must mean larger values, or the plate is not what we think."""
    assert _fit([_bar(387, 20), _bar(89, 85)]) is None


# -- identifying what the plate is about -----------------------------------

def test_the_attribute_survives_a_clipped_title():
    """OCR returns 'Attunement oy' for 'Attunement Cost' often enough to matter."""
    assert _attribute_of("Cinder-Wrought Aegis - Attunement oy") == "attunement_cost"


def test_the_attribute_falls_back_to_the_tier_labels():
    assert _attribute_of("", "", "", "Novice tolerance Adept tolerance") == "attunement_cost"


def test_each_plate_kind_is_recognised():
    assert _attribute_of("Marsh Revenant - Threat Rating") == "threat_rating"
    assert _attribute_of("Emberdeep - Recorded Garrison Strength") == "garrison_strength"


def test_an_unrecognisable_plate_yields_no_attribute():
    assert _attribute_of("A Portrait Of Someone") is None


# -- matching the subject's own bar ----------------------------------------

def test_punctuation_does_not_separate_a_plate_from_its_subject():
    """The filename loses the hyphen the archive's own spelling keeps."""
    assert _matches_subject("The Cinder-Wrought Aegis", "The Cinder Wrought Aegis")
    assert _matches_subject("Marsh Revenant", "Marsh Revenant")


def test_a_different_subject_is_not_matched():
    assert not _matches_subject("Thorn Wraith", "Marsh Revenant")
    assert not _matches_subject("", "Marsh Revenant")
