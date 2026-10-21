"""Microsoft Office previews and text, with the standard library only.

New formats (.docx, .xlsx, .xlsm, .pptx) are ZIP files with XML inside: this module.
Old binary formats (.doc, .xls, .ppt): see legacy_office.py.

Every reader returns a dict with "text" (for the search index) and preview data:
    document  -> {"html": str}
    workbook  -> {"sheets": [{"name", "columns", "rows", "total_rows", "total_columns", "truncated"}]}
    slides    -> {"slides": [{"number", "title", "paragraphs": [{"text", "level"}], "images"}]}
"""

import html
import os
import posixpath
import threading
from collections import OrderedDict
import re
import zipfile
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

WORD_EXTENSIONS = {".docx", ".docm", ".doc"}
EXCEL_EXTENSIONS = {".xlsx", ".xlsm", ".xls"}
POWERPOINT_EXTENSIONS = {".pptx", ".pptm", ".ppt"}
OFFICE_EXTENSIONS = WORD_EXTENSIONS | EXCEL_EXTENSIONS | POWERPOINT_EXTENSIONS

# Limits that keep previews fast and protect against huge or hostile files
MAX_XML_BYTES = 64 * 1024 * 1024
MAX_SHEETS = 30
MAX_ROWS = 300_000   # rows kept for the preview (the UI draws only the visible rows)
MAX_COLS = 200
MAX_CELLS = 3_000_000  # cells kept for the preview of one sheet
MAX_TEXT_CHARS = 2_000_000

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def preview_kind(ext: str) -> Optional[str]:
    ext = ext.lower()
    if ext in WORD_EXTENSIONS:
        return "document"
    if ext in EXCEL_EXTENSIONS:
        return "workbook"
    if ext in POWERPOINT_EXTENSIONS:
        return "slides"
    return None


def extract_office(path: str, ext: str, offset: int = 0, limit: int = MAX_ROWS,
                   sheet_index: Optional[int] = None, with_text: bool = True, quick: bool = False) -> Dict[str, Any]:
    """Preview data and text for any supported Office file (new or old format).

    For workbooks, offset/limit select the row window and sheet_index one sheet (a page request,
    without search text).
    """
    ext = ext.lower()
    if ext in (".doc", ".xls", ".ppt"):
        from app.indexer import legacy_office
        return legacy_office.extract(path, ext, offset=offset, limit=limit, sheet_index=sheet_index)
    with zipfile.ZipFile(path) as zf:
        if ext in WORD_EXTENSIONS:
            return _docx(zf)
        if ext in EXCEL_EXTENSIONS:
            return _xlsx(zf, offset, limit, sheet_index, with_text, quick)
        if ext in POWERPOINT_EXTENSIONS:
            return _pptx(zf)
    raise ValueError(f"Not an Office file: {ext}")


# Preview cache: opening the same unchanged file again is instant. Small on purpose.
_CACHE: "OrderedDict[Tuple[str, int, int, bool], Dict[str, Any]]" = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_FILES = 3
_CACHE_CELLS = 2_000_000


def _cell_count(result: Dict[str, Any]) -> int:
    return sum(len(r) for s in result.get("sheets") or [] for r in s.get("rows", []))


QUICK_ROWS = 2000  # rows per sheet in the quick first answer for large workbooks


def extract_office_preview(path: str, ext: str, quick: bool = False) -> Dict[str, Any]:
    """Preview data without search text, cached by path, size, and modification time.

    quick: the first QUICK_ROWS rows of each sheet (sheets that have more are marked partial).
    """
    if ext.lower() not in (".xlsx", ".xlsm"):
        quick = False  # only the .xlsx reader can stop early; other formats load completely
    st = os.stat(path)
    key = (os.path.normcase(path), st.st_mtime_ns, st.st_size, quick)
    with _CACHE_LOCK:
        full_key = key[:3] + (False,)
        if quick and full_key in _CACHE:
            return _CACHE[full_key]  # the full result is already here
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    if quick:
        result = extract_office(path, ext, limit=QUICK_ROWS, with_text=False, quick=True)
    else:
        result = extract_office(path, ext, with_text=False)
    result.pop("text", None)
    with _CACHE_LOCK:
        _CACHE[key] = result
        while len(_CACHE) > _CACHE_FILES or (len(_CACHE) > 1 and sum(_cell_count(v) for v in _CACHE.values()) > _CACHE_CELLS):
            _CACHE.popitem(last=False)
    return result


