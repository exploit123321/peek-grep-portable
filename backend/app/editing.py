"""Edit files from Quick Look: text, CSV, Excel (.xlsx/.xlsm), and Word (.docx).

Safety rules for every save:
- the file must be inside a working folder (checked by the router);
- the file must not have changed on disk since it was loaded (mtime_ns check);
- the old version is copied to data\\backups first;
- the new content goes to a temporary file in the same folder, then replaces the original
  (a file that is open in Excel or Word cannot be replaced, so the save fails safely).

Old binary formats (.doc, .xls, .ppt) are not editable: writing them back would mean
rebuilding their internal structure, with a high risk of damage.
"""

import csv
import io
import os
import re
import shutil
import tempfile
import threading
import time
import zipfile
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

from app.config import DATA_DIR
from app.indexer.office import (
    MAX_COLS,
    MAX_ROWS,
    _column_index,
    _rels,
    column_letter,
    extract_office,
    extract_office_preview,
)
from app.indexer.parsers import DELIMITERS, TEXT_EXTENSIONS, delimiter_name, detect_delimiter

MAX_EDIT_BYTES = 5 * 1024 * 1024
MAX_CSV_ROWS = 50_000
BACKUP_DIR = DATA_DIR / "backups"
MAX_BACKUPS = 200

CSV_EXTENSIONS = {".csv", ".tsv", ".tab"}
XLSX_EXTENSIONS = {".xlsx", ".xlsm"}
DOCX_EXTENSIONS = {".docx", ".docm"}

S_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S = "{" + S_NS + "}"
W = "{" + W_NS + "}"

_xml_lock = threading.Lock()  # ElementTree's prefix registry is global


