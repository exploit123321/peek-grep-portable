"""Working folder endpoints: list, check, save, pick, and re-index."""

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.config import DATA_DIR
from app.schemas import FolderCheckRequest, FolderListRequest, ReindexRequest
from app.settings import available_drives, check_folder, normalize_folder, suggested_folders
from app.state import desktop_hooks, index_manager, settings_store

router = APIRouter(prefix="/api", tags=["folders"])


@router.get("/folders")
async def list_folders() -> Dict[str, Any]:
    """Allowed folders with file counts, plus suggestions for the setup screen."""
    details = await run_in_threadpool(index_manager.folder_details)
    return {
        "setup_done": settings_store.setup_done,
        "folders": details,
        "suggestions": suggested_folders(),
        "drives": available_drives(),
        "data_dir": str(DATA_DIR),
        "can_pick": desktop_hooks.get("pick_folders") is not None,
    }


@router.post("/folders/check")
async def check(payload: FolderCheckRequest) -> Dict[str, Any]:
    """Validate one folder against the list the user is editing."""
    current = payload.current if payload.current is not None else settings_store.folders()
    return check_folder(payload.path, [normalize_folder(c) for c in current if c.strip()])


@router.put("/folders")
async def save_folders(payload: FolderListRequest) -> Dict[str, Any]:
    """Save the allowed folder list and start indexing the new folders."""
    errors: List[Dict[str, str]] = []
    for raw in payload.folders:
        path = normalize_folder(raw)
        if not os.path.isdir(path):
            errors.append({"path": path, "error": "This folder does not exist."})
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})
    result = await run_in_threadpool(index_manager.apply_folders, payload.folders)
    return {"success": True, **result}


@router.post("/folders/pick")
async def pick_folders() -> Dict[str, Any]:
    """Open the native folder dialog (only in the desktop window)."""
    picker = desktop_hooks.get("pick_folders")
    if picker is None:
        raise HTTPException(status_code=501, detail="No desktop window. Type the folder path instead.")
    paths: Optional[List[str]] = await run_in_threadpool(picker)
    return {"paths": [normalize_folder(p) for p in (paths or [])]}


@router.post("/reindex")
async def reindex(payload: Optional[ReindexRequest] = None) -> Dict[str, Any]:
    """Scan one working folder, or all of them, again."""
    if not settings_store.folders():
        raise HTTPException(status_code=409, detail="Choose a working folder first.")
    target = [payload.folder] if payload and payload.folder else None
    queued = index_manager.queue_scan(target)
    return {"status": "reindexing_started", "queued": queued}
