"""The wiki parser owns two things nothing else can recover: infoboxes and links."""

from pathlib import Path

from src.ingestion.parsers.markdown_parser import MarkdownParser, extract_wikilinks

ARTICLE = """![House Morvain](images/heraldry.png)

# House Morvain

House Morvain is seated at [[Ironfell Citadel]] and fought in [[The War of Endless Vigil]].

## Infobox

| Field | Value |
|---|---|
| Seat | [[Ironfell Citadel]] |
| Known members | [[Nymeria Palefroth]]; [[Isolde Thornwald]] |

## History

Founded long ago.
"""


def _parse(tmp_path: Path):
    source = tmp_path / "house_morvain.md"
    source.write_text(ARTICLE, encoding="utf-8")
    return MarkdownParser().parse(source, "doc-test", tmp_path)


def test_wikilinks_are_extracted_in_order_without_duplicates():
    assert extract_wikilinks("[[A]] then [[B]] then [[A]]") == ["A", "B"]


def test_infobox_becomes_a_table_and_a_retrievable_block(tmp_path):
    result = _parse(tmp_path)
    assert len(result.tables) == 1
    table = result.tables[0]
    assert table.columns == ["Field", "Value"]
    assert ["Seat", "[[Ironfell Citadel]]"] in table.rows
    assert any(b.content_type == "table" for b in result.blocks)


def test_heading_path_is_recorded_as_provenance(tmp_path):
    history = [b for b in _parse(tmp_path).blocks if "Founded long ago" in b.text]
    assert history and history[0].section_path == ("House Morvain", "History")


def test_leading_image_is_captured_as_a_figure(tmp_path):
    result = _parse(tmp_path)
    assert len(result.figures) == 1
    assert result.figures[0].caption == "House Morvain"
