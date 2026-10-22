"""Search settings: every rule of the smart search can be changed or turned off."""

import os
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.indexer.db import init_db, upsert_file
from app.indexer.smart_search import clear_cache, run_search
from app.main import app
from app.query import parse_query
from app.search_options import DEFAULTS, PRESETS, SearchOptions, merge, validate
from app.state import settings_store

FILES = {
    "Office/invoice.xlsx": "quarterly total",
    "Office/invoice1.xlsx": "total draft",
    "Office/invoiceold.pdf": "total from last year",
    "Office/memo.txt": "our memo about the total",
    "Home/e-mail.txt": "inbox",
    "Home/notes+ideas.txt": "memos and ideas",
    "Home/total.md": "receipt",
}


@pytest.fixture
def db(tmp_path):
    clear_cache()
    db_file = str(tmp_path / "opts.db")
    init_db(db_file)
    root = str(tmp_path / "root")
    for i, (rel, content) in enumerate(FILES.items()):
        path = os.path.join(root, *rel.split("/"))
        name = os.path.basename(path)
        upsert_file(path=path, filename=name, extension=os.path.splitext(name)[1].lower(),
                    size_bytes=len(content) * (i + 1), mtime=1_700_000_000 + i, is_text=True,
                    category="plain", content=content, db_path=db_file)
    return db_file, root


def names(db, q, abc=False, **opts):
    db_file, root = db
    res = run_search(q, db_path=db_file, roots=[root], options=replace(DEFAULTS, **opts))
    found = [r.filename for r in res["results"]]
    return sorted(found) if abc else found


def test_turned_off_searches_the_text_as_typed(db):
    # Off: no operators; "e-mail" and "notes+ideas" are plain names
    assert names(db, "e-mail", enabled=False) == ["e-mail.txt"]
    assert names(db, "notes+ideas", enabled=False) == ["notes+ideas.txt"]
    assert names(db, ".xlsx", enabled=False, abc=True) == ["invoice.xlsx", "invoice1.xlsx"]
    # Off with names and text (the "classic" preset): plain words also search the text
    classic = {k: v for k, v in PRESETS["classic"].items() if k in ("enabled", "default_scope")}
    assert names(db, "total", abc=True, **classic) == [
        "invoice.xlsx", "invoice1.xlsx", "invoiceold.pdf", "memo.txt", "total.md"]


def test_default_scope(db):
    assert names(db, "total") == ["total.md"]
    assert names(db, "total", default_scope="text", abc=True) == ["invoice.xlsx", "invoice1.xlsx", "invoiceold.pdf", "memo.txt"]
    assert names(db, "total", default_scope="both", abc=True) == [
        "invoice.xlsx", "invoice1.xlsx", "invoiceold.pdf", "memo.txt", "total.md"]
    # Extensions stay file filters in every scope
    assert names(db, "total .xlsx", default_scope="text", abc=True) == ["invoice.xlsx", "invoice1.xlsx"]


def test_custom_characters(db):
    opts = dict(text_char="=", and_char="&", not_char="!", literal_char="'")
    assert names(db, "invoice!old&.xlsx=total", abc=True, **opts) == ["invoice.xlsx", "invoice1.xlsx"]
    # The old characters are plain text now
    assert names(db, "e-mail", **opts) == ["e-mail.txt"]
    assert names(db, "notes+ideas", **opts) == ["notes+ideas.txt"]
    assert names(db, "'invoice!old", **opts) == []


def test_operators_off(db):
    assert names(db, "notes+ideas", and_char="") == ["notes+ideas.txt"]
    assert names(db, "e-mail", not_char="") == ["e-mail.txt"]
    assert names(db, "invoice:total", text_char="") == []  # ":" is part of the name now
    plan = parse_query("[a, b]", replace(DEFAULTS, group_open="", group_close=""))
    assert not plan.grouped


def test_dash_only_at_word_start(db):
    assert names(db, "e-mail", dash_mode="word_start") == ["e-mail.txt"]
    assert names(db, "invoice -old", dash_mode="word_start", abc=True) == ["invoice.xlsx", "invoice1.xlsx"]


def test_rules_off(db):
    # Exact names off: invoice.xlsx is a part of the name
    assert names(db, "invoice.xlsx", exact_names=False) == ["invoice.xlsx"]
    assert names(db, "voice.xlsx", exact_names=False) == ["invoice.xlsx"]
    assert names(db, "voice.xlsx") == []
    # Extensions off: ".pdf" is text of the name
    assert names(db, ".pdf", extensions=False) == ["invoiceold.pdf"]
    # Wildcards off: "*" is a character
    assert names(db, "inv*", wildcards=False) == []
    # Quotes off
    assert names(db, '"e-mail"', quotes=False) == []


def test_folders_whole_words_and_order(db):
    assert names(db, "home", abc=True) == []
    assert names(db, "home", names_include_folders=True, abc=True) == ["e-mail.txt", "notes+ideas.txt", "total.md"]
    assert names(db, ":memo", abc=True) == ["memo.txt", "notes+ideas.txt"]
    assert names(db, ":memo", text_prefix=False) == ["memo.txt"]
    assert names(db, "invoice", sort="name") == ["invoice.xlsx", "invoice1.xlsx", "invoiceold.pdf"]
    assert names(db, "invoice", sort="newest") == ["invoiceold.pdf", "invoice1.xlsx", "invoice.xlsx"]
    assert names(db, "", sort="size")[0] == "memo.txt"  # 24 characters x 4


def test_validation():
    cleaned, errors = validate({**DEFAULTS.to_dict(), "and_char": "-"})
    assert errors and "" in (cleaned["and_char"], cleaned["not_char"])
    _, errors = validate({**DEFAULTS.to_dict(), "text_char": "a"})
    assert errors
    _, errors = validate({**DEFAULTS.to_dict(), "text_char": "*"})
    assert errors  # "*" is a wildcard
    _, errors = validate({**DEFAULTS.to_dict(), "text_char": "*", "wildcards": False})
    assert not errors
    _, errors = validate({**DEFAULTS.to_dict(), "page_size": 5})
    assert errors
    for preset in PRESETS.values():
        assert validate(preset)[1] == []
    # Broken values in settings.json fall back to the defaults
    assert merge({"default_scope": "nowhere", "and_char": 5}) == DEFAULTS
    assert merge({"default_scope": "text"}) == SearchOptions(default_scope="text")


def test_settings_api():
    client = TestClient(app)
    try:
        body = client.get("/api/settings").json()
        assert body["search"] == DEFAULTS.to_dict() and len(body["search_presets"]) == len(PRESETS)
        res = client.put("/api/settings/search", json={"default_scope": "both", "and_char": "&"})
        assert res.status_code == 200 and res.json()["search"]["default_scope"] == "both"
        assert settings_store.search_options.and_char == "&"
        assert client.put("/api/settings/search", json={"and_char": "-"}).status_code == 400
        assert client.put("/api/settings/search", json={"bogus": 1}).status_code == 400
    finally:
        client.put("/api/settings/search", json=DEFAULTS.to_dict())
    assert settings_store.search_options == DEFAULTS
