"""Allowed working folders and user settings, stored as JSON in the portable data folder.

Nothing is indexed, watched, previewed, or opened outside the allowed folders.
A folder on the same drive as the app is stored with that flag, so the list stays
correct when a USB drive gets a different drive letter.
"""

import json
import os
import string
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import APP_HOME, DATA_DIR, SETTINGS_PATH

DEFAULT_HOTKEY = "alt+space"


def normalize_folder(path: str) -> str:
    """Return an absolute, normalized folder path (drive roots keep their trailing slash)."""
    cleaned = os.path.expandvars(os.path.expanduser(path.strip().strip('"').strip()))
    norm = os.path.normpath(os.path.abspath(cleaned))
    drive, rest = os.path.splitdrive(norm)
    if drive and rest in ("", os.sep):
        return drive.upper() + os.sep
    if drive and len(drive) == 2:
        norm = drive.upper() + rest
    return norm


def path_key(path: str) -> str:
    """Case-folded comparison key for a path."""
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def is_within(path: str, folder: str) -> bool:
    """True if path is the folder itself or anything below it."""
    p = path_key(path)
    f = path_key(folder)
    if p == f:
        return True
    if not f.endswith(os.sep):
        f += os.sep
    return p.startswith(f)


def is_drive_root(path: str) -> bool:
    drive, rest = os.path.splitdrive(normalize_folder(path))
    return bool(drive) and rest in ("", os.sep)


def app_drive() -> str:
    return os.path.splitdrive(str(APP_HOME))[0].upper()


class SettingsStore:
    """Thread-safe JSON settings with the list of allowed working folders."""

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path or SETTINGS_PATH)
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = {}
        self.drive_moved: Optional[Tuple[str, str]] = None
        self.load()

    # -- persistence -------------------------------------------------------

    def load(self) -> None:
        with self._lock:
            data: Dict[str, Any] = {}
            try:
                if self.path.exists():
                    data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[Settings] Could not read {self.path}: {e}")
                data = {}
            data.setdefault("version", 1)
            data.setdefault("setup_done", False)
            data.setdefault("folders", [])
            data.setdefault("hotkey", DEFAULT_HOTKEY)
            self._data = data
            self._apply_skip_folders()
            self._resolve_drive_letter()

    def _apply_skip_folders(self) -> None:
        """Optional "skip_folders" in settings.json replaces the default skip list."""
        from app.config import DEFAULT_SKIP_DIR_NAMES, SKIP_DIR_NAMES
        custom = self._data.get("skip_folders")
        SKIP_DIR_NAMES.clear()
        if isinstance(custom, list):
            SKIP_DIR_NAMES.update(str(n).strip().lower() for n in custom if str(n).strip())
        else:
            SKIP_DIR_NAMES.update(DEFAULT_SKIP_DIR_NAMES)

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)

    def _resolve_drive_letter(self) -> None:
        """If the app moved to another drive letter, move the same-drive folders with it."""
        current = app_drive()
        stored = (self._data.get("app_drive") or "").upper()
        self.drive_moved = None
        if not current:
            return
        if stored and stored != current:
            changed = False
            for entry in self._data["folders"]:
                if entry.get("on_app_drive") and entry["path"].upper().startswith(stored):
                    entry["path"] = current + entry["path"][len(stored):]
                    changed = True
            if changed:
                self.drive_moved = (stored, current)
        self._data["app_drive"] = current

    # -- folder list -------------------------------------------------------

    @property
    def setup_done(self) -> bool:
        return bool(self._data.get("setup_done"))

    @property
    def hotkey(self) -> str:
        return str(self._data.get("hotkey") or DEFAULT_HOTKEY)

    def set_hotkey(self, hotkey: str) -> None:
        with self._lock:
            self._data["hotkey"] = hotkey
            self.save()

    @property
    def shortcuts(self) -> Dict[str, List[str]]:
        """In-app keys the user changed: {action: ["Ctrl+K", ...]}. Missing actions use the defaults."""
        raw = self._data.get("shortcuts")
        if not isinstance(raw, dict):
            return {}
        return {str(k): [str(b) for b in v if isinstance(b, str)][:4]
                for k, v in raw.items() if isinstance(v, list)}

    def set_shortcuts(self, shortcuts: Dict[str, List[str]]) -> None:
        cleaned = {str(k)[:64]: [str(b)[:40] for b in v][:4] for k, v in shortcuts.items()}
        with self._lock:
            if cleaned:
                self._data["shortcuts"] = cleaned
            else:
                self._data.pop("shortcuts", None)
            self.save()

    @property
    def search_options(self):
        """How the smart search reads the search field ("search" in settings.json)."""
        from app.search_options import merge
        return merge(self._data.get("search"))

    def set_search_options(self, options: Dict[str, Any]) -> None:
        """Save only the options that differ from the defaults."""
        from app.search_options import DEFAULTS
        defaults = DEFAULTS.to_dict()
        changed = {k: v for k, v in options.items() if k in defaults and defaults[k] != v}
        with self._lock:
            if changed:
                self._data["search"] = changed
            else:
                self._data.pop("search", None)
            self.save()

    @property
    def start_with_windows(self) -> bool:
        """Start the app when you sign in to Windows (one entry in HKCU\\...\\Run, off by default)."""
        return bool(self._data.get("start_with_windows", False))

    @property
    def start_hidden(self) -> bool:
        """When Windows starts the app: stay in the tray (True) or open the window."""
        return bool(self._data.get("start_hidden", True))

    APP_KEYS = ("start_with_windows", "start_hidden", "open_on_mouse_monitor", "release_window_on_hide")

    def app_settings(self) -> Dict[str, bool]:
        return {k: getattr(self, k) for k in self.APP_KEYS}

    def set_app_settings(self, values: Dict[str, bool]) -> None:
        with self._lock:
            for k, v in values.items():
                if k in self.APP_KEYS:
                    self._data[k] = bool(v)
            self.save()

    @property
    def open_on_mouse_monitor(self) -> bool:
        """Open the window on the screen with the mouse pointer (not on a screen that is off)."""
        return bool(self._data.get("open_on_mouse_monitor", True))

    @property
    def release_window_on_hide(self) -> bool:
        """Close the WebView while the app is in the tray (saves about 190 MB; reopening takes about 1 s)."""
        return bool(self._data.get("release_window_on_hide", True))

    def folders(self) -> List[str]:
        with self._lock:
            return [entry["path"] for entry in self._data["folders"]]

    def set_folders(self, folders: List[str]) -> Tuple[List[str], List[str]]:
        """Replace the allowed folder list. Returns (added, removed)."""
        cleaned = merge_folders([normalize_folder(f) for f in folders if f and f.strip()])
        with self._lock:
            before = self.folders()
            drive = app_drive()
            self._data["folders"] = [
                {"path": f, "on_app_drive": bool(drive) and f.upper().startswith(drive)}
                for f in cleaned
            ]
            self._data["setup_done"] = True
            self.save()
        before_keys = {path_key(f) for f in before}
        after_keys = {path_key(f) for f in cleaned}
        added = [f for f in cleaned if path_key(f) not in before_keys]
        removed = [f for f in before if path_key(f) not in after_keys]
        return added, removed

    def is_allowed(self, path: str) -> bool:
        return self.covering_folder(path) is not None

    def covering_folder(self, path: str) -> Optional[str]:
        for folder in self.folders():
            if is_within(path, folder):
                return folder
        return None


