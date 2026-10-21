"""Unit tests for content extractors, CSV parsers, and image metadata."""

import os
import tempfile
from PIL import Image
import pytest
from app.indexer.parsers import (
    extract_file_content,
    get_file_category,
    is_text_file,
    parse_csv_content,
    simplify_aspect_ratio,
)

def test_get_file_category():
    """Verify correct categorization across file extensions."""
    assert get_file_category(".py") == "code"
    assert get_file_category(".ts") == "code"
    assert get_file_category(".json") == "code"
    assert get_file_category(".md") == "markdown"
    assert get_file_category(".csv") == "data"
    assert get_file_category(".tsv") == "data"
    assert get_file_category(".png") == "media"
    assert get_file_category(".jpg") == "media"
    assert get_file_category(".txt") == "plain"
    assert get_file_category(".unknown") == "plain"

def test_simplify_aspect_ratio():
    """Verify aspect ratio calculations."""
    assert simplify_aspect_ratio(1920, 1080) == "16:9"
    assert simplify_aspect_ratio(800, 600) == "4:3"
    assert simplify_aspect_ratio(500, 500) == "1:1"
    assert simplify_aspect_ratio(0, 100) == "N/A"

def test_parse_csv_content():
    """Verify parsing CSV rows and column headers."""
    csv_text = "id,name,role,score\n1,Elena,Architect,98\n2,Marcus,Engineer,94"
    cols, rows, total_rows = parse_csv_content(csv_text)

    assert cols == ["id", "name", "role", "score"]
    assert len(rows) == 2
    assert rows[0] == ["1", "Elena", "Architect", "98"]
    assert total_rows == 3

def test_extract_file_content_python(tmp_path):
    """Verify code content extraction."""
    py_file = tmp_path / "sample.py"
    py_content = "def calculate_sum(a: int, b: int) -> int:\n    return a + b\n"
    py_file.write_text(py_content, encoding="utf-8")

    text, meta = extract_file_content(str(py_file))
    assert text == py_content
    assert is_text_file(str(py_file), ".py") is True

def test_extract_file_content_csv(tmp_path):
    """Verify CSV extraction produces table_data dictionary."""
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("item,qty,price\nWidget,10,19.99\nGadget,5,49.99", encoding="utf-8")

    text, meta = extract_file_content(str(csv_file))
    assert "Widget" in text
    assert "table_data" in meta
    assert meta["table_data"]["columns"] == ["item", "qty", "price"]
    assert len(meta["table_data"]["rows"]) == 2

def test_extract_file_content_image(tmp_path):
    """Verify PIL image metadata extraction."""
    img_file = tmp_path / "test.png"
    img = Image.new("RGBA", (400, 300), color=(128, 64, 255, 255))
    img.save(str(img_file))

    text, meta = extract_file_content(str(img_file))
    assert "image_meta" in meta
    im_meta = meta["image_meta"]
    assert im_meta["width"] == 400
    assert im_meta["height"] == 300
    assert im_meta["format"] == "PNG"
    assert im_meta["aspect_ratio"] == "4:3"
    assert "PNG" in text

def test_extract_pdf_text(tmp_path):
    """Verify pypdf extracts text from PDF pages."""
    from app.indexer.parsers import extract_pdf_text
    pdf_file = tmp_path / "sample.pdf"
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        b"4 0 obj<</Length 44>>stream\n"
        b"BT /F1 12 Tf 100 700 Td (Autonomous Systems AI) Tj ET\n"
        b"endstream\nendobj\n"
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000056 00000 n \n0000000111 00000 n \n0000000234 00000 n \n0000000330 00000 n \n"
        b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n401\n%%EOF\n"
    )
    pdf_file.write_bytes(pdf_bytes)

    extracted = extract_pdf_text(str(pdf_file), max_pages=50)
    assert extracted is not None
    assert "Autonomous Systems AI" in extracted

def test_pdf_preview_and_raw_endpoint(tmp_path):
    """Verify /api/preview returns type=pdf and /api/raw sets inline PDF headers."""
    from fastapi.testclient import TestClient
    from app.main import app

    pdf_file = tmp_path / "document.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 dummy content")

    # Preview is allowed only inside working folders
    from app.state import settings_store
    settings_store.set_folders([str(tmp_path)])
    client = TestClient(app)

    # 1. Test /api/preview
    prev_res = client.get(f"/api/preview?path={pdf_file}")
    assert prev_res.status_code == 200
    prev_json = prev_res.json()
    assert prev_json["preview_type"] == "pdf"
    assert prev_json["filename"] == "document.pdf"

    # 2. Test /api/raw headers
    raw_res = client.get(f"/api/raw?path={pdf_file}")
    assert raw_res.status_code == 200
    assert "application/pdf" in raw_res.headers.get("content-type", "")
    assert "inline" in raw_res.headers.get("content-disposition", "")

