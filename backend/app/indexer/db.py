"""SQLite FTS5 database management and search operations with concurrency lock & backoff."""

import html
import os
import re
import sqlite3
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from app.config import DB_PATH
from app.schemas import SearchResultItem

# Thread-local storage for SQLite connections
_local = threading.local()

# Process-wide write mutex to prevent SQLite concurrent lock contention
_write_lock = threading.Lock()

# Snippet markers: FTS5 wraps hits in these, then the text is HTML-escaped and the markers become <mark>
_MARK_OPEN = "\x02"
_MARK_CLOSE = "\x03"

# Search filter groups (UI chips) that span more than one category
DOC_EXTENSIONS: Tuple[str, ...] = (".txt", ".rtf", ".log", ".doc", ".docx", ".odt")


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Get or create a thread-local SQLite connection with high busy timeout, WAL mode, and autocommit isolation."""
    target_path = db_path or DB_PATH
    conn = getattr(_local, "connection", None)
    current_path = getattr(_local, "current_path", None)

    if conn is None or current_path != target_path:
        os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
        conn = sqlite3.connect(target_path, timeout=60.0, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 60000;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA cache_size = -64000;")  # 64MB cache
        conn.execute("PRAGMA temp_store = MEMORY;")
        _local.connection = conn
        _local.current_path = target_path

    return conn

def execute_write_with_retry(action_fn: Callable[[], Any], max_attempts: int = 5) -> Any:
    """Execute a write transaction guarded by a thread mutex with exponential backoff on lock errors."""
    with _write_lock:
        last_err = None
        for attempt in range(max_attempts):
            try:
                return action_fn()
            except sqlite3.OperationalError as e:
                last_err = e
                err_str = str(e).lower()
                if "locked" in err_str or "busy" in err_str:
                    time.sleep(0.05 * (2 ** attempt))
                else:
                    raise
        if last_err:
            raise last_err

def _run_transaction(db_path: Optional[str], statements: Callable[[sqlite3.Cursor], Any]) -> Any:
    """Run statements in one guarded transaction."""
    def _tx():
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute("BEGIN TRANSACTION;")
        try:
            result = statements(cur)
            cur.execute("COMMIT;")
            return result
        except Exception:
            cur.execute("ROLLBACK;")
            raise
    return execute_write_with_retry(_tx)

def init_db(db_path: Optional[str] = None) -> None:
    """Initialize SQLite database tables and FTS5 virtual table."""
    def _init(cur: sqlite3.Cursor) -> None:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS files_meta (
                path TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                extension TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                mtime REAL NOT NULL,
                is_text INTEGER NOT NULL,
                category TEXT NOT NULL,
                fts_indexed INTEGER NOT NULL DEFAULT 0,
                seen_at REAL NOT NULL DEFAULT 0
            );
        """)
        # Columns added after the first release
        existing = {row[1] for row in cur.execute("PRAGMA table_info(files_meta);").fetchall()}
        if "fts_indexed" not in existing:
            cur.execute("ALTER TABLE files_meta ADD COLUMN fts_indexed INTEGER NOT NULL DEFAULT 0;")
        if "seen_at" not in existing:
            cur.execute("ALTER TABLE files_meta ADD COLUMN seen_at REAL NOT NULL DEFAULT 0;")

        cur.execute("CREATE INDEX IF NOT EXISTS idx_files_meta_filename ON files_meta(filename COLLATE NOCASE);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_files_meta_category ON files_meta(category);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_files_meta_mtime ON files_meta(mtime DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_files_meta_fts ON files_meta(fts_indexed, extension);")

        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS files_content_fts USING fts5(
                path UNINDEXED,
                content,
                tokenize = 'unicode61'
            );
        """)
    _run_transaction(db_path, _init)

def escape_fts5_query(query: str, prefix: bool = True) -> str:
    """
    Safely tokenize and escape search query terms for SQLite FTS5 MATCH.
    Prevents syntax errors caused by special characters (: , * , - , ^ , quotes, etc.).
    """
    if not query or not query.strip():
        return ""

    tokens = re.findall(r'[\w]+', query, re.UNICODE)
    if not tokens:
        return ""

    escaped_terms = []
    for token in tokens:
        clean = token.replace('"', '""')
        if prefix:
            escaped_terms.append(f'"{clean}"*')
        else:
            escaped_terms.append(f'"{clean}"')

    return " ".join(escaped_terms)

def escape_like(value: str) -> str:
    """Escape LIKE wildcards with '^' as the escape character."""
    return value.replace("^", "^^").replace("%", "^%").replace("_", "^_")

def folder_like_pattern(folder: str) -> str:
    """LIKE pattern for every path below a folder."""
    norm = os.path.normpath(os.path.abspath(folder))
    if not norm.endswith(os.sep):
        norm += os.sep
    return escape_like(norm) + "%"

def format_snippet(raw: Optional[str]) -> Optional[str]:
    """HTML-escape an FTS5 snippet and turn the hit markers into <mark> tags."""
    if not raw:
        return None
    text = re.sub(r"\s+", " ", raw).strip()
    text = html.escape(text, quote=False)
    return text.replace(_MARK_OPEN, "<mark>").replace(_MARK_CLOSE, "</mark>")

def upsert_file(
    path: str,
    filename: str,
    extension: str,
    size_bytes: int,
    mtime: float,
    is_text: bool,
    category: str,
    content: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    """Insert or update a single file record and its full-text content."""
    upsert_files_batch([{
        "path": path,
        "filename": filename,
        "extension": extension,
        "size_bytes": size_bytes,
        "mtime": mtime,
        "is_text": is_text,
        "category": category,
        "content": content,
    }], db_path=db_path)

def upsert_files_batch(
    items: List[Dict[str, Any]],
    db_path: Optional[str] = None,
) -> None:
    """Batch insert or update file records inside a guarded atomic SQLite transaction."""
    if not items:
        return

    now = time.time()
    meta_tuples = []
    fts_paths = []
    fts_inserts = []

    for it in items:
        norm_path = os.path.normpath(os.path.abspath(it["path"]))
        content_val = it.get("content")
        fts_flag = 1 if content_val else 0
        meta_tuples.append((
            norm_path,
            it["filename"],
            it["extension"],
            it["size_bytes"],
            it["mtime"],
            1 if it["is_text"] else 0,
            it["category"],
            fts_flag,
            it.get("seen_at", now),
        ))
        # Decoupled FTS handling: only modify FTS5 table if content was extracted
        if content_val:
            fts_paths.append((norm_path,))
            fts_inserts.append((norm_path, content_val))

    def _upsert(cur: sqlite3.Cursor) -> None:
        # A changed file (new mtime or size) goes back to the content queue
        cur.executemany("""
            INSERT INTO files_meta (path, filename, extension, size_bytes, mtime, is_text, category, fts_indexed, seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                filename = excluded.filename,
                extension = excluded.extension,
                size_bytes = excluded.size_bytes,
                mtime = excluded.mtime,
                is_text = excluded.is_text,
                category = excluded.category,
                seen_at = excluded.seen_at,
                fts_indexed = CASE
                    WHEN excluded.fts_indexed = 1 THEN 1
                    WHEN excluded.mtime != files_meta.mtime OR excluded.size_bytes != files_meta.size_bytes THEN 0
                    ELSE files_meta.fts_indexed
                END;
        """, meta_tuples)

        if fts_paths:
            cur.executemany("DELETE FROM files_content_fts WHERE path = ?;", fts_paths)
        if fts_inserts:
            cur.executemany("INSERT INTO files_content_fts (path, content) VALUES (?, ?);", fts_inserts)

    _run_transaction(db_path, _upsert)

def delete_file(path: str, db_path: Optional[str] = None) -> None:
    """Remove a file from both metadata and full-text index."""
    norm_path = os.path.normpath(os.path.abspath(path))

    def _delete(cur: sqlite3.Cursor) -> None:
        cur.execute("DELETE FROM files_content_fts WHERE path = ?;", (norm_path,))
        cur.execute("DELETE FROM files_meta WHERE path = ?;", (norm_path,))

    _run_transaction(db_path, _delete)

def delete_folder(folder: str, db_path: Optional[str] = None) -> int:
    """Remove every indexed file below a folder. Returns the number of removed files."""
    pattern = folder_like_pattern(folder)

    def _delete(cur: sqlite3.Cursor) -> int:
        cur.execute("DELETE FROM files_content_fts WHERE path LIKE ? ESCAPE '^';", (pattern,))
        cur.execute("DELETE FROM files_meta WHERE path LIKE ? ESCAPE '^';", (pattern,))
        return cur.rowcount

    return _run_transaction(db_path, _delete)

def delete_unseen_in_folder(folder: str, seen_before: float, db_path: Optional[str] = None) -> int:
    """After a full scan, remove files below a folder that the scan did not see (deleted files)."""
    pattern = folder_like_pattern(folder)

    def _sweep(cur: sqlite3.Cursor) -> int:
        cur.execute("""
            DELETE FROM files_content_fts WHERE path IN (
                SELECT path FROM files_meta WHERE path LIKE ? ESCAPE '^' AND seen_at < ?
            );
        """, (pattern, seen_before))
        cur.execute("DELETE FROM files_meta WHERE path LIKE ? ESCAPE '^' AND seen_at < ?;", (pattern, seen_before))
        return cur.rowcount

    return _run_transaction(db_path, _sweep)

def delete_outside_folders(folders: List[str], db_path: Optional[str] = None) -> int:
    """Remove every indexed file that is not below one of the given folders."""
    patterns = [folder_like_pattern(f) for f in folders]

    def _purge(cur: sqlite3.Cursor) -> int:
        if not patterns:
            cur.execute("DELETE FROM files_content_fts;")
            cur.execute("DELETE FROM files_meta;")
            return cur.rowcount
        keep = " OR ".join("path LIKE ? ESCAPE '^'" for _ in patterns)
        cur.execute(f"DELETE FROM files_content_fts WHERE NOT ({keep});", patterns)
        cur.execute(f"DELETE FROM files_meta WHERE NOT ({keep});", patterns)
        return cur.rowcount

    return _run_transaction(db_path, _purge)

def rebase_drive(old_drive: str, new_drive: str, db_path: Optional[str] = None) -> int:
    """Change the drive letter of indexed paths (the portable drive got a new letter)."""
    old = old_drive.rstrip(":\\").upper() + ":"
    new = new_drive.rstrip(":\\").upper() + ":"
    if old == new:
        return 0
    pattern = escape_like(old + os.sep) + "%"

    def _rebase(cur: sqlite3.Cursor) -> int:
        # Drop rows that would collide with paths that already exist on the new letter
        cur.execute("""
            DELETE FROM files_meta WHERE path LIKE ? ESCAPE '^'
              AND (? || substr(path, 3)) IN (SELECT path FROM files_meta);
        """, (pattern, new))
        cur.execute("UPDATE files_meta SET path = ? || substr(path, 3) WHERE path LIKE ? ESCAPE '^';", (new, pattern))
        changed = cur.rowcount
        cur.execute("UPDATE files_content_fts SET path = ? || substr(path, 3) WHERE path LIKE ? ESCAPE '^';", (new, pattern))
        return changed

    return _run_transaction(db_path, _rebase)

def get_unindexed_content_files(
    extensions: Tuple[str, ...],
    max_size_bytes: int = 10 * 1024 * 1024,
    limit: int = 50,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query batch of unindexed files eligible for Pass 2 background FTS extraction."""
    conn = get_db_connection(db_path)
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in extensions)
    sql = f"""
        SELECT path, filename, extension, size_bytes, mtime
        FROM files_meta
        WHERE fts_indexed = 0
          AND extension IN ({placeholders})
          AND size_bytes <= ?
        ORDER BY mtime DESC
        LIMIT ?;
    """
    cur.execute(sql, (*extensions, max_size_bytes, limit))
    rows = cur.fetchall()
    return [dict(r) for r in rows]

