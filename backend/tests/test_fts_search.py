"""Unit tests for SQLite FTS5 queries, snippet extraction, and punctuation safety."""

import os
import sqlite3
import pytest
from app.indexer.db import (
    count_files,
    count_unindexed_content_files,
    delete_file,
    escape_fts5_query,
    get_db_connection,
    get_unindexed_content_files,
    init_db,
    search_files,
    upsert_file,
)

@pytest.fixture
def test_db(tmp_path):
    """Provide a pristine isolated SQLite database for each test."""
    db_file = str(tmp_path / "fts_test.db")
    init_db(db_file)
    return db_file

def test_database_wal_mode_enabled(test_db):
    """Verify SQLite database runs in WAL journal mode."""
    conn = get_db_connection(test_db)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode;")
    mode = cur.fetchone()[0]
    assert mode.lower() == "wal"

def test_escape_fts5_query_punctuation_safety():
    """Verify punctuation characters do not crash FTS5 query parser."""
    # Test typical tricky punctuation inputs
    assert escape_fts5_query("script.py") == '"script"* "py"*'
    assert escape_fts5_query("foo:bar") == '"foo"* "bar"*'
    assert escape_fts5_query("(a OR b) -c*") == '"a"* "OR"* "b"* "c"*'
    assert escape_fts5_query("+++---***") == ""
    assert escape_fts5_query('test "quoted" item') == '"test"* "quoted"* "item"*'

def test_upsert_and_fts_search_with_mark_tags(test_db):
    """Verify FTS5 search extracts snippets surrounded by <mark> tags."""
    doc_path = r"C:\data\project\guide.md"
    content = (
        "Welcome to the Peek & Grep workstation guide. "
        "The architecture review recommends sub-50ms latency for queries. "
        "SQLite FTS5 inverted indexing ensures lightning fast results."
    )

    upsert_file(
        path=doc_path,
        filename="guide.md",
        extension=".md",
        size_bytes=len(content),
        mtime=1725550000.0,
        is_text=True,
        category="markdown",
        content=content,
        db_path=test_db,
    )

    assert count_files(test_db) == 1

    # Search for term 'architecture'
    results = search_files("architecture", mode="content", db_path=test_db)
    assert len(results) == 1
    assert results[0].filename == "guide.md"
    assert results[0].snippet is not None
    assert "<mark>" in results[0].snippet
    assert "</mark>" in results[0].snippet
    assert "architecture" in results[0].snippet.lower()

def test_punctuation_query_does_not_throw(test_db):
    """Verify searches with strange punctuation execute safely without exception."""
    upsert_file(
        path=r"C:\test\script.py",
        filename="script.py",
        extension=".py",
        size_bytes=100,
        mtime=1725550000.0,
        is_text=True,
        category="code",
        content="def calculate_metrics(rate: float) -> float: return rate * 1.5",
        db_path=test_db,
    )

    tricky_queries = [
        "script.py",
        "rate: float",
        "def () ->",
        "***???",
        "calculate+metrics",
        'test "quoted"',
        "nonexistent:tag(value)",
    ]

    for q in tricky_queries:
        # Must execute without raising sqlite3.OperationalError
        results = search_files(q, mode="all", db_path=test_db)
        assert isinstance(results, list)

def test_filename_ranking_priority(test_db):
    """Names without ":", text after ":"; a name that starts with the word ranks first."""
    # File 1 has exact filename match 'analysis.csv'
    upsert_file(
        path=r"C:\test\analysis.csv",
        filename="analysis.csv",
        extension=".csv",
        size_bytes=500,
        mtime=1725551000.0,
        is_text=True,
        category="data",
        content="id,name,role\n1,Alice,Engineer",
        db_path=test_db,
    )

    # File 2 contains word 'analysis' in content but not in filename
    upsert_file(
        path=r"C:\test\other.txt",
        filename="other.txt",
        extension=".txt",
        size_bytes=300,
        mtime=1725552000.0,
        is_text=True,
        category="plain",
        content="This is a deep analysis of system performance.",
        db_path=test_db,
    )

    # Without ":" only file names are searched; after ":" the text
    results = search_files("analysis", mode="all", db_path=test_db)
    assert [r.filename for r in results] == ["analysis.csv"]
    results = search_files(":analysis", mode="all", db_path=test_db)
    assert [r.filename for r in results] == ["other.txt"]
    # A name that starts with the word ranks above one that only contains it
    upsert_file(path=r"C:\test\old analysis.txt", filename="old analysis.txt", extension=".txt",
                size_bytes=10, mtime=1725553000.0, is_text=True, category="plain", content="x", db_path=test_db)
    results = search_files("analysis", mode="all", db_path=test_db)
    assert [r.filename for r in results] == ["analysis.csv", "old analysis.txt"]

