"""Geometric reading of chart-style figure plates.

Some plates do not print their value as a labelled number: they draw it as a bar
against two or three reference bars, and print a small number beside each one.
``plate_facts.extract_plate_facts`` refuses those outright, because a number
scraped from such a plate is as likely to be a scale tick as the answer — see
``is_chart_plate``. That refusal is honest, but it loses real values: the
Cinder-Wrought Aegis' attunement cost exists *only* on its plate.

This module reads them properly, using the one thing a bar chart gives us that
prose does not — geometry:

* every bar is a solid rectangle, so its pixel length is measurable exactly;
* the subject's own bar is drawn in a different colour and labelled with the
  subject's *name*, while the reference bars carry tier names ("Adept
  tolerance", "Menace");
* length is linear in value, so the reference bars calibrate a scale that the
  subject's bar can then be read against.

That calibration is what makes this safe. OCR of the small printed digits is
unreliable on this archive's stylised serif faces — tesseract reads the
Thrice-Bound Lantern's bold "55" as "25", and one plate's "55" reference as
"95". Neither error survives contact with the geometry: a bar shorter than the
"85" bar cannot be a 95. So we fit a line through the references, discard the
ones that do not sit on it, and only report a value when the drawing and the
printing agree — or when the drawing alone is unambiguous on a small scale.

Nothing here guesses. When the fit is weak or the readings disagree beyond
tolerance the module returns ``None`` and the caller keeps its existing
behaviour of naming the plate and declining to state a number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import combinations

from src.graph.plate_facts import PLATE_LABELS

# A bar must be at least this tall and long to be a bar rather than a rule, an
# underline or a stray run of antialiased pixels.
MIN_BAR_HEIGHT = 12
MIN_BAR_LENGTH = 30
# Fraction of a band's height a column must cover to count as part of the solid
# body of the bar. Antialiasing on the digits beside a bar shares the bar's
# colour, so taking the raw bounding box overstates the length by ~20px.
SOLID_COLUMN = 0.85
# Colours closer than this (summed channel distance) are the same colour.
COLOUR_TOLERANCE = 30
# A colour must cover this many pixels to be a candidate bar fill.
MIN_COLOUR_PIXELS = 2000

# How far a reference bar may sit off the fitted line and still count.
INLIER_PIXELS = 12.0
# The line must pass near the origin: a bar of value zero has no length.
MAX_INTERCEPT_FRACTION = 0.06
# How close the printed digit must be to the geometric prediction to be taken as
# the exact value. Proportional, because a garrison plate reads in thousands.
AGREEMENT_FRACTION = 0.03
AGREEMENT_FLOOR = 0.5
# Below this, values on the plate are small integers and geometry alone pins
# them down; above it a prediction is an estimate and only OCR can be exact.
SMALL_SCALE_MAX = 100.0
SMALL_SCALE_SNAP = 0.2

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
# Plate titles read "<subject> - <attribute>".
_TITLE_SPLIT = re.compile(r"\s+[-–—]\s+")

# Which attribute a plate is *about*. The full label phrases in `PLATE_LABELS`
# are tried first; these stems are the fallback, because OCR clips the end of a
# title surprisingly often ("Attunement Cost" comes back as "Attunement oy") and
# a clipped title is not a reason to discard a plate we can otherwise read. Each
# stem is distinctive enough that no two attributes can match the same text.
_ATTRIBUTE_STEMS: tuple[tuple[str, str], ...] = (
    ("attunement", "attunement_cost"),
    ("tolerance", "attunement_cost"),      # the reference tiers on a cost plate
    ("vitae-grain", "attunement_cost"),
    ("threat", "threat_rating"),
    ("vanguard scale", "threat_rating"),
    ("garrison", "garrison_strength"),
    ("souls under arms", "garrison_strength"),
    ("casualt", "recorded_casualties"),
    ("souls lost", "recorded_casualties"),
)


@dataclass
class Bar:
    """One rectangle on the plate, with whatever was printed beside it."""

    top: int
    bottom: int
    left: int
    right: int
    colour: tuple[int, int, int]
    label: str = ""
    printed: float | None = None

    @property
    def length(self) -> int:
        return self.right - self.left + 1


@dataclass
class ChartReading:
    """A value recovered from a chart plate, with the reasoning that justifies it."""

    attribute: str
    value_number: float
    value_text: str
    subject_label: str
    bar_pixels: int
    predicted: float
    printed: float | None
    confidence: float
    basis: str
    references: list[tuple[str, float, int]] = field(default_factory=list)

    def explain(self) -> str:
        refs = ", ".join(f"{name} = {value:g} at {px}px" for name, value, px in self.references)
        label = self.subject_label
        article = "" if label[:4].lower() == "the " else "the "
        return (f"read from the plate's own scale ({refs}); {article}{label} bar "
                f"is {self.bar_pixels}px, which the scale puts at {self.predicted:.1f} — "
                f"{self.basis}")


def _load(path: str):
    """Return (PIL image, numpy array) or None when imaging is unavailable."""
    try:
        import numpy as np  # noqa: PLC0415 - optional dependency, probed at runtime
        from PIL import Image  # noqa: PLC0415
    except ImportError:
        return None
    try:
        image = Image.open(path).convert("RGB")
    except Exception:
        return None
    return image, np.asarray(image).astype(int)


def find_bars(array) -> list[Bar]:
    """Locate solid rectangles by colour, measuring only their solid body."""
    import numpy as np  # noqa: PLC0415

    flat = array.reshape(-1, 3)
    colours, counts = np.unique(flat, axis=0, return_counts=True)
    background = colours[int(np.argmax(counts))]

    bars: list[Bar] = []
    for colour, count in zip(colours, counts, strict=False):
        if count < MIN_COLOUR_PIXELS or np.abs(colour - background).sum() < 40:
            continue
        mask = np.abs(array - colour).sum(axis=2) < COLOUR_TOLERANCE
        rows = np.nonzero(mask.any(axis=1))[0]
        if not len(rows):
            continue

        # Split the colour's pixels into horizontal bands; each band is at most
        # one bar. A frame or a rule spans the whole plate and is rejected below
        # by the fill and size tests.
        bands, start = [], rows[0]
        for previous, current in zip(rows, rows[1:], strict=False):
            if current - previous > 3:
                bands.append((start, previous))
                start = current
        bands.append((start, rows[-1]))

        for top, bottom in bands:
            height = bottom - top + 1
            if height < MIN_BAR_HEIGHT:
                continue
            band = mask[top:bottom + 1]
            solid = np.nonzero(band.sum(axis=0) >= SOLID_COLUMN * height)[0]
            if len(solid) < MIN_BAR_LENGTH:
                continue
            # The longest unbroken run of solid columns is the bar itself.
            runs, run_start = [], solid[0]
            for previous, current in zip(solid, solid[1:], strict=False):
                if current - previous > 1:
                    runs.append((run_start, previous))
                    run_start = current
            runs.append((run_start, solid[-1]))
            left, right = max(runs, key=lambda run: run[1] - run[0])
            if right - left + 1 < MIN_BAR_LENGTH:
                continue
            bars.append(Bar(int(top), int(bottom), int(left), int(right),
                            tuple(int(channel) for channel in colour)))

    bars.sort(key=lambda bar: bar.top)
    return bars


def _read_text(image, box, config: str, scale: int, fill: int) -> str:
    import pytesseract  # noqa: PLC0415
    from PIL import Image, ImageOps  # noqa: PLC0415

    width, height = image.size
    left, top, right, bottom = box
    crop = image.crop((max(0, left), max(0, top),
                       min(width, right), min(height, bottom))).convert("L")
    if crop.width < 2 or crop.height < 2:
        return ""
    crop = crop.resize((crop.width * scale, crop.height * scale), Image.LANCZOS)
    crop = ImageOps.expand(crop, border=40, fill=fill)
    return pytesseract.image_to_string(crop, config=config).strip().replace("\n", " ")


def annotate(image, array, bars: list[Bar]) -> None:
    """Fill in each bar's printed number (to its right) and label (beneath it)."""
    import numpy as np  # noqa: PLC0415

    flat = array.reshape(-1, 3)
    colours, counts = np.unique(flat, axis=0, return_counts=True)
    fill = int(colours[int(np.argmax(counts))].mean())

    for bar in bars:
        raw = _read_text(image, (bar.right + 4, bar.top - 6, bar.right + 95, bar.bottom + 6),
                         "--psm 7", 5, fill)
        match = _NUMBER.search(raw)
        if match:
            try:
                bar.printed = float(match.group(0).replace(",", ""))
            except ValueError:
                bar.printed = None
        bar.label = _read_text(image, (bar.left - 12, bar.bottom + 2,
                                       bar.left + 340, bar.bottom + 40),
                               "--psm 7", 5, fill)


