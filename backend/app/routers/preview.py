"""Preview payload generator for Code, Markdown, Tables, Images, and Text."""

import os
import urllib.parse
from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from app.indexer.parsers import (
    CODE_EXTENSIONS,
    DATA_EXTENSIONS,
    DELIMITERS,
    delimiter_name,
    detect_delimiter,
    MARKDOWN_EXTENSIONS,
    MEDIA_EXTENSIONS,
    extract_epub_data,
    extract_file_content,
    is_text_file,
    parse_csv_content,
)
from app.editing import edit_kind
from app.indexer.office import OFFICE_EXTENSIONS, extract_office, preview_kind
from app.schemas import EpubChapter, EpubPreviewMeta, ImagePreviewMeta, PreviewResponse, TablePreviewData
from app.state import require_allowed

router = APIRouter(prefix="/api", tags=["preview"])

# Quick Look shows the first part of very large text files
PREVIEW_TEXT_LIMIT = 2 * 1024 * 1024

def read_text_head(path: str, limit: int = PREVIEW_TEXT_LIMIT):
    """Read at most `limit` bytes of a text file. Returns (text, truncated)."""
    with open(path, "rb") as f:
        data = f.read(limit + 1)
    truncated = len(data) > limit
    return data[:limit].decode("utf-8", errors="replace"), truncated

LANGUAGE_MAP = {
    ".py": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".json": "json",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".sql": "sql",
    ".sh": "bash",
    ".bash": "bash",
    ".rs": "rust",
    ".go": "go",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "markup",
    ".md": "markdown",
    ".markdown": "markdown",
}

