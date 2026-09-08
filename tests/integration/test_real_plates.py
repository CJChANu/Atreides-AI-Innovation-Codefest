"""The chart reader against the archive's actual plates.

The unit tests pin the rules; this pins the outcome. Every value below was read
off the image by eye before the reader existed, so a regression here means the
reader has started disagreeing with the plate rather than with a fixture.

Skipped when the corpus or tesseract is unavailable, so the suite still runs on
a machine without the archive checked out.
"""

import shutil

import pytest

from src.common.config import SETTINGS
from src.graph.plate_chart import read_chart_plate
from src.ingestion.parsers.image_parser import describe_plate

pytestmark = [
    pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed"),
    pytest.mark.skipif(not (SETTINGS.corpus_root / "images").is_dir(),
                       reason="archive corpus not present"),
]

# (plate filename, attribute, value) — read from the plate by eye.
CHART_PLATES = [
    ("plate_01_location_emberdeep.png", "garrison_strength", 1114),
    ("plate_04_artifact_the_thrice_bound_edge.png", "attunement_cost", 94),
    ("plate_07_artifact_the_thrice_bound_lantern.png", "attunement_cost", 55),
    ("plate_10_creature_marsh_revenant.png", "threat_rating", 4),
    ("plate_13_artifact_the_cinder_wrought_aegis.png", "attunement_cost", 34),
]

# Plates that print their value plainly, or are pure artwork. Neither is a chart,
# and the reader must decline them rather than invent a scale.
NON_CHART_PLATES = [
    "plate_00_location_marrowwatch.png",
    "plate_02_conflict_the_accord_of_mournthrone.png",
    "plate_08_creature_weeping_lurker.png",
    "plate_14_creature_thorn_wraith.png",
]


def _read(name: str):
    path = SETTINGS.corpus_root / "images" / name
    kind, subject = describe_plate(path.stem)
    return read_chart_plate(str(path), caption=f"{kind} plate: {subject}", subject=subject)


@pytest.mark.parametrize(("name", "attribute", "value"), CHART_PLATES)
def test_each_chart_plate_reads_the_value_a_person_sees(name, attribute, value):
    reading = _read(name)
    assert reading is not None, f"{name} should be readable"
    assert reading.attribute == attribute
    assert reading.value_number == pytest.approx(value)


@pytest.mark.parametrize("name", NON_CHART_PLATES)
def test_a_plate_that_is_not_a_chart_is_declined(name):
    assert _read(name) is None


def test_a_contradicted_digit_is_reported_as_such():
    """OCR reads the Lantern's bold '55' as '25'. The scale settles it, and says so."""
    reading = _read("plate_07_artifact_the_thrice_bound_lantern.png")
    assert reading.value_number == 55
    assert reading.printed != 55
    assert "contradicts" in reading.basis


def test_the_reading_explains_the_scale_it_used():
    reading = _read("plate_10_creature_marsh_revenant.png")
    assert len(reading.references) >= 2
    explanation = reading.explain()
    assert "px" in explanation and "Marsh Revenant" in explanation


def test_the_aegis_cost_exists_only_on_its_plate(tmp_path):
    """This value appears in no table or sentence anywhere in the archive.

    It is the operand the reported calculation question was missing, so if the
    reader stops finding it, that question silently becomes unanswerable again.
    """
    reading = _read("plate_13_artifact_the_cinder_wrought_aegis.png")
    assert reading.value_number == 34
