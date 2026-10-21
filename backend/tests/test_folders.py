"""Tests for allowed working folders: nothing is indexed or read outside them."""

import os
import time

import pytest
from fastapi.testclient import TestClient

from app.engine import IndexManager
from app.indexer.crawler import IndexerProgressTracker, SafeDriveCrawler
from app.indexer.db import (
    count_files,
    format_snippet,
    get_file_meta,
    init_db,
    rebase_drive,
    search_files,
    upsert_file,
)
from app.settings import SettingsStore, check_folder, is_within, merge_folders, normalize_folder


def wait_until(predicate, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def make_tree(root, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def test_is_within_and_merge():
    assert is_within(r"D:\work\a\b.txt", r"D:\work")
    assert is_within(r"d:\WORK\a", r"D:\work")
    assert not is_within(r"D:\workshop\a.txt", r"D:\work")
    assert is_within(r"D:\x\y.txt", "D:\\")
    merged = merge_folders([r"D:\work\sub", r"D:\work", r"E:\docs", r"D:\WORK"])
    assert merged == [r"D:\work", r"E:\docs"]


def test_check_folder_rules(tmp_path):
    a = tmp_path / "a"
    (a / "inner").mkdir(parents=True)
    f = tmp_path / "file.txt"
    f.write_text("x")
    assert check_folder("", [])["ok"] is False
    assert check_folder(str(tmp_path / "missing"), [])["error"] == "This folder does not exist."
    assert check_folder(str(f), [])["error"] == "This is a file, not a folder."
    inside = check_folder(str(a / "inner"), [normalize_folder(str(a))])
    assert inside["ok"] is False and inside["covered_by"] == normalize_folder(str(a))
    outer = check_folder(str(tmp_path), [normalize_folder(str(a))])
    assert outer["ok"] is True and outer["contains"] == [normalize_folder(str(a))]


def test_settings_roundtrip(tmp_path):
    store = SettingsStore(str(tmp_path / "settings.json"))
    assert store.setup_done is False and store.folders() == []
    added, removed = store.set_folders([str(tmp_path / "x"), str(tmp_path / "x" / "y")])
    assert added == [normalize_folder(str(tmp_path / "x"))] and removed == []
    again = SettingsStore(str(tmp_path / "settings.json"))
    assert again.setup_done is True
    assert again.folders() == [normalize_folder(str(tmp_path / "x"))]
    assert again.is_allowed(str(tmp_path / "x" / "y" / "z.txt"))
    assert not again.is_allowed(str(tmp_path / "other.txt"))


def test_no_indexing_before_folders_are_chosen(tmp_path):
    store = SettingsStore(str(tmp_path / "settings.json"))
    db_file = str(tmp_path / "idx.db")
    manager = IndexManager(store, db_path=db_file, tracker=IndexerProgressTracker())
    manager.start()
    try:
        assert manager._started is False
        assert manager.watcher.is_active is False
        assert manager.status()["phase"] == "setup"
        assert count_files(db_file) == 0
    finally:
        manager.stop()


def test_apply_folders_indexes_only_allowed_and_purges_removed(tmp_path):
    a = tmp_path / "alpha"
    b = tmp_path / "beta"
    make_tree(a, {"notes.md": "alpha quokka", "sub/code.py": "print('alpha')"})
    make_tree(b, {"readme.txt": "beta platypus"})
    store = SettingsStore(str(tmp_path / "settings.json"))
    db_file = str(tmp_path / "idx.db")
    manager = IndexManager(store, db_path=db_file, tracker=IndexerProgressTracker())
    manager.start()
    try:
        manager.apply_folders([str(a)])
        assert wait_until(lambda: count_files(db_file) == 2)
        assert wait_until(lambda: len(search_files("quokka", mode="content", db_path=db_file)) == 1)
        assert search_files("platypus", mode="content", db_path=db_file) == []

        result = manager.apply_folders([str(b)])
        assert result["removed"] == [normalize_folder(str(a))]
        assert wait_until(lambda: count_files(db_file) == 1)
        assert get_file_meta(str(a / "notes.md"), db_path=db_file) is None
        assert wait_until(lambda: len(search_files("platypus", mode="content", db_path=db_file)) == 1)
    finally:
        manager.stop()


def test_rescan_removes_deleted_files(tmp_path):
    root = tmp_path / "w"
    make_tree(root, {"keep.txt": "k", "gone.txt": "g"})
    db_file = str(tmp_path / "idx.db")
    init_db(db_file)
    tracker = IndexerProgressTracker()
    SafeDriveCrawler(roots=[str(root)], db_path=db_file, tracker=tracker).crawl_and_index()
    assert count_files(db_file) == 2
    (root / "gone.txt").unlink()
    time.sleep(0.01)
    SafeDriveCrawler(roots=[str(root)], db_path=db_file, tracker=tracker).crawl_and_index()
    assert count_files(db_file) == 1
    assert tracker.get_status()["folders"][0]["state"] == "done"


def test_crawler_skips_data_folder(tmp_path):
    root = tmp_path / "w"
    make_tree(root, {"a.txt": "a", "appdata-copy/data/index.txt": "secret"})
    db_file = str(tmp_path / "idx.db")
    init_db(db_file)
    SafeDriveCrawler(roots=[str(root)], db_path=db_file, excluded=[str(root / "appdata-copy" / "data")],
                     tracker=IndexerProgressTracker()).crawl_and_index()
    assert count_files(db_file) == 1


def test_snippet_is_html_escaped(tmp_path):
    db_file = str(tmp_path / "idx.db")
    init_db(db_file)
    content = 'before <img src=x onerror="alert(1)"> marker word after'
    upsert_file(path=r"C:\t\x.html", filename="x.html", extension=".html", size_bytes=len(content),
                mtime=1.0, is_text=True, category="code", content=content, db_path=db_file)
    hits = search_files("marker", mode="content", db_path=db_file)
    assert len(hits) == 1
    assert "<img" not in hits[0].snippet
    assert "&lt;img" in hits[0].snippet
    assert "<mark>marker</mark>" in hits[0].snippet
    assert format_snippet(None) is None


def test_rebase_drive(tmp_path):
    db_file = str(tmp_path / "idx.db")
    init_db(db_file)
    upsert_file(path=r"E:\proj\doc.md", filename="doc.md", extension=".md", size_bytes=5, mtime=1.0,
                is_text=True, category="markdown", content="hello world", db_path=db_file)
    assert rebase_drive("E:", "F:", db_path=db_file) == 1
    assert get_file_meta(r"F:\proj\doc.md", db_path=db_file) is not None
    hits = search_files("hello", mode="content", db_path=db_file)
    assert hits and hits[0].path == r"F:\proj\doc.md"


def test_api_blocks_files_outside_working_folders(tmp_path):
    from app.main import app
    from app.state import settings_store

    inside = tmp_path / "inside"
    outside = tmp_path / "outside"
    make_tree(inside, {"ok.md": "# ok"})
    make_tree(outside, {"secret.md": "# secret"})

    with TestClient(app) as client:
        res = client.put("/api/folders", json={"folders": [str(inside)]})
        assert res.status_code == 200
        assert settings_store.is_allowed(str(inside / "ok.md"))

        assert client.get("/api/preview", params={"path": str(inside / "ok.md")}).status_code == 200
        assert client.get("/api/preview", params={"path": str(outside / "secret.md")}).status_code == 403
        assert client.get("/api/raw", params={"path": str(outside / "secret.md")}).status_code == 403
        assert client.post("/api/actions/copy-path", json={"path": str(outside / "secret.md")}).status_code == 403
        assert client.get("/api/search", params={"q": "x", "folder": str(outside)}).status_code == 403

        res = client.put("/api/folders", json={"folders": [str(tmp_path / "does-not-exist")]})
        assert res.status_code == 400

        status = client.get("/api/indexer/status").json()
        assert [f["path"] for f in status["folders"]] == [normalize_folder(str(inside))]

        page = client.get("/api/status")
        assert page.json()["setup_done"] is True


def test_api_rejects_foreign_host_header():
    from app.main import app
    with TestClient(app) as client:
        res = client.get("/api/status", headers={"host": "evil.example"})
        assert res.status_code == 400
