"""Unit tests for full-drive crawler, permission resilience, and two-tier indexing."""

import os
import tempfile
import pytest
from app.indexer.crawler import (
    SafeDriveCrawler,
    build_file_record,
    is_protected_directory,
    should_skip_metadata,
)
from app.indexer.db import count_files, get_file_meta, init_db, search_files

def test_is_protected_directory():
    """Verify protected Windows folders and bloat dirs are correctly identified."""
    assert is_protected_directory(r"C:\Windows\System32", "System32") is True
    assert is_protected_directory(r"C:\System Volume Information", "System Volume Information") is True
    assert is_protected_directory(r"C:\$Recycle.Bin", "$Recycle.Bin") is True
    assert is_protected_directory(r"C:\Users\Alice\AppData\Local\Temp", "Temp") is True
    assert is_protected_directory(r"C:\Users\Alice\AppData", "AppData") is True
    assert is_protected_directory(r"C:\Users\Alice\.cache", ".cache") is True
    assert is_protected_directory(r"D:\projects\.git", ".git") is True
    assert is_protected_directory(r"D:\projects\node_modules", "node_modules") is True
    assert is_protected_directory(r"D:\projects\src", "src") is False
    assert is_protected_directory(r"D:\documents", "documents") is False

def test_system_ignore_dirs_contains_all_noisy_folders():
    """Verify SYSTEM_IGNORE_DIRS contains all required noisy system and cache folders."""
    from app.config import SYSTEM_IGNORE_DIRS
    expected = {
        "windows", "programdata", "$recycle.bin", "system volume information",
        "appdata", "temp", ".cache",
        "node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build"
    }
    assert expected.issubset(SYSTEM_IGNORE_DIRS)
    for folder in expected:
        assert is_protected_directory(f"C:\\test\\{folder}", folder) is True

def test_should_skip_metadata():
    """Verify lock and temp file filters."""
    assert should_skip_metadata("lockfile.lock", ".lock") is True
    assert should_skip_metadata("cache.tmp", ".tmp") is True
    assert should_skip_metadata("~$draft.docx", ".docx") is True
    assert should_skip_metadata("report.pdf", ".pdf") is False
    assert should_skip_metadata("script.py", ".py") is False

def test_watcher_should_ignore_filters_noisy_paths():
    """Verify watchdog change handler immediately discards events on ignored/cache paths."""
    from app.indexer.watcher import DebouncedChangeHandler
    handler = DebouncedChangeHandler()
    try:
        # Noisy paths must be ignored
        assert handler.should_ignore(r"C:\Users\User\AppData\Local\Temp\cache.tmp") is True
        assert handler.should_ignore(r"C:\Windows\System32\drivers\etc\hosts") is True
        assert handler.should_ignore(r"D:\project\node_modules\pkg\index.js") is True
        assert handler.should_ignore(r"C:\$Recycle.Bin\deleted_file.txt") is True
        assert handler.should_ignore(r"C:\Users\User\.cache\thumbnails\img.png") is True
        assert handler.should_ignore(r"D:\work\~$document.docx") is True
        assert handler.should_ignore(r"D:\work\peek_grep.db-wal") is True

        # Valid project paths must NOT be ignored
        assert handler.should_ignore(r"D:\projects\code\main.py") is False
        assert handler.should_ignore(r"D:\docs\guide.md") is False
    finally:
        handler.stop()

def test_two_tier_indexing_whitelist_and_size_limit(tmp_path):
    """Verify Tier 1 metadata is captured for non-whitelisted or large files, while Tier 2 FTS is restricted."""
    # 1. Whitelisted code file <= 5MB -> both metadata and content
    py_file = tmp_path / "test.py"
    py_file.write_text("def unique_search_target(): pass", encoding="utf-8")
    rec_py = build_file_record(str(py_file), max_fts_size=5 * 1024 * 1024)
    assert rec_py is not None
    assert rec_py["filename"] == "test.py"
    assert rec_py["content"] is not None
    assert "unique_search_target" in rec_py["content"]

    # 2. Whitelisted code file > 5MB -> metadata only, content is None
    large_py = tmp_path / "huge.py"
    # Create 200 bytes file, but test with max_fts_size=100 bytes
    large_py.write_text("A" * 200, encoding="utf-8")
    rec_large = build_file_record(str(large_py), max_fts_size=100)
    assert rec_large is not None
    assert rec_large["filename"] == "huge.py"
    assert rec_large["content"] is None  # Content skipped due to 5MB threshold

    # 3. Non-whitelisted file (e.g. binary .dat or .iso) -> metadata only, content is None
    dat_file = tmp_path / "data.dat"
    dat_file.write_bytes(b"\x00\x01\x02\x03\x04")
    rec_dat = build_file_record(str(dat_file), max_fts_size=5 * 1024 * 1024)
    assert rec_dat is not None
    assert rec_dat["filename"] == "data.dat"
    assert rec_dat["content"] is None  # Not in whitelisted extensions

