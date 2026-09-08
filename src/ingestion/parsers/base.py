"""Parser contract.

A parser turns one file into (blocks, tables, figures). It owns provenance: page
numbers, heading paths and line ranges are decided here, where the format is
still known. Nothing downstream is allowed to invent them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from src.common.models import Block, Figure, Table


@dataclass
class ParseResult:
    blocks: list[Block] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    figures: list[Figure] = field(default_factory=list)
    page_count: int | None = None
    warnings: list[str] = field(default_factory=list)


class Parser(Protocol):
    def parse(self, path: Path, document_id: str, assets_dir: Path) -> ParseResult: ...
