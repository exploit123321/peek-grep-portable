"""Search endpoint: smart search syntax, groups for [a, b], and paging for endless scrolling."""

import time
from typing import Optional
from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool
from app.indexer.smart_search import run_search
from app.schemas import SearchResponse
from app.state import require_allowed, settings_store

router = APIRouter(prefix="/api", tags=["search"])

@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(default="", description="Search text: file names, and text after \":\" (smart search syntax)"),
    type_filter: str = Query(default="all", description="Category filter: all, code, docs, markdown, data, media, plain"),
    limit: int = Query(default=60, ge=1, le=500, description="Results per page"),
    offset: int = Query(default=0, ge=0, description="First result of the page"),
    group: Optional[int] = Query(default=None, ge=0, description="Grouped search: page of this group only"),
    folder: Optional[str] = Query(default=None, description="Limit results to one working folder"),
) -> SearchResponse:
    """One page of results. Grouped searches return the first page of every group."""
    start = time.perf_counter()

    if folder:
        require_allowed(folder)

    body = {"results": [], "total": 0, "groups": [], "grouped": False, "highlight": [], "explain": []}
    if settings_store.folders():
        body = await run_in_threadpool(
            run_search,
            query=q,
            type_filter=type_filter,
            folder=folder,
            offset=offset,
            limit=limit,
            group=group,
            group_limit=min(limit, 25),
            options=settings_store.search_options,
            roots=settings_store.folders(),
        )

    return SearchResponse(
        query=q,
        type_filter=type_filter,
        took_ms=round((time.perf_counter() - start) * 1000.0, 2),
        **body,
    )
