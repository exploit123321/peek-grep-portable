"""Filters after ";" in the search field: dates and size.

    ;dm from 01-03-2024 to 31-03-2024   modified in March 2024 (both days included)
    ;dc from 2023                      created in 2023 or later
    ;da to 15-06                       accessed on 15 June (this year) or before
    ;dm 2024-05 / ;dm may 2024         modified in May 2024
    ;dm 7d / ;dm since 2w              modified in the last 7 days / 2 weeks
    ;dm >3m                            modified more than 3 months ago
    ;size>10mb  ;size<=1.5 gb          sizes in b, kb, mb, gb, tb (1 kb = 1024 bytes)
    ;size from 1mb to 50mb             both ends included
    ;size small                        Windows size names: empty, tiny, small, medium, large, huge, gigantic

Fields: dm (modified), dc (created), da (accessed), size; long names work too (modified,
created, accessed). A date can be a day, a month, or a year: "from" takes its first moment,
"to" its last (so "to" includes the whole day). Several filters: ;dm 2024;size>1mb.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, List, Optional, Tuple

FIELDS = {
    "dm": "mtime", "modified": "mtime", "mod": "mtime", "date": "mtime", "changed": "mtime",
    "dc": "ctime", "created": "ctime", "made": "ctime",
    "da": "atime", "accessed": "atime", "opened": "atime",
    "size": "size", "sz": "size",
}
FIELD_LABELS = {"mtime": "modified", "ctime": "created", "atime": "accessed", "size": "size"}

_UNITS = {
    "b": 1, "byte": 1, "bytes": 1,
    "k": 1024, "kb": 1024, "kib": 1024,
    "m": 1024 ** 2, "mb": 1024 ** 2, "mib": 1024 ** 2,
    "g": 1024 ** 3, "gb": 1024 ** 3, "gib": 1024 ** 3,
    "t": 1024 ** 4, "tb": 1024 ** 4, "tib": 1024 ** 4,
}

# Windows Explorer size names
_NAMED_SIZES = {
    "empty": (0, 1),
    "tiny": (1, 16 * 1024),
    "small": (16 * 1024, 1024 ** 2),
    "medium": (1024 ** 2, 128 * 1024 ** 2),
    "large": (128 * 1024 ** 2, 1024 ** 3),
    "huge": (1024 ** 3, 4 * 1024 ** 3),
    "gigantic": (4 * 1024 ** 3, float("inf")),
}

# Month names (English and Latvian, without accents); 3 letters are enough
_MONTHS = [
    ("january", "janvaris"), ("february", "februaris"), ("march", "marts"), ("april", "aprilis"),
    ("may", "maijs"), ("june", "junijs"), ("july", "julijs"), ("august", "augusts"),
    ("september", "septembris"), ("october", "oktobris"), ("november", "novembris"), ("december", "decembris"),
]

_DURATION = re.compile(r"(\d+)\s*(h|hours?|d|days?|w|weeks?|m|mo|months?|y|years?)(\s+ago)?")
_NUM = re.compile(r"\d+")
FAR_FUTURE = 32503680000.0  # year 3000


@dataclass
class Value:
    """A date or a size: its period [start, end), the range for "=", and if it is an age (7d)."""

    start: float
    end: float
    eq_start: float
    eq_end: float
    age: bool = False


@dataclass
class Param:
    field: str                    # mtime, ctime, atime, size
    low: Optional[float] = None   # included
    high: Optional[float] = None  # excluded
    label: str = ""


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower().strip()


# -- dates -------------------------------------------------------------------------

def _month(word: str) -> Optional[int]:
    w = word.strip(".")
    if len(w) < 3:
        return None
    for k, names in enumerate(_MONTHS):
        if any(name.startswith(w) or w.startswith(name) for name in names):
            return k + 1
    return None


def _year(text: str) -> int:
    y = int(text)
    if len(text) <= 2:
        y += 2000 if y < 70 else 1900
    return y


def _period(y: int, m: Optional[int] = None, d: Optional[int] = None) -> Tuple[datetime, datetime]:
    if m is None:
        return datetime(y, 1, 1), datetime(y + 1, 1, 1)
    if d is None:
        return datetime(y, m, 1), (datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1))
    start = datetime(y, m, d)
    return start, start + timedelta(days=1)


def _relative(text: str, now: datetime) -> Optional[Tuple[datetime, datetime, bool]]:
    today = datetime(now.year, now.month, now.day)
    if text in ("today", "sodien"):
        return today, today + timedelta(days=1), False
    if text in ("yesterday", "vakar"):
        return today - timedelta(days=1), today, False
    if text in ("now",):
        return now, now, True
    m = re.fullmatch(r"(this|last)\s+(week|month|year)", text)
    if m:
        which, unit = m.groups()
        if unit == "week":
            start = today - timedelta(days=today.weekday())
            if which == "last":
                start -= timedelta(days=7)
            return start, start + timedelta(days=7), False
        if unit == "month":
            y, mo = now.year, now.month
            if which == "last":
                y, mo = (y - 1, 12) if mo == 1 else (y, mo - 1)
            return _period(y, mo) + (False,)
        y = now.year - (1 if which == "last" else 0)
        return _period(y) + (False,)
    m = _DURATION.fullmatch(text)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if unit.startswith("h"):
            point = now - timedelta(hours=n)
        elif unit.startswith("d"):
            point = now - timedelta(days=n)
        elif unit.startswith("w"):
            point = now - timedelta(weeks=n)
        elif unit.startswith("y"):
            point = now.replace(year=now.year - n) if not (now.month == 2 and now.day == 29) else now - timedelta(days=365 * n)
        else:  # months
            mo = now.month - n
            y = now.year + (mo - 1) // 12
            mo = (mo - 1) % 12 + 1
            point = now.replace(year=y, month=mo, day=min(now.day, 28))
        return point, point, True
    return None


def parse_date(text: str, order: str = "dmy", now: Optional[datetime] = None) -> Tuple[datetime, datetime, bool]:
    """(start, end, is_age) of a date text. order: dmy, mdy, or ymd for numbers like 01-02-2024."""
    now = now or datetime.now()
    t = _fold(text)
    rel = _relative(t, now)
    if rel:
        return rel

    words = [w for w in re.split(r"[\s,]+|(?<=\d)\.(?=\s|$)", t) if w]
    # Month names: "15 mar 2024", "mar 15 2024", "march 2024", "mar"
    named = [(_month(w), k) for k, w in enumerate(words) if not w[0].isdigit()]
    if named and all(m for m, _ in named) and len(named) == 1:
        month, k = named[0]
        nums = [w.strip(".") for j, w in enumerate(words) if j != k]
        if not all(n.isdigit() for n in nums) or len(nums) > 2:
            raise ValueError(f"“{text}” is not a date")
        day = year = None
        for n in nums:
            if len(n) == 4 or (year is None and day is not None):
                year = _year(n)
            elif day is None:
                day = int(n)
            else:
                year = _year(n)
        return _period(year or now.year, month, day) + (False,)

    parts = re.split(r"[-./\s]+", t.strip(".-/ "))
    if not parts or not all(p.isdigit() for p in parts) or len(parts) > 3:
        raise ValueError(f"“{text}” is not a date")
    if len(parts) == 1:
        if len(parts[0]) == 4:
            return _period(int(parts[0])) + (False,)
        if len(parts[0]) == 8:  # 20240315
            p = parts[0]
            return _period(int(p[:4]), int(p[4:6]), int(p[6:])) + (False,)
        raise ValueError(f"“{text}” is not a date")
    a = parts[0]
    if len(parts) == 2:
        x, y = parts
        if len(x) == 4:                 # 2024-05
            return _period(int(x), int(y)) + (False,)
        if len(y) == 4:                 # 05-2024
            return _period(int(y), int(x)) + (False,)
        day, month = (int(y), int(x)) if order == "mdy" else (int(x), int(y))
        return _period(now.year, month, day) + (False,)
    x, y, z = parts
    if len(a) == 4 or (order == "ymd" and len(z) <= 2):
        return _period(_year(x), int(y), int(z)) + (False,)
    if order == "mdy":
        return _period(_year(z), int(x), int(y)) + (False,)
    return _period(_year(z), int(y), int(x)) + (False,)


def _date_value(text: str, order: str, now: datetime) -> Value:
    try:
        start, end, age = parse_date(text, order, now)
    except Exception:
        # 15/03 in month-first order (or 03/15 in day-first): use the order that is a real date
        other = {"dmy": "mdy", "mdy": "dmy"}.get(order)
        try:
            if not other:
                raise ValueError
            start, end, age = parse_date(text, other, now)
        except Exception:
            raise ValueError(f"“{text}” is not a date")
    s, e = start.timestamp(), end.timestamp()
    if age:
        return Value(s, s, s, FAR_FUTURE, age=True)
    return Value(s, e, s, e)


def _fmt_date(ts: float, order: str) -> str:
    d = datetime.fromtimestamp(ts)
    if order == "mdy":
        return d.strftime("%m/%d/%Y")
    if order == "ymd":
        return d.strftime("%Y-%m-%d")
    return d.strftime("%d.%m.%Y")


# -- sizes -------------------------------------------------------------------------

def _size_value(text: str) -> Value:
    t = _fold(text).replace(" ", "")
    if t in _NAMED_SIZES:
        lo, hi = _NAMED_SIZES[t]
        return Value(lo, hi, lo, hi)
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)([a-z]*)", t)
    if not m or (m.group(2) and m.group(2) not in _UNITS):
        raise ValueError(f"“{text}” is not a size (use b, kb, mb, gb, or tb)")
    number, unit = m.group(1).replace(",", "."), m.group(2) or "b"
    factor = _UNITS[unit]
    value = float(number) * factor
    # "=" means the same when rounded like the text: 10mb is 9.5 to 10.5 MB
    decimals = len(number.split(".")[1]) if "." in number else 0
    half = 0.5 * factor / (10 ** decimals) if factor > 1 else 0.5
    return Value(value, value + 1, max(0.0, value - half), value + half)


def _fmt_size(n: float) -> str:
    if n == float("inf"):
        return "∞"
    for unit, factor in (("TB", 1024 ** 4), ("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if n >= factor:
            v = n / factor
            return f"{v:.1f}".rstrip("0").rstrip(".") + f" {unit}"
    return f"{int(n)} B"


# -- conditions --------------------------------------------------------------------

_OPS = ("<=", ">=", "!=", "<", ">", "=")


def _split_range(text: str) -> Optional[Tuple[str, str]]:
    """'a..b', 'a - b' (spaces around the dash), or 'a to b' / 'a until b'."""
    for sep in (r"\.\.", r"\s+-\s+", r"\s+(?:to|until|till|lidz)\s+"):
        parts = re.split(sep, text, maxsplit=1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            return parts[0].strip(), parts[1].strip()
    return None


def parse_param(segment: str, date_order: str = "dmy", now: Optional[datetime] = None) -> Param:
    """One filter like "dm from 01-03-2024 to 31-03-2024" or "size>10mb". Raises ValueError."""
    now = now or datetime.now()
    seg = segment.strip()
    m = re.match(r"([A-Za-z]+)\s*[:]?\s*(.*)$", seg, re.S)
    if not m or _fold(m.group(1)) not in FIELDS:
        raise ValueError(f"“{seg}”: start with dm, dc, da, or size")
    field = FIELDS[_fold(m.group(1))]
    rest = m.group(2).strip()
    if not rest:
        raise ValueError(f"“{seg}”: a {'size' if field == 'size' else 'date'} is missing")

    value = (lambda t: _size_value(t)) if field == "size" else (lambda t: _date_value(t, date_order, now))
    low: Optional[float] = None
    high: Optional[float] = None
    low_rest = _fold(rest)

    op = next((o for o in _OPS if rest.startswith(o)), None)
    size_label = ""
    # Words (English and Latvian): from/no/kops, after, to/until/lidz, before
    words = re.match(r"(from|since|after|to|until|till|before|no|lidz|kops)\b\s*(.*)$", low_rest, re.S)
    if op:
        v = value(rest[len(op):].strip())
        if field == "size" and op != "=":
            size_label = f"size {op.replace('<=', '≤').replace('>=', '≥')} {_fmt_size(v.start)}"
        if v.age:  # ages: "<7d" is younger than 7 days, ">3m" older than 3 months
            op = {"<": ">", ">": "<", "<=": ">=", ">=": "<="}.get(op, op)
        if op == ">":
            low = v.end
        elif op == ">=":
            low = v.start
        elif op == "<":
            high = v.start
        elif op == "<=":
            high = v.end
        elif op == "=":
            low, high = v.eq_start, v.eq_end
        else:
            raise ValueError(f"“{seg}”: “!=” is not supported")
    elif words:
        word, tail = words.group(1), words.group(2)
        if word in ("from", "since", "after", "no", "kops"):
            rng = re.split(r"\s+(?:to|until|till|lidz)\s+", tail, maxsplit=1, flags=re.I)
            first = value(rng[0].strip())
            low = first.end if word == "after" else first.start
            if len(rng) == 2:
                high = value(rng[1].strip()).end
        elif word == "before":
            high = value(tail.strip()).start
        else:  # to, until
            high = value(tail.strip()).end
    else:
        rng = _split_range(rest)
        if rng:
            low, high = value(rng[0]).start, value(rng[1]).end
        else:
            v = value(rest)
            low, high = v.eq_start, v.eq_end

    if high is not None and (high == float("inf") or high >= FAR_FUTURE):
        high = None  # no upper limit
    if low is not None and high is not None and low >= high:
        raise ValueError(f"“{seg}”: the start is after the end")
    return Param(field=field, low=low, high=high, label=size_label or _label(field, low, high, date_order))


def _label(field: str, low: Optional[float], high: Optional[float], order: str) -> str:
    name = FIELD_LABELS[field]
    if field == "size":
        if low is not None and high is not None:
            return f"{name} {_fmt_size(low)} – {_fmt_size(high)}"
        if low is not None:
            return f"{name} ≥ {_fmt_size(low)}"
        return f"{name} < {_fmt_size(high)}"
    fmt = lambda ts: _fmt_date(ts, order)  # noqa: E731
    last = (lambda ts: _fmt_date(ts - 1, order))  # noqa: E731  (high is the next day's start)
    if low is not None and high is not None and high < FAR_FUTURE:
        a, b = fmt(low), last(high)
        return f"{name} {a}" if a == b else f"{name} {a} – {b}"
    if low is not None:
        return f"{name} from {fmt(low)}"
    return f"{name} to {last(high)}"


def parse_params(segments: List[str], date_order: str = "dmy", now: Optional[datetime] = None) -> Tuple[List[Param], List[str]]:
    """All filters; the ones that cannot be read come back as messages (and are left out)."""
    params: List[Param] = []
    errors: List[str] = []
    for seg in segments:
        if not seg.strip():
            continue
        try:
            params.append(parse_param(seg, date_order, now))
        except ValueError as e:
            errors.append(str(e))
    return params, errors


def split_params(query: str, param_char: str, quotes: bool, group_open: str, group_close: str,
                 text_char: str = "", and_char: str = "", is_param: Optional[Callable[[str], bool]] = None,
                 ) -> Tuple[str, List[str]]:
    """The search and its filters: the text before the first top-level param_char, and the parts after it.

    With text_char and is_param, a filter may also come before the text search: in
    ".xlsx;size>150:product" the text_char after a whole filter ("size>150") starts the text search
    again, so this is the same as ".xlsx:product;size>150". ("dm:2024" stays one filter.)"""
    text, segments = _split_params(query, param_char, quotes, group_open, group_close)
    if not segments or not text_char or is_param is None:
        return text, segments
    kept: List[str] = []
    for seg in segments:
        cut = _text_after_param(seg, text_char, is_param)
        if cut is None:
            kept.append(seg)
            continue
        kept.append(seg[:cut])
        rest = seg[cut:]
        if text_char in text:
            # The text already has a text search: the new words must hit too
            rest = (and_char or " ") + rest[len(text_char):]
        text += rest
    return text, kept


def _text_after_param(seg: str, text_char: str, is_param: Callable[[str], bool]) -> Optional[int]:
    """Where the text search starts in a filter part ("size>150:product" -> 8), or None."""
    pos = seg.find(text_char)
    while pos > 0:
        if is_param(seg[:pos]):
            return pos
        pos = seg.find(text_char, pos + 1)
    return None


def _split_params(query: str, param_char: str, quotes: bool, group_open: str, group_close: str) -> Tuple[str, List[str]]:
    if not param_char:
        return query, []
    depth = 0
    quoted = False
    for i, ch in enumerate(query):
        if quotes and ch == '"':
            quoted = not quoted
        elif quoted:
            continue
        elif group_open and ch == group_open:
            depth += 1
        elif group_close and ch == group_close and depth:
            depth -= 1
        elif ch == param_char and depth == 0:
            return query[:i], query[i + 1:].split(param_char)
    return query, []

