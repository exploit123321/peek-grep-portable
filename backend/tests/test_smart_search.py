"""Smart search: file names by default, text after ":", extensions, +, -, [groups], literals, wildcards, paging."""

import os

import pytest

from app.indexer.db import init_db, upsert_file
from app.indexer.smart_search import clear_cache, run_search
from app.query import parse_query

FILES = {
    # relative path: content
    "notes/minutes.txt": "Minutes for Monday: our memo about the yearly total.",
    "notes/todo.md": "Our memo is to cut costs. note: done",
    "notes/invoice.xlsx": "Quarterly total sheet receipt sums",
    "notes/invoice1.xlsx": "total draft",
    "notes/invoice2.xlsx": "travel costs",
    "notes/invoice.pdf": "annual total review",
    "notes/invoiceold.pdf": "total from last year",
    "notes/invoice.docx": "total letter",
    "home/receipt.csv": "receipt,total\n10,20",
    "home/recipes.txt": "Totaling for the café: c++ classes and croissants",
    "home/2024-05 memo.txt": "may memo",
    "home/e-mail.txt": "inbox",
    "home/Ārste.txt": "vizīte pie ārsta",
}


@pytest.fixture
def db(tmp_path):
    clear_cache()
    db_file = str(tmp_path / "smart.db")
    init_db(db_file)
    root = str(tmp_path / "Work Root")
    for i, (rel, content) in enumerate(FILES.items()):
        path = os.path.join(root, *rel.split("/"))
        name = os.path.basename(path)
        upsert_file(path=path, filename=name, extension=os.path.splitext(name)[1].lower(),
                    size_bytes=len(content), mtime=1_700_000_000 + i, is_text=True,
                    category="plain", content=content, db_path=db_file)
    return db_file


def names(res):
    return sorted(r.filename for r in res["results"])


def search(db, q, **kw):
    return run_search(q, db_path=db, **kw)


INVOICES = ["invoice.docx", "invoice.pdf", "invoice.xlsx", "invoice1.xlsx", "invoice2.xlsx", "invoiceold.pdf"]


def test_names_by_default(db):
    # "invoice" is in no file text, only in names: parts of names match
    assert names(search(db, "invoice")) == INVOICES
    # Words that are only in the text of a file do not hit without ":"
    assert names(search(db, "total")) == []
    assert names(search(db, "MINUTES")) == ["minutes.txt"]


def test_name_with_extension_is_the_whole_name(db):
    assert names(search(db, "invoice.xlsx")) == ["invoice.xlsx"]
    assert names(search(db, "Invoice.XLSX")) == ["invoice.xlsx"]
    assert names(search(db, "invoice*.xlsx")) == ["invoice.xlsx", "invoice1.xlsx", "invoice2.xlsx"]


def test_extension_filters(db):
    assert names(search(db, ".xlsx")) == ["invoice.xlsx", "invoice1.xlsx", "invoice2.xlsx"]
    assert names(search(db, "invoice+.xlsx")) == ["invoice.xlsx", "invoice1.xlsx", "invoice2.xlsx"]
    assert names(search(db, "invoice-.xlsx")) == ["invoice.docx", "invoice.pdf", "invoiceold.pdf"]
    assert names(search(db, "invoice+.xlsx+.pdf")) == ["invoice.pdf", "invoice.xlsx", "invoice1.xlsx",
                                                       "invoice2.xlsx", "invoiceold.pdf"]


def test_text_after_colon(db):
    total_texts = ["invoice.docx", "invoice.pdf", "invoice.xlsx", "invoice1.xlsx", "invoiceold.pdf",
                   "minutes.txt", "receipt.csv", "recipes.txt"]
    assert names(search(db, ":total")) == total_texts
    assert names(search(db, ".xlsx:total")) == ["invoice.xlsx", "invoice1.xlsx"]
    assert names(search(db, "invoice+.xlsx:total")) == ["invoice.xlsx", "invoice1.xlsx"]
    assert names(search(db, "invoice.xlsx:total")) == ["invoice.xlsx"]
    # Names with "invoice" but not "old", only .xlsx and .pdf, "total" in the text
    assert names(search(db, "Invoice-old+.xlsx+.pdf:total")) == ["invoice.pdf", "invoice.xlsx", "invoice1.xlsx"]
    # Both words, or one without the other
    assert names(search(db, ":total+memo")) == ["minutes.txt"]
    assert names(search(db, ":total-draft+.xlsx")) == []  # .xlsx after ":" is text
    assert names(search(db, ".xlsx:total-draft")) == ["invoice.xlsx"]


