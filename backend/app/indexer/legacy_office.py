"""Old binary Office formats (Word 97-2003 .doc, Excel 97-2003 .xls, PowerPoint 97-2003 .ppt).

These files are OLE2 Compound Files: a small FAT file system inside one file. This module
has a minimal Compound File reader and simple text readers for the three formats:

    .doc -> paragraphs from the piece table (no formatting)
    .xls -> cell values per sheet (BIFF8), with dates
    .ppt -> slide titles and body text

The output has the same shape as office.py. Encrypted files raise ValueError.
"""

import html
import struct
from typing import Any, Dict, List, Optional, Tuple

from app.indexer.office import (
    MAX_CELLS,
    MAX_COLS,
    MAX_ROWS,
    MAX_SHEETS,
    _DATE_FORMAT_IDS,
    excel_date,
    format_number,
    is_date_format,
    paragraphs_html,
    sheet_result,
    table_html,
)

MAX_FILE_BYTES = 200 * 1024 * 1024
ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF


# -- Compound File (OLE2) reader ----------------------------------------------------

class CompoundFile:
    """Read-only access to the streams of an OLE2 Compound File."""

    SIGNATURE = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"

    def __init__(self, data: bytes):
        if len(data) < 512 or data[:8] != self.SIGNATURE:
            raise ValueError("Not an OLE2 Compound File")
        self.data = data
        self.sector_size = 1 << struct.unpack_from("<H", data, 0x1E)[0]
        self.mini_size = 1 << struct.unpack_from("<H", data, 0x20)[0]
        (num_fat, first_dir, _, self.cutoff, first_minifat, num_minifat,
         first_difat, num_difat) = struct.unpack_from("<IIIIIIII", data, 0x2C)

        # FAT sector numbers: 109 in the header, the rest in the DIFAT chain
        fat_sectors = [s for s in struct.unpack_from("<109I", data, 0x4C) if s < ENDOFCHAIN]
        per = self.sector_size // 4 - 1
        sec, seen = first_difat, 0
        while sec < ENDOFCHAIN and seen < num_difat + 1:
            values = struct.unpack_from(f"<{per + 1}I", self._sector(sec))
            fat_sectors.extend(v for v in values[:per] if v < ENDOFCHAIN)
            sec, seen = values[per], seen + 1
        fat_sectors = fat_sectors[:max(num_fat, 0) or len(fat_sectors)]
        self.fat: List[int] = []
        for s in fat_sectors:
            self.fat.extend(struct.unpack_from(f"<{self.sector_size // 4}I", self._sector(s)))

        self.entries = self._read_directory(first_dir)
        root = self.entries[0] if self.entries else None
        self.mini_stream = self._chain_bytes(root["start"], root["size"]) if root else b""
        self.minifat: List[int] = []
        if num_minifat and first_minifat < ENDOFCHAIN:
            raw = self._chain_bytes(first_minifat, None)
            self.minifat = list(struct.unpack_from(f"<{len(raw) // 4}I", raw))

    def _sector(self, n: int) -> bytes:
        start = (n + 1) * self.sector_size
        if start + self.sector_size > len(self.data):
            raise ValueError("Sector outside the file")
        return self.data[start:start + self.sector_size]

    def _chain(self, start: int, table: List[int]) -> List[int]:
        chain, sec = [], start
        while sec < ENDOFCHAIN:
            if sec >= len(table) or len(chain) > len(table):
                raise ValueError("Broken sector chain")
            chain.append(sec)
            sec = table[sec]
        return chain

    def _chain_bytes(self, start: int, size: Optional[int]) -> bytes:
        data = b"".join(self._sector(s) for s in self._chain(start, self.fat))
        return data if size is None else data[:size]

    def _read_directory(self, first_dir: int) -> List[Dict[str, Any]]:
        raw = self._chain_bytes(first_dir, None)
        entries = []
        for off in range(0, len(raw) - 127, 128):
            name_len = struct.unpack_from("<H", raw, off + 0x40)[0]
            kind = raw[off + 0x42]
            name = raw[off:off + max(0, name_len - 2)].decode("utf-16-le", errors="replace")
            start, size_lo, size_hi = struct.unpack_from("<III", raw, off + 0x74)
            size = size_lo if self.sector_size == 512 else size_lo | (size_hi << 32)
            entries.append({"name": name, "type": kind, "start": start, "size": size})
        return entries

    def stream(self, *names: str) -> Optional[bytes]:
        """Content of the first stream that has one of these names (case-insensitive)."""
        wanted = [n.lower() for n in names]
        for want in wanted:
            for e in self.entries:
                if e["type"] == 2 and e["name"].lower() == want:
                    if e["size"] < self.cutoff:
                        out = bytearray()
                        for s in self._chain(e["start"], self.minifat):
                            out += self.mini_stream[s * self.mini_size:(s + 1) * self.mini_size]
                        return bytes(out[:e["size"]])
                    return self._chain_bytes(e["start"], e["size"])
        return None


