import base64
import csv
from html.parser import HTMLParser
import io
import logging
import math
import os
import re
import warnings
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image
import pypdf

# Photos and videos (app/media.py: phones and Snapchat too)
from app.media import IMAGE_EXTENSIONS, MEDIA_EXTENSIONS, VIDEO_EXTENSIONS  # noqa: F401

# Silence noisy font/glyph/encoding warnings from pypdf and fonttools
logging.getLogger("pypdf").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", category=UserWarning, module="pypdf")

# Extension categories
CODE_EXTENSIONS = {
    ".py", ".pyw", ".js", ".jsx", ".ts", ".tsx", ".html", ".htm", ".css", ".scss",
    ".sass", ".less", ".json", ".sql", ".rs", ".go", ".c", ".cpp", ".cc", ".cxx",
    ".h", ".hpp", ".java", ".kt", ".kts", ".php", ".rb", ".sh", ".bash", ".zsh",
    ".yaml", ".yml", ".toml", ".xml", ".lua", ".swift", ".dart", ".r", ".scala"
}

MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd", ".mdx"}
DATA_EXTENSIONS = {".csv", ".tsv", ".tab"}
DOCUMENT_EXTENSIONS = {".pdf", ".txt", ".rtf", ".log", ".ini", ".cfg", ".conf", ".env", ".epub"}

def get_file_category(extension: str) -> str:
    """Return category identifier for a given file extension."""
    ext = extension.lower()
    if ext in CODE_EXTENSIONS:
        return "code"
    if ext in MARKDOWN_EXTENSIONS:
        return "markdown"
    if ext in DATA_EXTENSIONS:
        return "data"
    if ext in MEDIA_EXTENSIONS:
        return "media"
    if ext == ".pdf":
        return "pdf"
    if ext == ".epub":
        return "epub"
    if ext in (".xlsx", ".xlsm", ".xls"):
        return "data"
    if ext in (".docx", ".docm", ".doc", ".pptx", ".pptm", ".ppt"):
        return "office"
    return "plain"

def extract_pdf_text(filepath: str, max_pages: int = 50) -> Optional[str]:
    """Extract searchable plain text from PDF document capped at max_pages."""
    try:
        reader = pypdf.PdfReader(filepath)
        if getattr(reader, "is_encrypted", False):
            return None
        pages_text = []
        num_pages = min(len(reader.pages), max_pages)
        for idx in range(num_pages):
            try:
                extracted = reader.pages[idx].extract_text()
                if extracted:
                    pages_text.append(extracted)
            except Exception:
                continue
        full_text = "\n".join(pages_text).strip()
        return full_text if full_text else None
    except Exception:
        return None

class HTMLTextExtractor(HTMLParser):
    """Extract plain text from HTML while ignoring scripts and styles."""
    def __init__(self):
        super().__init__()
        self.text_parts: List[str] = []
        self._ignore = False

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ("script", "style", "head"):
            self._ignore = True

    def handle_endtag(self, tag):
        if tag.lower() in ("script", "style", "head"):
            self._ignore = False

    def handle_data(self, data):
        if not self._ignore:
            cleaned = data.strip()
            if cleaned:
                self.text_parts.append(cleaned)

    def get_text(self) -> str:
        return " ".join(self.text_parts)

def clean_html_text(html_content: str) -> str:
    """Strip HTML tags and return plain readable text."""
    try:
        parser = HTMLTextExtractor()
        parser.feed(html_content)
        return parser.get_text()
    except Exception:
        return re.sub(r'<[^>]+>', ' ', html_content).strip()

