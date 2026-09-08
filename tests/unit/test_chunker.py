"""Chunking may resize text; it may never invent or lose provenance."""

from src.common.models import Block
from src.ingestion.chunker import Chunker


def _chunk(blocks, **kwargs):
    return Chunker(**kwargs).chunk(
        blocks, document_id="doc-1", document_version=1,
        source_format="markdown", source_class="wiki",
    )


def test_tables_are_never_split():
    big_table = Block(text="row | value\n" * 400, content_type="table", table_id="t1")
    chunks = _chunk([big_table], target_chars=100, overlap_chars=0)
    table_chunks = [c for c in chunks if c.content_type == "table"]
    assert len(table_chunks) == 1
    assert table_chunks[0].table_ids == ["t1"]


def test_heading_is_bound_to_the_text_beneath_it():
    blocks = [
        Block(text="Weeping Lurker", content_type="heading"),
        Block(text="It waits in darkness.", content_type="paragraph"),
    ]
    chunks = _chunk(blocks)
    assert chunks[0].content.startswith("Weeping Lurker")
    assert "waits in darkness" in chunks[0].content


def test_page_range_is_inherited_from_the_blocks():
    blocks = [Block(text="a" * 50, page=4), Block(text="b" * 50, page=5)]
    chunk = _chunk(blocks, target_chars=1000, overlap_chars=0)[0]
    assert (chunk.page_start, chunk.page_end) == (4, 5)


def test_lowest_ocr_confidence_wins():
    """A chunk is only as trustworthy as its worst-read source block."""
    blocks = [Block(text="a" * 20, ocr_confidence=0.9), Block(text="b" * 20, ocr_confidence=0.4)]
    assert _chunk(blocks, target_chars=1000)[0].ocr_confidence == 0.4


def test_prose_chunks_overlap_so_cross_boundary_facts_survive():
    blocks = [Block(text="X" * 500), Block(text="Y" * 500), Block(text="Z" * 500)]
    chunks = _chunk(blocks, target_chars=600, overlap_chars=100)
    assert len(chunks) > 1
    assert chunks[1].content.startswith("X" * 10)
