"""Load and save files for editing in Quick Look (text, CSV, .xlsx, .docx)."""

import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app import editing
from app.state import require_allowed

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
    try:
        return await run_in_threadpool(editing.save, norm, os.path.splitext(norm)[1], int(req.mtime_ns), req.payload)
    except editing.EditError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Save failed, the file was not changed: {e}")
