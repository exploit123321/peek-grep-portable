"""Microsoft Office previews and text, with the standard library only.

New formats (.docx, .xlsx, .xlsm, .pptx) are ZIP files with XML inside: this module.
Old binary formats (.doc, .xls, .ppt): see legacy_office.py.

Every reader returns a dict with "text" (for the search index) and preview data:
    document  -> {"html": str}
    workbook  -> {"sheets": [{"name", "columns", "rows", "total_rows", "total_columns", "truncated"}]}
    slides    -> {"slides": [{"number", "title", "paragraphs": [{"text", "level"}], "images"}]}
"""

import html
import posixpath
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
MAX_ROWS = 300
MAX_COLS = 60
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


def extract_office(path: str, ext: str) -> Dict[str, Any]:
    """Preview data and text for any supported Office file (new or old format)."""
    ext = ext.lower()
    if ext in (".doc", ".xls", ".ppt"):
        from app.indexer import legacy_office
        return legacy_office.extract(path, ext)
    with zipfile.ZipFile(path) as zf:
        if ext in WORD_EXTENSIONS:
            return _docx(zf)
        if ext in EXCEL_EXTENSIONS:
            return _xlsx(zf)
        if ext in POWERPOINT_EXTENSIONS:
            return _pptx(zf)
    raise ValueError(f"Not an Office file: {ext}")


def extract_office_text(path: str, ext: str) -> Optional[str]:
    try:
        text = extract_office(path, ext).get("text") or ""
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


def sheet_result(name: str, cells: Dict[Tuple[int, int], str], total_rows: int) -> Dict[str, Any]:
    """Grid with Excel letters as headers. cells: (row, col) -> text, both 0-based."""
    if not cells:
        return {"name": name, "columns": [], "rows": [], "total_rows": 0, "total_columns": 0, "truncated": False}
    max_row = min(max(r for r, _ in cells), MAX_ROWS - 1)
    max_col = min(max(c for _, c in cells), MAX_COLS - 1)
    rows = [[cells.get((r, c), "") for c in range(max_col + 1)] for r in range(max_row + 1)]
    return {
        "name": name,
        "columns": [column_letter(c) for c in range(max_col + 1)],
        "rows": rows,
        "total_rows": max(total_rows, max_row + 1),
        "total_columns": max(c for _, c in cells) + 1,
        "truncated": total_rows > MAX_ROWS or max(c for _, c in cells) >= MAX_COLS,
    }


def _xlsx(zf: zipfile.ZipFile) -> Dict[str, Any]:
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
    for sheet in wb.iter(f"{S}sheet"):
        if len(sheets) >= MAX_SHEETS:
            break
        name = sheet.get("name", f"Sheet{len(sheets) + 1}")
        part = rels.get(sheet.get(f"{R}id", ""), "")
        if not part or part not in zf.namelist():
            continue
        if zf.getinfo(part).file_size > MAX_XML_BYTES * 4:
            sheets.append(sheet_result(name, {(0, 0): "This sheet is too large to preview."}, 1))
            continue
        cells: Dict[Tuple[int, int], str] = {}
        total_rows = 0
        row_index = -1
        with zf.open(part) as fh:
            for _, el in ET.iterparse(fh, events=("end",)):
                if el.tag != f"{S}row":
                    continue
                total_rows += 1
                row_index = int(el.get("r", row_index + 2)) - 1
                # All rows go into the search text; the preview keeps the first MAX_ROWS
                keep = row_index < MAX_ROWS
                if not keep and text_chars > MAX_TEXT_CHARS:
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
                        if keep and col_index < MAX_COLS:
                            cells[(row_index, col_index)] = val
                        texts.append(val)
                        text_chars += len(val) + 1
                el.clear()
        sheets.append(sheet_result(name, cells, total_rows))
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
