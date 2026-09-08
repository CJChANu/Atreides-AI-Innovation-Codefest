"""IDs must be stable across runs, or every stored citation breaks."""

from pathlib import Path

from src.common.ids import chunk_id, document_id


def test_document_id_is_deterministic():
    args = (Path("wiki/house_morvain.md"), 4096, "a" * 64)
    assert document_id(*args) == document_id(*args)


def test_document_id_changes_when_content_changes():
    path, size = Path("wiki/house_morvain.md"), 4096
    assert document_id(path, size, "a" * 64) != document_id(path, size, "b" * 64)


def test_document_id_is_case_insensitive_on_path():
    assert document_id(Path("Wiki/A.md"), 10, "c" * 64) == document_id(Path("wiki/a.md"), 10, "c" * 64)


def test_chunk_id_encodes_page():
    assert chunk_id("doc-1", 42, 3, 7) == "doc-1-p0042-s03-c007"
    assert chunk_id("doc-1", None, 0, 0) == "doc-1-pxxx-s00-c000"
