"""Filters after ";": modified, created, and accessed dates, and size."""

import os
from dataclasses import replace
from datetime import datetime

import pytest

from app.indexer.db import init_db, upsert_file
from app.indexer.smart_search import clear_cache, run_search
from app.params import parse_date, parse_param, split_params
from app.query import parse_query
from app.search_options import DEFAULTS

NOW = datetime(2026, 10, 22, 15, 0)


def ts(*args) -> float:
    return datetime(*args).timestamp()


@pytest.mark.parametrize("text,start,end", [
    ("15-03-2024", (2024, 3, 15), (2024, 3, 16)),
    ("15.03.2024", (2024, 3, 15), (2024, 3, 16)),
    ("15/03/24", (2024, 3, 15), (2024, 3, 16)),
    ("2024-03-15", (2024, 3, 15), (2024, 3, 16)),
    ("20240315", (2024, 3, 15), (2024, 3, 16)),
    ("15-03", (2026, 3, 15), (2026, 3, 16)),
    ("03-2024", (2024, 3, 1), (2024, 4, 1)),
    ("2024-03", (2024, 3, 1), (2024, 4, 1)),
    ("2024", (2024, 1, 1), (2025, 1, 1)),
    ("march 2024", (2024, 3, 1), (2024, 4, 1)),
    ("15 mar 2024", (2024, 3, 15), (2024, 3, 16)),
    ("mar 15 2024", (2024, 3, 15), (2024, 3, 16)),
    ("15. marts 2024", (2024, 3, 15), (2024, 3, 16)),
    ("december", (2026, 12, 1), (2027, 1, 1)),
    ("today", (2026, 10, 22), (2026, 10, 23)),
    ("yesterday", (2026, 10, 21), (2026, 10, 22)),
    ("last month", (2026, 9, 1), (2026, 10, 1)),
    ("this year", (2026, 1, 1), (2027, 1, 1)),
])
def test_date_formats(text, start, end):
    s, e, age = parse_date(text, "dmy", NOW)
    assert (s, e, age) == (datetime(*start), datetime(*end), False)


def test_date_orders():
    assert parse_date("03/15/2024", "mdy", NOW)[0] == datetime(2024, 3, 15)
    assert parse_date("24-03-15", "ymd", NOW)[0] == datetime(2024, 3, 15)
    # Day-first, but 03/15/2024 only works month-first: that order is used
    p = parse_param("dm 03/15/2024", "dmy", NOW)
    assert (p.low, p.high) == (ts(2024, 3, 15), ts(2024, 3, 16))


def test_ranges_include_both_days():
    p = parse_param("dm from 01-03-2024 to 31-03-2024", "dmy", NOW)
    assert (p.field, p.low, p.high) == ("mtime", ts(2024, 3, 1), ts(2024, 4, 1))
    p = parse_param("dc to 15-06-2024", "dmy", NOW)
    assert (p.field, p.low, p.high) == ("ctime", None, ts(2024, 6, 16))
    p = parse_param("da from 2023", "dmy", NOW)
    assert (p.field, p.low, p.high) == ("atime", ts(2023, 1, 1), None)
    p = parse_param("modified 01.03.2024..15.03.2024", "dmy", NOW)
    assert (p.low, p.high) == (ts(2024, 3, 1), ts(2024, 3, 16))
    p = parse_param("dm before 2020", "dmy", NOW)
    assert (p.low, p.high) == (None, ts(2020, 1, 1))
    p = parse_param("dm >=2025", "dmy", NOW)
    assert (p.low, p.high) == (ts(2025, 1, 1), None)


def test_ages():
    p = parse_param("dm 7d", "dmy", NOW)
    assert p.low == datetime(2026, 10, 15, 15, 0).timestamp() and p.high is None
    p = parse_param("dm >3m", "dmy", NOW)  # older than 3 months
    assert p.low is None and p.high == datetime(2026, 7, 22, 15, 0).timestamp()
    p = parse_param("dm to 1y", "dmy", NOW)
    assert p.high == datetime(2025, 10, 22, 15, 0).timestamp()


def test_sizes():
    assert (lambda p: (p.low, p.high))(parse_param("size>10mb")) == (10 * 1024 ** 2 + 1, None)
    assert (lambda p: (p.low, p.high))(parse_param("size<=1.5 gb")) == (None, 1.5 * 1024 ** 3 + 1)
    assert (lambda p: (p.low, p.high))(parse_param("size from 1mb to 50mb")) == (1024 ** 2, 50 * 1024 ** 2 + 1)
    assert (lambda p: (p.low, p.high))(parse_param("size small")) == (16 * 1024, 1024 ** 2)
    p = parse_param("size gigantic")
    assert p.low == 4 * 1024 ** 3 and p.high is None
    p = parse_param("size=10mb")
    assert (p.low, p.high) == (9.5 * 1024 ** 2, 10.5 * 1024 ** 2)
    assert parse_param("size 1,5kb").low == 1.45 * 1024


@pytest.mark.parametrize("bad", ["xx 2024", "dm", "dm 31-02-2024", "size>10 parsecs", "dm from 2025 to 2024", "dm 13/13/2024"])
def test_errors(bad):
    with pytest.raises(ValueError):
        parse_param(bad, "dmy", NOW)