def extract(path: str, ext: str, offset: int = 0, limit: int = MAX_ROWS,
            sheet_index: Optional[int] = None) -> Dict[str, Any]:
    with open(path, "rb") as f:
        data = f.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("File is too large to preview")
    cf = CompoundFile(data)
    if ext == ".doc":
        return _doc(cf)
    if ext == ".xls":
        return _xls(cf, offset, limit, sheet_index)
    if ext == ".ppt":
        return _ppt(cf)
    raise ValueError(f"Unsupported format {ext}")


# -- Word 97-2003 -------------------------------------------------------------------

def _clean_word_text(text: str) -> str:
    """Keep field results, drop field codes and object markers, map Word control marks."""
    out: List[str] = []
    depth_code: List[bool] = []  # per open field: True while in the code part
    for ch in text:
        if ch == "\x13":
            depth_code.append(True)
            continue
        if ch == "\x14":
            if depth_code:
                depth_code[-1] = False
            continue
        if ch == "\x15":
            if depth_code:
                depth_code.pop()
            continue
        if any(depth_code):
            continue
        if ch == "\x07":
            out.append("\t")          # table cell end
        elif ch in "\x0b":
            out.append("\n")          # line break
        elif ch == "\x0c":
            out.append("\r")          # page or section break
        elif ch in "\r\t" or ch >= " ":
            out.append(ch)
    return "".join(out)


def _doc(cf: CompoundFile) -> Dict[str, Any]:
    word = cf.stream("WordDocument")
    if not word or len(word) < 64 or struct.unpack_from("<H", word, 0)[0] != 0xA5EC:
        raise ValueError("Not a Word 97-2003 document")
    flags = struct.unpack_from("<H", word, 0x0A)[0]
    if flags & 0x0100:
        raise ValueError("This document is encrypted")
    table = cf.stream("1Table" if flags & 0x0200 else "0Table")
    if table is None:
        raise ValueError("The table stream is missing")

    pos = 32
    csw = struct.unpack_from("<H", word, pos)[0]
    pos += 2 + csw * 2
    cslw = struct.unpack_from("<H", word, pos)[0]
    rglw = pos + 2
    ccp_text = struct.unpack_from("<I", word, rglw + 3 * 4)[0]
    pos = rglw + cslw * 4 + 2
    fc_clx, lcb_clx = struct.unpack_from("<II", word, pos + 33 * 8)

    # Find the piece table (Pcdt) in the Clx
    i, end = fc_clx, fc_clx + lcb_clx
    plc = None
    while i < end:
        kind = table[i]
        if kind == 0x01:
            i += 3 + struct.unpack_from("<h", table, i + 1)[0]
        elif kind == 0x02:
            size = struct.unpack_from("<I", table, i + 1)[0]
            plc = table[i + 5:i + 5 + size]
            break
        else:
            break
    if plc is None:
        raise ValueError("No text found")

    n = (len(plc) - 4) // 12
    cps = struct.unpack_from(f"<{n + 1}I", plc, 0)
    pieces: List[str] = []
    for k in range(n):
        cp_start, cp_end = cps[k], min(cps[k + 1], ccp_text)
        if cp_start >= ccp_text:
            break
        fc = struct.unpack_from("<I", plc, (n + 1) * 4 + k * 8 + 2)[0]
        count = cp_end - cp_start
        if fc & 0x40000000:
            off = (fc & ~0x40000000) // 2
            pieces.append(word[off:off + count].decode("cp1252", errors="replace"))
        else:
            pieces.append(word[fc:fc + count * 2].decode("utf-16-le", errors="replace"))
    text = _clean_word_text("".join(pieces))

    # Table text: each cell ends with a cell mark, each row with one more mark,
    # so after the mapping above a row boundary is two tabs
    paragraphs: List[Tuple[str, str]] = []
    rows: List[List[str]] = []
    for para in text.split("\r"):
        if para.endswith("\t"):
            for row in para.rstrip("\t").split("\t\t"):
                rows.append([html.escape(c).replace("\n", "<br>") for c in row.split("\t")])
            continue
        if rows:
            paragraphs.append(("raw", table_html(rows)))
            rows = []
        if para.strip():
            paragraphs.append(("p", html.escape(para).replace("\n", "<br>")))
    if rows:
        paragraphs.append(("raw", table_html(rows)))
    return {"html": paragraphs_html(paragraphs), "text": text.replace("\r", "\n")}


