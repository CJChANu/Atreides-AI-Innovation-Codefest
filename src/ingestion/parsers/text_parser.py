"""Plain-text parser for in-world ephemera.

Ephemera are short and blank-line separated (ballads have stanzas, ledgers have
entries). We keep line ranges as provenance so a citation can point at the exact
stanza rather than "somewhere in this file".
"""

from __future__ import annotations

from pathlib import Path

from src.ingestion.parsers.base import ParseResult
from src.common.models import Block


class TextParser:
    def parse(self, path: Path, document_id: str, assets_dir: Path) -> ParseResult:
        result = ParseResult(page_count=None)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

        buffer: list[str] = []
        start = 1
        for index, line in enumerate(lines, start=1):
            if line.strip():
                if not buffer:
                    start = index
                buffer.append(line)
                continue
            if buffer:
                result.blocks.append(self._block(buffer, start, index - 1))
                buffer = []
        if buffer:
            result.blocks.append(self._block(buffer, start, len(lines)))
        return result

    @staticmethod
    def _block(buffer: list[str], start: int, end: int) -> Block:
        text = "\n".join(buffer).strip()
        # A markdown-style heading inside a .txt ephemeron still marks a section.
        content_type = "heading" if text.startswith("#") and len(buffer) == 1 else "paragraph"
        return Block(text=text.lstrip("# ").strip() if content_type == "heading" else text,
                     content_type=content_type, line_start=start, line_end=end)
