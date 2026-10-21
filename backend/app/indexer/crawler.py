"""Folder crawler with two-tier indexing, per-folder progress, and permission resilience."""

import os
import threading
import time
from typing import Any, Dict, List, Optional
from app.config import (
    CRAWLER_BATCH_SIZE,
    CRAWLER_FLUSH_INTERVAL,
    IGNORE_EXTENSIONS,
    MAX_FTS_SIZE_BYTES,
    MAX_METADATA_SIZE_BYTES,
    SKIP_DIR_NAMES,
    SKIP_PATH_PATTERNS,
    TIER2_FTS_EXTENSIONS,
)
from app.indexer.db import count_files, delete_unseen_in_folder, upsert_files_batch
from app.indexer.parsers import get_file_category, is_text_file


class IndexerProgressTracker:
    """Thread-safe state container reporting live crawl status, per folder and in total."""

    def __init__(self):
        self._lock = threading.Lock()
        self.is_crawling: bool = False
        self.total_indexed: int = 0
        self.current_drive: Optional[str] = None
        self.current_folder: Optional[str] = None
        self.current_path: Optional[str] = None
        self.start_time: float = 0.0
        self.duration_seconds: float = 0.0
        self.files_per_sec: float = 0.0
        self.errors_encountered: int = 0
        self.scanned_this_run: int = 0
        # folder path -> {"path", "state", "files", "started_at", "finished_at"}
        self.folders: Dict[str, Dict[str, Any]] = {}

    def queue_folders(self, roots: List[str]) -> None:
        with self._lock:
            for root in roots:
                self.folders[root] = {"path": root, "state": "queued", "files": 0,
                                      "started_at": None, "finished_at": None}

    def forget_folder(self, root: str) -> None:
        with self._lock:
            self.folders.pop(root, None)

    def start_crawl(self, roots: List[str], db_path: Optional[str] = None) -> None:
        total = count_files(db_path=db_path)
        with self._lock:
            self.is_crawling = True
            self.total_indexed = total
            self.current_drive = roots[0] if roots else None
            self.current_path = "Starting crawler..."
            self.start_time = time.time()
            self.duration_seconds = 0.0
            self.files_per_sec = 0.0
            self.errors_encountered = 0
            self.scanned_this_run = 0
            for root in roots:
                entry = self.folders.get(root)
                if entry is None or entry["state"] != "queued":
                    self.folders[root] = {"path": root, "state": "queued", "files": 0,
                                          "started_at": None, "finished_at": None}

    def start_folder(self, root: str) -> None:
        with self._lock:
            self.current_folder = root
            self.current_drive = os.path.splitdrive(root)[0] or root
            entry = self.folders.setdefault(root, {"path": root})
            entry.update({"state": "scanning", "files": 0, "started_at": time.time(), "finished_at": None})

    def finish_folder(self, root: str, state: str) -> None:
        with self._lock:
            entry = self.folders.setdefault(root, {"path": root, "files": 0})
            entry["state"] = state
            entry["finished_at"] = time.time()

    def update_progress(self, indexed_delta: int, current_path: str, drive: Optional[str] = None,
                        folder: Optional[str] = None) -> None:
        with self._lock:
            self.total_indexed += indexed_delta
            self.scanned_this_run += indexed_delta
            self.current_path = current_path
            if drive:
                self.current_drive = drive
            if folder and folder in self.folders:
                self.folders[folder]["files"] = self.folders[folder].get("files", 0) + indexed_delta
            elapsed = max(0.1, time.time() - self.start_time)
            self.duration_seconds = round(elapsed, 1)
            self.files_per_sec = round(self.scanned_this_run / elapsed, 1)

    def record_error(self) -> None:
        with self._lock:
            self.errors_encountered += 1

    def end_crawl(self, db_path: Optional[str] = None) -> None:
        total = count_files(db_path=db_path)
        with self._lock:
            self.is_crawling = False
            self.current_path = "Idle"
            self.current_folder = None
            self.total_indexed = total
            elapsed = max(0.1, time.time() - self.start_time)
            self.duration_seconds = round(elapsed, 2)
            self.files_per_sec = round(self.scanned_this_run / elapsed, 1)

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "is_crawling": self.is_crawling,
                "total_indexed": self.total_indexed,
                "current_drive": self.current_drive,
                "current_folder": self.current_folder,
                "current_path": self.current_path,
                "files_per_sec": self.files_per_sec,
                "elapsed_seconds": self.duration_seconds,
                "errors_encountered": self.errors_encountered,
                "folders": [dict(v) for v in self.folders.values()],
            }