def count_unindexed_content_files(
    extensions: Tuple[str, ...],
    max_size_bytes: int = 10 * 1024 * 1024,
    db_path: Optional[str] = None,
) -> int:
    """Number of files still waiting for full-text extraction."""
    try:
        conn = get_db_connection(db_path)
        placeholders = ",".join("?" for _ in extensions)
        row = conn.execute(f"""
            SELECT COUNT(*) FROM files_meta
            WHERE fts_indexed = 0 AND extension IN ({placeholders}) AND size_bytes <= ?;
        """, (*extensions, max_size_bytes)).fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        return 0

def mark_files_fts_indexed(
    indexed_items: List[Tuple[str, str]],  # (norm_path, content)
    skipped_paths: List[str],              # paths that failed or produced no text
    db_path: Optional[str] = None,
) -> None:
    """Commit batch of extracted content into FTS5 and update fts_indexed status in files_meta."""
    if not indexed_items and not skipped_paths:
        return

    def _mark(cur: sqlite3.Cursor) -> None:
        if indexed_items:
            delete_tuples = [(p,) for p, _ in indexed_items]
            cur.executemany("DELETE FROM files_content_fts WHERE path = ?;", delete_tuples)
            cur.executemany("INSERT INTO files_content_fts (path, content) VALUES (?, ?);", indexed_items)
            cur.executemany("UPDATE files_meta SET fts_indexed = 1 WHERE path = ?;", delete_tuples)

        if skipped_paths:
            skip_tuples = [(p,) for p in skipped_paths]
            cur.executemany("UPDATE files_meta SET fts_indexed = 2 WHERE path = ?;", skip_tuples)

    _run_transaction(db_path, _mark)

