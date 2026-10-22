"""Smart search syntax: turns the text in the search field into a search plan.

With the default settings, everything before ":" (or the whole search, without ":") is about
file names; after ":" it is the text inside the files. Everything is case-insensitive.

    invoice              file names that contain "invoice" (invoice1.xlsx, old invoice.docx)
    invoice.xlsx         exactly the file name invoice.xlsx
    invoice+.xlsx        names with "invoice", only .xlsx files (.xlsx alone: all .xlsx files)
    invoice-.xlsx        names with "invoice", but no .xlsx files
    invoice-old          names with "invoice" but without "old"
    :invoice             "invoice" in the text of any file
    .xlsx:total          "total" in the text of .xlsx files
    invoice+.xlsx:total  "total" in the text of .xlsx files with "invoice" in the name
    invoice-old+.xlsx+.pdf:total
                         "total" in .xlsx and .pdf files whose names have "invoice", not "old"
    :annual review       the words next to each other, in this order (a phrase)
    :total+memo          texts with both words anywhere; :total-draft leaves out texts with "draft"
    [invoice, receipt]   one expandable group per element (spaces after the comma do not matter)
    tot*l  rec?ipt       wildcards: * any characters, ? exactly one character
    /note:               "/" makes the rest literal: names with "note:" (inside [ ] up to , or ])
    "e-mail"             quotes: literal text, "" is a quote character

"+" and (outside brackets) "," join parts that must all hit; "-" starts a part that must not hit
(a "-" between two digits, as in 2024-05, is just a character). Brackets can stand anywhere: the
text around them applies to every element, so .xlsx:[total, tax] means .xlsx:total and .xlsx:tax.

After ";" come filters for dates and size (app/params.py): ;dm from 01-03-2024 to 31-03-2024,
;dc 2023, ;da 7d, ;size>10mb. They apply to every group.

Every character and rule can be changed or turned off in the search settings
(app/search_options.py): where words without ":" go (names, text, or both), the signs,
extensions, exact names, wildcards, quotes, groups, filters, or the whole smart search.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from app.params import Param, parse_params, split_params
from app.search_options import DEFAULTS, SearchOptions

# Token kinds
_TEXT = "text"
_AND = "and"
_COLON = "colon"
_NEG = "neg"
_GROUP = "group"

Token = Tuple  # (kind, ...) see _Scanner

# An extension: a dot and 1-10 letters or digits with at least one letter (.xlsx, .7z, not .5)
_EXT = r"\.((?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{1,10})"
_EXT_ONLY = re.compile(_EXT)
_EXACT_NAME = re.compile(r".*\S" + _EXT)


@dataclass
class Term:
    """One search part. pieces: ("text", s), ("any", "") for *, ("one", "") for ?."""

    pieces: List[Tuple[str, str]]
    negated: bool = False
    literal: bool = False
    exts: List[str] = field(default_factory=list)
    exact: bool = False  # the whole file name ("report.xlsx"), not a part of it

    @property
    def text(self) -> str:
        return "".join(p[1] if p[0] == "text" else ("*" if p[0] == "any" else "?") for p in self.pieces)

    @property
    def has_wildcards(self) -> bool:
        return any(p[0] != "text" for p in self.pieces)

    @property
    def is_blank(self) -> bool:
        """No characters to look for (empty, or only "*"): the term matches everything."""
        return not any((p[0] == "text" and p[1].strip()) or p[0] == "one" for p in self.pieces)

    def describe(self) -> dict:
        return {"text": self.text, "literal": self.literal, "exact": self.exact, "pieces": [list(p) for p in self.pieces]}


@dataclass
class Element:
    """One search: a group of [ ] or the whole query."""

    label: Optional[str] = None
    has_colon: bool = False
    name_terms: List[Term] = field(default_factory=list)     # file names
    content_terms: List[Term] = field(default_factory=list)  # file text
    any_terms: List[Term] = field(default_factory=list)      # file name or text (scope "both")
    exts: List[str] = field(default_factory=list)            # only these extensions (any of them)
    exclude_exts: List[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.name_terms or self.content_terms or self.any_terms or self.exts or self.exclude_exts)

    @property
    def positive_terms(self) -> List[Term]:
        return [t for t in self.name_terms + self.content_terms + self.any_terms if not t.negated]


@dataclass
class QueryPlan:
    raw: str
    grouped: bool
    elements: List[Element]
    params: List[Param] = field(default_factory=list)        # filters after ";" (all groups)
    param_errors: List[str] = field(default_factory=list)    # filters that could not be read


# -- scanning ------------------------------------------------------------------------

def _read_quoted(q: str, i: int) -> Tuple[str, int]:
    """Text up to the closing quote ("" is one quote). i points after the opening quote."""
    out: List[str] = []
    n = len(q)
    while i < n:
        ch = q[i]
        if ch == '"':
            if i + 1 < n and q[i + 1] == '"':
                out.append('"')
                i += 2
                continue
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    return "".join(out), i


class _Scanner:
    """Tokens of the search field, with the characters from the options."""

    def __init__(self, q: str, opts: SearchOptions):
        self.q = q
        self.o = opts
        self.item_end = (opts.list_char + opts.group_close) if opts.group_open else ""

    def scan(self, i: int, in_bracket: bool) -> Tuple[List[Token], int, str, int]:
        """Tokens from position i. Returns (tokens, next index, what ended the scan, end of item text)."""
        q, o, n = self.q, self.o, len(self.q)
        tokens: List[Token] = []
        buf: List[str] = []
        term_start = True

        def flush() -> None:
            if buf:
                tokens.append((_TEXT, "".join(buf), False))
                buf.clear()

        while i < n:
            ch = q[i]
            if in_bracket and ch in self.item_end:
                flush()
                return tokens, i + 1, ch, i
            if term_start:
                if ch.isspace():
                    i += 1
                    continue
                if o.not_char and ch == o.not_char and not (tokens and tokens[-1][0] == _NEG):
                    tokens.append((_NEG,))
                    i += 1
                    continue
                if o.literal_char and ch == o.literal_char:
                    j = i + 1
                    if in_bracket:
                        while j < n and q[j] not in self.item_end:
                            j += 1
                    else:
                        j = n
                    tokens.append((_TEXT, q[i + 1:j], True))
                    i = j
                    term_start = False
                    continue
                if o.quotes and ch == '"':
                    text, i = _read_quoted(q, i + 1)
                    tokens.append((_TEXT, text, True))
                    term_start = False
                    continue
            if o.group_open and ch == o.group_open and not in_bracket:
                flush()
                items: List[Tuple[List[Token], str]] = []
                i += 1
                while True:
                    start = i
                    item, i, ended, stop = self.scan(i, True)
                    single = len(item) == 1 and item[0][0] == _TEXT and item[0][2]
                    items.append((item, item[0][1].strip() if single else q[start:stop].strip()))
                    if ended != o.list_char:
                        break
                tokens.append((_GROUP, items))
                term_start = False
                continue
            if (o.and_char and ch == o.and_char) or (
                    o.comma_joins and o.list_char and ch == o.list_char and not in_bracket):
                flush()
                tokens.append((_AND,))
                i += 1
                term_start = True
                continue
            if o.text_char and ch == o.text_char:
                if ch == ":" and len(buf) == 1 and buf[0].isalpha() and i + 1 < n and q[i + 1] in "\\/":
                    buf.append(ch)  # a drive letter (C:\...) is not a name:text search
                    i += 1
                    continue
                flush()
                tokens.append((_COLON,))
                i += 1
                term_start = True
                continue
            if o.not_char and ch == o.not_char and self._dash_starts_part(buf, i):
                # "invoice-old": a new part that leaves out files with "old"
                flush()
                tokens.append((_AND,))
                tokens.append((_NEG,))
                i += 1
                term_start = True
                continue
            buf.append(ch)
            term_start = False
            i += 1
        flush()
        return tokens, i, "eof", n

    def _dash_starts_part(self, buf: List[str], i: int) -> bool:
        q, n = self.q, len(self.q)
        if self.o.dash_mode == "word_start":
            return bool(buf) and buf[-1].isspace() and i + 1 < n and not q[i + 1].isspace()
        # Anywhere, except between two digits (2024-05)
        return not (buf and buf[-1].isdigit() and i + 1 < n and q[i + 1].isdigit())


def _has_text(tokens: Sequence[Token]) -> bool:
    return any(t[0] == _TEXT and t[1].strip() for t in tokens) or any(t[0] == _COLON for t in tokens)


def _expand(tokens: List[Token], max_groups: int) -> Tuple[bool, List[Tuple[List[Token], Optional[str]]]]:
    """Replace each [ ] by one of its elements: one token list per combination."""
    combos: List[Tuple[List[Token], List[str]]] = [([], [])]
    grouped = False
    for tok in tokens:
        if tok[0] != _GROUP:
            for flat, _ in combos:
                flat.append(tok)
            continue
        items = [(it, label) for it, label in tok[1] if _has_text(it)]
        if not items:
            continue
        grouped = True
        expanded: List[Tuple[List[Token], List[str]]] = []
        for flat, labels in combos:
            for item, label in items:
                if len(expanded) >= max_groups:
                    break
                expanded.append((flat + list(item), labels + [label]))
        combos = expanded
    return grouped, [(flat, " · ".join(labels) if labels else None) for flat, labels in combos]


# -- terms -------------------------------------------------------------------------

def _wild_pieces(text: str, wildcards: bool) -> List[Tuple[str, str]]:
    if not wildcards:
        return [("text", text)] if text else []
    pieces: List[Tuple[str, str]] = []
    buf: List[str] = []
    for ch in text:
        if ch in "*?":
            if buf:
                pieces.append(("text", "".join(buf)))
                buf = []
            if ch == "*":
                if not (pieces and pieces[-1][0] == "any"):
                    pieces.append(("any", ""))
            else:
                pieces.append(("one", ""))
        else:
            buf.append(ch)
    if buf:
        pieces.append(("text", "".join(buf)))
    return pieces


def _extract_exts(text: str) -> Tuple[str, List[str]]:
    """Take extension filters (words like ".xlsx") out of a file name part."""
    exts: List[str] = []
    words = re.split(r"(\s+)", text)
    for k, word in enumerate(words):
        m = _EXT_ONLY.fullmatch(word)
        if m:
            exts.append("." + m.group(1).lower())
            words[k] = ""
    return "".join(words), exts


def _normalize_pieces(pieces: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Join neighbours, collapse white space, trim both ends."""
    out: List[Tuple[str, str]] = []
    for kind, text in pieces:
        if kind == "text":
            text = re.sub(r"\s+", " ", text)
            if not text:
                continue
            if out and out[-1][0] == "text":
                out[-1] = ("text", out[-1][1] + text)
                continue
        elif kind == "any" and out and out[-1][0] == "any":
            continue
        out.append((kind, text))
    if out and out[0][0] == "text":
        out[0] = ("text", out[0][1].lstrip())
    if out and out[-1][0] == "text":
        out[-1] = ("text", out[-1][1].rstrip())
    return [p for p in out if p[0] != "text" or p[1]]


