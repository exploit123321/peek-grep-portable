"""Native desktop operations for launching, revealing, and copying paths."""

import os
import subprocess
import sys
from fastapi import APIRouter, HTTPException
from app.schemas import ActionRequest, ActionResponse
from app.state import require_allowed

router = APIRouter(prefix="/api/actions", tags=["actions"])

@router.post("/open", response_model=ActionResponse)
async def open_file(payload: ActionRequest) -> ActionResponse:
    """Launch file in default desktop application."""
    norm_path = os.path.normpath(os.path.abspath(payload.path))
    require_allowed(norm_path)

    if not os.path.exists(norm_path):
        raise HTTPException(status_code=404, detail="Target path not found")

    try:
        if sys.platform == "win32":
            os.startfile(norm_path)
        elif sys.platform == "darwin":
            subprocess.run(["open", norm_path], check=False)
        else:
            subprocess.run(["xdg-open", norm_path], check=False)
        return ActionResponse(success=True, message=f"Opened {os.path.basename(norm_path)}", path=norm_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to open file: {e}")

@router.post("/reveal", response_model=ActionResponse)
async def reveal_file(payload: ActionRequest) -> ActionResponse:
    """Reveal item in system file explorer with selection highlighted."""
    norm_path = os.path.normpath(os.path.abspath(payload.path))
    require_allowed(norm_path)

    if not os.path.exists(norm_path):
        raise HTTPException(status_code=404, detail="Target path not found")

    try:
        if sys.platform == "win32":
            # Pass the command line as one string, without a shell: explorer.exe /select,"{path}"
            subprocess.Popen(f'explorer.exe /select,"{norm_path}"')
        elif sys.platform == "darwin":
            subprocess.run(["open", "-R", norm_path], check=False)
        else:
            subprocess.run(["xdg-open", os.path.dirname(norm_path)], check=False)
        return ActionResponse(success=True, message="Revealed in explorer", path=norm_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reveal file: {e}")

@router.post("/copy-path", response_model=ActionResponse)
async def copy_path(payload: ActionRequest) -> ActionResponse:
    """Return normalized absolute path for client-side clipboard writing."""
    norm_path = os.path.normpath(os.path.abspath(payload.path))
    require_allowed(norm_path)
    if not os.path.exists(norm_path):
        raise HTTPException(status_code=404, detail="Target path not found")
    return ActionResponse(success=True, message="Normalized path resolved", path=norm_path)
