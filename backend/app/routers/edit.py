"""Load and save files for editing in Quick Look (text, CSV, .xlsx, .docx)."""

import os
import subprocess
import sys
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app import editing
from app.state import index_manager, require_allowed, settings_store

router = APIRouter(prefix="/api/edit", tags=["edit"])


class SaveRequest(BaseModel):
    path: str
    mtime_ns: str
    payload: Dict[str, Any]


def _target(path: str) -> str:
    norm = os.path.normpath(os.path.abspath(path))
    require_allowed(norm)
    if not os.path.isfile(norm):
        raise HTTPException(status_code=404, detail="File not found")
    return norm


@router.get("")
async def load(path: str = Query(...)) -> Dict[str, Any]:
    norm = _target(path)
    try:
        return await run_in_threadpool(editing.load, norm, os.path.splitext(norm)[1])
    except editing.EditError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Cannot open this file for editing: {e}")


@router.post("/save")
async def save(req: SaveRequest) -> Dict[str, Any]:
    norm = _target(req.path)
    policy = editing.BackupPolicy.from_dict(settings_store.backups)
    try:
        result = await run_in_threadpool(editing.save, norm, os.path.splitext(norm)[1], int(req.mtime_ns), req.payload, policy)
    except editing.EditError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Save failed, the file was not changed: {e}")
    # The new text is searchable at once (the watcher would take a moment and runs again later)
    try:
        result["indexed"] = await run_in_threadpool(index_manager.index_file_now, norm)
    except Exception as e:
        print(f"[Edit] Saved, but indexing {norm} failed: {e}")
        result["indexed"] = False
    return result


@router.get("/backups")
async def backups() -> Dict[str, Any]:
    return await run_in_threadpool(editing.backups_info)


@router.delete("/backups")
async def delete_backups() -> Dict[str, Any]:
    return await run_in_threadpool(editing.delete_backups)


@router.post("/backups/open")
async def open_backups() -> Dict[str, Any]:
    """Show data\\backups in Explorer."""
    folder = editing.BACKUP_DIR
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(str(folder))
        else:
            subprocess.run(["xdg-open", str(folder)], check=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not open the folder: {e}")
    return editing.backups_info()
