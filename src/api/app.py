"""FastAPI application.

Routes are thin: they open the store, run the investigation, and map state to the
response. All the judgement lives in the layers below, which is what lets the CLI
and the API be demonstrably the same system.

Two safety properties are enforced at this boundary:

* **Asset and document routes never accept a filesystem path from the client.**
  They accept an id, look it up in the index, and resolve it under the corpus
  root — so a crafted `../../` cannot escape the archive.
* **The archive is opened read-only.** The API cannot modify the corpus.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.api.models import AskRequest, AskResponse
from src.api.service import to_response
from src.common.config import SETTINGS
from src.graph.fact_query import FactQuery
from src.orchestration.factory import build_system
from src.storage.db import ArchiveStore

app = FastAPI(
    title="Ashen Era Archive Investigator",
    description="Provenance-first multimodal archive investigation (Codefest 2026, sub-tracks 1C/1B)",
    version="2.0.0",
)

STATIC_DIR = Path(__file__).parent / "static"
UI_PATH = STATIC_DIR / "index.html"

# The UI's stylesheet, sandstorm engine and optional logo.png live here.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _store() -> ArchiveStore:
    if not SETTINGS.db_path.exists():
        raise HTTPException(503, "index not built — run scripts/ingest_archive.py")
    return ArchiveStore(SETTINGS.db_path)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def ui() -> str:
    return UI_PATH.read_text(encoding="utf-8")


@app.get("/api/health")
def health() -> dict:
    """Whether each subsystem is actually usable — never just 'ok'."""
    if not SETTINGS.db_path.exists():
        return {"status": "no_index", "detail": "run scripts/ingest_archive.py"}
    with _store() as store:
        _, gateway, modes = build_system(store, SETTINGS)
        counts = store.stats()
        status = gateway.status()
        return {
            "status": "ready",
            "mode": modes.label,
            "indexes": modes.to_dict(),
            "corpus": {
                "documents": counts["documents_indexed"],
                "pages": counts["pages"],
                "chunks": counts["chunks"],
                "tables": counts["tables"],
                "figures": counts["figures"],
            },
            "ai_gateway": {
                "configured": status.configured,
                "model": status.model,
                "circuit": status.circuit,
                "calls": status.calls,
                "failures": status.failures,
                "cache": {"hits": status.cache_hits, "misses": status.cache_misses},
            },
        }


@app.post("/api/questions", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    with _store() as store:
        budget = replace(SETTINGS.budget, max_iterations=request.options.max_iterations)
        investigator, gateway, _ = build_system(store, SETTINGS, budget=budget)
        if not request.options.allow_llm:
            # Explicit deterministic run — used in the demo to show the two modes
            # side by side, and to prove the fallback path is real.
            investigator.gateway = None
        state = investigator.investigate(request.question)
        response = to_response(state, store, FactQuery(store).title_of,
                               gateway.fallback_events)
        if not request.options.show_trace:
            response.trace = []
        return response


@app.get("/api/documents/{document_id}")
def document(document_id: str) -> dict:
    with _store() as store:
        row = store.get_document(document_id)
        if row is None:
            raise HTTPException(404, "unknown document")
        return dict(row)


@app.get("/api/documents/{document_id}/chunks")
def document_chunks(document_id: str, page: int | None = Query(default=None)) -> dict:
    """The extracted evidence for a document, optionally one page of it.

    This is what a citation link opens: the actual indexed text, so a reader can
    confirm the claim against what the system really read.
    """
    with _store() as store:
        if store.get_document(document_id) is None:
            raise HTTPException(404, "unknown document")
        sql = "SELECT chunk_id, page_start, section_path, content_type, content FROM chunks WHERE document_id = ?"
        params: list = [document_id]
        if page is not None:
            sql += " AND page_start = ?"
            params.append(page)
        rows = store.connection.execute(sql + " ORDER BY chunk_id", params).fetchall()
        return {"document_id": document_id, "page": page,
                "chunks": [dict(r) for r in rows]}


@app.get("/api/chunks/{chunk_id}")
def chunk(chunk_id: str) -> dict:
    with _store() as store:
        row = store.get_chunk(chunk_id)
        if row is None:
            raise HTTPException(404, "unknown chunk")
        return dict(row)


@app.get("/api/figures/{figure_id}/asset")
def figure_asset(figure_id: str) -> FileResponse:
    """Serve a figure's image by id.

    The path comes from the index, never from the request, and is then checked to
    be inside the corpus or the derived-assets directory before it is served.
    """
    with _store() as store:
        row = store.connection.execute(
            "SELECT asset_path FROM figures WHERE figure_id = ?", (figure_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "unknown figure")

    asset = Path(row["asset_path"]).resolve()
    allowed_roots = (SETTINGS.corpus_root.resolve(), SETTINGS.assets_dir.resolve())
    if not any(asset.is_relative_to(root) for root in allowed_roots):
        raise HTTPException(403, "asset outside the archive")
    if not asset.is_file():
        raise HTTPException(404, "asset file missing")
    return FileResponse(asset)


@app.get("/api/indexes/status")
def indexes_status() -> dict:
    with _store() as store:
        _, _, modes = build_system(store, SETTINGS)
        graph = store.connection.execute(
            "SELECT COUNT(*) n FROM edges").fetchone()["n"]
        facts = store.connection.execute(
            "SELECT COUNT(*) n FROM facts").fetchone()["n"]
        conflicts = store.connection.execute(
            """SELECT COUNT(*) n FROM (SELECT subject_id, attribute FROM facts
               GROUP BY subject_id, attribute HAVING COUNT(DISTINCT value_key) > 1)"""
        ).fetchone()["n"]
        return {**modes.to_dict(), "edges": graph, "facts": facts, "conflicts": conflicts}