def extract_office_text(path: str, ext: str) -> Optional[str]:
    try:
        # limit=0: text only, no preview cells
        text = extract_office(path, ext, limit=0).get("text") or ""
        return text[:MAX_TEXT_CHARS].strip() or None
    except Exception:
        return None


# -- helpers ---------------------------------------------------------------------------

def _read_xml(zf: zipfile.ZipFile, name: str) -> Optional[ET.Element]:
    try:
        info = zf.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_XML_BYTES:
        raise ValueError(f"{name} is too large to preview")
    return ET.fromstring(zf.read(name))


def _rels(zf: zipfile.ZipFile, part: str) -> Dict[str, str]:
    """Relationship id -> full part name, for one part (for example word/document.xml)."""
    folder, base = posixpath.split(part)
    root = _read_xml(zf, posixpath.join(folder, "_rels", base + ".rels"))
    result: Dict[str, str] = {}
    if root is None:
        return result
    for rel in root.iter(f"{PR}Relationship"):
        target = rel.get("Target", "")
        if rel.get("TargetMode") == "External":
            continue
        full = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
        result[rel.get("Id", "")] = full
    return result


def table_html(rows: List[List[str]]) -> str:
    if not rows:
        return ""
    out = ["<table>"]
    for i, row in enumerate(rows):
        tag = "th" if i == 0 and len(rows) > 1 else "td"
        out.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in row) + "</tr>")
    out.append("</table>")
    return "".join(out)


