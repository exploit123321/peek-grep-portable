"""Fast search endpoints with high-speed query dispatch and snippet extraction."""

import time
from typing import Optional
from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool
from app.indexer.db import search_files
from app.schemas import SearchResponse
from app.state import require_allowed, settings_store

router = APIRouter(prefix="/api", tags=["search"])

@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(default="", description="Search query string"),
    mode: str = Query(default="all", description="Search mode: all, filename, or content"),
    type_filter: str = Query(default="all", description="Category filter: all, code, docs, markdown, data, media, plain"),
    limit: int = Query(default=50, ge=1, le=200, description="Max results limit"),
    folder: Optional[str] = Query(default=None, description="Limit results to one working folder"),
) -> SearchResponse:
    """Execute debounced query against SQLite metadata and FTS5 inverted index."""
    start = time.perf_counter()

    if folder:
        require_allowed(folder)

    results = []
    if settings_store.folders():
        results = await run_in_threadpool(
            search_files,
            query=q,
            mode=mode,
            type_filter=type_filter,
            limit=limit,
            folder=folder,
        )

    duration_ms = (time.perf_counter() - start) * 1000.0

    return SearchResponse(
        query=q,
        mode=mode,
        type_filter=type_filter,
        total=len(results),
        took_ms=round(duration_ms, 2),
        results=results,
    )
