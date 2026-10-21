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

class SearchResponse(BaseModel):
    query: str
    mode: str
    type_filter: str
    total: int
    took_ms: float
    results: List[SearchResultItem]

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
    preview_type: str  # "code", "markdown", "table", "image", "plain", "binary", "pdf", "epub"
    content: Optional[str] = None
    language: Optional[str] = None
    table_data: Optional[TablePreviewData] = None
    image_meta: Optional[ImagePreviewMeta] = None
    epub_data: Optional[EpubPreviewMeta] = None
    raw_url: Optional[str] = None
    truncated: bool = False

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