def paragraphs_html(paragraphs: List[Tuple[str, str]]) -> str:
    """[(kind, escaped html)] with kind in p, h1..h6, li -> HTML (list items grouped)."""
    out: List[str] = []
    in_list = False
    for kind, body in paragraphs:
        if kind == "li":
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{body}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if kind == "raw":
            out.append(body)
        else:
            out.append(f"<{kind}>{body}</{kind}>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


# -- Word ------------------------------------------------------------------------------

def _docx_paragraph(p: ET.Element) -> Tuple[str, str, str]:
    """Return (kind, html, plain text) for one w:p."""
    style = ""
    ppr = p.find(f"{W}pPr")
    is_list = False
    if ppr is not None:
        ps = ppr.find(f"{W}pStyle")
        if ps is not None:
            style = (ps.get(f"{W}val") or "").lower()
        is_list = ppr.find(f"{W}numPr") is not None
    parts_html: List[str] = []
    parts_text: List[str] = []
    for r in p.iter(f"{W}r"):
        rpr = r.find(f"{W}rPr")
        bold = rpr is not None and rpr.find(f"{W}b") is not None and rpr.find(f"{W}b").get(f"{W}val") not in ("0", "false")
        italic = rpr is not None and rpr.find(f"{W}i") is not None and rpr.find(f"{W}i").get(f"{W}val") not in ("0", "false")
        for node in r:
            if node.tag == f"{W}t":
                txt = node.text or ""
                esc = html.escape(txt)
                if bold:
                    esc = f"<strong>{esc}</strong>"
                if italic:
                    esc = f"<em>{esc}</em>"
                parts_html.append(esc)
                parts_text.append(txt)
            elif node.tag == f"{W}tab":
                parts_html.append("&emsp;")
                parts_text.append("\t")
            elif node.tag in (f"{W}br", f"{W}cr"):
                parts_html.append("<br>")
                parts_text.append("\n")
    body = "".join(parts_html)
    text = "".join(parts_text)
    m = re.match(r"heading\s*([1-6])", style)
    if style == "title":
        kind = "h1"
    elif m:
        kind = f"h{int(m.group(1))}"
    elif is_list or "list" in style:
        kind = "li"
    else:
        kind = "p"
    return kind, body, text


def _docx(zf: zipfile.ZipFile) -> Dict[str, Any]:
    root = _read_xml(zf, "word/document.xml")
    if root is None:
        raise ValueError("word/document.xml is missing")
    body = root.find(f"{W}body")
    paragraphs: List[Tuple[str, str]] = []
    texts: List[str] = []
    for child in list(body if body is not None else []):
        if child.tag == f"{W}p":
            kind, body_html, text = _docx_paragraph(child)
            if body_html.strip() or kind != "p":
                paragraphs.append((kind, body_html or "&nbsp;"))
            texts.append(text)
        elif child.tag == f"{W}tbl":
            rows: List[List[str]] = []
            for tr in child.iter(f"{W}tr"):
                cells = []
                for tc in tr.findall(f"{W}tc"):
                    cell_parts = [_docx_paragraph(p) for p in tc.iter(f"{W}p")]
                    cells.append("<br>".join(h for _, h, _ in cell_parts if h))
                    texts.append(" ".join(t for _, _, t in cell_parts))
                rows.append(cells)
            paragraphs.append(("raw", table_html(rows)))
    return {"html": paragraphs_html(paragraphs), "text": "\n".join(texts)}


# -- Excel -----------------------------------------------------------------------------

# Built-in number formats that show dates or times
_DATE_FORMAT_IDS = set(range(14, 23)) | {45, 46, 47}


def is_date_format(code: str) -> bool:
    """True for number format codes with date or time parts (outside quotes and brackets)."""
    clean = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", code or "").lower()
    return bool(re.search(r"[dmyhs]", clean)) and "general" not in clean


def excel_date(serial: float, date1904: bool = False) -> str:
    base = datetime(1904, 1, 1) if date1904 else datetime(1899, 12, 30)
    try:
        value = base + timedelta(days=serial)
    except OverflowError:
        return format_number(serial)
    if value.hour or value.minute or value.second:
        if serial < 1:
            return value.strftime("%H:%M:%S")
        return value.strftime("%Y-%m-%d %H:%M")
    return value.strftime("%Y-%m-%d")


def format_number(value: float) -> str:
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.10g}"


def column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _column_index(ref: str) -> int:
    n = 0
    for ch in ref:
        if "A" <= ch <= "Z":
            n = n * 26 + (ord(ch) - 64)
        else:
            break
    return max(0, n - 1)


def sheet_result(name: str, cells: Dict[Tuple[int, int], str], total_rows: int, offset: int = 0,
                 limit: int = MAX_ROWS, total_columns: int = 0) -> Dict[str, Any]:
    """One row window of a sheet, with Excel letters as headers.

    cells: (row, col) -> text, both 0-based and absolute. total_rows: last used row + 1.
    """
    last_row = max((r for r, _ in cells), default=-1)
    total = max(total_rows, last_row + 1)
    total_cols = max(total_columns, max((c for _, c in cells), default=-1) + 1)
    width = min(total_cols, MAX_COLS)
    end = min(total, offset + limit)
    rows = [[cells.get((r, c), "") for c in range(width)] for r in range(offset, end)]
    return {
        "name": name,
        "columns": [column_letter(c) for c in range(width)],
        "rows": rows,
        "offset": offset,
        "total_rows": total,
        "total_columns": total_cols,
        "truncated": end < total or total_cols > MAX_COLS,
    }


# Fast reader for regular sheet XML (what Excel and most tools write): one compiled pattern over
# large chunks instead of an element tree per cell. Returns None when the XML is not regular,
# so that the ElementTree reader handles it.
_CELL_RE = re.compile(r'<c\b([^>]*?)\sr="([A-Z]{1,3})(\d+)"([^>]*?)(?:/>|>(.*?)</c>)', re.S)
_V_RE = re.compile(r"<v>(.*?)</v>", re.S)
_T_RE = re.compile(r"<t(?:\s[^>]*)?>(.*?)</t>", re.S)
_COL_CACHE: Dict[str, int] = {}


