"""Asking a vision model what is in a figure, when nothing else can.

147 of the archive's 187 figures carry no text at all: heraldry, portraits,
landscapes, battle paintings. OCR returns noise from them, the caption names the
file and not its contents, and every text route has been tried by the time this
is reached. They are the only evidence for a class of question the archive
plainly expects to be asked — what emblem a house bears, what an object in a
portrait is — and without a model that can see, the honest answer is "we cannot
read it."

Three constraints shape this module, all of them measured rather than assumed:

* **The main model cannot see.** `nvidia/nemotron-3-super-120b-a12b` reports
  `input_modalities: ["text"]`. Vision needs its own model and its own config
  key, which is why this is separate from the gateway's text path.
* **Payload size decides whether a call works.** The labelled plates are ~29KB
  and answer reliably; the artwork averages 1.3MB and failed twice in three
  attempts until downscaled. Images are resized before sending, always.
* **Free vision is intermittent.** Most free vision models return 429 or refuse
  outright. A failure here is normal and must degrade to an honest status, never
  to a guess.

The output is treated exactly like an LLM claim elsewhere in this system: a
*description*, quarantined, labelled as a visual observation with its own
confidence, never promoted to a recorded archive fact.
"""

from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# Longest edge, in pixels, an image is reduced to before sending. Large enough
# to read a printed label on a plate, small enough that the request succeeds.
MAX_EDGE = 1024
# JPEG quality for the downscaled copy. Artwork tolerates this; the labelled
# plates are sent as PNG when they are already small.
JPEG_QUALITY = 80
INLINE_LIMIT = 400_000  # bytes of base64 payload we are willing to send


class VisualStatus(str, Enum):
    """How far visual interpretation actually got.

    Reported instead of a bare success/failure so a reader can tell "the model
    read the number off the plate" from "we found the plate and could not read
    it" from "no vision model was configured at all". Those need different
    responses and only one of them is the archive's fault.
    """

    VERIFIED_VISUAL = "verified_visual"        # read, and corroborated by other evidence
    PARTIAL_VISUAL = "partial_visual"          # read, but not corroborated
    VISUAL_AMBIGUOUS = "visual_ambiguous"      # the model would not commit
    OCR_LOW_CONFIDENCE = "ocr_low_confidence"  # text was recovered but is unreliable
    VISION_UNAVAILABLE = "vision_unavailable"  # not configured, or the provider refused
    NOT_ESTABLISHED = "not_established"        # every route tried, nothing found


# Phrases a model uses when it will not commit. Treating these as an observation
# would turn "I cannot tell" into evidence.
_HEDGES = (
    "i cannot", "i can't", "unable to", "not clear", "unclear", "hard to tell",
    "cannot determine", "no image", "appears to be unavailable", "i don't see",
)


@dataclass
class VisualObservation:
    """What a vision model reported about one figure."""

    figure_id: str
    asset_path: str
    status: VisualStatus
    description: str = ""
    model: str = ""
    note: str = ""

    @property
    def usable(self) -> bool:
        return self.status in {VisualStatus.VERIFIED_VISUAL, VisualStatus.PARTIAL_VISUAL}

    def to_dict(self) -> dict:
        return {
            "figure_id": self.figure_id,
            "asset_path": self.asset_path,
            "status": self.status.value,
            "description": self.description,
            "model": self.model,
            "note": self.note,
        }


def _downscale(path: Path) -> tuple[str, str] | None:
    """Return (mime, base64) for a size-reduced copy, or None if it cannot be read."""
    try:
        from PIL import Image  # noqa: PLC0415 - optional dependency
    except ImportError:
        return None
    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            longest = max(image.size)
            if longest > MAX_EDGE:
                scale = MAX_EDGE / longest
                image = image.resize(
                    (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
                    Image.LANCZOS,
                )
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    except Exception:
        return None
    payload = base64.b64encode(buffer.getvalue()).decode()
    if len(payload) > INLINE_LIMIT:
        return None
    return "image/jpeg", payload


class VisionReader:
    """A narrow client for one multimodal model, or a disabled stand-in."""

    def __init__(self, settings, *, timeout: float = 90.0) -> None:
        self.model = getattr(settings, "vision_model", "") or ""
        self.base_url = getattr(settings, "llm_base_url", "") or ""
        self.api_key = getattr(settings, "llm_api_key", "") or ""
        self.timeout = timeout
        self.calls = 0
        self.failures = 0
        self.last_error = ""

    @property
    def available(self) -> bool:
        return bool(self.model and self.base_url and self.api_key)

    def describe(self, figure_id: str, asset_path: str, question: str) -> VisualObservation:
        """Ask what the figure shows. Never raises; returns a status instead."""
        if not self.available:
            return VisualObservation(
                figure_id=figure_id, asset_path=asset_path,
                status=VisualStatus.VISION_UNAVAILABLE,
                note="no vision model configured (set AEA_VISION_MODEL)")

        path = Path(asset_path)
        if not path.is_file():
            return VisualObservation(
                figure_id=figure_id, asset_path=asset_path,
                status=VisualStatus.VISION_UNAVAILABLE, note="asset file not found")

        encoded = _downscale(path)
        if encoded is None:
            return VisualObservation(
                figure_id=figure_id, asset_path=asset_path,
                status=VisualStatus.VISION_UNAVAILABLE,
                note="image could not be prepared for sending")
        mime, payload = encoded

        prompt = (
            "You are reading an illustration from a fictional archive. "
            "Describe only what is visibly present — symbols, objects, figures, "
            "colours, and any printed text or numbers. Do not guess at meaning, "
            "history, or names that are not written in the image. If you cannot "
            "make something out, say so plainly.\n\n"
            f"The question being investigated is: {question}"
        )
        body = {
            "model": self.model,
            "max_tokens": 320,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{payload}"}},
            ]}],
        }
        request = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
        )

        self.calls += 1
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                parsed = json.load(response)
            text = parsed["choices"][0]["message"]["content"] or ""
        except (urllib.error.URLError, KeyError, IndexError, ValueError, TimeoutError) as error:
            self.failures += 1
            self.last_error = f"{type(error).__name__}"
            return VisualObservation(
                figure_id=figure_id, asset_path=asset_path,
                status=VisualStatus.VISION_UNAVAILABLE, model=self.model,
                note=f"vision provider unavailable ({self.last_error})")

        description = " ".join(str(text).split())
        if not description:
            return VisualObservation(
                figure_id=figure_id, asset_path=asset_path,
                status=VisualStatus.VISUAL_AMBIGUOUS, model=self.model,
                note="the model returned nothing")
        if any(hedge in description.lower() for hedge in _HEDGES):
            return VisualObservation(
                figure_id=figure_id, asset_path=asset_path,
                status=VisualStatus.VISUAL_AMBIGUOUS, model=self.model,
                description=description, note="the model declined to commit")

        return VisualObservation(
            figure_id=figure_id, asset_path=asset_path,
            status=VisualStatus.PARTIAL_VISUAL, model=self.model,
            description=description,
            note="a model's reading of an image, not a recorded archive fact")