# -- Excel 97-2003 (BIFF8) ----------------------------------------------------------

def _records(data: bytes, start: int = 0):
    pos = start
    while pos + 4 <= len(data):
        rtype, size = struct.unpack_from("<HH", data, pos)
        yield rtype, data[pos + 4:pos + 4 + size], pos
        pos += 4 + size


class _ChunkReader:
    """Reads SST strings across CONTINUE records (a new option byte starts each chunk of characters)."""

    def __init__(self, chunks: List[bytes]):
        self.chunks = chunks
        self.ci = 0
        self.pos = 0

    def _ensure(self) -> None:
        while self.ci < len(self.chunks) and self.pos >= len(self.chunks[self.ci]):
            self.ci += 1
            self.pos = 0

    def bytes(self, n: int) -> bytes:
        out = bytearray()
        while n > 0:
            self._ensure()
            if self.ci >= len(self.chunks):
                raise ValueError("SST ends early")
            chunk = self.chunks[self.ci]
            take = min(n, len(chunk) - self.pos)
            out += chunk[self.pos:self.pos + take]
            self.pos += take
            n -= take
        return bytes(out)

    def chars(self, count: int, high: bool) -> str:
        out: List[str] = []
        while count > 0:
            if self.ci < len(self.chunks) and self.pos >= len(self.chunks[self.ci]):
                # Characters continue in the next CONTINUE record, after a new option byte
                self.ci += 1
                self.pos = 0
                if self.ci >= len(self.chunks):
                    break
                high = bool(self.chunks[self.ci][0] & 0x01)
                self.pos = 1
            chunk = self.chunks[self.ci]
            width = 2 if high else 1
            avail = (len(chunk) - self.pos) // width
            take = min(count, avail)
            raw = chunk[self.pos:self.pos + take * width]
            out.append(raw.decode("utf-16-le" if high else "latin-1", errors="replace"))
            self.pos += take * width
            count -= take
            if take == 0 and avail == 0 and self.pos < len(chunk):
                break
        return "".join(out)


def _xl_string(data: bytes, pos: int, len_bytes: int = 2) -> Tuple[str, int]:
    """XLUnicodeString (2-byte length) or ShortXLUnicodeString (1-byte length)."""
    count = data[pos] if len_bytes == 1 else struct.unpack_from("<H", data, pos)[0]
    pos += len_bytes
    flags = data[pos]
    pos += 1
    if flags & 0x01:
        return data[pos:pos + count * 2].decode("utf-16-le", errors="replace"), pos + count * 2
    return data[pos:pos + count].decode("latin-1", errors="replace"), pos + count


def _rk(value: int) -> float:
    if value & 0x02:
        num = float(value >> 2 if not value & 0x80000000 else (value >> 2) - (1 << 30))
    else:
        num = struct.unpack("<d", struct.pack("<Q", (value & 0xFFFFFFFC) << 32))[0]
    return num / 100 if value & 0x01 else num


