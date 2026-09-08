"""OCR adapter for the 17 simulated scans in the archive.

Those scans have no text layer at all (verified: PyMuPDF extracts 0 characters),
and most of them have *no twin* in another format — so without OCR that content
is simply absent from the index. That makes OCR a correctness requirement here,
not a nice-to-have.

Tesseract is an optional system dependency. When it is missing the adapter
reports ``available = False`` and ingestion records the affected pages as
``needs_ocr`` instead of pretending they are empty. The system should be honest
about a gap rather than silently answer "no evidence found".
"""

from __future__ import annotations

import shutil

# Rendering resolution for OCR. 200 dpi is the usual sweet spot: enough detail for
# the archive's stylised scan fonts without ballooning render time.
OCR_DPI = 200


class TesseractOCR:
    def __init__(self, dpi: int = OCR_DPI) -> None:
        self.dpi = dpi
        self._pytesseract = None
        self.available = False
        self.reason = ""
        self._probe()

    def _probe(self) -> None:
        if shutil.which("tesseract") is None:
            self.reason = "tesseract binary not found on PATH (brew install tesseract)"
            return
        try:
            import pytesseract  # noqa: PLC0415 - optional dependency, probed at runtime
        except ImportError:
            self.reason = "pytesseract not installed (pip install pytesseract pillow)"
            return
        self._pytesseract = pytesseract
        self.available = True

    def read_page(self, page) -> tuple[str, float]:
        """OCR a PyMuPDF page. Returns (text, mean word confidence in 0..1)."""
        if not self.available:
            return "", 0.0

        import io

        from PIL import Image

        pixmap = page.get_pixmap(dpi=self.dpi)
        image = Image.open(io.BytesIO(pixmap.tobytes("png")))
        data = self._pytesseract.image_to_data(
            image, output_type=self._pytesseract.Output.DICT
        )
        words, confidences = [], []
        for word, conf in zip(data["text"], data["conf"], strict=False):
            if not word.strip():
                continue
            words.append(word)
            try:
                value = float(conf)
            except (TypeError, ValueError):
                continue
            if value >= 0:
                confidences.append(value / 100.0)
        mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
        return " ".join(words), round(mean_conf, 3)


class NullOCR:
    """Stand-in used when OCR is disabled by configuration."""

    available = False
    reason = "OCR disabled by configuration (AEA_OCR_ENABLED=0)"

    def read_page(self, page) -> tuple[str, float]:  # noqa: ARG002
        return "", 0.0
