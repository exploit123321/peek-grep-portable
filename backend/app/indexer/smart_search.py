"""Search engine for the smart search syntax (see app/query.py).

Each search (the whole query, or one element of [ ]) becomes one SQL query over files_meta
with file name conditions (LIKE, or a Python regex for non-ASCII letters) and, after ":",
text conditions (FTS5 MATCH sub-queries). The full ranked list is kept for a few minutes, so scrolling
loads the next page without searching again; snippets are made only for the page.
"""

import re
import sqlite3
import threading
import time
import unicodedata
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from app.indexer.db import (
    _filter_clause,
    compiled_regex as _compiled,
    escape_like,
    format_snippet,
    get_db_connection,
)
from app.query import Element, QueryPlan, Term, explain, highlight_terms, parse_query
from app.schemas import SearchResultItem

MAX_WILDCARD_TERMS = 256
CACHE_SECONDS = 300.0
CACHE_ENTRIES = 48

_META_COLUMNS = "m.path, m.filename, m.extension, m.size_bytes, m.mtime, m.is_text, m.category"

_cache: "OrderedDict[tuple, Tuple[float, List[Dict[str, Any]]]]" = OrderedDict()
_cache_lock = threading.Lock()
_vocab_cache: Dict[str, Tuple[float, List[Tuple[str, int]]]] = {}


# -- patterns ----------------------------------------------------------------------