def test_exclusions(db):
    assert names(search(db, "-invoice+.pdf")) == []
    assert names(search(db, "-invoice:total")) == ["minutes.txt", "receipt.csv", "recipes.txt"]
    assert names(search(db, "-minutes:-cut, memo")) == ["2024-05 memo.txt"]
    assert names(search(db, ".txt-recipes-Ārste-minutes")) == ["2024-05 memo.txt", "e-mail.txt"]


def test_dash_between_digits_and_literals(db):
    assert names(search(db, "2024-05")) == ["2024-05 memo.txt"]
    # "e-mail" is e without mail; quotes or "/" keep the dash
    assert names(search(db, '"e-mail"')) == ["e-mail.txt"]
    assert names(search(db, "/e-mail")) == ["e-mail.txt"]
    assert "e-mail.txt" not in names(search(db, "e-mail"))


def test_groups(db):
    res = search(db, ".xlsx:[total, receipt]")
    assert res["grouped"] is True
    assert [(g["label"], g["total"]) for g in res["groups"]] == [("total", 2), ("receipt", 1)]
    res = search(db, "[invoice, receipt]")
    assert [g["total"] for g in res["groups"]] == [6, 1]
    assert search(db, "[invoice,receipt]")["groups"][1]["total"] == 1


def test_literal_slash_and_quotes(db):
    # "note:" as text of the name, not a file filter
    assert names(search(db, "/note:")) == []
    assert names(search(db, ":/note:")) == ["todo.md"]
    assert names(search(db, "recipes:/c++")) == ["recipes.txt"]
    assert names(search(db, 'recipes:"c++"')) == ["recipes.txt"]
    assert names(search(db, ":/total+memo")) == []


def test_wildcards(db):
    assert names(search(db, ":tot*ing")) == ["recipes.txt"]
    assert names(search(db, ":*aling")) == ["recipes.txt"]
    assert names(search(db, "rec?ipt")) == ["receipt.csv"]
    assert names(search(db, "m*tes")) == ["minutes.txt"]


def test_case_and_accents(db):
    assert names(search(db, "ārste")) == ["Ārste.txt"]
    assert names(search(db, "ĀRSTE")) == ["Ārste.txt"]
    assert names(search(db, ":arsta")) == ["Ārste.txt"]


def test_paging_is_uncapped(tmp_path):
    clear_cache()
    db_file = str(tmp_path / "many.db")
    init_db(db_file)
    root = str(tmp_path / "root")
    for i in range(130):
        path = os.path.join(root, f"file{i:03}.txt")
        upsert_file(path=path, filename=os.path.basename(path), extension=".txt", size_bytes=10,
                    mtime=1_700_000_000 + i, is_text=True, category="plain",
                    content=f"shared marker number {i}", db_path=db_file)
    for query in (":marker", "file"):
        seen = []
        offset = 0
        while True:
            res = run_search(query, offset=offset, limit=60, db_path=db_file)
            seen += [r.path for r in res["results"]]
            assert res["total"] == 130
            if not res["has_more"]:
                break
            offset += 60
        assert len(seen) == 130 and len(set(seen)) == 130
    # Empty query pages in SQL too
    first = run_search("", limit=100, db_path=db_file)
    assert first["total"] == 130 and first["has_more"]