def count_fts_indexed(db_path: Optional[str] = None) -> int:
    """Return total count of files with extracted full-text content."""
    try:
        conn = get_db_connection(db_path)
        row = conn.execute("SELECT COUNT(*) FROM files_meta WHERE fts_indexed = 1;").fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        return 0

def count_files(db_path: Optional[str] = None) -> int:
    """Return total count of indexed files."""
    try:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM files_meta;")
        row = cur.fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        return 0

def count_files_in_folders(folders: Iterable[str], db_path: Optional[str] = None) -> Dict[str, int]:
    """Number of indexed files below each folder."""
    counts: Dict[str, int] = {}
    try:
        conn = get_db_connection(db_path)
        for folder in folders:
            row = conn.execute("SELECT COUNT(*) FROM files_meta WHERE path LIKE ? ESCAPE '^';",
                               (folder_like_pattern(folder),)).fetchone()
            counts[folder] = row[0] if row else 0
    except sqlite3.OperationalError:
        pass
    return counts

def get_file_meta(path: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve metadata for a single file by path."""
    norm_path = os.path.normpath(os.path.abspath(path))
    conn = get_db_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM files_meta WHERE path = ?;", (norm_path,))
    row = cur.fetchone()
    if row:
        return dict(row)
    return None

def _filter_clause(type_filter: str, folder: Optional[str]) -> Tuple[str, List[Any]]:
    """SQL clause and parameters for the category chip and the folder scope."""
    clause = ""
    params: List[Any] = []
    tf = (type_filter or "all").lower()
    if tf == "docs":
        ext_marks = ",".join("?" for _ in DOC_EXTENSIONS)
        clause += f" AND (m.category IN ('markdown', 'pdf', 'epub') OR m.extension IN ({ext_marks}))"
        params.extend(DOC_EXTENSIONS)
    elif tf != "all":
        clause += " AND m.category = ?"
        params.append(tf)
    if folder:
        clause += " AND m.path LIKE ? ESCAPE '^'"
        params.append(folder_like_pattern(folder))
    return clause, params

def search_files(
    query: str,
    mode: str = "all",
    type_filter: str = "all",
    limit: int = 50,
    db_path: Optional[str] = None,
    folder: Optional[str] = None,
) -> List[SearchResultItem]:
    """Search indexed files with ranking and snippet generation."""
    conn = get_db_connection(db_path)
    cur = conn.cursor()
    clean_query = query.strip() if query else ""

    category_clause, cat_params = _filter_clause(type_filter, folder)

    # Empty query: return recently modified files
    if not clean_query:
        sql = f"""
            SELECT path, filename, extension, size_bytes, mtime, is_text, category
            FROM files_meta m
            WHERE 1=1 {category_clause}
            ORDER BY mtime DESC
            LIMIT ?;
        """
        cur.execute(sql, (*cat_params, limit))
        rows = cur.fetchall()
        return [
            SearchResultItem(
                path=r["path"],
                filename=r["filename"],
                extension=r["extension"],
                size_bytes=r["size_bytes"],
                mtime=r["mtime"],
                is_text=bool(r["is_text"]),
                snippet=None,
                match_type="all",
                category=r["category"],
            )
            for r in rows
        ]

    results_map: Dict[str, Dict[str, Any]] = {}

    # Filename search
    if mode in ("filename", "all"):
        filename_pattern = f"%{escape_like(clean_query)}%"
        filename_sql = f"""
            SELECT path, filename, extension, size_bytes, mtime, is_text, category
            FROM files_meta m
            WHERE (filename LIKE ? ESCAPE '^' OR path LIKE ? ESCAPE '^') {category_clause}
            LIMIT ?;
        """
        cur.execute(filename_sql, (filename_pattern, filename_pattern, *cat_params, limit * 2))
        fn_rows = cur.fetchall()

        lower_query = clean_query.lower()
        for r in fn_rows:
            p = r["path"]
            fname = r["filename"].lower()

            if fname == lower_query:
                score = 100.0
            elif fname.startswith(lower_query):
                score = 80.0
            elif lower_query in fname:
                score = 60.0
            else:
                score = 40.0

            results_map[p] = {
                "path": r["path"],
                "filename": r["filename"],
                "extension": r["extension"],
                "size_bytes": r["size_bytes"],
                "mtime": r["mtime"],
                "is_text": bool(r["is_text"]),
                "snippet": None,
                "match_type": "filename",
                "category": r["category"],
                "score": score,
            }

    # Content search (FTS5)
    if mode in ("content", "all"):
        fts_query = escape_fts5_query(clean_query, prefix=True)
        if fts_query:
            try:
                fts_sql = f"""
                    SELECT
                        f.path,
                        m.filename,
                        m.extension,
                        m.size_bytes,
                        m.mtime,
                        m.is_text,
                        m.category,
                        snippet(files_content_fts, 1, char(2), char(3), '…', 20) AS snippet_text,
                        bm25(files_content_fts) AS rank_score
                    FROM files_content_fts f
                    JOIN files_meta m ON f.path = m.path
                    WHERE files_content_fts MATCH ? {category_clause}
                    ORDER BY rank_score ASC
                    LIMIT ?;
                """
                cur.execute(fts_sql, (fts_query, *cat_params, limit * 2))
                content_rows = cur.fetchall()

                for r in content_rows:
                    p = r["path"]
                    bm25_score = float(r["rank_score"])
                    content_score = max(10.0, 50.0 - (bm25_score * 5.0))
                    snippet_html = format_snippet(r["snippet_text"])

                    if p in results_map:
                        results_map[p]["match_type"] = "both"
                        results_map[p]["snippet"] = snippet_html
                        results_map[p]["score"] += content_score + 25.0
                    else:
                        results_map[p] = {
                            "path": r["path"],
                            "filename": r["filename"],
                            "extension": r["extension"],
                            "size_bytes": r["size_bytes"],
                            "mtime": r["mtime"],
                            "is_text": bool(r["is_text"]),
                            "snippet": snippet_html,
                            "match_type": "content",
                            "category": r["category"],
                            "score": content_score,
                        }
            except sqlite3.OperationalError:
                pass

    sorted_items = sorted(
        results_map.values(),
        key=lambda x: (x["score"], x["mtime"]),
        reverse=True
    )

    return [
        SearchResultItem(
            path=item["path"],
            filename=item["filename"],
            extension=item["extension"],
            size_bytes=item["size_bytes"],
            mtime=item["mtime"],
            is_text=item["is_text"],
            snippet=item["snippet"],
            match_type=item["match_type"],
            category=item["category"],
        )
        for item in sorted_items[:limit]
    ]
