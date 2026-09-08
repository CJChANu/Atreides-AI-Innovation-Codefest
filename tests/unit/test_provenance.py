"""Source classification must be deterministic — it drives ranking and confidence."""

from pathlib import Path

import pytest

from src.common.provenance import SOURCE_CLASSES, classify, reliability_of


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("codex/codex_vaeloria_i.pdf", "codex"),
        ("codex/images/plate_04_artifact.png", "figure_plate"),
        ("wiki/images/atmo_heraldry.png", "figure_plate"),
        ("images/plate_00_location.png", "figure_plate"),
        ("chronicles/volume_i.pdf", "chronicle"),
        ("wiki/house_morvain.md", "wiki"),
        ("ephemera/ballad_concerning_emberdeep.docx", "ballad"),
        ("ephemera/decree_concerning_x.pdf", "official_record"),
        ("ephemera/trial_transcript_concerning_x.txt", "testimony"),
        ("ephemera/auction_catalogue_concerning_x.pdf", "commercial"),
        ("somewhere/unrecognised.txt", "unknown"),
    ],
)
def test_classify(relative, expected):
    assert classify(Path(relative)) == expected


def test_codex_outranks_ballad():
    """The reliability ordering is the whole point of the policy."""
    assert reliability_of("codex") > reliability_of("wiki") > reliability_of("ballad")


def test_every_class_has_a_reliability():
    for name, cls in SOURCE_CLASSES.items():
        assert 0.0 < cls.reliability <= 1.0, name
