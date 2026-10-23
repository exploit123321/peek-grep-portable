"""Search engine for the smart search syntax (see app/query.py).

Each search (the whole query, or one element of [ ]) becomes one SQL query over files_meta
with file name conditions (LIKE, or a Python regex for non-ASCII letters) and, after ":",
text conditions (FTS5 MATCH sub-queries). The full ranked list is kept for a few minutes, so scrolling
loads the next page without searching again; snippets are made only for the page.
"""

import os
import re
import sqlite3
import threading
import time
import unicodedata
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.indexer.db import (
    _MARK_CLOSE,
    _MARK_OPEN,
    _filter_clause,
    compiled_regex as _compiled,
    escape_like,
    folder_like_pattern,
    format_snippet,
    get_db_connection,
)
from app.params import Param
from app.query import Element, QueryPlan, Term, explain, highlight_terms, parse_query
from app.search_options import DEFAULTS, SearchOptions
from app.schemas import SearchResultItem

MAX_WILDCARD_TERMS = 256
CACHE_SECONDS = 300.0
CACHE_ENTRIES = 48

_META_COLUMNS = "m.id, m.path, m.filename, m.extension, m.size_bytes, m.mtime, m.is_text, m.category"

_cache: "OrderedDict[tuple, Tuple[float, List[Tuple[int, float, str]]]]" = OrderedDict()
_cache_lock = threading.Lock()
_vocab_cache: Dict[str, Tuple[float, List[Tuple[str, int]]]] = {}


# -- patterns ----------------------------------------------------------------------

