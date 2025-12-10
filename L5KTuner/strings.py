# strings.py
# Copyright (c) 2025 Alex Prochot
#
# String parsing and encoding helpers for L5K content.
"""String parsing, attribute splitting, and encoding helpers for L5K lines."""

from __future__ import annotations
import re
import textwrap

RE_DESC = re.compile(r'Description\s*:=\s*"([^"]*)"', re.DOTALL | re.IGNORECASE)
RE_ATTR_DEFAULTDATA_LEADCOMMA = re.compile(
    r',\s*DefaultData\s*:=\s*(\([^\)]*\)|"[^"]*"|[^,)]*)\s*(?=,|\))',
    re.IGNORECASE | re.DOTALL
)
RE_ATTR_DEFAULTDATA_TRAILCOMMA = re.compile(
    r'DefaultData\s*:=\s*(\([^\)]*\)|"[^"]*"|[^,)]*)\s*,\s*',
    re.IGNORECASE | re.DOTALL
)
RE_ATTR_DEFAULTDATA_END = re.compile(
    r'(?:,\s*)?DefaultData\s*:=\s*(\([^\)]*\)|"[^"]*"|[^,)]*)\s*(?=\))',
    re.IGNORECASE | re.DOTALL
)


def first_outside_parens(s: str, target: str) -> int:
    """
    Return the index of the first occurrence of `target` that is outside (), [], {}
    and outside both single- and double-quoted strings. -1 if none.
    """
    depth = 0
    in_sq = False   # Inside single quoted string
    in_dq = False   # Inside double quoted string
    esc = False
    for i, ch in enumerate(s):
        if in_sq:
            if esc:
                esc = False
            elif ch == '$':
                esc = True
            elif ch == "'":
                in_sq = False
            continue
        if in_dq:
            if esc:
                esc = False
            elif ch == '$':
                esc = True
            elif ch == '"':
                in_dq = False
            continue

        # not in string
        if ch == "'":
            in_sq = True
            continue
        if ch == '"':
            in_dq = True
            continue
        if ch in '([{':
            depth += 1
            continue
        if ch in ')]}':
            if depth > 0:
                depth -= 1
            continue

        if depth == 0 and s.startswith(target, i):
            return i
    return -1


def split_outer_attrs(left: str) -> tuple[str, str]:
    """
    If `left` ends with a single, balanced '(...)' at top level, split and return (prefix, attrs_inside).
    Else return (left, "").
    """
    s = left.rstrip()
    idx_last = s.rfind(")")

    # Remove everything after last ')'
    if idx_last != -1:
        s = s[:idx_last+1]

    if not s.endswith(')'):
        return left, ""
    # find matching '(' for the last ')'
    depth = 0
    start = None
    for i, ch in enumerate(s):
        if ch == '(':
            if depth == 0:
                start = i
            depth += 1
        elif ch == ')':
            depth -= 1
    # balanced and attrs end at the very end?
    if start is not None and depth == 0:
        return s[:start].rstrip(), s[start+1:-1]
    return left, ""


def encode_l5k_string(s: str) -> str:
    """
    Encode a Python string as an L5K string literal:
    - $ escapes the next character, so escape $ itself
    - escape double- and single-quotes
    - escape CR/LF
    """
    if not isinstance(s, str):
        return ""

    out = s.replace("$", "$$")
    out = out.replace('"', '$"').replace("'", "$'")
    out = out.replace("\r", "$R").replace("\n", "$N")

    return out


def dedent_lines(def_text: str) -> list[str]:
    """
    Remove common leading whitespace from a stored multi-line definition while
    preserving relative indentation between its lines.
    """
    if not def_text:
        return []
    return textwrap.dedent(def_text).strip("\n").splitlines()


def get_desc(text: str) -> str:
    """Extract Description := \"...\" from a text blob."""
    m = RE_DESC.search(text)
    return m.group(1) if m else ""


def set_desc(obj, text: str) -> None:
    """Set obj.description if present and a Description attribute is found in text."""
    desc = get_desc(text)
    if hasattr(obj, "description") and desc:
        obj.description = desc


def strip_attrs(definition: str, names: tuple[str, ...] = ("DefaultData",)) -> str:
    """
    Remove attributes listed in 'names' (case-insensitive) from the (...) list of a single
    AOI PARAMETER/LOCAL_TAG definition. Optimized for DefaultData removal.
    """
    if not definition or 'DefaultData' not in definition:
        return definition

    s = definition
    for _ in range(2):
        s2 = RE_ATTR_DEFAULTDATA_LEADCOMMA.sub('', s)
        s2 = RE_ATTR_DEFAULTDATA_TRAILCOMMA.sub('', s2)
        s2 = RE_ATTR_DEFAULTDATA_END.sub('', s2)
        if s2 == s:
            break
        s = s2
    return s