def test_delete_file_removes_from_meta_and_fts(test_db):
    """Verify deleting a file removes it from both tables."""
    path = r"C:\temp\doc.txt"
    upsert_file(
        path=path,
        filename="doc.txt",
        extension=".txt",
        size_bytes=50,
        mtime=1725550000.0,
        is_text=True,
        category="plain",
        content="Secret information for testing",
        db_path=test_db,
    )
    assert count_files(test_db) == 1

    # Ensure search finds it
    assert len(search_files("Secret", mode="content", db_path=test_db)) == 1

    # Delete
    delete_file(path, db_path=test_db)
    assert count_files(test_db) == 0
    assert len(search_files("Secret", mode="content", db_path=test_db)) == 0

def test_concurrent_writes_no_lock_error(test_db):
    """Verify simultaneous write operations across multiple threads never fail with 'database is locked'."""
    import concurrent.futures

    def worker(worker_id: int):
        for i in range(20):
            p = f"C:\\worker_{worker_id}\\file_{i}.py"
            upsert_file(
                path=p,
                filename=f"file_{i}.py",
                extension=".py",
                size_bytes=100 + i,
                mtime=1725550000.0 + i,
                is_text=True,
                category="code",
                content=f"print('Worker {worker_id} iteration {i}')",
                db_path=test_db,
            )
            if i % 5 == 0:
                delete_file(p, db_path=test_db)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(worker, wid) for wid in range(8)]
        for f in concurrent.futures.as_completed(futures):
            # Must complete with zero exceptions
            f.result()

    assert count_files(test_db) > 0


def test_office_files_have_a_larger_size_limit(test_db):
    """Office files are compressed: a 30 MB workbook is still read, a 30 MB text file is not."""
    from app.indexer.db import upsert_files_batch
    mb = 1024 * 1024
    upsert_files_batch([
        {"path": f"/tmp/big.{ext}", "filename": f"big.{ext}", "extension": f".{ext}", "size_bytes": 30 * mb,
         "mtime": 1.0, "is_text": False, "category": "doc"}
        for ext in ("xlsx", "txt")
    ], db_path=test_db)
    exts = (".xlsx", ".txt")
    both = dict(max_size_bytes=10 * mb, office_max_bytes=100 * mb, db_path=test_db)
    assert [r["extension"] for r in get_unindexed_content_files(exts, **both)] == [".xlsx"]
    assert count_unindexed_content_files(exts, **both) == 1
    assert get_unindexed_content_files(exts, max_size_bytes=10 * mb, db_path=test_db) == []


def test_upgrade_reads_large_office_files_again(test_db):
    """Text cut at the old 2 million character limit is read again after the update."""
    from app.indexer.db import mark_files_fts_indexed, upsert_files_batch
    upsert_files_batch([
        {"path": f"/tmp/{name}", "filename": name, "extension": "." + name.split(".")[1], "size_bytes": size,
         "mtime": 1.0, "is_text": False, "category": "doc"}
        for name, size in (("big.xlsx", 3_000_000), ("small.xlsx", 9_000), ("big.txt", 3_000_000))
    ], db_path=test_db)
    mark_files_fts_indexed([(os.path.normpath(f"/tmp/{n}"), "x") for n in ("big.xlsx", "small.xlsx", "big.txt")], [],
                           db_path=test_db)
    conn = get_db_connection(test_db)
    conn.execute("PRAGMA user_version = 0;")
    conn.commit()
    init_db(test_db)
    rows = dict(get_db_connection(test_db).execute("SELECT filename, fts_indexed FROM files_meta;").fetchall())
    assert rows == {"big.xlsx": 0, "small.xlsx": 1, "big.txt": 1}
    # Only once
    mark_files_fts_indexed([(os.path.normpath("/tmp/big.xlsx"), "x")], [], db_path=test_db)
    init_db(test_db)
    assert get_db_connection(test_db).execute("SELECT fts_indexed FROM files_meta WHERE filename = 'big.xlsx';").fetchone()[0] == 1