def fold(text: str) -> str:
    """Lower case without accents, like the FTS5 unicode61 tokenizer."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


# Letters with their accented forms, for snippet marks: the index folds accents ("cafe" finds "café")
def _letter_variants() -> Dict[str, str]:
    found: Dict[str, set] = {}
    for cp in range(0xC0, 0x2000):
        ch = chr(cp)
        base = fold(ch)
        if ch.isalpha() and len(base) == 1 and base.isascii() and base.isalpha():
            found.setdefault(base, set()).add(ch)
    return {b: "[" + b + "".join(sorted(v)) + "]" for b, v in found.items()}


_VARIANTS = _letter_variants()
SNIPPET_BEFORE = 60
SNIPPET_AFTER = 180


def _folded_char(ch: str) -> str:
    base = fold(ch)
    return _VARIANTS[base] if len(base) == 1 and base in _VARIANTS else re.escape(ch)


def _snippet_regex(term: Term, prefix: bool) -> Optional[str]:
    """Where a text term hits, for marking it in a snippet (like the index: case and accents
    do not matter, a word may go on when prefix is on)."""
    if term.is_blank:
        return None
    if term.literal:
        body = r"\s+".join("".join(_folded_char(c) for c in w) for w in term.text.split())
        return body or None
    marked = "".join(text if kind == "text" else ("\x01" if kind == "any" else "\x02") for kind, text in term.pieces)
    words = ["".join(r"\w*" if c == "\x01" else (r"\w" if c == "\x02" else _folded_char(c)) for c in w) for w in marked.split()]
    if not words:
        return None
    body = r"\s+".join(words)
    if marked[:1].isalnum() or marked[:1] in "_\x01\x02":
        body = r"(?<!\w)" + body
    # Like the search: a word with wildcards is a whole word, others may go on ("total" -> "totals")
    last = marked.split()[-1]
    goes_on = prefix and "\x01" not in last and "\x02" not in last
    return body + (r"\w*" if goes_on else r"(?!\w)")


def snippet_anchor(term: Term) -> str:
    """The longest plain part of a term, lower case ("word91999", "-6403s"): found with a plain
    string search, many times faster than the regex in a long text."""
    parts = [w.lower() for kind, text in term.pieces if kind == "text" for w in text.split()]
    best = max(parts, key=len, default="")
    return best if len(best) >= 3 else ""


def _first_hit(text: str, low: Optional[str], rx: "re.Pattern[str]", anchor: str) -> Optional[int]:
    if anchor and low is not None:
        pos = low.find(anchor)
        tries = 0
        while pos != -1 and tries < 2000:
            # The regex confirms the place (word start, wildcards before the anchor)
            m = rx.search(text, max(0, pos - 200), pos + len(anchor) + 200)
            while m and m.end() <= pos:
                m = rx.search(text, m.end(), pos + len(anchor) + 200)
            if m and m.start() <= pos < m.end():
                return m.start()
            pos = low.find(anchor, pos + 1)
            tries += 1
    # Not found that way (a hit with accents, "cafe" -> "café", or none): the whole text
    for m in rx.finditer(text):
        if m.end() > m.start():
            return m.start()
    return None


def make_snippet(text: str, regexes: Sequence["re.Pattern[str]"], anchors: Sequence[str] = ()) -> Optional[str]:
    """A short part of the text around its first hit, hits marked (HTML). The search stops at the
    first hit, so a very long text costs little."""
    low = text.lower() if any(anchors) else None
    if low is not None and len(low) != len(text):
        low = None  # a few letters change length in lower case: positions would not match
    first: Optional[int] = None
    for k, rx in enumerate(regexes):
        hit = _first_hit(text, low, rx, anchors[k] if k < len(anchors) else "")
        if hit is not None and (first is None or hit < first):
            first = hit
    if first is None:
        return None
    start = max(0, first - SNIPPET_BEFORE)
    if start:
        space = text.find(" ", start, first)
        start = space + 1 if space != -1 else start
    end = min(len(text), first + SNIPPET_AFTER)
    if end < len(text):
        space = text.rfind(" ", first + 40, end)
        end = space if space != -1 else end
    spans = sorted((m.start(), m.end()) for rx in regexes for m in rx.finditer(text, start, end) if m.end() > m.start())
    clean = lambda t: t.replace(_MARK_OPEN, "").replace(_MARK_CLOSE, "")  # noqa: E731
    out = ["…" if start else ""]
    pos = start
    for a, b in spans:
        if a < pos:
            continue
        out += [clean(text[pos:a]), _MARK_OPEN, clean(text[a:b]), _MARK_CLOSE]
        pos = b
    out += [clean(text[pos:end]), "…" if end < len(text) else ""]
    return format_snippet("".join(out))


def _name_regex(term: Term) -> str:
    out = []
    for kind, text in term.pieces:
        out.append(re.escape(text) if kind == "text" else (".*" if kind == "any" else "."))
    body = "".join(out)
    return f"^{body}$" if term.exact else body


def _like_pattern(term: Term) -> str:
    out = []
    for kind, text in term.pieces:
        out.append(escape_like(text) if kind == "text" else ("%" if kind == "any" else "_"))
    body = "".join(out)
    return body if term.exact else "%" + body + "%"


def _phrase_regex(marked: str, prefix: bool) -> str:
    """Words next to each other, in order, with only white space between them (\x01 = *, \x02 = ?).
    The last word may go on ("review" finds "reviews") when prefix is on."""
    words = []
    for word in marked.split():
        words.append("".join(r"\w*" if ch == "\x01" else (r"\w" if ch == "\x02" else re.escape(ch)) for ch in word))
    body = r"\s+".join(words)
    if marked[:1].isalnum() or marked[:1] in "_\x01\x02":
        body = r"(?<!\w)" + body
    if not prefix:
        body += r"(?!\w)"
    return body


def _text_regex(text: str) -> str:
    """Check for a literal text in file content: white space is flexible, the start is a word start."""
    words = [re.escape(w) for w in text.split()]
    body = r"\s+".join(words)
    if text[:1].isalnum() or text[:1] == "_":
        body = r"(?<!\w)" + body
    return body


def _vocab(conn: sqlite3.Connection, db_path: Optional[str], prefix: str) -> List[Tuple[str, int]]:
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.pg_vocab USING fts5vocab(main, files_content_fts, row);")
    if prefix:
        return conn.execute("SELECT term, doc FROM temp.pg_vocab WHERE term >= ? AND term < ?;",
                            (prefix, prefix + "\U0010ffff")).fetchall()
    key = db_path or ""
    now = time.time()
    hit = _vocab_cache.get(key)
    if hit and now - hit[0] < 20:
        return hit[1]
    rows = [(r[0], r[1]) for r in conn.execute("SELECT term, doc FROM temp.pg_vocab;")]
    _vocab_cache[key] = (now, rows)
    return rows


def _quote(token: str) -> str:
    return '"' + token.replace('"', '""') + '"'


def _wild_word(conn: sqlite3.Connection, db_path: Optional[str], word: str) -> Optional[str]:
    """FTS5 expression for one word with wildcards (\x01 = *, \x02 = ?). None: no such word."""
    stripped = word.replace("\x01", "").replace("\x02", "")
    if word.endswith("\x01") and "\x01" not in word[:-1] and "\x02" not in word and stripped:
        return _quote(fold(stripped)) + "*"
    regex = "".join(".*" if ch == "\x01" else ("." if ch == "\x02" else re.escape(fold(ch))) for ch in word)
    prefix = fold(re.split(r"[\x01\x02]", word, maxsplit=1)[0])
    rx = re.compile(regex)
    try:
        rows = _vocab(conn, db_path, prefix)
    except sqlite3.OperationalError:
        return None
    found = sorted(((doc, term) for term, doc in rows if rx.fullmatch(term)), reverse=True)[:MAX_WILDCARD_TERMS]
    if not found:
        return None
    return "(" + " OR ".join(_quote(term) for _, term in found) + ")"


def fts_expression(conn: sqlite3.Connection, db_path: Optional[str], term: Term,
                   prefix: bool = True) -> Tuple[Optional[str], Optional[str]]:
    """(FTS5 MATCH expression, regex the text must also contain). (None, None): cannot match.
    prefix: words also match longer words ("memo" finds "memos")."""
    if term.literal:
        text = term.text
        words = re.findall(r"\w+", text)
        if not words:
            return None, None
        phrase = _quote(" ".join(words)) + ("*" if prefix else "")
        verify = _text_regex(text) if re.search(r"[^\w\s]", text) or len(text.split()) > 1 else None
        return phrase, verify

    marked = "".join(text if kind == "text" else ("\x01" if kind == "any" else "\x02") for kind, text in term.pieces)
    parts: List[str] = []
    for word in re.findall(r"[\w\x01\x02]+", marked):
        if not word.replace("\x01", "").replace("\x02", ""):
            if "\x02" not in word:
                continue  # only "*": no limit
        if "\x01" in word or "\x02" in word:
            expr = _wild_word(conn, db_path, word)
            if expr is None:
                return None, None
            parts.append(expr)
        else:
            # One letter matches whole words only: "a*" would hit nearly every file
            parts.append(_quote(word) + ("*" if prefix and len(word) > 1 else ""))
    if not parts:
        return None, None
    if len(marked.split()) > 1:
        # Several words: a phrase. "annual review" must be these words next to each other, with
        # only white space between them ("annual.review" or "review annual" do not count); the
        # words in any place are "annual+review".
        if "\x01" not in marked and "\x02" not in marked:
            tokens = re.findall(r"\w+", marked)
            return _quote(" ".join(tokens)) + ("*" if prefix else ""), _phrase_regex(marked, prefix)
        return " AND ".join(parts), _phrase_regex(marked, prefix)
    # The index keeps only the words: signs between them ("*-6403s") are checked in the text
    verify = _phrase_regex(marked, prefix) if re.search(r"[^\w\s\x01\x02]", marked) else None
    return " AND ".join(parts), verify


# -- one search --------------------------------------------------------------------

class _Search:
    """SQL and ranking for one element."""

    def __init__(self, conn: sqlite3.Connection, db_path: Optional[str], el: Element,
                 type_filter: str, folder: Optional[str], opts: SearchOptions = DEFAULTS,
                 roots: Sequence[str] = (), params: Sequence[Param] = ()):
        self.conn = conn
        self.db_path = db_path
        self.el = el
        self.type_filter = type_filter
        self.folder = folder
        self.opts = opts
        self.roots = sorted((os.path.normpath(r) for r in roots), key=len, reverse=True)
        self.params = list(params)
        self._fts: Dict[int, Tuple[Optional[str], Optional[str]]] = {}

    # SQL pieces

    def _relpath_sql(self) -> Tuple[str, List[Any]]:
        """Path below the working folder (so a working folder named "Work" does not hit every file)."""
        if not self.roots:
            return "m.path", []
        parts, params = [], []
        for root in self.roots:
            base = root if root.endswith(os.sep) else root + os.sep
            parts.append("WHEN m.path LIKE ? ESCAPE '^' THEN substr(m.path, ?)")
            params += [folder_like_pattern(root), len(base) + 1]
        return "(CASE " + " ".join(parts) + " ELSE m.path END)", params

    def relpath(self, path: str) -> str:
        low = path.lower()
        for root in self.roots:
            base = root if root.endswith(os.sep) else root + os.sep
            if low.startswith(base.lower()):
                return path[len(base):]
        return path

    def _name_sql(self, term: Term) -> Tuple[str, List[Any]]:
        # With folder names on, a part of the name may also be a folder below the working folder
        column, params = (self._relpath_sql() if self.opts.names_include_folders and not term.exact
                          else ("m.filename", []))
        if term.text.isascii():
            return f"{column} LIKE ? ESCAPE '^'", params + [_like_pattern(term)]
        return f"pg_regexp(?, {column})", [_name_regex(term)] + params

    def fts(self, term: Term) -> Tuple[Optional[str], Optional[str]]:
        key = id(term)
        if key not in self._fts:
            self._fts[key] = fts_expression(self.conn, self.db_path, term, self.opts.text_prefix)
        return self._fts[key]

    def _content_sql(self, term: Term) -> Tuple[str, List[Any]]:
        expr, verify = self.fts(term)
        if expr is None:
            return "0", []
        # By the file id (the text row's rowid): only the index is read, not the stored texts
        sql = "m.id IN (SELECT rowid FROM files_content_fts WHERE files_content_fts MATCH ?"
        params: List[Any] = [expr]
        if verify:
            sql += " AND pg_regexp(?, content)"
            params.append(verify)
        return sql + ")", params

    def _term_sql(self, term: Term, where: str) -> Tuple[str, List[Any]]:
        if where == "name":
            sql, params = self._name_sql(term)
        elif where == "text":
            sql, params = self._content_sql(term)
        else:  # name or text
            a, pa = self._name_sql(term)
            b, pb = self._content_sql(term)
            sql, params = f"({a} OR {b})", pa + pb
        if term.negated:
            if term.exts:
                marks = ",".join("?" for _ in term.exts)
                return f"NOT (m.extension IN ({marks}) AND {sql})", list(term.exts) + params
            return f"NOT ({sql})", params
        return sql, params

    def where(self) -> Tuple[str, List[Any]]:
        clause, params = _filter_clause(self.type_filter, self.folder)
        el = self.el
        if el.exts:
            clause += f" AND m.extension IN ({','.join('?' for _ in el.exts)})"
            params += el.exts
        if el.exclude_exts:
            clause += f" AND m.extension NOT IN ({','.join('?' for _ in el.exclude_exts)})"
            params += el.exclude_exts
        # Filters after ";": dates and size (low included, high excluded)
        for param in self.params:
            column = {"mtime": "m.mtime", "ctime": "m.ctime", "atime": "m.atime", "size": "m.size_bytes"}[param.field]
            if param.low is not None:
                clause += f" AND {column} >= ?"
                params.append(param.low)
            if param.high is not None:
                clause += f" AND {column} < ?"
                params.append(param.high)
        for terms, where in ((el.name_terms, "name"), (el.content_terms, "text"), (el.any_terms, "any")):
            for term in terms:
                sql, p = self._term_sql(term, where)
                clause += f" AND {sql}"
                params += p
        return clause, params

    # ranking

    def name_terms(self) -> List[Term]:
        return [t for t in self.el.name_terms + self.el.any_terms if not t.negated]

    def text_expression(self) -> Optional[str]:
        """One OR expression of the positive text terms (for bm25 and snippets)."""
        terms = [t for t in self.el.content_terms + self.el.any_terms if not t.negated]
        exprs = [e for e in (self.fts(t)[0] for t in terms) if e]
        if not exprs:
            return None
        return " OR ".join(f"({e})" for e in exprs)

    _ORDER_SQL = {
        "best": "m.mtime DESC", "newest": "m.mtime DESC", "oldest": "m.mtime ASC",
        "name": "m.filename COLLATE NOCASE ASC", "size": "m.size_bytes DESC",
    }

    def filtered_page(self, start: int, size: int) -> Tuple[int, List[Dict[str, Any]]]:
        """Searches without positive terms (empty, ".xlsx", "-draft"): newest first (or the chosen order), paged in SQL."""
        clause, params = self.where()
        total = self.conn.execute(f"SELECT COUNT(*) FROM files_meta m WHERE 1=1 {clause};", params).fetchone()[0]
        rows = self.conn.execute(
            f"SELECT {_META_COLUMNS} FROM files_meta m WHERE 1=1 {clause} "
            f"ORDER BY {self._ORDER_SQL.get(self.opts.sort, 'm.mtime DESC')} LIMIT ? OFFSET ?;",
            (*params, size, start),
        ).fetchall()
        return total, [{**dict(r), "score": 0.0, "match_type": "all"} for r in rows]

    _SQL_ORDER = {
        "best": "score DESC, m.mtime DESC", "newest": "m.mtime DESC", "oldest": "m.mtime ASC",
        "name": "lower(m.filename) ASC", "size": "m.size_bytes DESC",
    }

    def _name_ranking_sql(self) -> Optional[Tuple[str, List[Any]]]:
        """Name searches (the usual case) are scored and sorted by SQLite: the whole name 100,
        the start 80, elsewhere 60, as below. None when Python must do it (text, folders, non-ASCII)."""
        el = self.el
        terms = [t for t in el.name_terms if not t.negated]
        if el.content_terms or el.any_terms or not terms or self.opts.names_include_folders:
            return None
        if not all(t.text.isascii() for t in terms):
            return None
        cases: List[str] = []
        params: List[Any] = []
        for t in terms:
            body = _like_pattern(t)
            if not t.exact:
                body = body[1:-1]  # without the % at both ends
            cases.append("(CASE WHEN m.filename LIKE ? ESCAPE '^' THEN 100.0 "
                         "WHEN m.filename LIKE ? ESCAPE '^' THEN 80.0 ELSE 60.0 END)")
            params += [body, body + "%"]
        return f"({' + '.join(cases)}) / {len(terms)}", params

    def ranked(self) -> List[Tuple[int, float, str]]:
        """Every match, best first, as (file id, score, match type). Only what the order needs is
        read here; the page loads the rest (load_page)."""
        clause, params = self.where()
        cur = self.conn.cursor()
        cur.row_factory = None  # plain tuples: much faster for many thousands of rows
        by_sql = self._name_ranking_sql()
        if by_sql:
            score_sql, score_params = by_sql
            order = self._SQL_ORDER.get(self.opts.sort, self._SQL_ORDER["best"])
            return [(file_id, score, "filename") for file_id, score in cur.execute(
                f"SELECT m.id, {score_sql} AS score FROM files_meta m WHERE 1=1 {clause} ORDER BY {order};",
                score_params + params)]
        rows = cur.execute(f"SELECT m.id, m.path, m.filename, m.mtime, m.size_bytes FROM files_meta m WHERE 1=1 {clause};",
                           params).fetchall()
        if not rows:
            return []

        bm25: Dict[int, float] = {}
        expr = self.text_expression()
        if expr:
            try:
                # By rowid (the file id): the scores need the index only, not the stored texts
                bm25 = dict(cur.execute(
                    "SELECT rowid, bm25(files_content_fts) FROM files_content_fts WHERE files_content_fts MATCH ?;", (expr,),
                ).fetchall())
            except sqlite3.OperationalError:
                pass

        matchers = [_compiled(_name_regex(t)) for t in self.name_terms()]
        folders = self.opts.names_include_folders
        scored: List[Tuple[float, int, str, Tuple[Any, ...]]] = []
        for row in rows:
            file_id, path, fname = row[0], row[1], row[2]
            name_score = 0.0
            if matchers:
                total = 0.0
                for rx in matchers:
                    if rx.fullmatch(fname):
                        total += 100.0
                    elif rx.match(fname):
                        total += 80.0
                    elif rx.search(fname):
                        total += 60.0
                    elif folders and rx.search(self.relpath(path)):
                        total += 40.0
                name_score = total / len(matchers)
            rank = bm25.get(file_id)
            content_score = max(10.0, 50.0 - rank * 5.0) if rank is not None else 0.0
            if name_score and content_score:
                scored.append((name_score + content_score + 25.0, file_id, "both", row))
            elif content_score:
                scored.append((content_score, file_id, "content", row))
            else:
                scored.append((name_score, file_id, "filename", row))
        sort = self.opts.sort
        if sort == "newest":
            scored.sort(key=lambda x: x[3][3], reverse=True)
        elif sort == "oldest":
            scored.sort(key=lambda x: x[3][3])
        elif sort == "name":
            scored.sort(key=lambda x: x[3][2].lower())
        elif sort == "size":
            scored.sort(key=lambda x: x[3][4], reverse=True)
        else:
            scored.sort(key=lambda x: (x[0], x[3][3]), reverse=True)
        return [(file_id, score, kind) for score, file_id, kind, _ in scored]

    def load_page(self, page: List[Tuple[int, float, str]]) -> List[Dict[str, Any]]:
        """The file details of one page of ranked(), in its order."""
        if not page:
            return []
        marks = ",".join("?" for _ in page)
        found = {r["id"]: dict(r) for r in self.conn.execute(
            f"SELECT {_META_COLUMNS} FROM files_meta m WHERE m.id IN ({marks});", [p[0] for p in page])}
        # A file removed since the search was made is left out
        return [{**found[i], "score": score, "match_type": kind} for i, score, kind in page if i in found]

    def snippets(self, items: List[Dict[str, Any]]) -> Dict[str, str]:
        """Snippets of one page, made here from the stored texts: the index's snippet() reads
        each whole text, very slow for long ones (a big workbook is millions of characters)."""
        if not self.opts.show_snippets:
            return {}
        ids = {i["id"]: i["path"] for i in items if i["match_type"] in ("content", "both")}
        terms = [t for t in self.el.content_terms + self.el.any_terms if not t.negated]
        pairs = [(r, snippet_anchor(t)) for t, r in ((t, _snippet_regex(t, self.opts.text_prefix)) for t in terms) if r]
        if not ids or not pairs:
            return {}
        regexes = [re.compile(r, re.IGNORECASE) for r, _ in pairs]
        anchors = [a for _, a in pairs]
        marks = ",".join("?" for _ in ids)
        out: Dict[str, str] = {}
        for rowid, text in self.conn.execute(
                f"SELECT rowid, content FROM files_content_fts WHERE rowid IN ({marks});", list(ids)):
            snippet = make_snippet(text or "", regexes, anchors)
            if snippet:
                out[ids[rowid]] = snippet
        return out


# -- public API --------------------------------------------------------------------

def _to_items(search: _Search, page: List[Dict[str, Any]]) -> List[SearchResultItem]:
    snippets = search.snippets(page)
    return [
        SearchResultItem(
            path=i["path"],
            filename=i["filename"],
            extension=i["extension"],
            size_bytes=i["size_bytes"],
            mtime=i["mtime"],
            is_text=bool(i["is_text"]),
            snippet=snippets.get(i["path"]),
            match_type=i["match_type"],
            category=i["category"],
        )
        for i in page
    ]


def _ranked_cached(search: _Search, key: tuple, fresh: bool) -> List[Tuple[int, float, str]]:
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and not fresh and now - hit[0] < CACHE_SECONDS:
            _cache.move_to_end(key)
            return hit[1]
    ranked = search.ranked()
    with _cache_lock:
        _cache[key] = (now, ranked)
        _cache.move_to_end(key)
        while len(_cache) > CACHE_ENTRIES:
            _cache.popitem(last=False)
    return ranked


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
    _vocab_cache.clear()


def run_search(
    query: str,
    type_filter: str = "all",
    folder: Optional[str] = None,
    offset: int = 0,
    limit: int = 60,
    group: Optional[int] = None,
    group_limit: int = 25,
    db_path: Optional[str] = None,
    options: SearchOptions = DEFAULTS,
    roots: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Search one page. Grouped queries ([a, b]) return the first page of every group,
    or with group=N the next page of group N."""
    conn = get_db_connection(db_path)
    plan: QueryPlan = parse_query(query or "", options)
    roots = list(roots or [])
    base_key = (db_path, query, type_filter, folder, tuple(roots), options.key())

    def page_of(index: int, el: Element, start: int, size: int) -> Dict[str, Any]:
        search = _Search(conn, db_path, el, type_filter, folder, options, roots, plan.params)
        if el.positive_terms:
            ranked = _ranked_cached(search, base_key + (index,), fresh=start == 0)
            total, page = len(ranked), search.load_page(ranked[start:start + size])
        else:
            total, page = search.filtered_page(start, size)
        return {
            "label": el.label or "",
            "total": total,
            "offset": start,
            "has_more": start + len(page) < total,
            "results": _to_items(search, page),
            "highlight": highlight_terms(el),
        }

    response: Dict[str, Any] = {"grouped": plan.grouped, "explain": explain(plan) if options.enabled else []}
    if plan.grouped and group is None:
        groups = [page_of(k, el, 0, group_limit) for k, el in enumerate(plan.elements)]
        response.update(groups=groups, total=sum(g["total"] for g in groups), offset=0,
                        has_more=False, results=[], highlight=[])
        return response

    index = group if (plan.grouped and group is not None and 0 <= group < len(plan.elements)) else 0
    one = page_of(index, plan.elements[index], max(0, offset), limit)
    response.update(groups=[], total=one["total"], offset=one["offset"], has_more=one["has_more"],
                    results=one["results"], highlight=one["highlight"])
    return response