def _make_term(segments: List[Tuple[str, bool]], negated: bool, names: bool, opts: SearchOptions) -> Term:
    """names: the term is (also) matched against file names, so extensions and exact names apply."""
    # Neighbouring plain segments are one text (for "[invoice, receipt].xlsx")
    merged: List[Tuple[str, bool]] = []
    for text, lit in segments:
        if merged and not lit and not merged[-1][1]:
            merged[-1] = (merged[-1][0] + text, False)
        else:
            merged.append((text, lit))
    pieces: List[Tuple[str, str]] = []
    exts: List[str] = []
    for text, lit in merged:
        if lit:
            pieces.append(("text", text))
        else:
            if names and opts.extensions:
                text, found = _extract_exts(text)
                exts.extend(found)
            pieces.extend(_wild_pieces(text, opts.wildcards))
    literal = bool(merged) and all(lit for _, lit in merged)
    term = Term(pieces=_normalize_pieces(pieces), negated=negated, literal=literal, exts=exts)
    # A name with an extension at the end is the whole file name
    term.exact = names and opts.exact_names and not literal and bool(_EXACT_NAME.fullmatch(term.text))
    return term


def _terms(tokens: List[Token], names: bool, opts: SearchOptions) -> List[Term]:
    terms: List[Term] = []
    chunk: List[Token] = []

    def close() -> None:
        if not chunk:
            return
        negated = chunk[0][0] == _NEG
        segments: List[Tuple[str, bool]] = []
        for k, tok in enumerate(chunk):
            if tok[0] == _TEXT:
                segments.append((tok[1], tok[2]))
            elif tok[0] == _NEG and k > 0:
                segments.append((opts.not_char, False))
            elif tok[0] == _COLON:
                segments.append((opts.text_char, False))
        if segments:
            terms.append(_make_term(segments, negated, names, opts))
        chunk.clear()

    for tok in tokens:
        if tok[0] == _AND:
            close()
        else:
            chunk.append(tok)
    close()
    return terms


