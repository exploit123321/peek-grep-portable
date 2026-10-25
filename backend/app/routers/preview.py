"""Preview payload generator for Code, Markdown, Tables, Images, and Text."""

import os
import urllib.parse
from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from app.indexer.parsers import (
    CODE_EXTENSIONS,
    DATA_EXTENSIONS,
    DELIMITERS,
    delimiter_name,
    detect_delimiter,
    MARKDOWN_EXTENSIONS,
    extract_epub_data,
    is_text_file,
    parse_csv_content,
)
from app.editing import edit_kind
from app.indexer.office import OFFICE_EXTENSIONS, extract_office_preview, preview_kind
from app.media import (
    BROWSER_IMAGE_EXTENSIONS,
    IMAGE_EXTENSIONS,
    MEDIA_EXTENSIONS,
    VIDEO_EXTENSIONS,
    VIDEO_MIME,
    image_info,
    media_extension,
    preview_jpeg,
    snapchat_overlay,
    video_info,
)
from app.schemas import (
    EpubChapter,
    EpubPreviewMeta,
    ImagePreviewMeta,
    PreviewResponse,
    TablePreviewData,
    VideoPreviewMeta,
)
from app.state import require_allowed, settings_store

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

def _raw_url(path: str) -> str:
    return f"/api/raw?path={urllib.parse.quote(path)}"


@router.get("/image")
async def get_image(path: str = Query(..., description="Absolute path to a photo")) -> Response:
    """A photo the WebView cannot show (HEIC, HEIF, TIFF) as JPEG: upright, at most 2560 pixels."""
    norm_path = os.path.normpath(os.path.abspath(path))
    require_allowed(norm_path)
    if not os.path.isfile(norm_path):
        raise HTTPException(status_code=404, detail="File not found")
    try:
        data = await run_in_threadpool(preview_jpeg, norm_path)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Cannot read this photo: {e}")
    # The URL has the file's change time: the WebView may keep it
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/preview", response_model=PreviewResponse)
async def get_preview(
    path: str = Query(..., description="Absolute path to file"),
    delimiter: str = Query("auto", description="Table separator: auto, comma, semicolon, tab, colon, pipe, space"),
    quick: bool = Query(False, description="Workbooks: first rows of each sheet only (a full request follows)"),
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

    raw_url = _raw_url(norm_path)

    # Photos and videos: the content decides (HEIC named .jpg, Snapchat files without extension)
    media_ext = media_extension(norm_path, ext)
    if media_ext in MEDIA_EXTENSIONS:
        overlay = snapchat_overlay(norm_path)
        overlay_url = _raw_url(overlay) if overlay and settings_store.is_allowed(overlay) else None
        if media_ext in IMAGE_EXTENSIONS:
            info = await run_in_threadpool(image_info, norm_path)
            # Without details (SVG) the WebView still shows it; HEIC without them cannot be read at all
            if info is not None or media_ext in BROWSER_IMAGE_EXTENSIONS:
                display_url = None
                if media_ext not in BROWSER_IMAGE_EXTENSIONS:
                    display_url = f"/api/image?path={urllib.parse.quote(norm_path)}&v={stat.st_mtime_ns}"
                return PreviewResponse(
                    editable=edit_kind(ext),
                    path=norm_path,
                    filename=filename,
                    extension=ext,
                    size_bytes=size_bytes,
                    mtime=mtime,
                    preview_type="image",
                    image_meta=ImagePreviewMeta(**info) if info else None,
                    raw_url=raw_url,
                    display_url=display_url,
                    overlay_url=overlay_url,
                )
        elif media_ext in VIDEO_EXTENSIONS:
            info = await run_in_threadpool(video_info, norm_path) if media_ext in VIDEO_MIME else None
            return PreviewResponse(
                path=norm_path,
                filename=filename,
                extension=ext,
                size_bytes=size_bytes,
                mtime=mtime,
                preview_type="video",
                video_meta=VideoPreviewMeta(**info) if info else None,
                media_mime=VIDEO_MIME.get(media_ext),
                raw_url=raw_url,
                overlay_url=overlay_url,
            )

    if ext in OFFICE_EXTENSIONS:
        try:
            office = await run_in_threadpool(extract_office_preview, norm_path, ext, quick)
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
            # Tables load completely (up to 100 MB); the UI draws only the visible rows
            content, truncated = read_text_head(norm_path, limit=100 * 1024 * 1024)
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
    else:
        # Photos and videos by their content (a .mov plays as MP4; Snapchat files without extension)
        kind = media_extension(norm_path, ext)
        if kind in VIDEO_MIME:
            media_type = VIDEO_MIME[kind]
        elif kind in IMAGE_EXTENSIONS and kind != ext:
            media_type = {".jpg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp",
                          ".avif": "image/avif"}.get(kind)

    return FileResponse(norm_path, media_type=media_type, headers=headers)
