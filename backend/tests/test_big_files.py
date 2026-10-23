"""Large files rules: which files are read with the larger limits."""

import os

import pytest
from fastapi.testclient import TestClient

from app.big_files import BIG_MAX_BYTES, matches, normalize_rules
from app.indexer.db import get_db_connection, get_unindexed_content_files, init_db, upsert_files_batch
from app.main import app
from app.state import settings_store

client = TestClient(app)
MB = 1024 * 1024
FILE = os.path.abspath("/data/exports/report.csv")


def test_normalize_rules():
    rules = normalize_rules([
        {"kind": "type", "value": "*.XLSX"}, {"kind": "type", "value": "xlsx"},
        {"kind": "name", "value": " big "}, {"kind": "name", "value": ""},
        {"kind": "file", "value": f'"{FILE}"'},
    ])
    assert rules == [{"kind": "type", "value": ".xlsx"}, {"kind": "name", "value": "big"},
                     {"kind": "file", "value": os.path.normpath(FILE)}]
    for bad in ([{"kind": "file", "value": "report.csv"}], [{"kind": "size", "value": "1"}], "big"):
        with pytest.raises(ValueError):
            normalize_rules(bad)


def test_matches():
    rules = normalize_rules([{"kind": "name", "value": "big"}])
    assert matches(rules, "/x/BigData.xlsx", "BigData.xlsx", ".xlsx")
    assert not matches(rules, "/x/data.xlsx", "data.xlsx", ".xlsx")
    assert matches(normalize_rules([{"kind": "type", "value": ".csv"}]), "/x/a.CSV", "a.CSV", ".csv")
    assert matches(normalize_rules([{"kind": "file", "value": FILE}]), FILE, "report.csv", ".csv")


def test_matching_files_get_the_larger_size_limit(tmp_path):
    db = str(tmp_path / "big.db")
    init_db(db)
    upsert_files_batch([
        {"path": f"/tmp/{name}", "filename": name, "extension": os.path.splitext(name)[1], "size_bytes": size,
         "mtime": 1.0, "is_text": False, "category": "doc"}
        for name, size in (("bigdata.csv", 150 * MB), ("other.csv", 150 * MB), ("huge.csv", BIG_MAX_BYTES + 1))
    ], db_path=db)
    exts = (".csv",)
    assert get_unindexed_content_files(exts, 10 * MB, db_path=db) == []
    rules = normalize_rules([{"kind": "name", "value": "big"}, {"kind": "name", "value": "huge"}])
    found = get_unindexed_content_files(exts, 10 * MB, db_path=db, office_max_bytes=100 * MB, big_rules=rules)
    assert [r["filename"] for r in found] == ["bigdata.csv"]


def test_api_saves_rules():
    try:
        res = client.put("/api/settings/big_files", json={"rules": [{"kind": "name", "value": "big"}]})
        assert res.status_code == 200 and res.json()["big_files"] == [{"kind": "name", "value": "big"}]
        assert settings_store.big_files == [{"kind": "name", "value": "big"}]
        assert client.put("/api/settings/big_files", json={"rules": [{"kind": "file", "value": "x"}]}).status_code == 400
    finally:
        client.put("/api/settings/big_files", json={"rules": []})
    assert settings_store.big_files == []