def _fit(references: list[Bar]) -> tuple[float, float, list[Bar]] | None:
    """Fit ``length = slope * value + intercept`` over the reference bars.

    Fitted from every pair in turn rather than by least squares, because a single
    misread digit would drag a least-squares line badly: one plate prints "55"
    and OCR returns "95", which is longer than its "85" neighbour and therefore
    provably wrong. The pair whose line the most other references sit on wins,
    and near-ties go to the line passing closest to the origin — a bar of value
    zero has zero length, so a large intercept means the fit is wrong.
    """
    usable = [bar for bar in references if bar.printed is not None and bar.printed > 0]
    if len(usable) < 2:
        return None

    longest = max(bar.length for bar in usable)
    best: tuple[tuple[int, float], float, float, list[Bar]] | None = None

    for first, second in combinations(usable, 2):
        if first.printed == second.printed:
            continue
        slope = (second.length - first.length) / (second.printed - first.printed)
        if slope <= 0:
            continue
        intercept = first.length - slope * first.printed
        if abs(intercept) > MAX_INTERCEPT_FRACTION * longest:
            continue
        inliers = [bar for bar in usable
                   if abs(slope * bar.printed + intercept - bar.length) <= INLIER_PIXELS]
        score = (len(inliers), -abs(intercept))
        if best is None or score > best[0]:
            best = (score, slope, intercept, inliers)

    if best is None or best[0][0] < 2:
        return None
    _, slope, intercept, inliers = best
    return slope, intercept, inliers