@router.get("/preview", response_model=PreviewResponse)
async def get_preview(
    path: str = Query(..., description="Absolute path to file"),
    delimiter: str = Query("auto", description="Table separator: auto, comma, semicolon, tab, colon, pipe, space"),
) -> PreviewResponse:
    """Produce formatted preview payload for Quick Look HUD overlay."""
    norm_path = os.path.normpath(os.path.abspath(path))
    require_allowed(norm_path)

    if not os.path.exists(norm_path) or not os.path.isfile(norm_path):
        raise HTTPException(status_code=404, detail=f"File not found: {norm_path}")

    filename = os.path.basename(norm_path)
    ext = os.path.splitext(filename)[1].lower()
    stat = os.stat(norm_path)
    size_bytes = stat.st_size
    mtime = stat.st_mtime

    raw_url = f"/api/raw?path={urllib.parse.quote(norm_path)}"

    # Determine preview type
    if ext in MEDIA_EXTENSIONS:
        searchable_text, meta = extract_file_content(norm_path)
        img_info = meta.get("image_meta")
        img_meta = None
        if img_info:
            img_meta = ImagePreviewMeta(
                width=img_info["width"],
                height=img_info["height"],
                format=img_info["format"],
                mode=img_info["mode"],
                aspect_ratio=img_info["aspect_ratio"],
            )

        return PreviewResponse(
            editable=edit_kind(ext),
            path=norm_path,
            filename=filename,
            extension=ext,
            size_bytes=size_bytes,
            mtime=mtime,
            preview_type="image",
            image_meta=img_meta,
            raw_url=raw_url,
        )

    if ext in OFFICE_EXTENSIONS:
        try:
            office = await run_in_threadpool(extract_office, norm_path, ext)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Cannot read this Office file: {e}")
        return PreviewResponse(
            editable=edit_kind(ext),
            path=norm_path,
            filename=filename,
            extension=ext,
            size_bytes=size_bytes,
            mtime=mtime,
            preview_type=preview_kind(ext),
            document_html=office.get("html"),
            sheets=office.get("sheets"),
            slides=office.get("slides"),
            raw_url=raw_url,
        )

    if ext in DATA_EXTENSIONS:
        try:
            content, truncated = read_text_head(norm_path)
            default = "\t" if ext in (".tsv", ".tab") else ","
            chosen = DELIMITERS.get(delimiter.lower())
            sep = chosen if chosen is not None else detect_delimiter(content, default=default)
            cols, rows, total_rows = parse_csv_content(content, delimiter=sep)
            return PreviewResponse(
                editable=edit_kind(ext),
                path=norm_path,
                filename=filename,
                extension=ext,
                size_bytes=size_bytes,
                mtime=mtime,
                preview_type="table",
                content=content,
                truncated=truncated,
                table_data=TablePreviewData(
                    columns=cols,
                    rows=rows,
                    total_rows=total_rows,
                    total_columns=len(cols),
                    delimiter=delimiter_name(sep),
                    detected=chosen is None,
                ),
                raw_url=raw_url,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to parse tabular file: {e}")

    if ext in MARKDOWN_EXTENSIONS:
        try:
            content, truncated = read_text_head(norm_path)
            return PreviewResponse(
                editable=edit_kind(ext),
                path=norm_path,
                filename=filename,
                extension=ext,
                size_bytes=size_bytes,
                mtime=mtime,
                preview_type="markdown",
                content=content,
                truncated=truncated,
                language="markdown",
                raw_url=raw_url,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read markdown: {e}")

    if ext in CODE_EXTENSIONS:
        try:
            content, truncated = read_text_head(norm_path)
            lang = LANGUAGE_MAP.get(ext, "plain")
            return PreviewResponse(
                editable=edit_kind(ext),
                path=norm_path,
                filename=filename,
                extension=ext,
                size_bytes=size_bytes,
                mtime=mtime,
                preview_type="code",
                content=content,
                truncated=truncated,
                language=lang,
                raw_url=raw_url,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read code file: {e}")

    # Fallback to plain text or binary
    if is_text_file(norm_path, ext):
        try:
            content, truncated = read_text_head(norm_path)
            return PreviewResponse(
                editable=edit_kind(ext),
                path=norm_path,
                filename=filename,
                extension=ext,
                size_bytes=size_bytes,
                mtime=mtime,
                preview_type="plain",
                content=content,
                truncated=truncated,
                language="plain",
                raw_url=raw_url,
            )
        except Exception:
            pass

    if ext == ".pdf":
        return PreviewResponse(
            editable=edit_kind(ext),
            path=norm_path,
            filename=filename,
            extension=ext,
            size_bytes=size_bytes,
            mtime=mtime,
            preview_type="pdf",
            content=None,
            raw_url=raw_url,
        )

    if ext == ".epub":
        epub_info = extract_epub_data(norm_path)
        chapters_data = [
            EpubChapter(title=ch.get("title"), content=ch.get("content", ""))
            for ch in epub_info.get("chapters", [])
        ]
        epub_meta = EpubPreviewMeta(
            title=epub_info.get("title"),
            author=epub_info.get("author"),
            language=epub_info.get("language"),
            cover_data_url=epub_info.get("cover_data_url"),
            chapters=chapters_data,
            total_chapters=len(chapters_data),
        )
        return PreviewResponse(
            editable=edit_kind(ext),
            path=norm_path,
            filename=filename,
            extension=ext,
            size_bytes=size_bytes,
            mtime=mtime,
            preview_type="epub",
            content=epub_info.get("text"),
            epub_data=epub_meta,
            raw_url=raw_url,
        )

    return PreviewResponse(
        path=norm_path,
        filename=filename,
        extension=ext,
        size_bytes=size_bytes,
        mtime=mtime,
        preview_type="binary",
        content=None,
        raw_url=raw_url,
    )

@router.get("/raw")
async def get_raw_file(path: str = Query(..., description="Absolute path to file")) -> FileResponse:
    """Serve raw file for inline media streaming and preview rendering."""
    norm_path = os.path.normpath(os.path.abspath(path))
    require_allowed(norm_path)
    if not os.path.exists(norm_path) or not os.path.isfile(norm_path):
        raise HTTPException(status_code=404, detail="File not found")

    ext = os.path.splitext(norm_path)[1].lower()
    media_type = None
    # Raw files never run scripts in the app's origin (HTML, SVG, XML)
    headers = {"X-Content-Type-Options": "nosniff"}
    if ext != ".pdf":
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'"
    if ext == ".pdf":
        media_type = "application/pdf"
        headers["Content-Disposition"] = "inline"
        headers["Content-Type"] = "application/pdf"
    elif ext == ".epub":
        media_type = "application/epub+zip"
        headers["Content-Disposition"] = f'attachment; filename="{os.path.basename(norm_path)}"'

    return FileResponse(norm_path, media_type=media_type, headers=headers)
