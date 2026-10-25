"""Office previews and text: new (.docx .xlsx .pptx) and old binary (.doc .xls .ppt) formats.

The files in tests/fixtures were made with Microsoft Word, Excel, and PowerPoint (same content
in both formats).
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.indexer.fts_worker import FTSContentWorker
from app.indexer.office import column_letter, extract_office, is_date_format
from app.indexer.parsers import get_file_category

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("ext", [".docx", ".doc"])
def test_word(ext):
    r = extract_office(str(FIXTURES / f"sample{ext}"), ext)
    assert "Quarterly Report" in r["html"]
    assert "marmalade" in r["text"] and "zebras" in r["text"]
    assert "<table>" in r["html"] and "North" in r["html"] and "4200" in r["html"]


@pytest.mark.parametrize("ext", [".xlsx", ".xls"])
def test_excel(ext):
    r = extract_office(str(FIXTURES / f"sample{ext}"), ext)
    names = [s["name"] for s in r["sheets"]]
    assert names == ["Prices", "Many"]
    prices = r["sheets"][0]
    assert prices["columns"] == ["A", "B", "C", "D"]
    assert prices["rows"][0] == ["Name", "Price", "Date", "Label"]
    assert prices["rows"][1] == ["Teapot", "12.5", "2026-10-21", "Teapot-label"]
    assert prices["rows"][2][1] == "1234567"
    assert prices["rows"][2][3] == "Ūnicode žluťoučký"
    many = r["sheets"][1]
    assert many["total_rows"] == 3000 and len(many["rows"]) == 3000 and many["truncated"] is False
    # Strings far into the shared string table (old format: across CONTINUE records)
    assert "uniquestring2999-xxxxxxxxxx" in r["text"]


@pytest.mark.parametrize("ext", [".pptx", ".ppt"])
def test_powerpoint(ext):
    r = extract_office(str(FIXTURES / f"sample{ext}"), ext)
    assert [s["title"] for s in r["slides"]] == ["Launch Plan", "Goals"]
    body = [p["text"] for p in r["slides"][1]["paragraphs"]]
    assert body[:3] == ["Faster search", "Safer folders", "Portable build"]
    assert "Footnote about pelicans" in body


def test_helpers_and_categories():
    assert column_letter(0) == "A" and column_letter(25) == "Z" and column_letter(26) == "AA"
    assert is_date_format("yyyy-mm-dd") and is_date_format("[$-409]d-mmm") and not is_date_format("0.00")
    assert not is_date_format('"Day" 0')
    assert get_file_category(".xlsx") == "data" and get_file_category(".xls") == "data"
    assert get_file_category(".docx") == "office" and get_file_category(".ppt") == "office"


def test_office_text_is_indexed_and_previewed(tmp_path):
    from app.indexer.crawler import IndexerProgressTracker, SafeDriveCrawler
    from app.indexer.db import init_db, search_files
    from app.main import app
    from app.state import settings_store

    for f in FIXTURES.iterdir():
        if f.is_file():
            (tmp_path / f.name).write_bytes(f.read_bytes())
    db_file = str(tmp_path / "idx.db")
    init_db(db_file)
    SafeDriveCrawler(roots=[str(tmp_path)], db_path=db_file, tracker=IndexerProgressTracker()).crawl_and_index()
    worker = FTSContentWorker(db_path=db_file, batch_size=100)
    while worker.process_batch():
        pass
    found = {r.filename for r in search_files("pelicans", mode="content", db_path=db_file)}
    assert found == {"sample.pptx", "sample.ppt"}
    found = {r.filename for r in search_files("marmalade", mode="content", db_path=db_file)}
    assert found == {"sample.docx", "sample.doc"}
    docs = {r.filename for r in search_files("", type_filter="docs", db_path=db_file)}
    assert {"sample.docx", "sample.doc", "sample.pptx", "sample.ppt"} <= docs

    settings_store.set_folders([str(tmp_path)])
    client = TestClient(app)
    res = client.get("/api/preview", params={"path": str(tmp_path / "sample.xls")}).json()
    assert res["preview_type"] == "workbook" and res["sheets"][0]["name"] == "Prices"
    res = client.get("/api/preview", params={"path": str(tmp_path / "sample.ppt")}).json()
    assert res["preview_type"] == "slides" and res["slides"][0]["title"] == "Launch Plan"
    res = client.get("/api/preview", params={"path": str(tmp_path / "sample.doc")}).json()
    assert res["preview_type"] == "document" and "marmalade" in res["document_html"]

    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"not a zip file")
    assert client.get("/api/preview", params={"path": str(broken)}).status_code == 422