def extract_epub_data(filepath: str, max_chapters: int = 100) -> Dict[str, Any]:
    """Extract metadata, cover art, and readable text/chapters from an EPUB file."""
    result: Dict[str, Any] = {
        "title": None,
        "author": None,
        "language": None,
        "cover_data_url": None,
        "text": None,
        "chapters": [],
    }

    if not os.path.exists(filepath):
        return result

    try:
        with zipfile.ZipFile(filepath, "r") as zf:
            namelist = zf.namelist()

            # 1. Find OPF package file from META-INF/container.xml
            opf_path = None
            if "META-INF/container.xml" in namelist:
                try:
                    container_xml = zf.read("META-INF/container.xml")
                    tree = ET.fromstring(container_xml)
                    for elem in tree.iter():
                        if elem.tag.endswith("rootfile"):
                            opf_path = elem.attrib.get("full-path")
                            if opf_path:
                                break
                except Exception:
                    pass

            if not opf_path:
                for name in namelist:
                    if name.lower().endswith(".opf"):
                        opf_path = name
                        break

            if not opf_path or opf_path not in namelist:
                return result

            opf_dir = os.path.dirname(opf_path)
            opf_content = zf.read(opf_path)
            opf_tree = ET.fromstring(opf_content)

            # 2. Extract Metadata (Title, Author, Language)
            for elem in opf_tree.iter():
                tag_lower = elem.tag.lower()
                if tag_lower.endswith("title") and not result["title"] and elem.text:
                    result["title"] = elem.text.strip()
                elif tag_lower.endswith("creator") and not result["author"] and elem.text:
                    result["author"] = elem.text.strip()
                elif tag_lower.endswith("language") and not result["language"] and elem.text:
                    result["language"] = elem.text.strip()

            if not result["title"]:
                result["title"] = os.path.splitext(os.path.basename(filepath))[0]

            # 3. Parse Manifest & Spine
            manifest: Dict[str, Dict[str, str]] = {}
            cover_item_id = None

            for elem in opf_tree.iter():
                tag_lower = elem.tag.lower()
                if tag_lower.endswith("item"):
                    item_id = elem.attrib.get("id")
                    href = elem.attrib.get("href")
                    media_type = elem.attrib.get("media-type", "")
                    properties = elem.attrib.get("properties", "")
                    if item_id and href:
                        manifest[item_id] = {
                            "href": href,
                            "media_type": media_type,
                            "properties": properties,
                        }
                        if "cover-image" in properties or item_id.lower() in ("cover", "cover-image"):
                            cover_item_id = item_id
                elif tag_lower.endswith("meta"):
                    if elem.attrib.get("name") == "cover":
                        cover_item_id = elem.attrib.get("content")

            # 4. Extract Cover Image if available
            if cover_item_id and cover_item_id in manifest:
                cover_href = manifest[cover_item_id]["href"]
                cover_path = os.path.normpath(os.path.join(opf_dir, cover_href)).replace("\\", "/")
                if cover_path in namelist:
                    try:
                        cover_bytes = zf.read(cover_path)
                        media_type = manifest[cover_item_id]["media_type"] or "image/jpeg"
                        b64_img = base64.b64encode(cover_bytes).decode("ascii")
                        result["cover_data_url"] = f"data:{media_type};base64,{b64_img}"
                    except Exception:
                        pass

            # 5. Extract Spine Chapters
            spine_ids: List[str] = []
            for elem in opf_tree.iter():
                if elem.tag.lower().endswith("itemref"):
                    idref = elem.attrib.get("idref")
                    if idref and idref in manifest:
                        spine_ids.append(idref)

            if not spine_ids:
                spine_ids = [
                    mid for mid, info in manifest.items()
                    if info["media_type"] in ("application/xhtml+xml", "text/html", "text/xml")
                    or info["href"].lower().endswith((".xhtml", ".html", ".htm"))
                ]

            chapters: List[Dict[str, str]] = []
            all_text_parts: List[str] = []

            for item_id in spine_ids[:max_chapters]:
                item_info = manifest.get(item_id)
                if not item_info:
                    continue

                ch_href = item_info["href"]
                ch_path = os.path.normpath(os.path.join(opf_dir, ch_href)).replace("\\", "/")
                if ch_path not in namelist:
                    continue

                try:
                    ch_raw = zf.read(ch_path).decode("utf-8", errors="replace")

                    # Extract chapter title
                    ch_title = None
                    title_match = re.search(r'<(?:h[1-2]|title)[^>]*>(.*?)</(?:h[1-2]|title)>', ch_raw, re.IGNORECASE | re.DOTALL)
                    if title_match:
                        ch_title = clean_html_text(title_match.group(1))
                    if not ch_title:
                        ch_title = f"Chapter {len(chapters) + 1}"

                    ch_text = clean_html_text(ch_raw)
                    if ch_text:
                        all_text_parts.append(ch_text)

                    # Extract body content for clean rendering if <body> exists
                    body_match = re.search(r'<body[^>]*>(.*?)</body>', ch_raw, re.IGNORECASE | re.DOTALL)
                    ch_body = body_match.group(1) if body_match else ch_raw

                    chapters.append({
                        "title": ch_title,
                        "content": ch_body,
                    })
                except Exception:
                    continue

            result["chapters"] = chapters
            result["text"] = "\n\n".join(all_text_parts).strip() if all_text_parts else None

    except Exception:
        pass

    return result

TEXT_EXTENSIONS = CODE_EXTENSIONS | MARKDOWN_EXTENSIONS | DATA_EXTENSIONS | {
    ".txt", ".log", ".ini", ".cfg", ".env", ".conf"
}
BINARY_EXTENSIONS = MEDIA_EXTENSIONS | {
    ".pdf", ".epub", ".zip", ".tar", ".gz", ".exe", ".bin", ".dll", ".sys", ".iso", ".dat",
    ".obj", ".o", ".pyc", ".pyd", ".so", ".dylib", ".class", ".jar"
}

def is_text_file(filepath: str, extension: str, probe_bytes: bool = False) -> bool:
    """Determine if a file is plain text / code or binary without unnecessary disk reads."""
    ext = extension.lower()
    if ext in TEXT_EXTENSIONS:
        return True
    if ext in BINARY_EXTENSIONS:
        return False
    if not probe_bytes:
        return False

    # Probe first 1024 bytes for null byte
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(1024)
            return b"\x00" not in chunk
    except Exception:
        return False