def _xls(cf: CompoundFile, row_offset: int = 0, row_limit: int = MAX_ROWS,
         sheet_index: Optional[int] = None) -> Dict[str, Any]:
    data = cf.stream("Workbook", "Book")
    if not data:
        raise ValueError("Not an Excel 97-2003 workbook")

    sst: List[str] = []
    formats: Dict[int, str] = {}
    xf_formats: List[int] = []
    sheets_info: List[Tuple[str, int]] = []
    date1904 = False

    records = list(_records(data))
    i = 0
    while i < len(records):
        rtype, body, _ = records[i]
        if rtype == 0x002F:
            raise ValueError("This workbook is encrypted")
        if rtype == 0x0022 and len(body) >= 2:
            date1904 = struct.unpack_from("<H", body, 0)[0] == 1
        elif rtype == 0x041E and len(body) >= 5:
            ifmt = struct.unpack_from("<H", body, 0)[0]
            formats[ifmt] = _xl_string(body, 2)[0]
        elif rtype == 0x00E0 and len(body) >= 4:
            xf_formats.append(struct.unpack_from("<H", body, 2)[0])
        elif rtype == 0x0085 and len(body) >= 8:
            offset = struct.unpack_from("<I", body, 0)[0]
            sheet_type = body[5]
            name = _xl_string(body, 6, len_bytes=1)[0]
            if sheet_type == 0:
                sheets_info.append((name, offset))
        elif rtype == 0x00FC and len(body) >= 8:
            chunks = [body[8:]]
            j = i + 1
            while j < len(records) and records[j][0] == 0x003C:
                chunks.append(records[j][1])
                j += 1
            unique = struct.unpack_from("<I", body, 4)[0]
            reader = _ChunkReader(chunks)
            try:
                for _ in range(unique):
                    count, flags = struct.unpack("<HB", reader.bytes(3))
                    runs = struct.unpack("<H", reader.bytes(2))[0] if flags & 0x08 else 0
                    ext = struct.unpack("<i", reader.bytes(4))[0] if flags & 0x04 else 0
                    sst.append(reader.chars(count, bool(flags & 0x01)))
                    if runs:
                        reader.bytes(runs * 4)
                    if ext > 0:
                        reader.bytes(ext)
            except (ValueError, struct.error):
                pass  # keep the strings that were read
            i = j
            continue
        elif rtype == 0x000A:  # EOF of the globals
            break
        i += 1

    def is_date(ixfe: int) -> bool:
        if ixfe >= len(xf_formats):
            return False
        fid = xf_formats[ixfe]
        return fid in _DATE_FORMAT_IDS or (fid in formats and is_date_format(formats[fid]))

    def number(value: float, ixfe: int) -> str:
        return excel_date(value, date1904) if is_date(ixfe) else format_number(value)

    sheets: List[Dict[str, Any]] = []
    texts: List[str] = []
    for sheet_no, (name, stream_pos) in enumerate(sheets_info[:MAX_SHEETS]):
        if sheet_index is not None and sheet_no != sheet_index:
            continue
        cells: Dict[Tuple[int, int], str] = {}
        total_rows = 0
        last = [-1, -1]  # last used row and column
        window = [row_limit]  # rows kept for the preview (smaller when the cell cap is reached)
        pending_formula: Optional[Tuple[int, int]] = None

        def put(r: int, c: int, value: str) -> None:
            if value == "":
                return
            last[0], last[1] = max(last[0], r), max(last[1], c)
            if row_offset <= r < row_offset + window[0] and c < MAX_COLS:
                cells[(r, c)] = value
                if len(cells) >= MAX_CELLS:
                    window[0] = r + 1 - row_offset  # cell cap: the preview ends after this row
            if sheet_index is None:
                texts.append(value)

        for rtype, body, _ in _records(data, stream_pos):
            try:
                if rtype == 0x000A:
                    break
                if rtype == 0x0200 and len(body) >= 14:
                    total_rows = struct.unpack_from("<I", body, 4)[0]
                elif rtype == 0x00FD and len(body) >= 10:
                    r, c, _, idx = struct.unpack_from("<HHHI", body, 0)
                    put(r, c, sst[idx] if idx < len(sst) else "")
                elif rtype == 0x0204 and len(body) >= 9:
                    r, c, _ = struct.unpack_from("<HHH", body, 0)
                    put(r, c, _xl_string(body, 6)[0])
                elif rtype == 0x0203 and len(body) >= 14:
                    r, c, x = struct.unpack_from("<HHH", body, 0)
                    put(r, c, number(struct.unpack_from("<d", body, 6)[0], x))
                elif rtype == 0x027E and len(body) >= 10:
                    r, c, x, rk = struct.unpack_from("<HHHI", body, 0)
                    put(r, c, number(_rk(rk), x))
                elif rtype == 0x00BD and len(body) >= 6:
                    r, first = struct.unpack_from("<HH", body, 0)
                    count = (len(body) - 6) // 6
                    for k in range(count):
                        x, rk = struct.unpack_from("<HI", body, 4 + k * 6)
                        put(r, first + k, number(_rk(rk), x))
                elif rtype == 0x0205 and len(body) >= 8:
                    r, c, _, val, is_err = struct.unpack_from("<HHHBB", body, 0)
                    put(r, c, "#ERROR" if is_err else ("TRUE" if val else "FALSE"))
                elif rtype == 0x0006 and len(body) >= 14:
                    r, c, x = struct.unpack_from("<HHH", body, 0)
                    res = body[6:14]
                    if res[6:8] == b"\xff\xff":
                        if res[0] == 0:
                            pending_formula = (r, c)
                        elif res[0] == 1:
                            put(r, c, "TRUE" if res[2] else "FALSE")
                    else:
                        put(r, c, number(struct.unpack("<d", res)[0], x))
                elif rtype == 0x0207 and pending_formula and len(body) >= 3:
                    put(pending_formula[0], pending_formula[1], _xl_string(body, 0)[0])
                    pending_formula = None
            except (struct.error, IndexError):
                continue
        sheets.append(sheet_result(name, cells, max(total_rows, last[0] + 1), row_offset, window[0], last[1] + 1))
    return {"sheets": sheets, "text": "\n".join(n for n, _ in sheets_info) + "\n" + " ".join(texts)}


