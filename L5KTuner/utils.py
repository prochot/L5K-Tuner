# utils.py
# Copyright (c) 2025 Alex Prochot
#
# Parsing and naming helpers used across the L5K processor.
"""Parsing and naming helpers shared by parser/GUI/export."""


from __future__ import annotations
import logging
import os
import pathlib
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


def configure_logging(app_name: str = "L5K Tuner", log_name: str = "l5k_tuner.log") -> None:
    """Configure file logging in a user-writable location."""
    log_path = get_log_path(app_name, log_name)
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler):
            handler_path = pathlib.Path(getattr(handler, "baseFilename", ""))
            if handler_path and handler_path.resolve() == log_path.resolve():
                return
    handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)


def get_log_path(app_name: str = "L5K Tuner", log_name: str = "l5k_tuner.log") -> pathlib.Path:
    log_dir_override = os.getenv("L5KTUNER_LOG_DIR")
    if log_dir_override:
        log_dir = pathlib.Path(log_dir_override)
    else:
        base = os.getenv("USERPROFILE")
        base_dir = pathlib.Path(base) if base else pathlib.Path.home()
        log_dir = base_dir / "Documents" / "EWEB Apps" / app_name / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / log_name