def _bucket(scope: str) -> str:
    return {"names": "name_terms", "text": "content_terms"}.get(scope, "any_terms")


def _element(tokens: List[Token], label: Optional[str], opts: SearchOptions) -> Element:
    el = Element(label=label)
    colon = next((k for k, t in enumerate(tokens) if t[0] == _COLON), None)
    if colon is None:
        # Words without the text sign go where the settings say
        setattr(el, _bucket(opts.default_scope), _terms(tokens, opts.default_scope != "text", opts))
        if opts.default_scope == "text":
            # Extensions are still file filters, also when words search the text
            for t in el.content_terms:
                if opts.extensions and not t.literal:
                    rest, found = _extract_exts(t.text)
                    if found:
                        t.pieces = _normalize_pieces(_wild_pieces(rest, opts.wildcards))
                        t.exts = found
    else:
        el.has_colon = True
        el.name_terms = _terms(tokens[:colon], True, opts)
        el.content_terms = _terms(tokens[colon + 1:], False, opts)

    for bucket in ("name_terms", "content_terms", "any_terms"):
        kept: List[Term] = []
        for term in getattr(el, bucket):
            if term.is_blank:
                # Only extensions (".xlsx", "-.tmp", "*.pdf"): a file filter
                (el.exclude_exts if term.negated else el.exts).extend(term.exts)
                continue
            if not term.negated and term.exts:
                el.exts.extend(term.exts)
                term.exts = []
            kept.append(term)
        setattr(el, bucket, kept)
    el.exts = list(dict.fromkeys(el.exts))
    el.exclude_exts = list(dict.fromkeys(el.exclude_exts))
    return el


