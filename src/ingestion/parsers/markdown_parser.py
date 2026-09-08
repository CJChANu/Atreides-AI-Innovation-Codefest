"""Markdown parser for the fan-wiki articles.

Wiki pages have no pages to cite, so the heading path *is* the provenance. They
also carry two structures we must not lose:

* ``| Field | Value |`` infobox tables, which hold the crisp facts (seat, doctrine,
  known members) that multi-hop questions hinge on;
* ``[[Wiki Links]]``, which are an explicit, human-authored relation signal — a
  free head start for the knowledge graph, far more precise than LLM extraction.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.common.ids import figure_id as make_figure_id
from src.common.ids import table_id as make_table_id
from src.common.models import Block, Figure, Table
from src.ingestion.parsers.base import ParseResult

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_IMAGE = re.compile(r"^!\[(?P<alt>[^\]]*)\]\((?P<src>[^)]+)\)\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")

WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")


def extract_wikilinks(text: str) -> list[str]:
    """Return the targets of every ``[[link]]`` in `text`, de-duplicated, in order."""
    seen: dict[str, None] = {}
    for match in WIKILINK.finditer(text):
        seen.setdefault(match.group(1).strip(), None)
    return list(seen)


def _split_row(line: str) -> list[str]:
    cells = line.strip().strip("|").split("|")
    return [c.strip() for c in cells]


class MarkdownParser:
    def parse(self, path: Path, document_id: str, assets_dir: Path) -> ParseResult:
        result = ParseResult(page_count=None)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

        section: list[str] = []
        buffer: list[str] = []
        buffer_start = 1
        table_ordinal = 0
        figure_ordinal = 0

        def flush(end_line: int) -> None:
            text = "\n".join(buffer).strip()
            buffer.clear()
            if text:
                result.blocks.append(
                    Block(
                        text=text,
                        content_type="paragraph",
                        section_path=tuple(section),
                        line_start=buffer_start,
                        line_end=end_line,
                    )
                )

        index = 0
        while index < len(lines):
            line = lines[index]
            line_no = index + 1

            heading = _HEADING.match(line)
            if heading:
                flush(line_no - 1)
                level = len(heading.group(1))
                title = heading.group(2).strip()
                del section[level - 1 :]
                section.append(title)
                result.blocks.append(
                    Block(text=title, content_type="heading", section_path=tuple(section),
                          line_start=line_no, line_end=line_no)
                )
                buffer_start = line_no + 1
                index += 1
                continue

            image = _IMAGE.match(line)
            if image:
                flush(line_no - 1)
                src = image.group("src")
                result.figures.append(
                    Figure(
                        figure_id=make_figure_id(document_id, None, figure_ordinal),
                        document_id=document_id,
                        page=None,
                        caption=image.group("alt").strip(),
                        # Wiki images live beside the article; keep the corpus path so
                        # the UI can serve the original asset read-only.
                        asset_path=str((path.parent / src).resolve()),
                        nearby_text="\n".join(lines[max(0, index - 2) : index + 3]),
                    )
                )
                figure_ordinal += 1
                buffer_start = line_no + 1
                index += 1
                continue

            # A markdown table: header row, separator row, then body rows.
            if line.strip().startswith("|") and index + 1 < len(lines) and _TABLE_SEP.match(lines[index + 1]):
                flush(line_no - 1)
                columns = _split_row(line)
                rows: list[list[str]] = []
                cursor = index + 2
                while cursor < len(lines) and lines[cursor].strip().startswith("|"):
                    rows.append(_split_row(lines[cursor]))
                    cursor += 1
                caption = section[-1] if section else path.stem
                table = Table(
                    table_id=make_table_id(document_id, None, table_ordinal),
                    document_id=document_id,
                    page=None,
                    section_path=tuple(section),
                    caption=caption,
                    columns=columns,
                    rows=rows,
                )
                result.tables.append(table)
                # The table is also a first-class retrievable block: infobox rows are
                # often the only place a fact is stated in a single sentence-free line.
                result.blocks.append(
                    Block(text=table.as_retrieval_text(), content_type="table",
                          section_path=tuple(section), line_start=line_no,
                          line_end=cursor, table_id=table.table_id)
                )
                index = cursor
                buffer_start = index + 1
                continue

            buffer.append(line)
            index += 1

        flush(len(lines))
        return result