class EditError(Exception):
    """A save or load that must not happen. status is the HTTP status code."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def edit_kind(ext: str) -> Optional[str]:
    ext = ext.lower()
    if ext in CSV_EXTENSIONS:
        return "csv"
    if ext in XLSX_EXTENSIONS:
        return "workbook"
    if ext in DOCX_EXTENSIONS:
        return "document"
    if ext in TEXT_EXTENSIONS:
        return "text"
    return None


# -- common ------------------------------------------------------------------------

def _stat(path: str) -> int:
    return os.stat(path).st_mtime_ns


def _check_unchanged(path: str, mtime_ns: int) -> None:
    if _stat(path) != int(mtime_ns):
        raise EditError("The file changed on disk after you opened it. Close the editor and open it again.", 409)


def _backup(path: str) -> str:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"{stamp}_{os.path.basename(path)}"
    n = 1
    while target.exists():
        target = BACKUP_DIR / f"{stamp}-{n}_{os.path.basename(path)}"
        n += 1
    shutil.copy2(path, target)
    backups = sorted(BACKUP_DIR.iterdir(), key=lambda p: p.stat().st_mtime)
    for old in backups[:-MAX_BACKUPS]:
        try:
            old.unlink()
        except OSError:
            pass
    return str(target)


def _replace(path: str, write: Callable[[str], None]) -> None:
    """Write through a temporary file in the same folder, then replace the original."""
    folder = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".peekgrep-", suffix=".tmp", dir=folder)
    os.close(fd)
    try:
        write(tmp)
        try:
            shutil.copymode(path, tmp)
        except OSError:
            pass
        for attempt in range(3):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 2:
                    raise EditError("The file is open in another program (for example Excel or Word). "
                                    "Close it there and save again.", 423)
                time.sleep(0.3)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _write_bytes(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)


def _read_limited(path: str) -> bytes:
    size = os.path.getsize(path)
    if size > MAX_EDIT_BYTES:
        raise EditError(f"The file is larger than {MAX_EDIT_BYTES // (1024 * 1024)} MB. Open it in its own app to edit it.", 413)
    with open(path, "rb") as f:
        return f.read()


def decode_text(raw: bytes) -> Tuple[str, str, str]:
    """Return (text with \\n line ends, encoding, newline). Raises EditError for binary data."""
    if raw.startswith(b"\xef\xbb\xbf"):
        enc = "utf-8-sig"
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        enc = "utf-16"
    else:
        if b"\x00" in raw[:8192]:
            raise EditError("This file has binary data and cannot be edited as text.", 415)
        try:
            raw.decode("utf-8")
            enc = "utf-8"
        except UnicodeDecodeError:
            enc = "cp1252"
            try:
                raw.decode("cp1252")
            except UnicodeDecodeError:
                enc = "latin-1"
    text = raw.decode(enc)
    newline = "\r\n" if "\r\n" in text else ("\r" if "\r" in text and "\n" not in text else "\n")
    return text.replace("\r\n", "\n").replace("\r", "\n"), enc, newline


def _encode_text(text: str, enc: str, newline: str) -> bytes:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if newline != "\n":
        text = text.replace("\n", newline)
    try:
        return text.encode(enc)
    except UnicodeEncodeError as e:
        raise EditError(f"A character cannot be saved in this file's encoding ({enc}): {e.object[e.start:e.end]!r}", 422)


# -- load --------------------------------------------------------------------------

def load(path: str, ext: str) -> Dict[str, Any]:
    kind = edit_kind(ext)
    if kind is None:
        if ext.lower() in (".doc", ".xls", ".ppt"):
            raise EditError("Old Office formats cannot be edited here. Use Open to edit the file in its own app.", 415)
        raise EditError("This file type cannot be edited here.", 415)
    mtime_ns = _stat(path)
    base: Dict[str, Any] = {"kind": kind, "mtime_ns": str(mtime_ns)}

    if kind == "text":
        text, enc, newline = decode_text(_read_limited(path))
        return {**base, "text": text, "encoding": enc, "newline": newline}

    if kind == "csv":
        text, enc, newline = decode_text(_read_limited(path))
        default = "\t" if ext.lower() in (".tsv", ".tab") else ","
        sep = detect_delimiter(text, default=default)
        rows = list(csv.reader(io.StringIO(text), delimiter=sep))
        if len(rows) > MAX_CSV_ROWS:
            raise EditError(f"The file has more than {MAX_CSV_ROWS:,} rows. Edit it in its own app or as text.", 413)
        return {**base, "text": text, "rows": rows, "delimiter": delimiter_name(sep), "encoding": enc, "newline": newline}

    if kind == "workbook":
        if os.path.getsize(path) > MAX_EDIT_BYTES * 4:
            raise EditError("The workbook is too large to edit here.", 413)
        preview = extract_office_preview(path, ext)
        formulas = _xlsx_formula_cells(path)
        # Copies: the preview data is cached and shared
        sheets = [{**sheet, "formulas": sorted(formulas.get(sheet["name"], []))} for sheet in preview["sheets"]]
        return {**base, "sheets": sheets}

    if kind == "document":
        if os.path.getsize(path) > MAX_EDIT_BYTES * 4:
            raise EditError("The document is too large to edit here.", 413)
        with zipfile.ZipFile(path) as zf:
            root = ET.fromstring(zf.read("word/document.xml"))
        return {**base, "paragraphs": _docx_paragraphs(root)}

    raise EditError("This file type cannot be edited here.", 415)


# -- save --------------------------------------------------------------------------

def save(path: str, ext: str, mtime_ns: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    kind = edit_kind(ext)
    if kind is None:
        raise EditError("This file type cannot be edited here.", 415)
    _check_unchanged(path, mtime_ns)

    if kind == "text" or (kind == "csv" and payload.get("text") is not None):
        raw = _read_limited(path)
        _, enc, newline = decode_text(raw)
        data = _encode_text(str(payload.get("text", "")), enc, newline)
        backup = _backup(path)
        _replace(path, lambda tmp: _write_bytes(tmp, data))

    elif kind == "csv":
        raw = _read_limited(path)
        text, enc, newline = decode_text(raw)
        sep = DELIMITERS.get(str(payload.get("delimiter", "")), None) or detect_delimiter(text)
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise EditError("No rows to save.")
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=sep, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        for row in rows:
            writer.writerow(["" if c is None else str(c) for c in row])
        out = buf.getvalue()
        if not text.endswith("\n") and out.endswith("\n"):
            out = out[:-1]
        data = _encode_text(out, enc, newline)
        backup = _backup(path)
        _replace(path, lambda tmp: _write_bytes(tmp, data))

    elif kind == "workbook":
        changes = payload.get("changes") or {}
        backup = _backup(path)
        _replace(path, lambda tmp: _xlsx_save(path, tmp, changes))

    elif kind == "document":
        changes = payload.get("changes") or {}
        backup = _backup(path)
        _replace(path, lambda tmp: _docx_save(path, tmp, changes))

    else:
        raise EditError("This file type cannot be edited here.", 415)

    return {"success": True, "mtime_ns": str(_stat(path)), "backup": backup}


# -- XML that keeps Office happy ----------------------------------------------------

_ATTR_RE = re.compile(r'([\w:.-]+)\s*=\s*"([^"]*)"')


def _parse_keep_prefixes(raw: bytes) -> ET.Element:
    """Parse XML so that serialization uses the original namespace prefixes."""
    for _, (prefix, uri) in ET.iterparse(io.BytesIO(raw), events=("start-ns",)):
        try:
            ET.register_namespace(prefix, uri)
        except ValueError:
            pass
    return ET.fromstring(raw)


def _serialize(root: ET.Element, original: bytes) -> bytes:
    """Serialize, then add back root declarations that ElementTree dropped (mc:Ignorable needs them)."""
    out = ET.tostring(root, encoding="unicode")
    orig_text = original.decode("utf-8", errors="replace")
    m_orig = re.search(r"<(?!\?)([^\s>/!]+)([^>]*)>", orig_text)
    m_new = re.match(r"<([^\s>/]+)([^>]*?)(/?)>", out)
    if m_orig and m_new:
        attrs = dict(_ATTR_RE.findall(m_new.group(2)))
        for k, v in _ATTR_RE.findall(m_orig.group(2)):
            attrs.setdefault(k, v)
        tag = "<" + m_new.group(1) + "".join(f' {k}="{v}"' for k, v in attrs.items()) + m_new.group(3) + ">"
        out = tag + out[m_new.end():]
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n' + out).encode("utf-8")


def _rewrite_zip(src: str, dst: str, replaced: Dict[str, bytes], removed: Tuple[str, ...] = ()) -> None:
    """Copy a ZIP, with some parts replaced or removed (order and compression kept)."""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            if info.filename in removed:
                continue
            data = replaced.get(info.filename)
            if data is None:
                data = zin.read(info.filename)
            zout.writestr(info, data, compress_type=info.compress_type)


# -- Excel --------------------------------------------------------------------------

def _sheet_parts(zf: zipfile.ZipFile) -> Dict[str, str]:
    """Sheet name -> part name."""
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = _rels(zf, "xl/workbook.xml")
    rid = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    return {s.get("name", ""): rels.get(s.get(rid, ""), "") for s in wb.iter(f"{S}sheet")}


def _xlsx_formula_cells(path: str) -> Dict[str, List[List[int]]]:
    result: Dict[str, List[List[int]]] = {}
    with zipfile.ZipFile(path) as zf:
        for name, part in _sheet_parts(zf).items():
            if not part or part not in zf.namelist():
                continue
            cells: List[List[int]] = []
            with zf.open(part) as fh:
                for _, el in ET.iterparse(fh, events=("end",)):
                    if el.tag == f"{S}c" and el.find(f"{S}f") is not None:
                        ref = el.get("r", "")
                        row = int(re.sub(r"\D", "", ref) or 0) - 1
                        col = _column_index(ref)
                        if 0 <= row < MAX_ROWS and col < MAX_COLS:
                            cells.append([row, col])
                    elif el.tag == f"{S}row":
                        el.clear()
            result[name] = cells
    return result


def _date_to_serial(text: str) -> Optional[float]:
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            value = datetime.strptime(text, fmt)
        except ValueError:
            continue
        delta = value - datetime(1899, 12, 30)
        return delta.days + delta.seconds / 86400
    return None


def _set_cell(c: ET.Element, value: str, is_date_cell: bool) -> None:
    """Write a value into a cell element; keeps the style (s) attribute."""
    for child in list(c):
        c.remove(child)
    c.attrib.pop("t", None)
    if value == "":
        return
    number: Optional[float] = None
    if is_date_cell:
        number = _date_to_serial(value)
    if number is None and re.fullmatch(r"-?\d+(\.\d+)?([eE][-+]?\d+)?", value.strip()):
        number = float(value)
    if number is not None:
        v = ET.SubElement(c, f"{S}v")
        v.text = str(int(number)) if number == int(number) and abs(number) < 1e15 else repr(number)
    elif value.upper() in ("TRUE", "FALSE"):
        c.set("t", "b")
        ET.SubElement(c, f"{S}v").text = "1" if value.upper() == "TRUE" else "0"
    else:
        c.set("t", "inlineStr")
        is_ = ET.SubElement(c, f"{S}is")
        t = ET.SubElement(is_, f"{S}t")
        t.text = value
        if value != value.strip():
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def _xlsx_save(src: str, dst: str, changes: Dict[str, Dict[str, str]]) -> None:
    """changes: sheet name -> {"row,col": value} (0-based)."""
    preview = extract_office_preview(src, os.path.splitext(src)[1])
    date_cells: Dict[str, set] = {}
    replaced: Dict[str, bytes] = {}
    removed: Tuple[str, ...] = ()
    formula_overwritten = False
    with zipfile.ZipFile(src) as zf, _xml_lock:
        parts = _sheet_parts(zf)
        for sheet_name, cell_changes in changes.items():
            part = parts.get(sheet_name)
            if not part or part not in zf.namelist() or not cell_changes:
                continue
            # Cells shown as dates in the preview get date input converted back to Excel numbers
            sheet_preview = next((s for s in preview["sheets"] if s["name"] == sheet_name), None)
            if sheet_preview:
                date_cells[sheet_name] = {
                    (r, c) for r, row in enumerate(sheet_preview["rows"]) for c, v in enumerate(row)
                    if re.fullmatch(r"\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?", v or "")
                }
            raw = zf.read(part)
            root = _parse_keep_prefixes(raw)
            sheet_data = root.find(f"{S}sheetData")
            if sheet_data is None:
                continue
            rows = {int(r.get("r", "0")): r for r in sheet_data.findall(f"{S}row")}
            for key, value in cell_changes.items():
                r0, c0 = (int(x) for x in key.split(","))
                rnum, ref = r0 + 1, f"{column_letter(c0)}{r0 + 1}"
                row = rows.get(rnum)
                if row is None:
                    row = ET.Element(f"{S}row", {"r": str(rnum)})
                    later = [i for i, el in enumerate(list(sheet_data)) if int(el.get("r", "0")) > rnum]
                    sheet_data.insert(later[0] if later else len(sheet_data), row)
                    rows[rnum] = row
                cell = next((c for c in row.findall(f"{S}c") if c.get("r") == ref), None)
                if cell is None:
                    cell = ET.Element(f"{S}c", {"r": ref})
                    cols = [_column_index(c.get("r", "A")) for c in row.findall(f"{S}c")]
                    pos = next((i for i, col in enumerate(cols) if col > c0), len(cols))
                    row.insert(pos, cell)
                if cell.find(f"{S}f") is not None:
                    formula_overwritten = True
                _set_cell(cell, str(value), (r0, c0) in date_cells.get(sheet_name, set()))
            replaced[part] = _serialize(root, raw)

        if formula_overwritten and "xl/calcChain.xml" in zf.namelist():
            # The calculation chain lists formula cells; Excel rebuilds it when it is missing
            removed = ("xl/calcChain.xml",)
            ct_raw = zf.read("[Content_Types].xml")
            ct = _parse_keep_prefixes(ct_raw)
            for el in list(ct):
                if el.get("PartName") == "/xl/calcChain.xml":
                    ct.remove(el)
            replaced["[Content_Types].xml"] = _serialize(ct, ct_raw)
            rels_name = "xl/_rels/workbook.xml.rels"
            rels_raw = zf.read(rels_name)
            rels = _parse_keep_prefixes(rels_raw)
            for el in list(rels):
                if el.get("Target", "").endswith("calcChain.xml"):
                    rels.remove(el)
            replaced[rels_name] = _serialize(rels, rels_raw)

        # Let Excel recalculate formulas that use the changed cells
        wb_raw = zf.read("xl/workbook.xml")
        wb = _parse_keep_prefixes(wb_raw)
        calc = wb.find(f"{S}calcPr")
        if calc is None:
            # Schema order: calcPr follows sheets, functionGroups, externalReferences, definedNames
            calc = ET.Element(f"{S}calcPr")
            names = [f"{S}sheets", f"{S}functionGroups", f"{S}externalReferences", f"{S}definedNames"]
            after = [i for i, el in enumerate(list(wb)) if el.tag in names]
            wb.insert(after[-1] + 1 if after else len(wb), calc)
        calc.set("fullCalcOnLoad", "1")
        replaced["xl/workbook.xml"] = _serialize(wb, wb_raw)

    _rewrite_zip(src, dst, replaced, removed)


# -- Word ---------------------------------------------------------------------------

# Paragraphs with these parts are locked: a plain-text rewrite would lose them
_LOCKING = {f"{W}drawing", f"{W}pict", f"{W}object", f"{W}fldChar", f"{W}instrText", f"{W}fldSimple",
            f"{W}footnoteReference", f"{W}endnoteReference", f"{W}sym", f"{W}txbxContent",
            f"{W}hyperlink", f"{W}ins", f"{W}del", f"{W}moveFrom", f"{W}moveTo", f"{W}commentReference",
            f"{W}smartTag", f"{W}customXml", f"{W}sdt"}
# Range markers stay in an edited paragraph
_MARKERS = {f"{W}bookmarkStart", f"{W}bookmarkEnd", f"{W}commentRangeStart", f"{W}commentRangeEnd",
            f"{W}permStart", f"{W}permEnd"}


def _docx_body_paragraphs(root: ET.Element) -> List[ET.Element]:
    """Paragraphs of the body and its tables, in document order (not text boxes)."""
    body = root.find(f"{W}body")
    result: List[ET.Element] = []

    def walk(el: ET.Element) -> None:
        for child in el:
            if child.tag == f"{W}p":
                result.append(child)
            elif child.tag in (f"{W}tbl", f"{W}tr", f"{W}tc", f"{W}sdt", f"{W}sdtContent"):
                walk(child)

    if body is not None:
        walk(body)
    return result


def _paragraph_text(p: ET.Element) -> str:
    parts: List[str] = []
    for r in p.iter(f"{W}r"):
        for node in r:
            if node.tag == f"{W}t":
                parts.append(node.text or "")
            elif node.tag == f"{W}tab":
                parts.append("\t")
            elif node.tag in (f"{W}br", f"{W}cr"):
                parts.append("\n")
    return "".join(parts)


def _docx_paragraphs(root: ET.Element) -> List[Dict[str, Any]]:
    result = []
    in_table = {id(p) for tbl in root.iter(f"{W}tbl") for p in tbl.iter(f"{W}p")}
    for i, p in enumerate(_docx_body_paragraphs(root)):
        style = ""
        ps = p.find(f"{W}pPr/{W}pStyle")
        if ps is not None:
            style = ps.get(f"{W}val", "")
        locked = any(el.tag in _LOCKING for el in p.iter())
        result.append({
            "id": i,
            "text": _paragraph_text(p),
            "style": style,
            "table": id(p) in in_table,
            "locked": locked,
        })
    return result


def _docx_set_text(p: ET.Element, text: str) -> None:
    """Replace the runs of a paragraph with one run that keeps the first run's format."""
    first_rpr = None
    first_run = p.find(f".//{W}r")
    if first_run is not None and first_run.find(f"{W}rPr") is not None:
        first_rpr = first_run.find(f"{W}rPr")
    for child in list(p):
        if child.tag != f"{W}pPr" and child.tag not in _MARKERS:
            p.remove(child)
    run = ET.SubElement(p, f"{W}r")
    if first_rpr is not None:
        run.append(first_rpr)
    lines = text.replace("\r\n", "\n").split("\n")
    for k, line in enumerate(lines):
        if k:
            ET.SubElement(run, f"{W}br")
        chunks = line.split("\t")
        for j, chunk in enumerate(chunks):
            if j:
                ET.SubElement(run, f"{W}tab")
            if chunk:
                t = ET.SubElement(run, f"{W}t")
                t.text = chunk
                t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def _docx_save(src: str, dst: str, changes: Dict[str, str]) -> None:
    """changes: paragraph id -> new text."""
    with zipfile.ZipFile(src) as zf, _xml_lock:
        raw = zf.read("word/document.xml")
        root = _parse_keep_prefixes(raw)
        paragraphs = _docx_body_paragraphs(root)
        for key, text in changes.items():
            i = int(key)
            if i < 0 or i >= len(paragraphs):
                raise EditError("The document changed. Close the editor and open it again.", 409)
            p = paragraphs[i]
            if any(el.tag in _LOCKING for el in p.iter()):
                raise EditError("A paragraph with a picture or field cannot be edited here.", 422)
            _docx_set_text(p, str(text))
        data = _serialize(root, raw)
    _rewrite_zip(src, dst, {"word/document.xml": data})