def merge_folders(folders: List[str]) -> List[str]:
    """Remove duplicates and folders that sit inside another folder of the list."""
    result: List[str] = []
    for folder in sorted(folders, key=lambda f: len(path_key(f))):
        if any(is_within(folder, kept) for kept in result):
            continue
        result.append(folder)
    order: Dict[str, int] = {}
    for i, f in enumerate(folders):
        order.setdefault(path_key(f), i)
    return sorted(result, key=lambda f: order.get(path_key(f), 0))


def check_folder(raw_path: str, current: List[str]) -> Dict[str, Any]:
    """Validate a folder before the user adds it."""
    if not raw_path or not raw_path.strip():
        return {"ok": False, "path": "", "error": "Enter a folder path."}
    path = normalize_folder(raw_path)
    result: Dict[str, Any] = {"ok": True, "path": path, "error": None, "warning": None,
                              "covered_by": None, "contains": []}
    if not os.path.exists(path):
        return {**result, "ok": False, "error": "This folder does not exist."}
    if not os.path.isdir(path):
        return {**result, "ok": False, "error": "This is a file, not a folder."}
    if is_within(path, str(DATA_DIR)):
        return {**result, "ok": False, "error": "This folder holds the app's own data."}
    for folder in current:
        if is_within(path, folder):
            if path_key(path) == path_key(folder):
                return {**result, "ok": False, "covered_by": folder, "error": "This folder is already in the list."}
            return {**result, "ok": False, "covered_by": folder,
                    "error": f"This folder is already inside {folder}."}
    result["contains"] = [f for f in current if is_within(f, path)]
    if is_drive_root(path):
        result["warning"] = "This is a whole drive. The first scan can take a long time."
    elif result["contains"]:
        result["warning"] = f"This folder replaces {len(result['contains'])} folder(s) in the list that are inside it."
    return result


def suggested_folders() -> List[Dict[str, str]]:
    """Common user folders that exist on this PC (shown unticked in the setup screen)."""
    home = Path(os.path.expanduser("~"))
    names = [("Documents", "Documents"), ("Desktop", "Desktop"), ("Downloads", "Downloads"),
             ("Pictures", "Pictures")]
    result: List[Dict[str, str]] = []
    for label, sub in names:
        p = home / sub
        if p.is_dir():
            result.append({"label": label, "path": normalize_folder(str(p))})
    onedrive = os.environ.get("OneDrive")
    if onedrive and os.path.isdir(onedrive):
        result.append({"label": "OneDrive", "path": normalize_folder(onedrive)})
    return result


def available_drives() -> List[str]:
    return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
