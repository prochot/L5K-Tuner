# exporter.py
# Copyright (c) 2025 Alex Prochot
#
# Helpers for building filtered L5K output and selection exports.
"""Utilities for emitting filtered L5K text from selection structures."""

from __future__ import annotations
from typing import List
import re

from .l5k_types import SelectionDict
from . import models


def export_whitelist(parser, selection: SelectionDict) -> str:
    """
    Construct a clean L5K from the parsed Project and the selection:
    - Header
    - CONTROLLER header (original lines)
    - Selected UDTs (with only selected members)
    - Selected AOIs (minimal header + selected params/local tags)
    - Controller TAG block (selected tags, no := values)
    - Program TAG blocks (selected program tags)
    - END_CONTROLLER
    Everything else is omitted by design.
    """
    out: list[str] = []

    # Ensure header/controller header are present on this parser instance
    parser._ensure_header_for_export()
    parser._ensure_controller_header()

    # 1) Header
    hdr_obj = getattr(parser.project, "header", None)
    header_blob = parser.header_text or (hdr_obj.content if hdr_obj and getattr(hdr_obj, "content", None) else "")
    if header_blob:
        out.append(header_blob.rstrip("\n"))
        out.append("")

    # 2) CONTROLLER header
    hdr_lines = getattr(parser, "controller_header_lines", None)
    if hdr_lines:
        out.extend(hdr_lines)
    else:
        # Fallback if no capture (should not happen if _capture_controller_header ran)
        cname = getattr(parser, "controller_name", None) or "Controller"
        out.append(f"CONTROLLER {cname}")

    indent = "\t"             # one-level indent for sections inside CONTROLLER

    # 3) UDTs
    udt_sel = selection.get("udts", set())
    for name, udt in parser.project.udts.items():
        if name not in udt_sel:
            continue
        out.extend(udt.to_l5k(indent))
        out.append("")  # blank line for readability

    # 4) AOIs (filtered; no ENCODED_DATA emission)
    aoi_sel = selection.get("aois", set())
    params_sel_map = selection.get("aoi_parameters", {})
    locals_sel_map = selection.get("aoi_localtags", {})

    for name, aoi in parser.project.aois.items():
        sel_params = params_sel_map.get(name, set())
        sel_locals = locals_sel_map.get(name, set())

        if (name not in aoi_sel) and not sel_params and not sel_locals:
            continue

        # AOI header
        desc = getattr(aoi, "description", "")
        if isinstance(desc, str) and desc.strip():
            enc = parser._encode_l5k_string(desc)
            out.append(f'{indent}ADD_ON_INSTRUCTION_DEFINITION {name} (Description := "{enc}")')
        else:
            out.append(f"{indent}ADD_ON_INSTRUCTION_DEFINITION {name} ()")

        # PARAMETERS section (only when there are parameters selected)
        if sel_params:
            out.append(f"{indent*2}PARAMETERS")
            for pname, p in aoi.parameters.items():
                if pname in sel_params:
                    out.extend(p.to_l5k(level=3, indent=indent))
            out.append(f"{indent*2}END_PARAMETERS")
            out.append("") # blank line for readability

        # LOCAL_TAGS section (only selected locals; include placeholder if none)
        out.append(f"{indent*2}LOCAL_TAGS")
        emitted_local = 0
        for lname, t in aoi.localtags.items():
            if lname in sel_locals:
                out.extend(t.to_l5k(level=3, indent=indent))
                emitted_local += 1

        if emitted_local == 0 and name in aoi_sel:
            out.append(f'{indent*3}__PlaceHolder : BOOL (Description := "Required for AVEVA Edge");')

        out.append(f"{indent*2}END_LOCAL_TAGS")
        out.append("")  # blank line for readability
        out.append(f"{indent}END_ADD_ON_INSTRUCTION_DEFINITION")
        out.append("")  # blank line for readability

    # 5) Controller TAGS (value-free; you already store cleaned definitions)
    tag_sel = selection.get("tags", set())
    if tag_sel:
        out.append(f"{indent}TAG")
        # Preserve original order by iterating project.tags and filtering by selection
        for tname, tag in parser.project.tags.items():
            if tname not in tag_sel:
                continue
            # prints name + type (+ Description) without values
            out.extend(tag.to_l5k(level=2, indent=indent))
        out.append(f"{indent}END_TAG")
        out.append("")

    # 6) Program TAG blocks
    program_tag_sel = selection.get("program_tags", {})
    for pname, prog in parser.project.programs.items():
        sel_prog_tags = program_tag_sel.get(pname, set())
        if not sel_prog_tags:
            continue

        out.append(parser._render_program_header_line(prog, indent))
        out.append(f"{indent*2}TAG")
        for tname, tag in prog.tags.items():
            if tname in sel_prog_tags:
                out.extend(tag.to_l5k(level=3, indent=indent))
        out.append(f"{indent*2}END_TAG")
        out.append(f"{indent}END_PROGRAM")
        out.append("")

    # 7) END_CONTROLLER
    out.append("END_CONTROLLER")
    out.append("")  # trailing newline

    return "\n".join(out)