def _plain_element(query: str, opts: SearchOptions) -> Element:
    """Smart search off: the text as typed, one part, no special characters."""
    el = Element()
    text = re.sub(r"\s+", " ", query).strip()
    if text:
        setattr(el, _bucket(opts.default_scope), [Term(pieces=[("text", text)])])
    return el


def parse_query(query: str, opts: SearchOptions = DEFAULTS) -> QueryPlan:
    """Parse the search field with the given search settings."""
    if not opts.enabled:
        return QueryPlan(raw=query or "", grouped=False, elements=[_plain_element(query or "", opts)])
    text, segments = split_params(query or "", opts.param_char, opts.quotes, opts.group_open, opts.group_close)
    params, errors = parse_params(segments, opts.date_order)
    tokens, _, _, _ = _Scanner(text, opts).scan(0, False)
    grouped, combos = _expand(tokens, 60)
    elements = [_element(flat, label if grouped else None, opts) for flat, label in combos]
    return QueryPlan(raw=query or "", grouped=grouped, elements=elements or [Element()],
                     params=params, param_errors=errors)


# -- display -----------------------------------------------------------------------

_FIELDS = (("name_terms", "name"), ("content_terms", "text"), ("any_terms", "any"))


def explain(plan: QueryPlan) -> List[dict]:
    """Short chips that say what the search does (shared by every group)."""
    def chips(el: Element) -> List[Tuple[str, str, bool]]:
        out: List[Tuple[str, str, bool]] = []
        out += [("ext", e, False) for e in el.exts]
        out += [("not-ext", e, False) for e in el.exclude_exts]
        for bucket, fld in _FIELDS:
            for t in getattr(el, bucket):
                kind = ("not-" if t.negated else "") + ("exact" if t.exact and fld == "name" else fld)
                text = t.text + ("".join(" " + e for e in t.exts) if t.exts else "")
                out.append((kind, text, t.literal))
        return out

    lists = [chips(el) for el in plan.elements]
    common = [c for c in lists[0] if all(c in other for other in lists[1:])] if lists else []
    result = [{"kind": k, "text": t, "literal": lit} for k, t, lit in common]
    if plan.grouped:
        result.insert(0, {"kind": "groups", "text": str(len(plan.elements)), "literal": False})
    result += [{"kind": "param", "text": p.label, "literal": False} for p in plan.params]
    result += [{"kind": "param-error", "text": e, "literal": False} for e in plan.param_errors]
    return result


def highlight_terms(el: Element) -> List[dict]:
    """Positive terms for highlighting in names and previews."""
    out: List[dict] = []
    for bucket, fld in _FIELDS:
        for t in getattr(el, bucket):
            if not t.negated:
                out.append({**t.describe(), "field": fld})
    return out