# -- PowerPoint 97-2003 -------------------------------------------------------------

RT_DOCUMENT = 0x03E8
RT_SLIDE = 0x03EE
RT_SLIDE_LIST = 0x0FF0
RT_SLIDE_PERSIST = 0x03F3
RT_TEXT_HEADER = 0x0F9F
RT_TEXT_CHARS = 0x0FA0
RT_TEXT_BYTES = 0x0FA8
RT_USER_EDIT = 0x0FF5
RT_PERSIST_DIR = 0x1772
RT_BLIP_REF = 0xF007  # one per picture in a slide drawing
TITLE_TYPES = {0, 6}


def _ppt_atoms(data: bytes, start: int, end: int, depth: int = 0):
    """Walk records; yields (type, instance, body_start, body_end) for every record."""
    pos = start
    while pos + 8 <= end:
        ver_inst, rtype, size = struct.unpack_from("<HHI", data, pos)
        body_start = pos + 8
        body_end = min(end, body_start + size)
        yield rtype, ver_inst >> 4, body_start, body_end
        if (ver_inst & 0x0F) == 0x0F and depth < 32:
            yield from _ppt_atoms(data, body_start, body_end, depth + 1)
        pos = body_start + size


def _ppt_record(data: bytes, offset: int) -> Tuple[int, int, int]:
    """(type, body_start, body_end) of the record at an offset."""
    _, rtype, size = struct.unpack_from("<HHI", data, offset)
    return rtype, offset + 8, min(len(data), offset + 8 + size)


def _ppt_text(data: bytes, rtype: int, a: int, b: int) -> str:
    raw = data[a:b]
    text = raw.decode("utf-16-le", errors="replace") if rtype == RT_TEXT_CHARS else raw.decode("latin-1", errors="replace")
    return text.replace("\x0b", "\n")