def test_split_and_plan():
    assert split_params("invoice;dm 2024;size>1mb", ";", True, "[", "]") == ("invoice", ["dm 2024", "size>1mb"])
    # Inside quotes and brackets ";" is text
    assert split_params('"a;b";dm 2024', ";", True, "[", "]") == ('"a;b"', ["dm 2024"])
    assert split_params("[a;b, c];size>1mb", ";", True, "[", "]") == ("[a;b, c]", ["size>1mb"])
    plan = parse_query("invoice;dm 2024;nonsense")
    assert [p.field for p in plan.params] == ["mtime"] and len(plan.param_errors) == 1
    # A literal ends at the filter sign
    plan = parse_query(":/c++;size>1kb")
    assert plan.elements[0].content_terms[0].text == "c++" and plan.params[0].field == "size"
    # Off: ";" is plain text
    assert not parse_query("a;size>1kb", replace(DEFAULTS, param_char="")).params


@pytest.fixture
def db(tmp_path):
    clear_cache()
    db_file = str(tmp_path / "params.db")
    init_db(db_file)
    rows = [
        # name, size, modified, created, accessed
        ("invoice-march.xlsx", 2048, ts(2024, 3, 15), ts(2024, 3, 1), ts(2026, 10, 20)),
        ("invoice-june.xlsx", 20 * 1024 ** 2, ts(2024, 6, 30, 23, 0), ts(2023, 12, 31), ts(2024, 7, 1)),
        ("notes.txt", 100, ts(2025, 1, 10), ts(2025, 1, 10), ts(2025, 1, 10)),
        ("photo.png", 3 * 1024 ** 3, ts(2023, 5, 5), ts(2023, 5, 5), ts(2023, 5, 5)),
    ]
    for name, size, m, c, a in rows:
        upsert_file(path=os.path.join(str(tmp_path), name), filename=name, extension=os.path.splitext(name)[1],
                    size_bytes=size, mtime=m, ctime=c, atime=a, is_text=True, category="plain",
                    content="total", db_path=db_file)
    return db_file


def found(db, q):
    res = run_search(q, db_path=db)
    return sorted(r.filename for r in res["results"]), res


def test_filters_in_search(db):
    assert found(db, ";dm from 01-03-2024 to 30-06-2024")[0] == ["invoice-june.xlsx", "invoice-march.xlsx"]
    assert found(db, ";dm to 15-03-2024")[0] == ["invoice-march.xlsx", "photo.png"]
    assert found(db, ";dc 2023")[0] == ["invoice-june.xlsx", "photo.png"]
    assert found(db, ";da from 01-10-2026")[0] == ["invoice-march.xlsx"]
    assert found(db, ";size>10mb")[0] == ["invoice-june.xlsx", "photo.png"]
    assert found(db, ";size<1kb")[0] == ["notes.txt"]
    assert found(db, ";size huge")[0] == ["photo.png"]
    assert found(db, "invoice;size>10mb")[0] == ["invoice-june.xlsx"]
    assert found(db, ".xlsx:total;dm 2024-03")[0] == ["invoice-march.xlsx"]
    # Filters apply to every group
    res = found(db, "[invoice, notes];dm 2024")[1]
    assert [g["total"] for g in res["groups"]] == [2, 0]
    # Chips: the filters and the ones that were not understood
    chips = found(db, "invoice;dm 2024;size>>1")[1]["explain"]
    assert {"kind": "param", "text": "modified 01.01.2024 – 31.12.2024", "literal": False} in chips
    assert any(c["kind"] == "param-error" for c in chips)


def test_old_index_gets_new_columns(tmp_path):
    import sqlite3
    db_file = str(tmp_path / "old.db")
    con = sqlite3.connect(db_file)
    con.execute("""CREATE TABLE files_meta (path TEXT PRIMARY KEY, filename TEXT NOT NULL, extension TEXT NOT NULL,
                   size_bytes INTEGER NOT NULL, mtime REAL NOT NULL, is_text INTEGER NOT NULL, category TEXT NOT NULL)""")
    con.execute("INSERT INTO files_meta VALUES ('/x/a.txt', 'a.txt', '.txt', 1, 1700000000, 1, 'plain')")
    con.commit()
    con.close()
    init_db(db_file)
    con = sqlite3.connect(db_file)
    assert con.execute("SELECT ctime, atime FROM files_meta").fetchone() == (1700000000, 1700000000)
    con.close()


def test_filters_before_the_text_search():
    """".xlsx;size>150:product" is the same as ".xlsx:product;size>150"; "dm:2024" stays one filter."""
    from app.query import explain, parse_query
    chips = lambda q: [(c["kind"], c["text"]) for c in explain(parse_query(q))]
    assert chips(".xlsx;size>150:product") == chips(".xlsx:product;size>150") == [
        ("ext", ".xlsx"), ("text", "product"), ("param", "size > 150 B")]
    assert chips(";size>1mb:total") == [("text", "total"), ("param", "size > 1 MB")]
    assert chips("a:b;size>1kb:c") == [("name", "a"), ("text", "b"), ("text", "c"), ("param", "size > 1 KB")]
    assert chips(".xlsx;dm 2024:product;size<5mb")[1:] == [
        ("text", "product"), ("param", "modified 01.01.2024 – 31.12.2024"), ("param", "size < 5 MB")]
    assert chips("x;dm:2024") == [("name", "x"), ("param", "modified 01.01.2024 – 31.12.2024")]
    assert split_params("x;dm:2024", ";", True, "[", "]", ":", "+", lambda s: False) == ("x", ["dm:2024"])
