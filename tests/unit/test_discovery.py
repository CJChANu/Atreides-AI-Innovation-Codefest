"""Format-twin resolution: the same content must not be indexed twice."""

from src.ingestion.discovery import discover


def _write(root, relative, text="content"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_pdf_wins_over_its_docx_twin(tmp_path):
    """PDFs carry page numbers; a citation without a page is worth less."""
    _write(tmp_path, "codex/annals.pdf")
    _write(tmp_path, "codex/annals.docx")
    found = {f.relative_path.suffix: f for f in discover(tmp_path)}
    assert found[".pdf"].superseded_by is None
    assert found[".docx"].superseded_by == found[".pdf"].document_id


def test_unpaired_files_are_never_superseded(tmp_path):
    _write(tmp_path, "wiki/emberdeep.md")
    assert discover(tmp_path)[0].superseded_by is None


def test_scans_are_tagged_as_their_own_format(tmp_path):
    _write(tmp_path, "ephemera/ballad_concerning_x.scan.pdf")
    found = discover(tmp_path)[0]
    assert found.source_format == "pdf_scan"
    assert found.source_class == "ballad"


def test_archive_metadata_is_not_treated_as_a_document(tmp_path):
    _write(tmp_path, "README.txt")
    _write(tmp_path, "sample_questions.json")
    _write(tmp_path, "wiki/real.md")
    assert [f.relative_path.name for f in discover(tmp_path)] == ["real.md"]
