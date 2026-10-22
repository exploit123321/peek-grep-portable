"""Keyboard shortcuts: the global show/hide key and the in-app keys, saved in data\\settings.json."""

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.settings import DEFAULT_HOTKEY
from app.state import desktop_hooks, settings_store

router = APIRouter(prefix="/api", tags=["settings"])

_MODIFIERS = ("ctrl", "shift", "alt", "windows")
_ACTION = re.compile(r"^[a-z0-9_]{1,64}$")
_BINDING = re.compile(r"^((Ctrl|Shift|Alt|Meta)\+){0,4}\S{1,24}$")


def valid_hotkey(hotkey: str) -> bool:
    """A global key in the names of the "keyboard" package: modifiers, then one key (F keys alone are fine)."""
    parts = hotkey.split("+")
    if not all(parts):
        return False
    *mods, key = parts
    if any(m not in _MODIFIERS for m in mods) or len(set(mods)) != len(mods):
        return False
    if not re.fullmatch(r"[a-z0-9]+", key) or key in _MODIFIERS:
        return False
    return bool(mods) or bool(re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", key))


class ShortcutsUpdate(BaseModel):
    hotkey: Optional[str] = None
    shortcuts: Optional[Dict[str, List[str]]] = None


def _settings() -> Dict[str, Any]:
    return {
        "hotkey": settings_store.hotkey,
        "default_hotkey": DEFAULT_HOTKEY,
        "shortcuts": settings_store.shortcuts,
        "can_set_hotkey": desktop_hooks.get("set_hotkey") is not None,
    }


@router.get("/settings")
async def get_settings() -> Dict[str, Any]:
    return _settings()


@router.put("/settings/shortcuts")
async def save_shortcuts(payload: ShortcutsUpdate) -> Dict[str, Any]:
    if payload.shortcuts is not None:
        for action, bindings in payload.shortcuts.items():
            if not _ACTION.match(action) or len(bindings) > 4 or not all(_BINDING.match(b) for b in bindings):
                raise HTTPException(status_code=400, detail=f"Not a valid shortcut for {action}.")
        settings_store.set_shortcuts(payload.shortcuts)

    if payload.hotkey is not None:
        hotkey = payload.hotkey.strip().lower().replace(" ", "")
        if not valid_hotkey(hotkey):
            raise HTTPException(status_code=400, detail="The global key needs Ctrl, Alt, Shift, or Win and one key (or an F key).")
        if hotkey != settings_store.hotkey:
            hook = desktop_hooks.get("set_hotkey")
            if hook is not None:
                try:
                    await run_in_threadpool(hook, hotkey)
                except Exception as e:
                    raise HTTPException(status_code=400, detail=f"Windows did not accept {hotkey}: {e}")
            settings_store.set_hotkey(hotkey)
    return _settings()