# Global singleton tracker
crawler_tracker = IndexerProgressTracker()

def is_protected_directory(dir_path: str, dir_name: str, root: Optional[str] = None) -> bool:
    """Check if directory is a protected Windows system folder or development bloat.

    When root (the working folder) is given, path patterns that the root itself matches
    do not apply, because the user selected that folder on purpose.
    """
    lower_name = dir_name.lower().strip()
    if lower_name in SKIP_DIR_NAMES or lower_name.startswith("$"):
        return True

    lower_path = dir_path.lower()
    lower_root = root.lower() if root else ""
    for pattern in SKIP_PATH_PATTERNS:
        if pattern in lower_path and pattern not in lower_root:
            return True

    return False

def should_skip_metadata(filename: str, ext: str) -> bool:
    """Determine if a file should be skipped even for basic metadata."""
    if ext in IGNORE_EXTENSIONS:
        return True
    if filename.startswith("~$"):
        return True
    return False

def should_skip_directory(dir_name: str) -> bool:
    """Check if a directory matches protected or bloat directories."""
    return is_protected_directory("", dir_name)

def should_skip_file(filename: str) -> bool:
    """Check if file should be skipped from crawling."""
    ext = os.path.splitext(filename)[1].lower()
    return should_skip_metadata(filename, ext)

def process_single_file(filepath: str, max_fts_size: int = MAX_FTS_SIZE_BYTES, db_path: Optional[str] = None) -> bool:
    """Process and index an individual file."""
    rec = build_file_record(filepath, max_fts_size)
    if rec:
        upsert_files_batch([rec], db_path=db_path)
        return True
    return False

