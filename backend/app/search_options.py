"""Search settings: how the smart search reads the search field, and how results show.

Kept in data\\settings.json as "search": {...}. Missing keys use the defaults below, so an old
settings file keeps working. The app's Search settings panel writes this block.
"""

from dataclasses import asdict, dataclass, fields
from typing import Any, Dict, List, Tuple

SCOPES = ("names", "text", "both")
DASH_MODES = ("anywhere", "word_start")
SORTS = ("best", "newest", "oldest", "name", "size")
GROUPS_OPEN = ("auto", "all", "none")
PASTE_MODES = ("table", "groups", "text")
LIST_WHERE = ("names", "text")
LIST_MODES = ("groups", "together")
DATE_ORDERS = ("dmy", "mdy", "ymd")

# How the signs are named in messages
_SIGN_NAMES = {
    "text_char": "the text sign", "and_char": "the “every part” sign", "not_char": "the “leave out” sign",
    "literal_char": "the literal sign", "group_open": "the group start", "group_close": "the group end",
    "list_char": "the separator", "param_char": "the filter sign", "quotes": "quotes", "wildcards": "the wildcards", "extensions": "file types (.xlsx)",
}

# Characters that a search operator may use: punctuation only, never letters, digits, or spaces
_ALLOWED_CHARS = set("!#$%&*+,-./:;<=>?@[\\]^_`{|}~'\"")


@dataclass(frozen=True)
class SearchOptions:
    # Smart search
    enabled: bool = True              # off: the text is searched as typed, no special characters
    default_scope: str = "names"      # where words without the text sign go: names, text, or both
    text_char: str = ":"              # name:text separator ("" = off)
    and_char: str = "+"               # every part must hit ("" = off)
    not_char: str = "-"               # leave out ("" = off)
    dash_mode: str = "anywhere"       # not_char anywhere (invoice-old) or only at a word start (memo -draft)
    literal_char: str = "/"           # the rest is literal ("" = off)
    quotes: bool = True               # "text" is literal
    group_open: str = "["             # [a, b]: one group per element ("" = off)
    group_close: str = "]"
    list_char: str = ","              # separates the elements of a group
    param_char: str = ";"             # filters after it: ;dm from 01-03-2024 ;size>10mb ("" = off)
    date_order: str = "dmy"           # 01-03-2024 is day-month-year (dmy), month-day-year (mdy), or ymd
    comma_joins: bool = True          # outside a group, list_char joins parts like and_char
    extensions: bool = True           # ".xlsx" is a file type filter
    exact_names: bool = True          # "invoice.xlsx" is the whole file name
    wildcards: bool = True            # * and ?
    names_include_folders: bool = False  # names also match folder names below the working folder
    text_prefix: bool = True          # text words match word beginnings ("memo" finds "memos")
    # Results
    sort: str = "best"
    page_size: int = 60
    show_snippets: bool = True
    show_chips: bool = True
    groups_open: str = "auto"         # auto: a single group opens; all; none
    search_delay_ms: int = 110
    # Pasting a list (cells from Excel)
    paste_list: str = "table"         # table: edit first; groups: search at once; text: paste as text
    list_where: str = "names"
    list_mode: str = "groups"
    # Quick Look
    preview_highlight: bool = True
    preview_jump: bool = True
    type_to_find: bool = True

    def key(self) -> Tuple:
        return tuple(getattr(self, f.name) for f in fields(self))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


DEFAULTS = SearchOptions()

# Ready-made sets for the most common wishes. Only the keys listed change.
PRESETS: Dict[str, Dict[str, Any]] = {
    "smart": {**DEFAULTS.to_dict()},
    "smart_both": {**DEFAULTS.to_dict(), "default_scope": "both", "dash_mode": "word_start"},
    "classic": {**DEFAULTS.to_dict(), "enabled": False, "default_scope": "both"},
    "names_only": {**DEFAULTS.to_dict(), "enabled": False, "default_scope": "names"},
    "text_first": {**DEFAULTS.to_dict(), "default_scope": "text", "dash_mode": "word_start"},
}

PRESET_LABELS = {
    "smart": "Smart (names first, ':' for text)",
    "smart_both": "Smart, words in names and text",
    "classic": "Classic: names and text, no special characters",
    "names_only": "File names only, no special characters",
    "text_first": "Smart, words in the text first",
}


def merge(raw: Any) -> SearchOptions:
    """Options from settings.json; unknown or invalid values fall back to the defaults."""
    if not isinstance(raw, dict):
        return DEFAULTS
    cleaned, _ = validate({**DEFAULTS.to_dict(), **raw}, strict=False)
    return SearchOptions(**cleaned)


def validate(data: Dict[str, Any], strict: bool = True) -> Tuple[Dict[str, Any], List[str]]:
    """Check and clean the options. strict: report errors (else invalid values become defaults)."""
    errors: List[str] = []
    out: Dict[str, Any] = {}
    defaults = DEFAULTS.to_dict()
    choices = {
        "default_scope": SCOPES, "dash_mode": DASH_MODES, "sort": SORTS, "groups_open": GROUPS_OPEN,
        "paste_list": PASTE_MODES, "list_where": LIST_WHERE, "list_mode": LIST_MODES, "date_order": DATE_ORDERS,
    }
    ranges = {"page_size": (20, 500), "search_delay_ms": (0, 2000)}
    chars = ("text_char", "and_char", "not_char", "literal_char", "group_open", "group_close", "list_char", "param_char")

    for name, default in defaults.items():
        value = data.get(name, default)
        if isinstance(default, bool):
            if not isinstance(value, bool):
                errors.append(f"{name} must be true or false.")
                value = default
        elif isinstance(default, int):
            lo, hi = ranges[name]
            if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
                errors.append(f"{name} must be a number from {lo} to {hi}.")
                value = default
        elif name in choices:
            if value not in choices[name]:
                errors.append(f"{name} must be one of: {', '.join(choices[name])}.")
                value = default
        elif name in chars:
            value = value.strip() if isinstance(value, str) else value
            if not isinstance(value, str) or len(value) > 1 or (value and value not in _ALLOWED_CHARS):
                errors.append(f"{_SIGN_NAMES[name].capitalize()} must be one punctuation character, or empty to turn it off.")
                value = default
        out[name] = value

    # Brackets come in pairs; a group needs its separator
    if bool(out["group_open"]) != bool(out["group_close"]):
        errors.append("Groups need both an opening and a closing character (or neither).")
        out["group_open"] = out["group_close"] = ""
    if out["group_open"] and not out["list_char"]:
        errors.append("Groups need a separator character.")
        out["list_char"] = defaults["list_char"]

    # One meaning per character (quotes and wildcards included)
    used: Dict[str, str] = {}
    if out["quotes"]:
        used['"'] = "quotes"
    if out["wildcards"]:
        used["*"] = "wildcards"
        used["?"] = "wildcards"
    if out["extensions"] or out["exact_names"]:
        used["."] = "extensions"
    for name in chars:
        ch = out[name]
        if not ch:
            continue
        if ch in used and not (name == "list_char" and used[ch] == "list_char"):
            errors.append(f"“{ch}” can't be {_SIGN_NAMES[name]}: {_SIGN_NAMES.get(used[ch], used[ch])} already use{'' if used[ch] in ('quotes', 'wildcards') else 's'} it.")
            out[name] = ""
            continue
        used[ch] = name

    if not strict:
        return out, []
    return out, errors