def test_crawler_full_traversal_and_status(tmp_path):
    """Verify SafeDriveCrawler traverses tree, commits in batch, and updates status tracker."""
    db_file = str(tmp_path / "drive_test.db")
    init_db(db_file)

    sandbox = tmp_path / "root"
    sandbox.mkdir()

    # Valid files
    (sandbox / "guide.md").write_text("# Deployment Guide\nArchitecture details", encoding="utf-8")
    (sandbox / "data.csv").write_text("id,val\n1,Alpha", encoding="utf-8")

    # Protected/ignored folder
    git_dir = sandbox / ".git"
    git_dir.mkdir()
    (git_dir / "index").write_text("git internal", encoding="utf-8")

    crawler = SafeDriveCrawler(roots=[str(sandbox)], batch_size=2, db_path=db_file)
    result = crawler.crawl_and_index()

    assert result["indexed_count"] == 2
    assert count_files(db_file) == 2

    # Pass 2 worker extracts content into FTS5
    from app.indexer.fts_worker import FTSContentWorker
    worker = FTSContentWorker(db_path=db_file)
    worker.process_batch()

    # Verify FTS search finds content in guide.md
    search_res = search_files("Architecture", mode="content", db_path=db_file)
    assert len(search_res) == 1
    assert search_res[0].filename == "guide.md"

def test_crawler_1000_batch_buffering(tmp_path):
    """Verify crawler buffers up to 1,000 files in memory before executing bulk transaction."""
    db_file = str(tmp_path / "batch_test.db")
    init_db(db_file)

    sandbox = tmp_path / "bulk_root"
    sandbox.mkdir()

    # Generate 1,050 files
    for i in range(1050):
        (sandbox / f"file_{i}.txt").write_text(f"Line content {i}", encoding="utf-8")

    crawler = SafeDriveCrawler(roots=[str(sandbox)], batch_size=1000, db_path=db_file)
    result = crawler.crawl_and_index()

    assert result["indexed_count"] == 1050
    assert count_files(db_file) == 1050

    # Pass 2 worker processes files into FTS
    from app.indexer.fts_worker import FTSContentWorker
    worker = FTSContentWorker(db_path=db_file, batch_size=1100)
    worker.process_batch()

    # Search verified across the batch
    hits = search_files("content 500", mode="content", db_path=db_file)
    assert len(hits) == 1
    assert hits[0].filename == "file_500.txt"

def test_pdf_and_image_content_decoupled_from_crawler(tmp_path):
    """Verify crawler captures metadata only and skips deep content extraction for pdf/images."""
    # PDF file
    pdf_file = tmp_path / "document.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 header content")
    rec_pdf = build_file_record(str(pdf_file), extract_content=False)
    assert rec_pdf is not None
    assert rec_pdf["filename"] == "document.pdf"
    assert rec_pdf["content"] is None  # Skipped from deep crawl extraction

    # PNG file
    png_file = tmp_path / "photo.png"
    png_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    rec_png = build_file_record(str(png_file), extract_content=False)
    assert rec_png is not None
    assert rec_png["filename"] == "photo.png"
    assert rec_png["content"] is None  # Skipped from deep crawl extraction

def test_two_pass_pdf_fts_indexing_and_search(tmp_path):
    """Verify Pass 1 captures PDF metadata and Pass 2 indexes text for FTS search."""
    import pypdf
    db_file = str(tmp_path / "pdf_test.db")
    init_db(db_file)

    # Create a real searchable PDF using pypdf
    pdf_path = tmp_path / "quantum_computing.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    # pypdf Writer can create annotations or we can write a simple valid text PDF stream
    # or write a minimal valid PDF with text stream
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        b"4 0 obj<</Length 55>>stream\n"
        b"BT /F1 12 Tf 100 700 Td (Superconducting Qubits and Entanglement) Tj ET\n"
        b"endstream\nendobj\n"
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000056 00000 n \n0000000111 00000 n \n0000000234 00000 n \n0000000341 00000 n \n"
        b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n412\n%%EOF\n"
    )
    pdf_path.write_bytes(pdf_bytes)

    # Pass 1: Crawl metadata only
    crawler = SafeDriveCrawler(roots=[str(tmp_path)], db_path=db_file)
    crawler.crawl_and_index()
    assert count_files(db_file) >= 1

    # Pass 2: Background FTS worker extracts PDF text
    from app.indexer.fts_worker import FTSContentWorker
    worker = FTSContentWorker(db_path=db_file)
    indexed_count = worker.process_batch()
    assert indexed_count >= 1

    # Search for keyword inside the PDF
    results = search_files("Entanglement", mode="content", db_path=db_file)
    assert len(results) >= 1
    assert results[0].filename == "quantum_computing.pdf"
    assert results[0].snippet is not None
    assert "Entanglement" in results[0].snippet or "Qubits" in results[0].snippet