def _col(letters: str) -> int:
    idx = _COL_CACHE.get(letters)
    if idx is None:
        idx = _column_index(letters)
        _COL_CACHE[letters] = idx
    return idx


def _xlsx_sheet_fast(zf: zipfile.ZipFile, part: str, shared: List[str], date_styles: set, date1904: bool,
                     offset: int, limit: int, texts: Optional[List[str]], quick: bool = False):
    import codecs
    from html import unescape

    with zf.open(part) as fh:
        head = fh.read(65536).decode("utf-8", errors="replace")
        # Regular XML only: default namespace, every cell with a position
        if re.search(r"<\w+:c[\s>]", head) or ("<c>" in head) or re.search(r"<c(?![^>]*\sr=)[\s>]", head):
            return None
    row_lists: Dict[int, List[str]] = {}
    cell_count = 0
    last_row = -1
    max_col = -1
    chars = 0
    end_row = offset + limit
    n_shared = len(shared)
    col_cache = _COL_CACHE
    finditer = _CELL_RE.finditer
    v_search = _V_RE.search
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    buf = ""
    current_r = -2
    current_list: Optional[List[str]] = None
    stopped = False
    with zf.open(part) as fh:
        while not stopped:
            chunk = fh.read(4 * 1024 * 1024)
            buf += decoder.decode(chunk, final=not chunk)
            cut = buf.rfind("</row>") + 6 if chunk else len(buf)
            if cut <= 5 and chunk:
                continue
            block, buf = buf[:cut], buf[cut:]
            for m in finditer(block):
                before, letters, rownum, after, inner = m.groups()
                if not inner:
                    continue
                r = int(rownum) - 1
                c = col_cache.get(letters)
                if c is None:
                    c = _col(letters)
                keep = offset <= r < end_row and c < MAX_COLS
                if quick and r >= end_row:
                    stopped = True
                    break
                if not keep and texts is None:
                    if r > last_row:
                        last_row = r
                    if c > max_col:
                        max_col = c
                    continue
                if ' t="' in before or ' t="' in after:
                    attrs = before + after
                    t = attrs.split(' t="', 1)[1].split('"', 1)[0]
                else:
                    t = "n"
                if t == "s":
                    vm = v_search(inner)
                    raw = vm.group(1) if vm else ""
                    val = shared[int(raw)] if raw.isdigit() and int(raw) < n_shared else ""
                elif t == "inlineStr":
                    val = "".join(_T_RE.findall(inner))
                    if "&" in val:
                        val = unescape(val)
                else:
                    vm = v_search(inner)
                    raw = vm.group(1) if vm else ""
                    if not raw:
                        continue
                    if t == "n":
                        if date_styles and (' s="' in before or ' s="' in after):
                            attrs = before + after
                            style = int(attrs.split(' s="', 1)[1].split('"', 1)[0])
                        else:
                            style = -1
                        if style in date_styles:
                            try:
                                val = excel_date(float(raw), date1904)
                            except ValueError:
                                val = raw
                        elif raw.isdigit():
                            val = raw
                        else:
                            try:
                                val = format_number(float(raw))
                            except ValueError:
                                val = raw
                    elif t == "b":
                        val = "TRUE" if raw == "1" else "FALSE"
                    else:
                        val = unescape(raw) if "&" in raw else raw
                if val == "":
                    continue
                if r > last_row:
                    last_row = r
                if c > max_col:
                    max_col = c
                if keep:
                    if r != current_r:
                        current_r = r
                        current_list = row_lists.get(r)
                        if current_list is None:
                            current_list = row_lists[r] = []
                    if len(current_list) <= c:
                        current_list.extend([""] * (c + 1 - len(current_list)))
                    current_list[c] = val
                    cell_count += 1
                    if cell_count >= MAX_CELLS:
                        end_row = r + 1  # cell cap: the preview ends after this row
                if texts is not None and chars <= MAX_TEXT_CHARS:
                    texts.append(val)
                    chars += len(val) + 1
            if not chunk:
                break
    return row_lists, last_row, max_col, chars, end_row - offset, stopped