def simplify_aspect_ratio(width: int, height: int) -> str:
    """Compute simplified aspect ratio string (e.g. '16:9', '4:3', '1:1')."""
    if width <= 0 or height <= 0:
        return "N/A"
    g = math.gcd(width, height)
    w = width // g
    h = height // g
    if w > 30 or h > 30:
        ratio = width / height
        return f"{ratio:.2f}:1"
    return f"{w}:{h}"

# Separators the table preview offers (name -> character)
DELIMITERS: Dict[str, str] = {
    "comma": ",",
    "semicolon": ";",
    "tab": "\t",
    "colon": ":",
    "pipe": "|",
    "space": " ",
}

def detect_delimiter(text: str, default: str = ",") -> str:
    """Find the separator that splits the first lines into the same number of columns.

    Space is never detected (too common in normal text); choose it by hand.
    The order breaks ties: comma, semicolon, tab, pipe, colon.
    """
    lines = [line for line in text.splitlines()[:30] if line.strip()]
    if not lines:
        return default
    best, best_score = default, 0.0
    for name in ("comma", "semicolon", "tab", "pipe", "colon"):
        d = DELIMITERS[name]
        # csv.reader respects quotes, so a separator inside "..." does not count
        counts = [len(next(csv.reader([line], delimiter=d), [])) - 1 for line in lines]
        first = counts[0]
        if first <= 0:
            continue
        same = sum(1 for c in counts if c == first) / len(counts)
        score = same * (1 + min(first, 50) / 50)
        if same >= 0.6 and score > best_score:
            best, best_score = d, score
    return best

def delimiter_name(d: str) -> str:
    for name, char in DELIMITERS.items():
        if char == d:
            return name
    return "comma"

def parse_csv_content(text_content: str, delimiter: str = ",", max_rows: int = 300_000,
                      max_cells: int = 3_000_000) -> Tuple[List[str], List[List[str]], int]:
    """Parse CSV text into columns (first row) and data rows, up to the preview limits."""
    reader = csv.reader(io.StringIO(text_content), delimiter=delimiter)
    rows: List[List[str]] = []
    columns: List[str] = []
    total_rows = 0
    cells = 0

    for i, row in enumerate(reader):
        total_rows += 1
        if i == 0:
            columns = [col.strip() for col in row]
        elif len(rows) < max_rows and cells < max_cells:
            rows.append(row)
            cells += len(row)

    if not columns and rows:
        columns = [f"Col {idx+1}" for idx in range(len(rows[0]))]

    return columns, rows, total_rows

def extract_file_content(filepath: str, max_size_bytes: int = 10 * 1024 * 1024) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Extract text content (for indexing & preview) and supplementary metadata.
    Returns: (searchable_text, extra_metadata_dict)
    """
    ext = os.path.splitext(filepath)[1].lower()
    meta: Dict[str, Any] = {}

    try:
        size = os.path.getsize(filepath)
        if size > max_size_bytes:
            return None, {"error": "File exceeds max size limit"}

        # Images
        if ext in IMAGE_EXTENSIONS:
            try:
                with Image.open(filepath) as img:
                    width, height = img.size
                    img_format = img.format or ext.lstrip(".").upper()
                    mode = img.mode
                    aspect_ratio = simplify_aspect_ratio(width, height)
                    meta["image_meta"] = {
                        "width": width,
                        "height": height,
                        "format": img_format,
                        "mode": mode,
                        "aspect_ratio": aspect_ratio,
                    }
                    searchable_text = f"{os.path.basename(filepath)} image {img_format} {width}x{height} {mode} aspect ratio {aspect_ratio}"
                    return searchable_text, meta
            except Exception as e:
                return None, {"error": str(e)}

        # PDF documents
        if ext == ".pdf":
            try:
                reader = pypdf.PdfReader(filepath)
                pages_text = []
                for idx, page in enumerate(reader.pages[:50]):  # Cap at 50 pages for indexing
                    try:
                        extracted = page.extract_text()
                        if extracted:
                            pages_text.append(extracted)
                    except Exception:
                        # Gracefully continue on corrupt font glyphs or malformed pages
                        continue
                full_text = "\n".join(pages_text)
                meta["page_count"] = len(reader.pages)
                return full_text, meta
            except Exception as e:
                return None, {"error": str(e)}

        # Data files (CSV/TSV)
        if ext in DATA_EXTENSIONS:
            delimiter = "\t" if ext in (".tsv", ".tab") else ","
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                cols, rows, total_rows = parse_csv_content(content, delimiter=delimiter)
                meta["table_data"] = {
                    "columns": cols,
                    "rows": rows,
                    "total_rows": total_rows,
                    "total_columns": len(cols),
                }
                return content, meta
            except Exception as e:
                return None, {"error": str(e)}

        # Code, Markdown, and Plain Text
        if is_text_file(filepath, ext):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                return content, meta
            except UnicodeDecodeError:
                with open(filepath, "r", encoding="latin-1", errors="replace") as f:
                    content = f.read()
                return content, meta

    except Exception as e:
        return None, {"error": str(e)}

    return None, meta