def test_parser_shapes():
    el = parse_query("-notes:-draft, memo").elements[0]
    assert [t.text for t in el.name_terms] == ["notes"] and el.name_terms[0].negated
    assert [(t.text, t.negated) for t in el.content_terms] == [("draft", True), ("memo", False)]
    el = parse_query("Invoice-old+.xlsx+.pdf:total").elements[0]
    assert [(t.text, t.negated) for t in el.name_terms] == [("Invoice", False), ("old", True)]
    assert el.exts == [".xlsx", ".pdf"] and [t.text for t in el.content_terms] == ["total"]
    el = parse_query("invoice-.xlsx").elements[0]
    assert el.exclude_exts == [".xlsx"]
    el = parse_query("invoice.xlsx").elements[0]
    assert el.name_terms[0].exact and not el.exts
    el = parse_query("notes:/total+memo").elements[0]
    assert el.content_terms[0].literal and el.content_terms[0].text == "total+memo"
    plan = parse_query("[a, b]:[c, d]")
    assert [e.label for e in plan.elements] == ["a · c", "a · d", "b · c", "b · d"]
    plan = parse_query('["Smith, John", x]')
    assert [e.label for e in plan.elements] == ["Smith, John", "x"]
    assert not parse_query(r"C:\Users\me").elements[0].has_colon


def test_words_after_colon_are_a_phrase(tmp_path):
    """":annual review" is these words next to each other; ":annual+review" is both words anywhere."""
    clear_cache()
    db_file = str(tmp_path / "phrase.db")
    init_db(db_file)
    texts = {
        "plain.txt": "The Annual review of costs",
        "lines.txt": "annual\n   reviews are due",
        "code.ts": "costs.annual.review(items)",
        "reversed.txt": "review the annual numbers",
        "apart.txt": "annual numbers need a review",
    }
    for i, (name, content) in enumerate(texts.items()):
        upsert_file(path=os.path.join(str(tmp_path), name), filename=name, extension=os.path.splitext(name)[1],
                    size_bytes=len(content), mtime=1_700_000_000 + i, is_text=True, category="plain",
                    content=content, db_path=db_file)

    def found(q, **kw):
        return sorted(r.filename for r in run_search(q, db_path=db_file, **kw)["results"])

    assert found(":annual review") == ["lines.txt", "plain.txt"]
    assert found(":annual+review") == ["apart.txt", "code.ts", "lines.txt", "plain.txt", "reversed.txt"]
    assert found(":ann* review") == ["lines.txt", "plain.txt"]
    assert found(':"annual review"') == ["lines.txt", "plain.txt"]
    # Whole words only (text_prefix off): "reviews" is not "review"
    from dataclasses import replace
    from app.search_options import DEFAULTS
    assert found(":annual review", options=replace(DEFAULTS, text_prefix=False)) == ["plain.txt"]


def test_saved_edit_is_searchable_at_once(tmp_path):
    from app.engine import IndexManager
    from app.indexer.db import get_file_meta, upsert_files_batch
    from app.indexer.crawler import build_file_record
    from app.settings import SettingsStore

    clear_cache()
    db_file = str(tmp_path / "now.db")
    init_db(db_file)
    folder = tmp_path / "docs"
    folder.mkdir()
    note = folder / "plan.txt"
    note.write_text("budget for the garden", encoding="utf-8")
    upsert_files_batch([build_file_record(str(note))], db_path=db_file)
    assert names(run_search(":garden", db_path=db_file)) == ["plan.txt"]

    manager = IndexManager(SettingsStore(str(tmp_path / "settings.json")), db_path=db_file)
    note.write_text("budget for the orchard", encoding="utf-8")
    os.utime(note, (1_800_000_000, 1_800_000_000))
    assert manager.index_file_now(str(note))
    assert names(run_search(":orchard", db_path=db_file)) == ["plan.txt"]
    assert names(run_search(":garden", db_path=db_file)) == []

    # No text left: the old text is gone from the index too
    note.write_text("", encoding="utf-8")
    os.utime(note, (1_800_000_100, 1_800_000_100))
    manager.index_file_now(str(note))
    assert names(run_search(":orchard", db_path=db_file)) == []
    assert get_file_meta(str(note), db_path=db_file)["fts_indexed"] == 2
    # A file the index does not hold stays out
    assert not manager.index_file_now(str(folder / "missing.txt"))
