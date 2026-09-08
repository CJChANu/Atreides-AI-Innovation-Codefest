"""Corpus discovery, fingerprinting and format-twin resolution.

Two decisions live here, both driven by what the archive actually contains:

1. **Twin resolution.** Eleven documents ship as both ``.pdf`` and ``.docx`` with
   identical content. Indexing both would double-count evidence and make
   contradiction detection see a document disagreeing with itself. We keep the
   PDF (it carries real page numbers, which we need for citations) and record the
   DOCX as superseded so the choice stays visible.
2. **Scan detection.** ``*.scan.pdf`` files are simulated scans with no text
   layer. They are tagged ``pdf_scan`` at discovery so the pipeline can route
   them and report OCR coverage separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.common.ids import document_id as make_document_id
from src.common.ids import file_hash
from src.common.models import SourceFormat
from src.common.provenance import classify, reliability_of

TEXT_EXTENSIONS = {".txt", ".md"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
# Directory entries and archive metadata that are not documents.
SKIP_NAMES = {".DS_Store", "README.txt", "sample_questions.json"}

# When the same stem appears in several formats, prefer the one that preserves
# page numbers. Lower index wins.
FORMAT_PREFERENCE = [".pdf", ".docx", ".md", ".txt"]


@dataclass
class DiscoveredFile:
    path: Path
    relative_path: Path
    document_id: str
    source_format: SourceFormat
    source_class: str
    reliability: float
    file_hash: str
    file_size: int
    title: str
    superseded_by: str | None = None
    notes: str = ""


def _source_format(path: Path) -> SourceFormat | None:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "pdf_scan" if path.name.lower().endswith(".scan.pdf") else "pdf"
    if suffix == ".docx":
        return "docx"
    if suffix == ".md":
        return "markdown"
    if suffix == ".txt":
        return "text"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    return None


def _title_from(path: Path) -> str:
    stem = path.stem.removesuffix(".scan")
    return stem.replace("_", " ").strip().title()


def _twin_key(path: Path) -> tuple[str, str]:
    """Group key for format twins: same directory + same stem (scan suffix stripped)."""
    return (str(path.parent), path.stem.removesuffix(".scan").lower())


def discover(corpus_root: Path) -> list[DiscoveredFile]:
    """Walk the corpus and return one record per file, twins already resolved."""
    candidates: list[Path] = []
    for path in sorted(corpus_root.rglob("*")):
        if not path.is_file() or path.name in SKIP_NAMES or path.name.startswith("."):
            continue
        if _source_format(path) is None:
            continue
        candidates.append(path)

    # Resolve twins before hashing so the winner is decided on path facts alone.
    groups: dict[tuple[str, str], list[Path]] = {}
    for path in candidates:
        groups.setdefault(_twin_key(path), []).append(path)

    preferred: dict[Path, Path | None] = {}
    for members in groups.values():
        if len(members) == 1:
            preferred[members[0]] = None
            continue
        ranked = sorted(members, key=lambda p: FORMAT_PREFERENCE.index(p.suffix.lower())
                        if p.suffix.lower() in FORMAT_PREFERENCE else 99)
        winner = ranked[0]
        preferred[winner] = None
        for loser in ranked[1:]:
            preferred[loser] = winner

    discovered: list[DiscoveredFile] = []
    winner_ids: dict[Path, str] = {}

    # Two passes: winners first, so a superseded file can point at a real ID.
    for path in candidates:
        if preferred[path] is not None:
            continue
        winner_ids[path] = _build(path, corpus_root, None).document_id

    for path in candidates:
        supersedes = preferred[path]
        record = _build(path, corpus_root, winner_ids.get(supersedes) if supersedes else None)
        discovered.append(record)
    return discovered


def _build(path: Path, corpus_root: Path, superseded_by: str | None) -> DiscoveredFile:
    relative = path.relative_to(corpus_root)
    digest = file_hash(path)
    size = path.stat().st_size
    source_class = classify(relative)
    fmt = _source_format(path)
    assert fmt is not None
    return DiscoveredFile(
        path=path,
        relative_path=relative,
        document_id=make_document_id(relative, size, digest),
        source_format=fmt,
        source_class=source_class,
        reliability=reliability_of(source_class),
        file_hash=digest,
        file_size=size,
        title=_title_from(path),
        superseded_by=superseded_by,
        notes="duplicate format of a preferred document" if superseded_by else "",
    )
