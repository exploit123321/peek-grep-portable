"""Settings the app can change: keyboard shortcuts (the global show/hide key and the in-app keys)
and the search settings. Saved in data\\settings.json."""

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.indexer.smart_search import clear_cache
from app.search_options import DEFAULTS, PRESET_LABELS, PRESETS, validate
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
        "search": settings_store.search_options.to_dict(),
        "search_defaults": DEFAULTS.to_dict(),
        "search_presets": [{"id": k, "label": PRESET_LABELS[k], "options": v} for k, v in PRESETS.items()],
        "app": settings_store.app_settings(),
        "autostart_available": desktop_hooks.get("set_autostart") is not None,
        "backups": settings_store.backups,
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


@router.put("/settings/search")
async def save_search_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Search settings: unknown keys are refused, missing keys keep their current value."""
    unknown = [k for k in payload if k not in DEFAULTS.to_dict()]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown search setting: {', '.join(unknown)}.")
    merged = {**settings_store.search_options.to_dict(), **payload}
    cleaned, errors = validate(merged)
    if errors:
        raise HTTPException(status_code=400, detail=" ".join(errors))
    settings_store.set_search_options(cleaned)
    clear_cache()
    return _settings()


@router.put("/settings/backups")
async def save_backup_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Backups when the editor saves: on/off, how many per file, and how often a new one is made."""
    from app.editing import BackupPolicy
    limits = BackupPolicy.LIMITS
    for k, v in payload.items():
        if k == "enabled" and isinstance(v, bool):
            continue
        if k in limits and isinstance(v, int) and not isinstance(v, bool) and limits[k][0] <= v <= limits[k][1]:
            continue
        raise HTTPException(status_code=400, detail=f"Not a valid backup setting: {k}.")
    settings_store.set_backups(payload)
    return _settings()


@router.put("/settings/app")
async def save_app_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Start with Windows, start in the tray, the screen to open on, and freeing memory in the tray."""
    keys = settings_store.APP_KEYS
    bad = [k for k, v in payload.items() if k not in keys or not isinstance(v, bool)]
    if bad:
        raise HTTPException(status_code=400, detail=f"Unknown or not true/false: {', '.join(bad)}.")
    before = settings_store.app_settings()
    after = {**before, **payload}
    if (after["start_with_windows"], after["start_hidden"]) != (before["start_with_windows"], before["start_hidden"]):
        hook = desktop_hooks.get("set_autostart")
        if hook is None and after["start_with_windows"]:
            raise HTTPException(status_code=400, detail="Start with Windows works in the desktop app only.")
        if hook is not None:
            try:
                await run_in_threadpool(hook, after["start_with_windows"], after["start_hidden"])
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Windows did not accept the startup entry: {e}")
    settings_store.set_app_settings(payload)
    return _settings()