def test_extract_epub_data_and_preview_endpoint(tmp_path):
    """Verify extract_epub_data parses metadata, cover, and chapters, and /api/preview serves it."""
    import zipfile
    from app.indexer.parsers import extract_epub_data
    from fastapi.testclient import TestClient
    from app.main import app

    epub_file = tmp_path / "time_machine.epub"

    container_xml = (
        '<?xml version="1.0"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '  <rootfiles>'
        '    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
        '  </rootfiles>'
        '</container>'
    )

    content_opf = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '    <dc:title>The Time Machine</dc:title>'
        '    <dc:creator>H. G. Wells</dc:creator>'
        '    <dc:language>en</dc:language>'
        '    <meta name="cover" content="cover-image"/>'
        '  </metadata>'
        '  <manifest>'
        '    <item id="cover-image" href="cover.png" media-type="image/png" properties="cover-image"/>'
        '    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
        '  </manifest>'
        '  <spine>'
        '    <itemref idref="ch1"/>'
        '  </spine>'
        '</package>'
    )

    ch1_html = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<!DOCTYPE html>'
        '<html xmlns="http://www.w3.org/1999/xhtml">'
        '<head><title>Chapter I: Introduction</title></head>'
        '<body>'
        '  <h1>Chapter I</h1>'
        '  <p>The Time Traveller was expounding a recondite matter to us regarding the Fourth Dimension.</p>'
        '</body>'
        '</html>'
    )

    png_bytes = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4'
        b'\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82'
    )

    with zipfile.ZipFile(epub_file, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", content_opf)
        zf.writestr("OEBPS/cover.png", png_bytes)
        zf.writestr("OEBPS/ch1.xhtml", ch1_html)

    # 1. Test direct parser
    data = extract_epub_data(str(epub_file))
    assert data["title"] == "The Time Machine"
    assert data["author"] == "H. G. Wells"
    assert data["language"] == "en"
    assert data["cover_data_url"] is not None
    assert "data:image/png;base64," in data["cover_data_url"]
    assert len(data["chapters"]) == 1
    assert "Time Traveller" in data["text"]
    assert "Chapter I" in data["chapters"][0]["title"]

    # 2. Test FastAPI /api/preview (allowed only inside working folders)
    from app.state import settings_store
    settings_store.set_folders([str(tmp_path)])
    client = TestClient(app)
    res = client.get(f"/api/preview?path={epub_file}")
    assert res.status_code == 200
    pdata = res.json()
    assert pdata["preview_type"] == "epub"
    assert pdata["epub_data"]["title"] == "The Time Machine"
    assert pdata["epub_data"]["author"] == "H. G. Wells"
    assert pdata["epub_data"]["total_chapters"] == 1
    assert "Time Traveller" in pdata["content"]






def test_detect_delimiter_and_preview_choice(tmp_path):
    """Separator is found automatically and can be forced in the preview API."""
    from fastapi.testclient import TestClient
    from app.indexer.parsers import detect_delimiter
    from app.main import app
    from app.state import settings_store

    assert detect_delimiter("a;b;c\n1;2;3\n4;5;6") == ";"
    assert detect_delimiter("a\tb\n1\t2") == "\t"
    assert detect_delimiter("a|b|c\n1|2|3") == "|"
    assert detect_delimiter('name,note\n"x","1;2;3"\n"y","4;5"') == ","
    assert detect_delimiter("time:value\n10:5\n11:7") == ":"
    assert detect_delimiter("just text") == ","

    f = tmp_path / "eu.csv"
    f.write_text("Name;Price;City\nTea;1,50;Riga\nCoffee;2,10;Tallinn\n", encoding="utf-8")
    settings_store.set_folders([str(tmp_path)])
    client = TestClient(app)

    auto = client.get("/api/preview", params={"path": str(f)}).json()["table_data"]
    assert auto["columns"] == ["Name", "Price", "City"] and auto["delimiter"] == "semicolon" and auto["detected"]

    forced = client.get("/api/preview", params={"path": str(f), "delimiter": "comma"}).json()["table_data"]
    assert forced["delimiter"] == "comma" and forced["detected"] is False
    assert forced["columns"] == ["Name;Price;City"]
