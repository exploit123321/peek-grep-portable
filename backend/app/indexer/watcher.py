"""Watchdog real-time file system change listener, limited to the allowed working folders."""

import os
import threading
import time
from typing import Dict, List, Optional, Set
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from app.config import (
    IGNORE_EXTENSIONS,
    SKIP_DIR_NAMES,
    SKIP_PATH_PATTERNS,
    SYSTEM_IGNORE_DIRS,
)
from app.indexer.crawler import process_single_file
from app.indexer.db import delete_file


def _key(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


class DebouncedChangeHandler(FileSystemEventHandler):
    """Handles file modifications and deletions with a small debounce window and strict path pruning."""

    def __init__(
        self,
        debounce_sec: float = 0.5,
        db_path: Optional[str] = None,
        roots: Optional[List[str]] = None,
        excluded: Optional[List[str]] = None,
    ):
        super().__init__()
        self.debounce_sec = debounce_sec
        self.db_path = db_path
        self.root_keys = [_key(r) for r in roots] if roots is not None else None
        self.excluded_keys = [_key(p) for p in (excluded or [])]
        self._pending_updates: Dict[str, float] = {}
        self._pending_deletes: Set[str] = set()
        self._lock = threading.Lock()
        self._running = True
        self._worker_thread = threading.Thread(target=self._debounce_worker, daemon=True)
        self._worker_thread.start()

    def _root_of(self, norm_key: str) -> Optional[str]:
        """Return the working folder that holds this path ('' when no folder limit is set)."""
        if self.root_keys is None:
            return ""
        for root in self.root_keys:
            prefix = root if root.endswith(os.sep) else root + os.sep
            if norm_key == root or norm_key.startswith(prefix):
                return root
        return None

    def should_ignore(self, path: Optional[str]) -> bool:
        """
        Strictly verify if a file system event path should be discarded immediately.
        Discards paths outside the working folders, and paths that intersect SYSTEM_IGNORE_DIRS,
        protected patterns, or ignored extensions below the working folder.
        """
        if not path:
            return True

        norm = _key(path)
        root = self._root_of(norm)
        if root is None:
            return True

        for ex in self.excluded_keys:
            if norm == ex or norm.startswith(ex + os.sep):
                return True

        # Only the part below the working folder is checked against the ignore rules
        relative = norm[len(root):] if root else norm
        parts = relative.split(os.sep)
        for part in parts[:-1] if root else parts:
            clean_part = part.strip()
            if clean_part in SKIP_DIR_NAMES:
                return True
            if clean_part.startswith("$"):
                return True

        # Check substring path patterns (e.g. appdata, temp, system volume information, windows)
        for pattern in SKIP_PATH_PATTERNS:
            if pattern in norm and pattern not in root:
                return True

        # Check filename prefixes (office temp files, hidden files)
        basename = os.path.basename(norm)
        if basename.startswith("~$") or basename.startswith("."):
            return True

        # Check extensions
        ext = os.path.splitext(basename)[1].lower()
        if ext in IGNORE_EXTENSIONS:
            return True

        # Ephemeral system files
        if ext in {".tmp", ".log", ".lock", ".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3"}:
            return True

        return False

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory or self.should_ignore(event.src_path):
            return
        with self._lock:
            self._pending_updates[event.src_path] = time.time()

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory or self.should_ignore(event.src_path):
            return
        with self._lock:
            self._pending_updates[event.src_path] = time.time()

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory or self.should_ignore(event.src_path):
            return
        with self._lock:
            self._pending_updates.pop(event.src_path, None)
            self._pending_deletes.add(event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        src_ignored = self.should_ignore(event.src_path)
        dest_path = getattr(event, "dest_path", None)
        dest_ignored = self.should_ignore(dest_path)

        with self._lock:
            if not src_ignored:
                self._pending_updates.pop(event.src_path, None)
                self._pending_deletes.add(event.src_path)
            if dest_path and not dest_ignored:
                self._pending_updates[dest_path] = time.time()

    def _debounce_worker(self) -> None:
        while self._running:
            time.sleep(0.2)
            now = time.time()
            to_update: List[str] = []
            to_delete: List[str] = []

            with self._lock:
                for path, timestamp in list(self._pending_updates.items()):
                    if now - timestamp >= self.debounce_sec:
                        to_update.append(path)
                        del self._pending_updates[path]

                if self._pending_deletes:
                    # Apps (and this one) save by writing a temporary file and renaming it over
                    # the old one; Windows reports that as a delete, so a file that is there is updated
                    for path in self._pending_deletes:
                        if os.path.isfile(path):
                            self._pending_updates.setdefault(path, now)
                        else:
                            to_delete.append(path)
                    self._pending_deletes.clear()

            for path in to_delete:
                try:
                    delete_file(path, db_path=self.db_path)
                except Exception as e:
                    print(f"[Watcher] Error deleting {path}: {e}")

            for path in to_update:
                try:
                    process_single_file(path, db_path=self.db_path)
                except Exception as e:
                    print(f"[Watcher] Error processing {path}: {e}")

    def stop(self) -> None:
        self._running = False


class FileWatcherManager:
    """Manages the lifecycle of Watchdog observers over the working folders."""

    def __init__(self, roots: Optional[List[str]] = None, db_path: Optional[str] = None,
                 excluded: Optional[List[str]] = None):
        self.roots = list(roots or [])
        self.db_path = db_path
        self.excluded = list(excluded or [])
        self.observer: Optional[Observer] = None
        self.handler: Optional[DebouncedChangeHandler] = None
        self.watched: List[str] = []

    @property
    def is_active(self) -> bool:
        return self.observer is not None and bool(self.watched)

    def start(self, roots: Optional[List[str]] = None) -> None:
        """Start the watchdog observer (no folders means nothing is watched)."""
        if roots is not None:
            self.roots = list(roots)
        if self.observer is not None or not self.roots:
            return

        self.handler = DebouncedChangeHandler(db_path=self.db_path, roots=self.roots, excluded=self.excluded)
        self.observer = Observer()
        self.watched = []

        for root in self.roots:
            norm_root = os.path.normpath(os.path.abspath(root))
            if os.path.isdir(norm_root):
                try:
                    self.observer.schedule(self.handler, norm_root, recursive=True)
                    self.watched.append(norm_root)
                    print(f"[Watcher] Observing filesystem changes in: {norm_root}")
                except Exception as e:
                    print(f"[Watcher] Warning: could not watch {norm_root}: {e}")

        try:
            self.observer.start()
        except Exception as e:
            print(f"[Watcher] Error starting observer: {e}")

    def restart(self, roots: List[str]) -> None:
        self.stop()
        self.start(roots)

    def stop(self) -> None:
        """Stop the watchdog observer cleanly."""
        if self.handler:
            self.handler.stop()
            self.handler = None
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join(timeout=2)
            except Exception:
                pass
            self.observer = None
            self.watched = []
            print("[Watcher] Observer stopped.")