def build_file_record(
    filepath: str,
    max_fts_size: int = MAX_FTS_SIZE_BYTES,
    stat_obj: Optional[os.stat_result] = None,
    filename: Optional[str] = None,
    extract_content: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """
    Produce an indexed file record:
    - Pass 1 (Primary pass): Fast stat-only metadata extraction (path, filename, size, extension, mtime).
      Zero disk file opens / content parsing during Pass 1 (content is None).
    - Standalone / Direct call: Extracts content if requested or when stat_obj is None.
    """
    if extract_content is None:
        extract_content = (stat_obj is None)

    try:
        norm_path = os.path.normpath(os.path.abspath(filepath))
        fname = filename or os.path.basename(norm_path)
        ext = os.path.splitext(fname)[1].lower()

        if should_skip_metadata(fname, ext):
            return None

        if stat_obj is None:
            stat_obj = os.stat(norm_path)

        size = stat_obj.st_size
        mtime = stat_obj.st_mtime

        if size > MAX_METADATA_SIZE_BYTES:
            return None

        category = get_file_category(ext)
        is_text = is_text_file(norm_path, ext, probe_bytes=False)

        content: Optional[str] = None
        # During Pass 1, extract_content is False. Only read if explicitly requested (e.g. standalone/tests)
        if extract_content and ext in TIER2_FTS_EXTENSIONS and size <= max_fts_size:
            try:
                with open(norm_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except Exception:
                content = None

        return {
            "path": norm_path,
            "filename": fname,
            "extension": ext,
            "size_bytes": size,
            "mtime": mtime,
            "is_text": is_text,
            "category": category,
            "content": content,
        }
    except (PermissionError, FileNotFoundError, OSError):
        return None
    except Exception:
        return None


class SafeDriveCrawler:
    """Folder crawler with decoupled stat-only walk, batch buffering, timed flush, and a sweep of deleted files."""

    def __init__(
        self,
        roots: Optional[List[str]] = None,
        batch_size: int = CRAWLER_BATCH_SIZE,
        max_fts_size: int = MAX_FTS_SIZE_BYTES,
        flush_interval: float = CRAWLER_FLUSH_INTERVAL,
        db_path: Optional[str] = None,
        excluded: Optional[List[str]] = None,
        tracker: Optional[IndexerProgressTracker] = None,
    ):
        self.roots = list(roots or [])
        self.batch_size = batch_size
        self.max_fts_size = max_fts_size
        self.flush_interval = flush_interval
        self.db_path = db_path
        self.excluded = [os.path.normcase(os.path.normpath(p)) for p in (excluded or [])]
        self.tracker = tracker or crawler_tracker
        self._stop_requested = False

    def stop(self) -> None:
        self._stop_requested = True

    def _is_excluded(self, path: str) -> bool:
        key = os.path.normcase(path)
        return any(key == ex or key.startswith(ex + os.sep) for ex in self.excluded)

    def crawl_folder(self, root_dir: str) -> int:
        """Walk one working folder. Returns the number of files written."""
        tracker = self.tracker
        norm_root = os.path.normpath(os.path.abspath(root_dir))
        if not os.path.isdir(norm_root):
            tracker.finish_folder(root_dir, "missing")
            return 0

        tracker.start_folder(root_dir)
        scan_started = time.time()
        drive_label = os.path.splitdrive(norm_root)[0] or norm_root
        batch: List[Dict[str, Any]] = []
        written = 0
        last_flush_time = time.time()
        dirs_to_visit: List[str] = [norm_root]

        def flush(current: str) -> None:
            nonlocal written, last_flush_time
            if not batch:
                return
            upsert_files_batch(batch, db_path=self.db_path)
            written += len(batch)
            tracker.update_progress(indexed_delta=len(batch), current_path=current,
                                    drive=drive_label, folder=root_dir)
            batch.clear()
            last_flush_time = time.time()

        while dirs_to_visit and not self._stop_requested:
            curr_dir = dirs_to_visit.pop()
            try:
                with os.scandir(curr_dir) as it:
                    for entry in it:
                        if self._stop_requested:
                            break
                        try:
                            is_dir = entry.is_dir(follow_symlinks=False)
                        except (PermissionError, FileNotFoundError, OSError):
                            tracker.record_error()
                            continue

                        if is_dir:
                            if not is_protected_directory(entry.path, entry.name, norm_root) and not self._is_excluded(entry.path):
                                dirs_to_visit.append(entry.path)
                            continue

                        try:
                            stat_res = entry.stat(follow_symlinks=False)
                        except (PermissionError, FileNotFoundError, OSError):
                            tracker.record_error()
                            continue

                        record = build_file_record(
                            entry.path,
                            max_fts_size=self.max_fts_size,
                            stat_obj=stat_res,
                            filename=entry.name,
                        )
                        if record:
                            record["seen_at"] = scan_started
                            batch.append(record)

                        # Buffer discovered files in memory: flush every 1,000 files or every 0.5s
                        if len(batch) >= self.batch_size or (time.time() - last_flush_time >= self.flush_interval and batch):
                            flush(entry.path)
            except (PermissionError, FileNotFoundError, OSError):
                tracker.record_error()
                if curr_dir == norm_root:
                    # The folder itself cannot be read: keep the old index entries
                    tracker.finish_folder(root_dir, "error")
                    return written

        if self._stop_requested:
            tracker.finish_folder(root_dir, "stopped")
            return written

        flush("Complete")
        # Files that were indexed before but not seen now were deleted or moved
        delete_unseen_in_folder(norm_root, scan_started, db_path=self.db_path)
        tracker.finish_folder(root_dir, "done")
        return written

    def crawl_and_index(self) -> Dict[str, Any]:
        """Walk every working folder in turn."""
        self.tracker.start_crawl(self.roots, db_path=self.db_path)
        indexed_total = 0
        try:
            for root_dir in self.roots:
                if self._stop_requested:
                    break
                indexed_total += self.crawl_folder(root_dir)
        finally:
            self.tracker.end_crawl(db_path=self.db_path)

        return {
            "indexed_count": indexed_total,
            "status": self.tracker.get_status(),
        }

# Backwards-compatibility alias
DirectoryCrawler = SafeDriveCrawler