def fold(text: str) -> str:
    """Lower case without accents, like the FTS5 unicode61 tokenizer."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


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


def fts_expression(conn: sqlite3.Connection, db_path: Optional[str], term: Term) -> Tuple[Optional[str], Optional[str]]:
    """(FTS5 MATCH expression, regex the text must also contain). (None, None): cannot match."""
    if term.literal:
        text = term.text
        words = re.findall(r"\w+", text)
        if not words:
            return None, None
        phrase = _quote(" ".join(words)) + "*"
        verify = _text_regex(text) if re.search(r"[^\w\s]", text) else None
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
            parts.append(_quote(word) + ("*" if len(word) > 1 else ""))
    if not parts:
        return None, None
    return " AND ".join(parts), None


# -- one search --------------------------------------------------------------------

class _Search:
    """SQL and ranking for one element."""

    def __init__(self, conn: sqlite3.Connection, db_path: Optional[str], el: Element,
                 type_filter: str, folder: Optional[str]):
        self.conn = conn
        self.db_path = db_path
        self.el = el
        self.type_filter = type_filter
        self.folder = folder
        self._fts: Dict[int, Tuple[Optional[str], Optional[str]]] = {}

    # SQL pieces

    def _name_sql(self, term: Term) -> Tuple[str, List[Any]]:
        if term.text.isascii():
            return "m.filename LIKE ? ESCAPE '^'", [_like_pattern(term)]
        return "pg_regexp(?, m.filename)", [_name_regex(term)]

    def fts(self, term: Term) -> Tuple[Optional[str], Optional[str]]:
        key = id(term)
        if key not in self._fts:
            self._fts[key] = fts_expression(self.conn, self.db_path, term)
        return self._fts[key]

    def _content_sql(self, term: Term) -> Tuple[str, List[Any]]:
        expr, verify = self.fts(term)
        if expr is None:
            return "0", []
        sql = "m.path IN (SELECT path FROM files_content_fts WHERE files_content_fts MATCH ?"
        params: List[Any] = [expr]
        if verify:
            sql += " AND pg_regexp(?, content)"
            params.append(verify)
        return sql + ")", params

    def _term_sql(self, term: Term, in_name: bool) -> Tuple[str, List[Any]]:
        sql, params = self._name_sql(term) if in_name else self._content_sql(term)
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
        for terms, in_name in ((el.name_terms, True), (el.content_terms, False)):
            for term in terms:
                sql, p = self._term_sql(term, in_name)
                clause += f" AND {sql}"
                params += p
        return clause, params

    # ranking

    def name_terms(self) -> List[Term]:
        return [t for t in self.el.name_terms if not t.negated]

    def text_expression(self) -> Optional[str]:
        """One OR expression of the positive text terms (for bm25 and snippets)."""
        terms = [t for t in self.el.content_terms if not t.negated]
        exprs = [e for e in (self.fts(t)[0] for t in terms) if e]
        if not exprs:
            return None
        return " OR ".join(f"({e})" for e in exprs)

    def filtered_page(self, start: int, size: int) -> Tuple[int, List[Dict[str, Any]]]:
        """Searches without positive terms (empty, ".xlsx", "-draft"): newest files first, paged in SQL."""
        clause, params = self.where()
        total = self.conn.execute(f"SELECT COUNT(*) FROM files_meta m WHERE 1=1 {clause};", params).fetchone()[0]
        rows = self.conn.execute(
            f"SELECT {_META_COLUMNS} FROM files_meta m WHERE 1=1 {clause} ORDER BY m.mtime DESC LIMIT ? OFFSET ?;",
            (*params, size, start),
        ).fetchall()
        return total, [{**dict(r), "score": 0.0, "match_type": "all"} for r in rows]

    def ranked(self) -> List[Dict[str, Any]]:
        """Every match, best first."""
        clause, params = self.where()
        rows = self.conn.execute(f"SELECT {_META_COLUMNS} FROM files_meta m WHERE 1=1 {clause};", params).fetchall()
        if not rows:
            return []

        bm25: Dict[str, float] = {}
        expr = self.text_expression()
        if expr:
            try:
                for r in self.conn.execute(
                    "SELECT path, bm25(files_content_fts) FROM files_content_fts WHERE files_content_fts MATCH ?;", (expr,),
                ):
                    bm25[r[0]] = float(r[1])
            except sqlite3.OperationalError:
                pass

        matchers = [_compiled(_name_regex(t)) for t in self.name_terms()]
        results: List[Dict[str, Any]] = []
        for r in rows:
            item = dict(r)
            name_score = 0.0
            if matchers:
                fname = item["filename"]
                total = 0.0
                for rx in matchers:
                    if rx.fullmatch(fname):
                        total += 100.0
                    elif rx.match(fname):
                        total += 80.0
                    elif rx.search(fname):
                        total += 60.0
                name_score = total / len(matchers)
            content_score = max(10.0, 50.0 - bm25[item["path"]] * 5.0) if item["path"] in bm25 else 0.0
            if name_score and content_score:
                item["match_type"] = "both"
                item["score"] = name_score + content_score + 25.0
            elif content_score:
                item["match_type"] = "content"
                item["score"] = content_score
            else:
                item["match_type"] = "filename"
                item["score"] = name_score
            results.append(item)
        results.sort(key=lambda x: (x["score"], x["mtime"]), reverse=True)
        return results

    def snippets(self, items: List[Dict[str, Any]]) -> Dict[str, str]:
        paths = [i["path"] for i in items if i["match_type"] in ("content", "both")]
        expr = self.text_expression()
        if not paths or not expr:
            return {}
        marks = ",".join("?" for _ in paths)
        try:
            rows = self.conn.execute(
                f"""SELECT path, snippet(files_content_fts, 1, char(2), char(3), '…', 20)
                    FROM files_content_fts WHERE files_content_fts MATCH ? AND path IN ({marks});""",
                (expr, *paths),
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
        out: Dict[str, str] = {}
        for path, raw in rows:
            snippet = format_snippet(raw)
            if snippet and path not in out:
                out[path] = snippet
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


def _ranked_cached(search: _Search, key: tuple, fresh: bool) -> List[Dict[str, Any]]:
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
) -> Dict[str, Any]:
    """Search one page. Grouped queries ([a, b]) return the first page of every group,
    or with group=N the next page of group N."""
    conn = get_db_connection(db_path)
    plan: QueryPlan = parse_query(query or "")
    base_key = (db_path, query, type_filter, folder)

    def page_of(index: int, el: Element, start: int, size: int) -> Dict[str, Any]:
        search = _Search(conn, db_path, el, type_filter, folder)
        if el.positive_terms:
            ranked = _ranked_cached(search, base_key + (index,), fresh=start == 0)
            total, page = len(ranked), ranked[start:start + size]
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

    response: Dict[str, Any] = {"grouped": plan.grouped, "explain": explain(plan)}
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