def _ppt_persist_directory(cf: CompoundFile, data: bytes) -> Tuple[Dict[int, int], int]:
    """persist id -> record offset (newest edit wins), and the document persist id."""
    current = cf.stream("Current User")
    if not current or len(current) < 20:
        return {}, 0
    edit_offset = struct.unpack_from("<I", current, 16)[0]
    directory: Dict[int, int] = {}
    doc_ref = 0
    seen = set()
    while 0 < edit_offset < len(data) and edit_offset not in seen:
        seen.add(edit_offset)
        rtype, a, b = _ppt_record(data, edit_offset)
        if rtype != RT_USER_EDIT or b - a < 20:
            break
        last_edit, persist_dir, doc_persist = struct.unpack_from("<III", data, a + 8)
        doc_ref = doc_ref or doc_persist
        dtype, da, db = _ppt_record(data, persist_dir)
        if dtype == RT_PERSIST_DIR:
            pos = da
            while pos + 4 <= db:
                head = struct.unpack_from("<I", data, pos)[0]
                first, count = head & 0xFFFFF, head >> 20
                pos += 4
                for k in range(count):
                    if pos + 4 > db:
                        break
                    directory.setdefault(first + k, struct.unpack_from("<I", data, pos)[0])
                    pos += 4
        edit_offset = last_edit
    return directory, doc_ref


def _ppt_collect(data: bytes, a: int, b: int, slide: Dict[str, Any]) -> None:
    """Add the text atoms of one record range to a slide (title or paragraphs)."""
    text_type = 1
    for rtype, _, x, y in _ppt_atoms(data, a, b):
        if rtype == RT_TEXT_HEADER and y - x >= 4:
            text_type = struct.unpack_from("<I", data, x)[0]
        elif rtype == RT_BLIP_REF:
            slide["images"] += 1
        elif rtype in (RT_TEXT_CHARS, RT_TEXT_BYTES):
            lines = [line.strip() for line in _ppt_text(data, rtype, x, y).split("\r") if line.strip()]
            if not lines:
                continue
            if text_type in TITLE_TYPES and not slide["title"]:
                slide["title"] = " ".join(lines)
            else:
                known = {p["text"] for p in slide["paragraphs"]}
                slide["paragraphs"].extend({"text": line, "level": 0} for line in lines if line not in known)


def _ppt(cf: CompoundFile) -> Dict[str, Any]:
    data = cf.stream("PowerPoint Document")
    if not data:
        raise ValueError("Not a PowerPoint 97-2003 presentation")

    directory, doc_ref = _ppt_persist_directory(cf, data)
    doc_offset = directory.get(doc_ref)
    if doc_offset is not None and _ppt_record(data, doc_offset)[0] == RT_DOCUMENT:
        _, doc_a, doc_b = _ppt_record(data, doc_offset)
    else:
        doc_a, doc_b = 0, len(data)  # no directory: scan the whole stream

    # The slide list (instance 0) gives the slide order; older files also keep text there
    slides: List[Dict[str, Any]] = []
    list_end = -1
    current: Optional[Dict[str, Any]] = None
    text_type = 1
    for rtype, inst, a, b in _ppt_atoms(data, doc_a, doc_b):
        if rtype == RT_SLIDE_LIST:
            if inst == 0 and not slides:
                list_end = b
            else:
                list_end = -1
            continue
        if list_end < 0 or a >= list_end:
            continue
        if rtype == RT_SLIDE_PERSIST and b - a >= 4:
            current = {"title": "", "paragraphs": [], "images": 0,
                       "persist": struct.unpack_from("<I", data, a)[0]}
            slides.append(current)
        elif rtype == RT_TEXT_HEADER and b - a >= 4:
            text_type = struct.unpack_from("<I", data, a)[0]
        elif rtype in (RT_TEXT_CHARS, RT_TEXT_BYTES) and current is not None:
            lines = [line.strip() for line in _ppt_text(data, rtype, a, b).split("\r") if line.strip()]
            if text_type in TITLE_TYPES and not current["title"]:
                current["title"] = " ".join(lines)
            else:
                current["paragraphs"].extend({"text": line, "level": 0} for line in lines)

    # Newer writers keep the text in each slide's drawing: read the slide records
    for slide in slides:
        offset = directory.get(slide["persist"])
        if offset is None or offset >= len(data):
            continue
        rtype, a, b = _ppt_record(data, offset)
        if rtype == RT_SLIDE:
            _ppt_collect(data, a, b, slide)

    result = [{"number": i + 1, "title": s["title"], "paragraphs": s["paragraphs"], "images": s["images"]}
              for i, s in enumerate(slides)]
    text = "\n".join([s["title"] for s in result] + [p["text"] for s in result for p in s["paragraphs"]])
    return {"slides": result, "text": text}
