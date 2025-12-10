# utils.py
# Copyright (c) 2025 Alex Prochot
#
# Parsing and naming helpers used across the L5K processor.
"""Parsing and naming helpers shared by parser/GUI/export."""


from __future__ import annotations
from typing import Optional


def paren_delta(line: str) -> int:
    """Return net '(' - ')' on this line, ignoring parentheses inside strings."""
    delta = 0
    in_str = False
    esc = False
    for ch in line:
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        else:
            if ch == '"':
                in_str = True
            elif ch == '(':
                delta += 1
            elif ch == ')':
                delta -= 1
    return delta


def extract_block_name(header_line: str, header: str) -> Optional[str]:
    """
    Extracts the name from lines like:
      'DATATYPE  DateTime (Description := "...")'
      'ADD_ON_INSTRUCTION_DEFINITION  MyAOI (Version := 1.0)'
    """
    import re
    m = re.search(r'^' + re.escape(header) + r'\s+([^\s(]+)', header_line)
    return m.group(1) if m else None


def match_aoi_param_name(stripped_line: str) -> Optional[str]:
    import re
    m = re.match(r'^([\w]+)\s+(?:OF|:)\s+([\w\.]+)', stripped_line)
    return m.group(1) if m else None


def match_aoi_local_name(stripped_line: str) -> Optional[str]:
    import re
    m = re.match(r'^([\w]+)\s*:\s*([\w]+)', stripped_line)
    return m.group(1) if m else None


def name_for_display(obj) -> str:
    """UDTMember has name_dims so this shows e.g. DATA[8]; others just use .name."""
    return obj.display_name() if hasattr(obj, "display_name") else getattr(obj, "name", "")