def rows_result(name: str, row_lists: Dict[int, List[str]], total_rows: int, offset: int, limit: int,
                total_columns: int) -> Dict[str, Any]:
    """Same output as sheet_result, from rows that are already lists."""
    total = total_rows
    width = min(total_columns, MAX_COLS)
    end = min(total, offset + limit)
    empty = [""] * width
    rows = []
    for r in range(offset, end):
        row = row_lists.get(r)
        if row is None:
            rows.append(list(empty))
        elif len(row) < width:
            rows.append(row + [""] * (width - len(row)))
        else:
            rows.append(row[:width])
    return {
        "name": name,
        "columns": [column_letter(c) for c in range(width)],
        "rows": rows,
        "offset": offset,
        "total_rows": total,
        "total_columns": total_columns,
        "truncated": end < total or total_columns > MAX_COLS,
    }


def _xlsx(zf: zipfile.ZipFile, offset: int = 0, limit: int = MAX_ROWS,
          sheet_index: Optional[int] = None, with_text: bool = True, quick: bool = False) -> Dict[str, Any]:
    """quick: stop reading each sheet after the row window (the result is marked partial)."""
    wb = _read_xml(zf, "xl/workbook.xml")
    if wb is None:
        raise ValueError("xl/workbook.xml is missing")
    rels = _rels(zf, "xl/workbook.xml")
    pr = wb.find(f"{S}workbookPr")
    date1904 = pr is not None and pr.get("date1904") in ("1", "true")

    shared: List[str] = []
    sst = _read_xml(zf, "xl/sharedStrings.xml")
    if sst is not None:
        for si in sst.findall(f"{S}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{S}t")))

    # Which cell styles show dates
    date_styles: set = set()
    styles = _read_xml(zf, "xl/styles.xml")
    if styles is not None:
        custom = {int(f.get("numFmtId", "0")): f.get("formatCode", "") for f in styles.iter(f"{S}numFmt")}
        xfs = styles.find(f"{S}cellXfs")
        for i, xf in enumerate(list(xfs) if xfs is not None else []):
            fid = int(xf.get("numFmtId", "0"))
            if fid in _DATE_FORMAT_IDS or (fid in custom and is_date_format(custom[fid])):
                date_styles.add(i)

    sheets: List[Dict[str, Any]] = []
    texts: List[str] = []
    text_chars = 0
    for number, sheet in enumerate(wb.iter(f"{S}sheet")):
        if number >= MAX_SHEETS:
            break
        if sheet_index is not None and number != sheet_index:
            continue
        name = sheet.get("name", f"Sheet{number + 1}")
        part = rels.get(sheet.get(f"{R}id", ""), "")
        if not part or part not in zf.namelist():
            continue
        if zf.getinfo(part).file_size > MAX_XML_BYTES * 4:
            sheets.append(sheet_result(name, {(0, 0): "This sheet is too large to preview."}, 1))
            continue
        want_text = with_text and sheet_index is None
        fast = _xlsx_sheet_fast(zf, part, shared, date_styles, date1904, offset, limit,
                                texts if want_text else None, quick)
        if fast is not None:
            fast_cells, fast_last_row, fast_max_col, fast_chars, fast_limit, stopped = fast
            text_chars += fast_chars
            result = rows_result(name, fast_cells, fast_last_row + 1, offset, fast_limit, fast_max_col + 1)
            result["partial"] = stopped
            sheets.append(result)
            continue
        cells: Dict[Tuple[int, int], str] = {}
        last_row = -1
        max_col = -1
        row_index = -1
        with zf.open(part) as fh:
            for _, el in ET.iterparse(fh, events=("end",)):
                if el.tag != f"{S}row":
                    continue
                row_index = int(el.get("r", row_index + 2)) - 1
                # The preview keeps one row window; all rows go into the search text
                keep = offset <= row_index < offset + limit
                if not keep and (not want_text or text_chars > MAX_TEXT_CHARS):
                    if len(el):
                        last_row = max(last_row, row_index)
                        ref = el[-1].get("r")
                        if ref:
                            max_col = max(max_col, _column_index(ref))
                    el.clear()
                    continue
                col_index = -1
                for c in el.findall(f"{S}c"):
                    ref = c.get("r")
                    col_index = _column_index(ref) if ref else col_index + 1
                    t = c.get("t", "n")
                    v = c.find(f"{S}v")
                    raw = v.text if v is not None and v.text is not None else ""
                    if t == "s" and raw.isdigit():
                        val = shared[int(raw)] if int(raw) < len(shared) else ""
                    elif t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter(f"{S}t"))
                    elif t == "b":
                        val = "TRUE" if raw == "1" else "FALSE"
                    elif t in ("str", "e"):
                        val = raw
                    elif raw:
                        try:
                            num = float(raw)
                            style = int(c.get("s", "0"))
                            val = excel_date(num, date1904) if style in date_styles else format_number(num)
                        except ValueError:
                            val = raw
                    else:
                        val = ""
                    if val != "":
                        last_row = max(last_row, row_index)
                        max_col = max(max_col, col_index)
                        if keep and col_index < MAX_COLS:
                            cells[(row_index, col_index)] = val
                            if len(cells) >= MAX_CELLS:
                                # Cell cap: the preview ends after this row
                                limit = row_index + 1 - offset
                        if want_text:
                            texts.append(val)
                            text_chars += len(val) + 1
                el.clear()
        sheets.append(sheet_result(name, cells, last_row + 1, offset, limit, max_col + 1))
    return {"sheets": sheets, "text": "\n".join(s["name"] for s in sheets) + "\n" + " ".join(texts)}