def _attribute_from_title(title: str) -> str | None:
    """'Marsh Revenant - Threat Rating' -> 'threat_rating'."""
    parts = _TITLE_SPLIT.split(title)
    tail = parts[-1] if len(parts) > 1 else title
    lowered = " ".join(tail.lower().split())
    for phrase, attribute in sorted(PLATE_LABELS.items(), key=lambda kv: -len(kv[0])):
        if phrase in lowered:
            return attribute
    return None


def _attribute_of(*texts: str) -> str | None:
    """The attribute a plate reports, from its title, body text or tier labels.

    Tried in order of how much the source proves: a full label phrase in the
    title is conclusive, a stem anywhere on the plate is strong enough given
    that the plate has already been established as a chart about one subject.
    """
    for text in texts:
        found = _attribute_from_title(text)
        if found:
            return found
    haystack = " ".join(" ".join(texts).lower().split())
    for stem, attribute in _ATTRIBUTE_STEMS:
        if stem in haystack:
            return attribute
    return None


def _matches_subject(label: str, subject: str) -> bool:
    def fold(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", text.lower())

    left, right = fold(label), fold(subject)
    if not left or not right:
        return False
    return left == right or left in right or right in left


def read_chart_plate(asset_path: str, caption: str = "",
                     subject: str = "") -> ChartReading | None:
    """Recover the subject's value from a bar-chart plate, or ``None``.

    ``subject`` is the name the plate is about; the subject's own bar is the one
    labelled with it. Returning ``None`` is a normal outcome — the caller should
    fall back to reporting that the plate exists and could not be read.
    """
    loaded = _load(asset_path)
    if loaded is None:
        return None
    image, array = loaded

    try:
        bars = find_bars(array)
    except Exception:
        return None
    if len(bars) < 3:
        # A chart needs the subject plus at least two references to calibrate.
        return None

    try:
        annotate(image, array, bars)
        title = _read_text(image, (0, 0, image.width, int(image.height * 0.2)), "--psm 6", 2, 239)
        body = _read_text(image, (0, 0, image.width, image.height), "--psm 3", 1, 239)
    except Exception:
        return None

    # The subject's bar is drawn in its own colour; the references share one.
    counts: dict[tuple[int, int, int], int] = {}
    for bar in bars:
        counts[bar.colour] = counts.get(bar.colour, 0) + 1
    reference_colour = max(counts, key=lambda colour: counts[colour])
    candidates = [bar for bar in bars if bar.colour != reference_colour]
    references = [bar for bar in bars if bar.colour == reference_colour]
    if len(candidates) != 1 or len(references) < 2:
        return None
    target = candidates[0]

    # The bar must be labelled with the subject we were asked about. Without this
    # the reading could silently come from another plate's subject.
    if subject and not _matches_subject(target.label, subject):
        return None

    fitted = _fit(references)
    if fitted is None:
        return None
    slope, intercept, inliers = fitted

    predicted = (target.length - intercept) / slope
    if predicted <= 0:
        return None

    tolerance = max(AGREEMENT_FLOOR, AGREEMENT_FRACTION * predicted)
    printed = target.printed

    if printed is not None and abs(printed - predicted) <= tolerance:
        # The drawing and the printing agree: take the printed number, which is
        # exact where the geometry is only proportional.
        value, confidence, basis = printed, 0.93, "the printed number agrees"
    elif predicted < SMALL_SCALE_MAX and abs(predicted - round(predicted)) <= SMALL_SCALE_SNAP:
        # A small integer scale, and the bar lands cleanly on one of its steps.
        # The printed digit, if any, disagreed — say so rather than hide it.
        value = float(round(predicted))
        confidence = 0.78
        basis = ("the printed number could not be read reliably"
                 if printed is None else
                 f"the printed number read as {printed:g}, which the scale contradicts")
    else:
        return None

    labels = " ".join(bar.label for bar in references)
    attribute = _attribute_of(title, caption, body, labels)
    if attribute is None:
        return None

    named = []
    for bar in inliers:
        label = " ".join(bar.label.split()) or "reference"
        named.append((label, float(bar.printed), bar.length))
    named.sort(key=lambda item: item[1])

    text = f"{value:,.0f}" if value >= 1000 else f"{value:g}"
    return ChartReading(
        attribute=attribute, value_number=value, value_text=text,
        subject_label=" ".join(target.label.split()) or subject,
        bar_pixels=target.length, predicted=predicted, printed=printed,
        confidence=confidence, basis=basis, references=named,
    )
