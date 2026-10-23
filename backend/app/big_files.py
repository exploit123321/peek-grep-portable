"""Large files: rules (Settings > Large files) for files whose text is indexed with larger limits.

A rule is a file type (".csv"), a part of the file name ("big" also matches bigdata.xlsx), or one
file (its full path). A file that matches any rule is read up to BIG_MAX_BYTES, and up to
BIG_TEXT_CHARS of its text go into the search index.
"""

import os
from typing import Any, Dict, List, Tuple

BIG_MAX_BYTES = 200 * 1024 * 1024
BIG_TEXT_CHARS = 100_000_000
MAX_RULES = 50
KINDS = ("type", "name", "file")


def normalize_rules(raw: Any) -> List[Dict[str, str]]:
    """Checked and cleaned rules: types as ".csv", names as typed, files as full paths.
    Empty values and duplicates go. ValueError for anything else."""
    if not isinstance(raw, list):
        raise ValueError("Large files must be a list of rules.")
    out: List[Dict[str, str]] = []
    seen = set()
    for rule in raw:
        if not isinstance(rule, dict) or rule.get("kind") not in KINDS or not isinstance(rule.get("value"), str):
            raise ValueError('Each rule needs a kind ("type", "name" or "file") and a value.')
        kind, value = rule["kind"], rule["value"].strip().strip('"')
        if not value:
            continue
        if kind == "type":
            value = "." + value.lstrip("*").lstrip(".").lower()
            if value == "." or any(ch in value for ch in "\\/:*?<>|"):
                raise ValueError(f"Not a file type: {rule['value']}. Use for example .xlsx")
        elif kind == "file":
            if not os.path.isabs(value):
                raise ValueError(f"A file needs its full path: {value}")
            value = os.path.normpath(value)
        if len(value) > 1024:
            raise ValueError("A rule can have at most 1024 characters.")
        key = (kind, os.path.normcase(value) if kind == "file" else value.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"kind": kind, "value": value})
    if len(out) > MAX_RULES:
        raise ValueError(f"At most {MAX_RULES} rules.")
    return out


def matches(rules: List[Dict[str, str]], path: str, filename: str, ext: str) -> bool:
    """True if the file matches any rule (names and types ignore case)."""
    for rule in rules:
        kind, value = rule["kind"], rule["value"]
        if kind == "type" and ext.lower() == value:
            return True
        if kind == "name" and value.lower() in filename.lower():
            return True
        if kind == "file" and os.path.normcase(os.path.normpath(path)) == os.path.normcase(value):
            return True
    return False


def sql_condition(rules: List[Dict[str, str]]) -> Tuple[str, Tuple[Any, ...]]:
    """The same test as matches() for files_meta rows, as SQL ("0" without rules)."""
    parts: List[str] = []
    args: List[Any] = []
    for rule in rules:
        kind, value = rule["kind"], rule["value"]
        if kind == "type":
            parts.append("extension = ?")
            args.append(value)
        elif kind == "name":
            parts.append("instr(lower(filename), ?) > 0")
            args.append(value.lower())
        else:
            parts.append("path = ? COLLATE NOCASE")
            args.append(value)
    return ("(" + " OR ".join(parts) + ")" if parts else "0"), tuple(args)


def new_rules(before: List[Dict[str, str]], after: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Rules in after that were not in before (their files are read again)."""
    old = {(r["kind"], r["value"].lower()) for r in before}
    return [r for r in after if (r["kind"], r["value"].lower()) not in old]