# -- PowerPoint ------------------------------------------------------------------------

def _pptx(zf: zipfile.ZipFile) -> Dict[str, Any]:
    pres = _read_xml(zf, "ppt/presentation.xml")
    if pres is None:
        raise ValueError("ppt/presentation.xml is missing")
    rels = _rels(zf, "ppt/presentation.xml")
    slides: List[Dict[str, Any]] = []
    texts: List[str] = []
    lst = pres.find(f"{P}sldIdLst")
    for number, sid in enumerate(list(lst) if lst is not None else [], start=1):
        part = rels.get(sid.get(f"{R}id", ""), "")
        root = _read_xml(zf, part) if part else None
        if root is None:
            continue
        title = ""
        paragraphs: List[Dict[str, Any]] = []
        for sp in root.iter(f"{P}sp"):
            ph = sp.find(f"{P}nvSpPr/{P}nvPr/{P}ph")
            ph_type = ph.get("type", "body") if ph is not None else ""
            body = sp.find(f"{P}txBody")
            if body is None:
                continue
            lines = []
            for para in body.findall(f"{A}p"):
                text = "".join(t.text or "" for t in para.iter(f"{A}t")).strip()
                if not text:
                    continue
                ppr = para.find(f"{A}pPr")
                level = int(ppr.get("lvl", "0")) if ppr is not None else 0
                lines.append({"text": text, "level": level})
            if ph_type in ("title", "ctrTitle") and lines and not title:
                title = " ".join(l["text"] for l in lines)
            else:
                paragraphs.extend(lines)
        for tbl in root.iter(f"{A}tbl"):
            for tr in tbl.iter(f"{A}tr"):
                row = [" ".join(t.text or "" for t in tc.iter(f"{A}t")).strip() for tc in tr.iter(f"{A}tc")]
                if any(row):
                    paragraphs.append({"text": " | ".join(row), "level": 0})
        images = sum(1 for _ in root.iter(f"{P}pic"))
        slides.append({"number": number, "title": title, "paragraphs": paragraphs, "images": images})
        texts.append(title)
        texts.extend(p["text"] for p in paragraphs)
    return {"slides": slides, "text": "\n".join(texts)}
