"""Editing: text, CSV, Excel (.xlsx), and Word (.docx). Saves keep encoding, line ends, and
everything that was not edited; every save makes a backup and refuses stale or locked files."""

import os
import shutil
import zipfile
from pathlib import Path

import pytest

from app import editing
from app.indexer.office import extract_office

FIXTURES = Path(__file__).parent / "fixtures"


def test_text_keeps_crlf_bom_and_cp1252(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_bytes("﻿line one\r\nlīne two\r\n".encode("utf-8"))
    m = editing.load(str(f), ".txt")
    assert m["text"] == "line one\nlīne two\n" and m["encoding"] == "utf-8-sig" and m["newline"] == "\r\n"
    res = editing.save(str(f), ".txt", int(m["mtime_ns"]), {"text": "line one\nchanged\n"})
    assert f.read_bytes() == b"\xef\xbb\xbfline one\r\nchanged\r\n"
    assert os.path.exists(res["backup"])

    old = tmp_path / "old.ini"
    old.write_bytes("caf\xe9=1\n".encode("cp1252"))
    m = editing.load(str(old), ".ini")
    assert m["encoding"] == "cp1252" and m["text"] == "café=1\n"
    editing.save(str(old), ".ini", int(m["mtime_ns"]), {"text": "café=2\n"})
    assert old.read_bytes() == "café=2\n".encode("cp1252")


def test_conflict_and_binary_are_refused(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("one", encoding="utf-8")
    m = editing.load(str(f), ".txt")
    os.utime(f, ns=(int(m["mtime_ns"]) + 5_000_000_000,) * 2)
    with pytest.raises(editing.EditError) as e:
        editing.save(str(f), ".txt", int(m["mtime_ns"]), {"text": "two"})
    assert e.value.status == 409 and f.read_text(encoding="utf-8") == "one"

    b = tmp_path / "b.txt"
    b.write_bytes(b"abc\x00def")
    with pytest.raises(editing.EditError):
        editing.load(str(b), ".txt")
    with pytest.raises(editing.EditError) as e:
        editing.load(str(FIXTURES / "sample.xls"), ".xls")
    assert e.value.status == 415


def test_csv_grid_keeps_separator(tmp_path):
    f = tmp_path / "eu.csv"
    f.write_bytes(b"Name;Price\r\nTea;1,50\r\n")
    m = editing.load(str(f), ".csv")
    assert m["delimiter"] == "semicolon" and m["rows"] == [["Name", "Price"], ["Tea", "1,50"]]
    rows = m["rows"] + [["Milk; fresh", "0,99"]]
    editing.save(str(f), ".csv", int(m["mtime_ns"]), {"rows": rows, "delimiter": "semicolon"})
    assert f.read_bytes() == b'Name;Price\r\nTea;1,50\r\n"Milk; fresh";0,99\r\n'


def test_xlsx_cells_change_and_rest_stays(tmp_path):
    f = tmp_path / "book.xlsx"
    shutil.copy(FIXTURES / "sample.xlsx", f)
    before = zipfile.ZipFile(f).namelist()
    m = editing.load(str(f), ".xlsx")
    prices = m["sheets"][0]
    assert [3, 3] not in prices["formulas"] and [1, 3] in prices["formulas"] and [1, 2] in prices["formulas"]
    changes = {"Prices": {"1,1": "99", "4,4": "new cell", "1,2": "2026-12-24", "2,0": "Pot  "}}
    editing.save(str(f), ".xlsx", int(m["mtime_ns"]), {"changes": changes})
    after = extract_office(str(f), ".xlsx")["sheets"][0]["rows"]
    assert after[1][1] == "99" and after[4][4] == "new cell" and after[1][2] == "2026-12-24" and after[2][0] == "Pot  "
    assert after[0] == ["Name", "Price", "Date", "Label", ""]
    names = zipfile.ZipFile(f).namelist()
    assert set(names) <= set(before) and "xl/sharedStrings.xml" in names
    assert b'fullCalcOnLoad="1"' in zipfile.ZipFile(f).read("xl/workbook.xml")


def test_docx_changes_only_edited_paragraph(tmp_path):
    f = tmp_path / "doc.docx"
    shutil.copy(FIXTURES / "sample.docx", f)
    m = editing.load(str(f), ".docx")
    texts = [p["text"] for p in m["paragraphs"]]
    idx = texts.index("The marmalade sales grew strongly this quarter.")
    cell = texts.index("North")
    assert m["paragraphs"][cell]["table"] is True
    editing.save(str(f), ".docx", int(m["mtime_ns"]),
                 {"changes": {str(idx): "Jam sales\tdoubled.\nSecond line", str(cell): "South"}})
    m2 = editing.load(str(f), ".docx")
    texts2 = [p["text"] for p in m2["paragraphs"]]
    assert texts2[idx] == "Jam sales\tdoubled.\nSecond line" and texts2[cell] == "South"
    assert [t for i, t in enumerate(texts2) if i not in (idx, cell)] == [t for i, t in enumerate(texts) if i not in (idx, cell)]
    html = extract_office(str(f), ".docx")["html"]
    assert "<h1>Quarterly Report</h1>" in html and "South" in html


def test_api_edit_routes(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.state import settings_store

    f = tmp_path / "x.md"
    f.write_text("# Title\n", encoding="utf-8")
    settings_store.set_folders([str(tmp_path)])
    client = TestClient(app)
    m = client.get("/api/edit", params={"path": str(f)}).json()
    assert m["kind"] == "text"
    r = client.post("/api/edit/save", json={"path": str(f), "mtime_ns": m["mtime_ns"], "payload": {"text": "# New\n"}})
    assert r.status_code == 200 and f.read_text(encoding="utf-8") == "# New\n"
    r = client.post("/api/edit/save", json={"path": str(f), "mtime_ns": m["mtime_ns"], "payload": {"text": "stale"}})
    assert r.status_code == 409
    assert client.get("/api/preview", params={"path": str(f)}).json()["editable"] == "text"
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("no", encoding="utf-8")
    assert client.get("/api/edit", params={"path": str(outside)}).status_code == 403


def _backup_files(folder):
    return sorted(p.name for p in folder.rglob("*") if p.is_file())


def test_one_backup_per_editing_session(tmp_path, monkeypatch):
    monkeypatch.setattr(editing, "BACKUP_DIR", tmp_path / "backups")
    f = tmp_path / "plan.txt"
    f.write_text("first\n", encoding="utf-8")

    def edit(text, policy=None):
        m = editing.load(str(f), ".txt")
        return editing.save(str(f), ".txt", int(m["mtime_ns"]), {"text": text}, policy)

    first = edit("second\n")
    assert first["backup"] and Path(first["backup"]).read_text(encoding="utf-8") == "first\n"
    assert Path(first["backup"]).parent == editing.backup_folder(str(f))
    # More saves soon after: the backup from before the session is kept, no new ones
    again = edit("third\n")
    assert again["backup"] is None and again["backup_kept"] == first["backup"]
    edit("fourth\n")
    assert len(_backup_files(tmp_path / "backups")) == 1

    # Changed by another program since this app saved it: that version is backed up
    f.write_text("from another app\n", encoding="utf-8")
    os.utime(f, ns=(os.stat(f).st_mtime_ns + 2_000_000_000,) * 2)
    other = edit("fifth\n")
    assert other["backup"] and Path(other["backup"]).read_text(encoding="utf-8") == "from another app\n"

    # A backup at every save, with only the newest kept per file
    every = editing.BackupPolicy(per_file=2, gap_minutes=0)
    for text in ("6\n", "7\n", "8\n"):
        edit(text, every)
    kept = [p for p in editing.backup_folder(str(f)).iterdir()]
    assert len(kept) == 2 and sorted(p.read_text(encoding="utf-8") for p in kept) == ["6\n", "7\n"]

    # Backups off
    off = edit("9\n", editing.BackupPolicy(enabled=False))
    assert off["backup"] is None and len(_backup_files(tmp_path / "backups")) == 2


def test_backup_policy_limits_and_delete_all(tmp_path, monkeypatch):
    monkeypatch.setattr(editing, "BACKUP_DIR", tmp_path / "backups")
    p = editing.BackupPolicy.from_dict({"per_file": 999, "gap_minutes": -5, "enabled": 0, "other": 1})
    assert p.to_dict() == {"enabled": False, "per_file": 50, "gap_minutes": 0}
    # Files with the same name in two folders keep separate backups
    a, b = tmp_path / "x" / "same.txt", tmp_path / "y" / "same.txt"
    for f in (a, b):
        f.parent.mkdir()
        f.write_text("old", encoding="utf-8")
        m = editing.load(str(f), ".txt")
        editing.save(str(f), ".txt", int(m["mtime_ns"]), {"text": "new"})
    assert editing.backup_folder(str(a)) != editing.backup_folder(str(b))
    (tmp_path / "backups" / "20240101-101010_older.txt").write_text("from an older version")
    info = editing.backups_info()
    assert info["count"] == 3 and info["bytes"] > 0
    assert editing.delete_backups()["count"] == 0 and list((tmp_path / "backups").iterdir()) == []
