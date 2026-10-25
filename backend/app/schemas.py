"""Pydantic data transfer objects and schemas for Peek & Grep."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class SearchResultItem(BaseModel):
    path: str
    filename: str
    extension: str
    size_bytes: int
    mtime: float
    is_text: bool
    snippet: Optional[str] = None
    match_type: str = "content"  # "filename", "content", "both"
    category: str = "plain"      # "code", "markdown", "data", "media", "plain"

class HighlightTerm(BaseModel):
    text: str
    literal: bool = False
    exact: bool = False           # the whole file name
    pieces: List[List[str]] = []  # ["text", "abc"], ["any", ""] for *, ["one", ""] for ?
    field: str = "name"           # name or text

class ExplainChip(BaseModel):
    kind: str   # ext, not-ext, name, not-name, exact, not-exact, text, not-text, groups
    text: str
    literal: bool = False

class SearchGroup(BaseModel):
    label: str
    total: int
    offset: int = 0
    has_more: bool = False
    results: List[SearchResultItem]
    highlight: List[HighlightTerm] = []

class SearchResponse(BaseModel):
    query: str
    type_filter: str
    total: int
    took_ms: float
    results: List[SearchResultItem]
    offset: int = 0
    has_more: bool = False
    grouped: bool = False
    groups: List[SearchGroup] = []
    highlight: List[HighlightTerm] = []
    explain: List[ExplainChip] = []

class TablePreviewData(BaseModel):
    columns: List[str]
    rows: List[List[str]]
    total_rows: int
    total_columns: int
    delimiter: str = "comma"   # name of the separator used
    detected: bool = True      # True when the separator was found automatically

class ImagePreviewMeta(BaseModel):
    width: int
    height: int
    format: str
    mode: str
    aspect_ratio: str
    taken: Optional[str] = None   # "2024-05-01 14:03" (EXIF)
    camera: Optional[str] = None  # "Apple iPhone 15 Pro"

class VideoPreviewMeta(BaseModel):
    duration: Optional[float] = None  # seconds
    width: Optional[int] = None       # as shown (after the rotation)
    height: Optional[int] = None
    rotation: int = 0
    codec: Optional[str] = None       # "hvc1", "avc1", ...
    codec_name: Optional[str] = None  # "HEVC (H.265)"
    audio: bool = False
    created: Optional[str] = None
    camera: Optional[str] = None

class SheetData(BaseModel):
    name: str
    columns: List[str]
    rows: List[List[str]]
    total_rows: int
    total_columns: int
    truncated: bool = False
    partial: bool = False  # quick answer: more rows follow in the full preview

class SlideParagraph(BaseModel):
    text: str
    level: int = 0

class SlideData(BaseModel):
    number: int
    title: str = ""
    paragraphs: List[SlideParagraph] = []
    images: int = 0

class EpubChapter(BaseModel):
    title: Optional[str] = None
    content: str

class EpubPreviewMeta(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    language: Optional[str] = None
    cover_data_url: Optional[str] = None
    chapters: List[EpubChapter] = []
    total_chapters: int = 0

class PreviewResponse(BaseModel):
    path: str
    filename: str
    extension: str
    size_bytes: int
    mtime: float
    preview_type: str  # code, markdown, table, image, video, plain, binary, pdf, epub, document, workbook, slides
    content: Optional[str] = None
    language: Optional[str] = None
    table_data: Optional[TablePreviewData] = None
    image_meta: Optional[ImagePreviewMeta] = None
    epub_data: Optional[EpubPreviewMeta] = None
    document_html: Optional[str] = None
    sheets: Optional[List[SheetData]] = None
    slides: Optional[List[SlideData]] = None
    raw_url: Optional[str] = None
    # Photos the WebView cannot show (HEIC): a JPEG made for the preview
    display_url: Optional[str] = None
    video_meta: Optional[VideoPreviewMeta] = None
    # The type a video is served as ("video/mp4"); None: a container the WebView cannot play (AVI, WMV)
    media_mime: Optional[str] = None
    # Snapchat memory: its text and stickers, drawn over the photo or video
    overlay_url: Optional[str] = None
    truncated: bool = False
    editable: Optional[str] = None  # text, csv, workbook, document (None: not editable)

class ActionRequest(BaseModel):
    path: str

class ActionResponse(BaseModel):
    success: bool
    message: str
    path: Optional[str] = None

class ResizeWindowRequest(BaseModel):
    width: int
    height: int

class WindowSizeResponse(BaseModel):
    width: int
    height: int
    is_maximized: bool = False

class StatusResponse(BaseModel):
    status: str
    version: str
    indexed_files: int
    content_indexed: int
    setup_done: bool
    folders: List[str]
    data_dir: str
    db_path: str
    portable: bool = True

class FolderListRequest(BaseModel):
    folders: List[str]

class FolderCheckRequest(BaseModel):
    path: str
    current: Optional[List[str]] = None

class ReindexRequest(BaseModel):
    folder: Optional[str] = None

