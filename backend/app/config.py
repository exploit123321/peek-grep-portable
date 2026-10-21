"""Configuration for Peek & Grep Portable: data folder, ignore rules, and size limits.

The app keeps all of its state (settings, index, logs, browser cache) in one data folder.
In the portable release the layout is:

    <home>\\PeekGrep.exe
    <home>\\runtime\\        Python runtime
    <home>\\app\\            this code (desktop_app.py, backend\\, frontend\\dist\\)
    <home>\\data\\           settings.json, index.db, app.log, webview\\
"""

import os
from pathlib import Path
from typing import List, Set

APP_VERSION = "3.0.0"

BASE_DIR = Path(__file__).resolve().parent.parent  # backend\
PROJECT_ROOT = BASE_DIR.parent                     # folder with desktop_app.py and frontend\


def _detect_home() -> Path:
    """Find the portable home folder (the folder that holds app\\ and runtime\\)."""
    env_home = os.environ.get("PEEK_GREP_HOME")
    if env_home:
        return Path(env_home).resolve()
    if PROJECT_ROOT.name.lower() == "app" and (PROJECT_ROOT.parent / "runtime").is_dir():
        return PROJECT_ROOT.parent
    return PROJECT_ROOT


APP_HOME: Path = _detect_home()
DATA_DIR: Path = Path(os.environ.get("PEEK_GREP_DATA") or (APP_HOME / "data")).resolve()

DB_PATH: str = os.environ.get("PEEK_GREP_DB_PATH", str(DATA_DIR / "index.db"))
SETTINGS_PATH: str = os.environ.get("PEEK_GREP_SETTINGS", str(DATA_DIR / "settings.json"))
LOG_PATH: str = str(DATA_DIR / "app.log")

# Noisy system, cache, and development ignore directories
SYSTEM_IGNORE_DIRS: Set[str] = {
    "windows",
    "programdata",
    "$recycle.bin",
    "system volume information",
    "appdata",
    "temp",
    ".cache",
    "node_modules",
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
}

# Windows protected system folders and bloat directories to strictly skip
SKIP_DIR_NAMES: Set[str] = SYSTEM_IGNORE_DIRS | {
    "$winreagent",
    "recovery",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".system_generated",
    "coverage",
    ".next",
    ".turbo",
}

# Alias for backwards compatibility
IGNORE_DIRS: Set[str] = SKIP_DIR_NAMES

# Substring path exclusions (case-insensitive). They do not apply inside a working folder
# that itself matches the pattern, because the user selected that folder on purpose.
SKIP_PATH_PATTERNS: List[str] = [
    r"c:\windows",
    r"c:\programdata",
    r"appdata\local\temp",
    r"appdata\local\microsoft",
    r"$recycle.bin",
    r"system volume information",
]

# Text and code extensions that the crawler or the watcher can read at once
TIER2_FTS_EXTENSIONS: Set[str] = {
    ".txt",
    ".md",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".csv",
    ".sql",
    ".rs",
    ".go",
    ".html",
    ".css",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".xml",
}

# All formats that get full-text indexing (the content worker reads these)
CONTENT_INDEX_EXTENSIONS: Set[str] = TIER2_FTS_EXTENSIONS | {
    ".pdf", ".epub",
    # Microsoft Office, new and old formats (text is read by indexer/office.py)
    ".docx", ".docm", ".doc", ".xlsx", ".xlsm", ".xls", ".pptx", ".pptm", ".ppt",
}

# Strict file size boundary for direct full-text reads by the crawler and watcher (2MB)
MAX_FTS_SIZE_BYTES: int = 2 * 1024 * 1024

# Maximum file size for the content worker (PDF, EPUB, and large text files)
MAX_CONTENT_SIZE_BYTES: int = 10 * 1024 * 1024

# Maximum file size for Tier 1 metadata indexing (skip virtual/sparse files > 500GB)
MAX_METADATA_SIZE_BYTES: int = 500 * 1024 * 1024 * 1024

# Extensions to skip even for metadata (system lock / temp files)
IGNORE_EXTENSIONS: Set[str] = {
    ".lock",
    ".tmp",
    ".db-wal",
    ".db-shm",
}

# Batch size and time flush interval for high-throughput SQLite commits
CRAWLER_BATCH_SIZE: int = 1000
CRAWLER_FLUSH_INTERVAL: float = 0.5
