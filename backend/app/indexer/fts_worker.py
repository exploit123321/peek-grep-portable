"""Pass 2: Background FTS content worker for PDF, EPUB, Markdown, text, code, and CSV."""

import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.config import CONTENT_INDEX_EXTENSIONS, MAX_CONTENT_SIZE_BYTES
from app.indexer.db import (
    count_fts_indexed,
    get_unindexed_content_files,
    mark_files_fts_indexed,
)
from app.indexer.office import OFFICE_EXTENSIONS, extract_office_text
from app.indexer.parsers import extract_epub_data, extract_pdf_text

# Whitelisted extensions for Pass 2 deep full-text indexing
PASS2_EXTENSIONS: Tuple[str, ...] = tuple(sorted(CONTENT_INDEX_EXTENSIONS))

class FTSContentWorkerTracker:
    """Thread-safe status tracker for Pass 2 background FTS content indexing."""

    def __init__(self):
        self._lock = threading.Lock()
        self.is_running: bool = False
        self.total_indexed: int = 0
        self.current_file: Optional[str] = None
        self.errors_encountered: int = 0

    def update_progress(self, indexed_delta: int, current_file: str) -> None:
        with self._lock:
            self.total_indexed += indexed_delta
            self.current_file = current_file

    def record_error(self) -> None:
        with self._lock:
            self.errors_encountered += 1

    def set_running(self, running: bool) -> None:
        with self._lock:
            self.is_running = running
            if not running:
                self.current_file = "Idle"

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "is_running": self.is_running,
                "total_content_indexed": self.total_indexed,
                "current_file": self.current_file,
                "errors_encountered": self.errors_encountered,
            }

fts_worker_tracker = FTSContentWorkerTracker()

class FTSContentWorker:
    """Secondary background thread worker extracting text and indexing into FTS5."""

    def __init__(
        self,
        extensions: Tuple[str, ...] = PASS2_EXTENSIONS,
        max_size_bytes: int = MAX_CONTENT_SIZE_BYTES,
        batch_size: int = 50,
        db_path: Optional[str] = None,
        path_filter: Optional[Callable[[str], bool]] = None,
    ):
        self.extensions = extensions
        self.max_size_bytes = max_size_bytes
        self.batch_size = batch_size
        self.db_path = db_path
        self.path_filter = path_filter
        self._stop_requested = threading.Event()

    def stop(self) -> None:
        self._stop_requested.set()

    def extract_text_from_file(self, filepath: str, ext: str) -> Optional[str]:
        """Extract plain text based on file format (PDF, EPUB, Markdown, text, code, CSV)."""
        try:
            if not os.path.exists(filepath):
                return None

            if ext == ".pdf":
                return extract_pdf_text(filepath, max_pages=50)

            if ext == ".epub":
                epub_info = extract_epub_data(filepath)
                return epub_info.get("text")

            if ext in OFFICE_EXTENSIONS:
                return extract_office_text(filepath, ext)

            # Text / Code / CSV / Markdown
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read().strip()
                return content if content else None
            except Exception:
                return None
        except Exception:
            return None

    def process_batch(self, limit: Optional[int] = None) -> int:
        """Process a single batch of unindexed files. Returns number of processed items (indexed or skipped)."""
        batch_limit = limit or self.batch_size
        unindexed_batch = get_unindexed_content_files(
            extensions=self.extensions,
            max_size_bytes=self.max_size_bytes,
            limit=batch_limit,
            db_path=self.db_path,
        )

        if not unindexed_batch:
            return 0

        indexed_items: List[Tuple[str, str]] = []
        skipped_paths: List[str] = []

        for item in unindexed_batch:
            if self._stop_requested.is_set():
                break

            path = item["path"]
            ext = item["extension"].lower()

            # Never read a file outside the allowed folders
            if self.path_filter and not self.path_filter(path):
                skipped_paths.append(path)
                continue

            fts_worker_tracker.update_progress(0, path)

            try:
                text = self.extract_text_from_file(path, ext)
                if text:
                    indexed_items.append((path, text))
                else:
                    skipped_paths.append(path)
            except Exception:
                fts_worker_tracker.record_error()
                skipped_paths.append(path)

        if indexed_items or skipped_paths:
            mark_files_fts_indexed(
                indexed_items=indexed_items,
                skipped_paths=skipped_paths,
                db_path=self.db_path,
            )
            fts_worker_tracker.update_progress(
                indexed_delta=len(indexed_items),
                current_file="Batch indexed",
            )

        return len(indexed_items) + len(skipped_paths)

    def run(self) -> None:
        """Main worker loop continuously processing unindexed files in background."""
        fts_worker_tracker.set_running(True)
        fts_worker_tracker.total_indexed = count_fts_indexed(self.db_path)

        try:
            while not self._stop_requested.is_set():
                count = self.process_batch()
                if count == 0:
                    # No pending files, sleep 1.0s before polling again
                    if self._stop_requested.wait(1.0):
                        break
                    continue

                # Brief yield so other threads / UI requests have priority
                time.sleep(0.01)

        finally:
            fts_worker_tracker.set_running(False)
