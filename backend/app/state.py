"""Shared singletons: the settings store, the index manager, and the desktop window hooks."""

import os
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException

from app.config import DB_PATH
from app.engine import IndexManager
from app.settings import SettingsStore

settings_store = SettingsStore()
index_manager = IndexManager(settings_store, db_path=DB_PATH)

# Window hooks registered by desktop_app (empty when the API runs without a window)
desktop_hooks: Dict[str, Optional[Callable[..., Any]]] = {
    "hide": None,
    "show": None,
    "resize": None,
    "toggle_maximize": None,
    "window_size": None,
    "pick_folders": None,
    "open_data_folder": None,
    "quit": None,
    "set_hotkey": None,
    "set_autostart": None,
}


def require_allowed(path: str) -> None:
    """Refuse any file access outside the allowed working folders."""
    if not settings_store.is_allowed(path):
        raise HTTPException(status_code=403, detail="This file is outside your working folders.")


def allowed_files(paths: Any, limit: int = 500) -> List[str]:
    """Existing files in the working folders (for dragging files out of the window)."""
    if not isinstance(paths, (list, tuple)):
        return []
    found: List[str] = []
    for p in paths[:limit]:
        if isinstance(p, str) and p:
            norm = os.path.normpath(os.path.abspath(p))
            if os.path.isfile(norm) and settings_store.is_allowed(norm):
                found.append(norm)
    return found
