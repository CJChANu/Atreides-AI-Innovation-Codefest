"""Reading the original passage back out of the archive for a stored fact.

The fact store is an index, not a substitute for the corpus. Every row in it was
extracted from a chunk and keeps that chunk's id, which means a stored value can
always be traced back to the sentence a person actually wrote — but only if
something does the tracing.

Until it does, a citation is a promise: "this came from page 16 of the codex".
Quoting the line turns it into something a reader can check without leaving the
answer. That difference matters most exactly where the extraction is most likely
to be wrong — a mis-parsed table row, a value read off a plate, a sentence the
prose reader matched — because the quote is what exposes it.

Nothing here changes an answer. It shows the evidence the answer already rested
on.
"""

from __future__ import annotations

import re

MAX_EXCERPT = 220

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
_MARKUP = re.compile(r"[*_`]{1,3}")


def _clean(text: str) -> str:
    text = _WIKILINK.sub(lambda match: match.group(1), text)
    text = _MARKUP.sub("", text)
    return " ".join(text.split())


def _fold(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _shorten(text: str) -> str:
    return text if len(text) <= MAX_EXCERPT else text[: MAX_EXCERPT - 1].rstrip() + "…"


def find_excerpt(content: str, value: str, subject: str = "") -> str:
    """The line or sentence in `content` that carries `value`.

    Table rows are matched as lines, because a codex row ("| Forged | 123 AS |")
    is not a sentence and splitting it as one loses the label that gives the
    number meaning. Prose is matched as sentences.
    """
    if not content:
        return ""
    target = _fold(value)
    if not target:
        return ""

    # A table row is the most precise unit when the value came from a table, and
    # the archive writes them two ways: markdown pipes in the source files, and
    # "Label | Value" lines once an infobox has been flattened into a chunk.
    # Matching only the markdown form quotes the entire infobox instead of the
    # single row that carries the value.
    candidates: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if "|" not in stripped or target not in _fold(stripped):
            continue
        cleaned = _clean(stripped.strip("|"))
        cleaned = re.sub(r"\s*\|\s*", " — ", cleaned).strip(" —")
        # Skip the header row: it labels the columns, it states nothing.
        if not cleaned or _fold(cleaned) in {"field value", "columns field value"}:
            continue
        candidates.append(cleaned)
    if candidates:
        # The shortest matching row is the most specific one.
        return _shorten(min(candidates, key=len))

    cleaned = _clean(content)
    for sentence in _SENTENCE_SPLIT.split(cleaned):
        if target in _fold(sentence):
            return _shorten(sentence.strip())

    # The value is in this chunk but split across lines. Fall back to a window
    # around it rather than quoting the whole chunk.
    position = _fold(cleaned).find(target)
    if position >= 0:
        start = max(0, position - 80)
        window = cleaned[start:position + len(value) + 120].strip()
        return _shorten(("…" if start > 0 else "") + window)

    if subject:
        for sentence in _SENTENCE_SPLIT.split(cleaned):
            if _fold(subject) in _fold(sentence):
                return _shorten(sentence.strip())
    return ""


def attach_excerpts(rows, store) -> None:
    """Fill in `excerpt` on each fact row, reading its chunk from the archive.

    Chunks are fetched once per id: a multi-part answer commonly cites the same
    infobox for several of its facts.
    """
    wanted = {row.chunk_id for row in rows if row.chunk_id and not row.excerpt}
    if not wanted:
        return

    contents: dict[str, str] = {}
    for chunk_id in wanted:
        try:
            chunk = store.get_chunk(chunk_id)
        except Exception:
            chunk = None
        if chunk is None:
            continue
        contents[chunk_id] = chunk["content"] if "content" in chunk.keys() else ""

    for row in rows:
        if row.excerpt or row.chunk_id not in contents:
            continue
        row.excerpt = find_excerpt(contents[row.chunk_id], row.value_text,
                                   row.subject_name)
