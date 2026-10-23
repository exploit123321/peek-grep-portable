"""Index manager: owns the crawler, the content worker, and the watcher.

Nothing runs until the user confirms at least one working folder. When the folder list
changes, removed folders are purged from the index, new folders are scanned, and the
watcher restarts on the new list.
"""

import os
import queue
import threading
import time
from typing import Any, Dict, List, Optional

from app.big_files import BIG_MAX_BYTES, matches
from app.config import DATA_DIR, MAX_CONTENT_SIZE_BYTES, MAX_OFFICE_SIZE_BYTES, content_size_limit
from app.indexer.crawler import IndexerProgressTracker, SafeDriveCrawler, build_file_record, crawler_tracker
from app.indexer.db import (
    count_files,
    count_files_in_folders,
    count_fts_indexed,
    count_unindexed_content_files,
    delete_folder,
    delete_outside_folders,
    get_file_meta,
    init_db,
    mark_files_fts_indexed,
    rebase_drive,
    upsert_files_batch,
)
from app.indexer.fts_worker import PASS2_EXTENSIONS, FTSContentWorker, fts_worker_tracker
from app.indexer.smart_search import clear_cache
from app.indexer.watcher import FileWatcherManager
from app.settings import SettingsStore, path_key


class IndexManager:
    """Single owner of all background indexing work."""

    def __init__(self, settings: SettingsStore, db_path: Optional[str] = None,
                 tracker: Optional[IndexerProgressTracker] = None):
        self.settings = settings
        self.db_path = db_path
        self.tracker = tracker or crawler_tracker
        self.excluded = [str(DATA_DIR)]
        self.watcher = FileWatcherManager(db_path=db_path, excluded=self.excluded)
        self._lock = threading.RLock()
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._queued: Dict[str, bool] = {}
        self._crawler: Optional[SafeDriveCrawler] = None
        self._crawl_thread: Optional[threading.Thread] = None
        self._fts_worker: Optional[FTSContentWorker] = None
        self._fts_thread: Optional[threading.Thread] = None
        self._started = False
        self._stopping = False
        self.last_change: float = time.time()

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Open the database and start work only if folders are configured."""
        init_db(self.db_path)
        moved = self.settings.drive_moved
        if moved:
            changed = rebase_drive(moved[0], moved[1], db_path=self.db_path)
            print(f"[Index] App drive moved {moved[0]} -> {moved[1]}: rebased {changed} paths.")
            self.settings.save()

        folders = self.settings.folders()
        if not self.settings.setup_done or not folders:
            print("[Index] No working folders yet. Waiting for the user to choose folders.")
            return

        # Safety: the index may hold paths from an older folder list
        delete_outside_folders(folders, db_path=self.db_path)
        self._start_workers(folders)
        # Catch up on changes made while the app was closed
        self.queue_scan(folders)

    def _start_workers(self, folders: List[str]) -> None:
        with self._lock:
            if not self._started:
                self._started = True
                self._crawl_thread = threading.Thread(target=self._crawl_loop, name="crawler", daemon=True)
                self._crawl_thread.start()
                self._fts_worker = FTSContentWorker(db_path=self.db_path, path_filter=self.settings.is_allowed,
                                                   big_rules=lambda: self.settings.big_files)
                self._fts_thread = threading.Thread(target=self._fts_worker.run, name="content", daemon=True)
                self._fts_thread.start()
            self.watcher.restart(folders)

    def stop(self) -> None:
        self._stopping = True
        with self._lock:
            if self._crawler:
                self._crawler.stop()
            self._queue.put(None)
            if self._fts_worker:
                self._fts_worker.stop()
            self.watcher.stop()

    # -- folder changes --------------------------------------------------------

    def apply_folders(self, folders: List[str]) -> Dict[str, Any]:
        """Save a new folder list and update the index to match it."""
        added, removed = self.settings.set_folders(folders)
        current = self.settings.folders()
        with self._lock:
            # Stop a scan of a folder that the user removed
            if self._crawler and any(path_key(r) in {path_key(x) for x in removed} for r in self._crawler.roots):
                self._crawler.stop()
            for folder in removed:
                self._queued.pop(path_key(folder), None)
                self.tracker.forget_folder(folder)
        purged = 0
        for folder in removed:
            purged += delete_folder(folder, db_path=self.db_path)
        if removed:
            purged += delete_outside_folders(current, db_path=self.db_path)
        if current:
            self._start_workers(current)
            self.queue_scan(added)
        else:
            self.watcher.stop()
        self.last_change = time.time()
        return {"added": added, "removed": removed, "purged_files": purged, "folders": current}

    def queue_scan(self, folders: Optional[List[str]] = None) -> List[str]:
        """Queue a scan of some or all working folders."""
        allowed = self.settings.folders()
        targets = folders if folders is not None else allowed
        accepted: List[str] = []
        allowed_keys = {path_key(f): f for f in allowed}
        for folder in targets:
            key = path_key(folder)
            if key not in allowed_keys or self._queued.get(key):
                continue
            self._queued[key] = True
            canonical = allowed_keys[key]
            self.tracker.queue_folders([canonical])
            self._queue.put(canonical)
            accepted.append(canonical)
        if accepted and not self._started:
            self._start_workers(allowed)
        return accepted

    def _crawl_loop(self) -> None:
        while not self._stopping:
            folder = self._queue.get()
            if folder is None:
                break
            if path_key(folder) not in {path_key(f) for f in self.settings.folders()}:
                self._queued.pop(path_key(folder), None)
                continue
            crawler = SafeDriveCrawler(roots=[folder], db_path=self.db_path,
                                       excluded=self.excluded, tracker=self.tracker)
            with self._lock:
                self._crawler = crawler
            try:
                print(f"[Crawler] Scanning {folder}")
                result = crawler.crawl_and_index()
                print(f"[Crawler] {folder}: {result['indexed_count']} files")
            except Exception as e:
                print(f"[Crawler] Error in {folder}: {e}")
                self.tracker.finish_folder(folder, "error")
            finally:
                with self._lock:
                    self._crawler = None
                self._queued.pop(path_key(folder), None)
                self.last_change = time.time()

    def index_file_now(self, path: str) -> bool:
        """Index one file at once, its name and its text (after a save in the editor), so a
        search finds the new text without waiting for the watcher. Files the index skips stay out."""
        if get_file_meta(path, db_path=self.db_path) is None:
            return False
        rec = build_file_record(path, extract_content=False)
        if rec is None:
            return False
        upsert_files_batch([rec], db_path=self.db_path)
        ext = rec["extension"]
        big = matches(self.settings.big_files, rec["path"], rec["filename"], ext)
        if ext in PASS2_EXTENSIONS and rec["size_bytes"] <= (BIG_MAX_BYTES if big else content_size_limit(ext)):
            text = FTSContentWorker(db_path=self.db_path).extract_text_from_file(rec["path"], ext, big)
            if text:
                mark_files_fts_indexed([(rec["path"], text)], [], db_path=self.db_path)
            else:
                mark_files_fts_indexed([], [rec["path"]], db_path=self.db_path)
        self.last_change = time.time()
        clear_cache()
        return True

    # -- status ----------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        crawl = self.tracker.get_status()
        known = {path_key(f["path"]): f for f in crawl.get("folders", [])}
        folders = []
        for folder in self.settings.folders():
            entry = known.get(path_key(folder), {})
            folders.append({
                "path": folder,
                "state": entry.get("state", "idle"),
                "files": entry.get("files", 0),
                "exists": os.path.isdir(folder),
            })
        pending = count_unindexed_content_files(PASS2_EXTENSIONS, MAX_CONTENT_SIZE_BYTES, db_path=self.db_path,
                                                office_max_bytes=MAX_OFFICE_SIZE_BYTES,
                                                big_rules=self.settings.big_files)
        busy_scan = crawl["is_crawling"] or not self._queue.empty()
        phase = "setup" if not self.settings.setup_done or not folders else (
            "scanning" if busy_scan else ("reading" if pending else "ready"))
        return {
            "phase": phase,
            "is_crawling": crawl["is_crawling"],
            "total_indexed": count_files(self.db_path),
            "current_folder": crawl.get("current_folder"),
            "current_path": crawl.get("current_path"),
            "files_per_sec": crawl.get("files_per_sec", 0),
            "elapsed_seconds": crawl.get("elapsed_seconds", 0),
            "errors_encountered": crawl.get("errors_encountered", 0),
            "folders": folders,
            "content": {
                "indexed": count_fts_indexed(self.db_path),
                "pending": pending,
                "current_file": fts_worker_tracker.get_status().get("current_file"),
            },
            "watcher_active": self.watcher.is_active,
        }

    def folder_details(self) -> List[Dict[str, Any]]:
        folders = self.settings.folders()
        counts = count_files_in_folders(folders, db_path=self.db_path)
        crawl = {path_key(f["path"]): f for f in self.tracker.get_status().get("folders", [])}
        return [{
            "path": f,
            "files": counts.get(f, 0),
            "exists": os.path.isdir(f),
            "state": crawl.get(path_key(f), {}).get("state", "idle"),
        } for f in folders]
