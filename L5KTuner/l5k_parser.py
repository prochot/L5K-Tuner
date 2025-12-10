# l5k_parser.py
# Copyright (c) 2025 Alex Prochot
#
# Parser and exporter for Rockwell L5K files with selection support.
"""Parser for Rockwell L5K text with export/filter helpers."""


from __future__ import annotations
import re
from typing import Set, Dict, List, Optional, Tuple
from dataclasses import dataclass
import textwrap

from . import models
from .l5k_types import SelectionDict
from . import exporter
from . import utils
from .strings import (
    first_outside_parens,
    split_outer_attrs,
    encode_l5k_string,
    dedent_lines,
    get_desc,
    set_desc,
    strip_attrs,
    RE_DESC,
)
from .patterns import (
    RE_CONTROLLER_HDR,
    RE_UDT_TYPEFIRST,
    RE_UDT_BIT_ALIAS,
    RE_FAMILYTYPE,
    RE_AOI_PARAM_DEF,
    RE_AOI_PARAM,
    RE_AOI_LOCALTAG,
    RE_TAG_PREFIX,
)

@dataclass
class TagBuffer:
    """
    Holds incremental parsing state for TAG statements (handles nested parens and quoted strings).
    feed() returns True when a top-level ';' is seen so callers can emit the accumulated statement.
    """
    parts: list[str]
    depth: int = 0
    in_sq: bool = False
    in_dq: bool = False
    esc: bool = False

    def reset(self) -> None:
        self.parts.clear()
        self.depth = 0
        self.in_sq = False
        self.in_dq = False
        self.esc = False

    def feed(self, chunk: str) -> bool:
        self.parts.append(chunk)
        complete = False
        for ch in chunk:
            if self.in_sq:
                if self.esc:
                    self.esc = False
                elif ch == '$':
                    self.esc = True
                elif ch == "'":
                    self.in_sq = False
                continue
            if self.in_dq:
                if self.esc:
                    self.esc = False
                elif ch == '$':
                    self.esc = True
                elif ch == '"':
                    self.in_dq = False
                continue

            if ch == "'":
                self.in_sq = True
                continue
            if ch == '"':
                self.in_dq = True
                continue
            if ch in '([{':
                self.depth += 1
                continue
            if ch in ')]}':
                if self.depth > 0:
                    self.depth -= 1
                continue
            if ch == ';' and self.depth == 0:
                complete = True
        return complete

    def flush(self) -> str:
        stmt = " ".join(self.parts)
        self.reset()
        return stmt


@dataclass
class ParseState:
    in_udt: bool = False
    in_aoi: bool = False
    in_aoi_params: bool = False
    in_aoi_localtags: bool = False
    in_controller: bool = False
    in_tags: bool = False
    in_program: bool = False
    in_prog_tags: bool = False
    cur_program: Optional[str] = None


@dataclass
class ExportState:
    in_udt: bool = False
    in_aoi: bool = False
    in_params: bool = False
    in_locals: bool = False
    in_controller: bool = False
    in_routine: bool = False
    in_tags: bool = False
    current_udt: Optional[str] = None
    current_aoi: Optional[str] = None


class L5KParser:
    """
    Parses L5K files and supports:
      • Extracting the file header block (always included in export)
      • Collecting UDTs (with hidden SINT 'word' → BIT children nesting)
      • Collecting AOIs (parameters & local tags), capturing multi-line definitions
      • Resolving AOI parameter 'OF' paths to base types
      • Collecting global TAGS (name, data type, description) from CONTROLLER/TAG
      • Exporting a filtered subset
    Notes:
      • AOI member definitions may span multiple lines and are captured from the
        first line through the first line that ends with ');'.
    """

    HEADER_OPEN_RE = re.compile(r'^(?:\ufeff)?\(\*{5,}\s*$')   # e.g., (********
    HEADER_CLOSE_RE = re.compile(r'^\*{5,}\)\s*$')             # e.g., ********)

    def __init__(self, file_content: str) -> None:
        self.file_content: str = file_content
        self.lines: List[str] = file_content.splitlines()
        self.project = models.L5KProject()
        self.corrected_tags_log: List[str] = []
        self.controller_name: str | None = None
        self.controller_header_lines: list[str] = []
        self.header_text: str = ""

    # ---------- Public API ----------
    def parse(self) -> Tuple[models.L5KProject, List[str]]:
        self._parse_header()
        self._parse_structures()
        self._resolve_nested_types()
        return self.project, self.corrected_tags_log

    # ---------- Internal parsing ----------
    def _parse_header(self) -> None:
        """
        Extract the header block and store in project.header.
        Header spans from the first line that matches HEADER_OPEN_RE
        through the first line that matches HEADER_CLOSE_RE, **plus the next 2 lines**.
        The body begins at the first line that starts with 'CONTROLLER' after that.
        """
        lines = self.lines
        n = len(lines)
        start: Optional[int] = None
        end: Optional[int] = None

        # Find open
        for i, ln in enumerate(lines):
            s = ln.lstrip('\ufeff').rstrip('\r\n')
            if self.HEADER_OPEN_RE.match(s.strip()):
                start = i
                break
        if start is None:
            return  # no header

        # Find close
        for j in range(start, n):
            s = lines[j].lstrip('\ufeff').rstrip('\r\n')
            if self.HEADER_CLOSE_RE.match(s.strip()):
                end = j
                break
        if end is None:
            end = start  # malformed header; at least include the open line

        # Include next two lines after the closing delimiter, if available
        end_inclusive = min(end + 2, n - 1)
        header_lines = lines[start:end_inclusive + 1]
        header_text = "\n".join(header_lines)
        self.header_text = header_text

        if hasattr(self.project, "header"):
            self.project.header = models.L5KHeader(header_text)  # type: ignore[attr-defined]

    def _parse_structures(self) -> None:
        """
        State machine to collect UDTs and AOIs into self.project.*
        Handles hidden SINT word + BIT alias hierarchy for UDTs.
        Captures full multi-line definitions for AOI members until a line ends with ');'.
        Also collects global TAGS from CONTROLLER/TAG.
        """
        lines = self.lines
        n = len(lines)
        i = 0
        project = self.project
        if project is None:
            return
        udts: Dict[str, models.UDT] = project.udts
        aois: Dict[str, models.AOI] = project.aois
        tags: Dict[str, models.Tag] = project.tags
        programs: Dict[str, models.Program] = project.programs

        state = ParseState()
        current_struct = None
        tag_buf = TagBuffer(parts=[])
        prog_tag_buf = TagBuffer(parts=[])

        def capture_block(start_idx: int) -> Tuple[str, int]:
            """
            Capture from start_idx up to and including a line that ends with ');'.
            Returns (joined_text, next_index_after_block).
            """
            acc = [lines[start_idx].rstrip("\n")]
            j = start_idx + 1

            first = lines[start_idx].strip()
            # If first line obviously single-line (ends with ';' and no '('), return it
            # 1) ends with ');' (with or without '(')
            # 2) or has no '(' and ends with ';'
            if first.endswith(');') or ( '(' not in first and first.endswith(';') ):
                text = textwrap.dedent("\n".join(acc)).strip("\n")
                return text, j
            
            depth = utils.paren_delta(lines[start_idx])
            while j < n:
                line_j = lines[j].rstrip("\n")
                acc.append(line_j)
                depth += utils.paren_delta(line_j)
                if depth == 0 and line_j.strip().endswith(';'):
                    j += 1
                    break
                j += 1
            
            text = textwrap.dedent("\n".join(acc)).strip("\n")
            return text, j

        while i < n:
            raw = lines[i]
            stripped = raw.strip()
            if not stripped:
                i += 1
                continue

            # --- Controller / Tags transitions
            if stripped.startswith("CONTROLLER"):
                state.in_controller = True

                # Capture header exactly once with proper delimiter
                if not getattr(self, "controller_header_lines", None):
                    hdr, j, ctrl_name = self._capture_controller_header(lines, i)
                    self.controller_header_lines = hdr          # list[str]
                    self.controller_name = ctrl_name            # optional, if you want to use it later
                    i = j
                    continue

                i += 1
                continue
            elif stripped.startswith("END_CONTROLLER"):
                state.in_controller = False
                i += 1
                continue

            if state.in_controller and (not state.in_program) and stripped == "TAG":
                state.in_tags = True
                tag_buf.reset()
                i += 1
                continue
            elif state.in_controller and (not state.in_program) and stripped == "END_TAG":
                # flush any partial tag before closing
                if tag_buf.parts:
                    self._emit_tag_spec(tag_buf.flush())
                else:
                    tag_buf.reset()
                state.in_tags = False
                i += 1
                continue

            if state.in_program and stripped == "TAG":
                state.in_prog_tags = True
                prog_tag_buf.reset()
                i += 1
                continue
            elif state.in_program and stripped == "END_TAG":
                if state.in_prog_tags and prog_tag_buf.parts and state.cur_program:
                    self._emit_prog_tag_spec(state.cur_program, prog_tag_buf.flush())
                else:
                    prog_tag_buf.reset()
                state.in_prog_tags = False
                i += 1
                continue

            # --- State transitions
            if stripped.startswith("DATATYPE"):
                # Capture the entire DATATYPE header (may span multiple lines) up to the closing ')'
                hdr_lines = [raw.rstrip("\n")]
                j = i + 1

                depth = utils.paren_delta(stripped)
                if depth > 0:
                    while j < n:
                        line_j = lines[j].rstrip("\n")
                        hdr_lines.append(line_j)
                        depth += utils.paren_delta(line_j)
                        j += 1
                        if depth <= 0:
                            break
                header_blob = " ".join(l.strip() for l in hdr_lines)

                # Log unballanced parens in header for debugging
                if utils.paren_delta(" ".join(hdr_lines)) != 0:
                    self.corrected_tags_log.append(
                        f"Unballanced parens in header starting at line {i+1}"
                    )

                # Name comes from the first header line
                name = utils.extract_block_name(hdr_lines[0].strip(), header="DATATYPE")
                if not name:
                    i = j
                    continue

                current_struct = models.UDT(name)
                # Fill description and FamilyType from the combined header blob
                set_desc(current_struct, header_blob)
                ft = self._get_family_type(header_blob)
                if ft:
                    current_struct.family_type = ft
                # else keep default "NoFamily"

                udts[name] = current_struct  # type: ignore[attr-defined]
                # Continue parsing on the first member line after the header
                i = j
                state.in_udt = True
                state.in_aoi = False
                state.in_aoi_params = False
                state.in_aoi_localtags = False
                continue
            elif stripped.startswith("END_DATATYPE"):
                state.in_udt = False
                current_struct = None
                i += 1
                continue
            elif stripped.startswith("ADD_ON_INSTRUCTION_DEFINITION"):
                state.in_aoi = True
                state.in_udt = False
                name = utils.extract_block_name(stripped, header="ADD_ON_INSTRUCTION_DEFINITION")
                if not name:
                    i += 1
                    continue
                current_struct = models.AOI(name)
                set_desc(current_struct, stripped)
                aois[name] = current_struct  # type: ignore[attr-defined]
                i += 1
                continue
            elif stripped.startswith("END_ADD_ON_INSTRUCTION_DEFINITION"):
                state.in_aoi = False
                current_struct = None
                i += 1
                continue

            # --- Encoded AOI header
            if stripped.startswith("ENCODED_DATA"):
                meta_lines = [raw.rstrip("\n")]
                j = i + 1
                # collect lines until we hit a closing ')' of the metadata parens
                while j < n:
                    meta_lines.append(lines[j].rstrip("\n"))
                    if ')' in lines[j]:
                        j += 1
                        break
                    j += 1
                meta_blob = " ".join(l.strip() for l in meta_lines)
                if "EncodedType := ADD_ON_INSTRUCTION_DEFINITION" in meta_blob:
                    mname = re.search(r'Name\s*:=\s*"([^"]+)"', meta_blob)
                    aoi_name = mname.group(1) if mname else None
                    if aoi_name:
                        state.in_aoi = True
                        state.in_udt = False
                        state.in_aoi_params = False
                        state.in_aoi_localtags = False
                        current_struct = models.AOI(aoi_name)
                        # set description from meta blob if present
                        set_desc(current_struct, meta_blob)
                        aois[aoi_name] = current_struct  # type: ignore[attr-defined]
                i = j
                continue

            if stripped.startswith("END_ENCODED_DATA"):
                state.in_aoi = False
                current_struct = None
                i += 1
                continue

            # --- PROGRAM start/end ---
            if stripped.startswith("PROGRAM"):
                # Extract program name (token immediately after PROGRAM, before any attrs)
                after_kw = raw.split("PROGRAM", 1)[1].lstrip()
                prog_name = after_kw.split(None, 1)[0] if after_kw else ""
                if "(" in prog_name:
                    prog_name = prog_name.split("(", 1)[0]

                desc = get_desc(raw) if prog_name else ""
                existing = programs.get(prog_name) if prog_name else None
                if prog_name and existing is None:
                    programs[prog_name] = models.Program(prog_name, desc or "")
                elif prog_name and existing and (not existing.description) and desc:
                    existing.description = desc

                state.in_program = bool(prog_name)
                state.cur_program = prog_name or None
                state.in_prog_tags = False
                i += 1
                continue
            elif stripped.startswith("END_PROGRAM"):
                # Flush any in-progress tag capture
                if state.in_prog_tags and prog_tag_buf.parts and state.cur_program:
                    self._emit_prog_tag_spec(state.cur_program, prog_tag_buf.flush())
                else:
                    prog_tag_buf.reset()

                state.in_program = False
                state.cur_program = None
                state.in_prog_tags = False
                i += 1
                continue

            # --- Tag lines within PROGRAM/TAG (incremental, multiline-safe) ---
            if state.in_program and state.in_prog_tags and state.cur_program:
                if prog_tag_buf.feed(raw.strip()):
                    self._emit_prog_tag_spec(state.cur_program, prog_tag_buf.flush())
                i += 1
                continue

            # --- Tag lines within CONTROLLER/TAG (incremental, multiline-safe) ---
            if state.in_controller and state.in_tags:
                chunk = raw.strip()

                if tag_buf.feed(chunk):
                    self._emit_tag_spec(tag_buf.flush())

                i += 1
                continue

            # --- Sub-state transitions within AOI
            if state.in_aoi:
                if stripped == "PARAMETERS":
                    state.in_aoi_params = True
                    i += 1
                    continue
                elif stripped == "END_PARAMETERS":
                    state.in_aoi_params = False
                    i += 1
                    continue
                elif stripped == "LOCAL_TAGS":
                    state.in_aoi_localtags = True
                    i += 1
                    continue
                elif stripped == "END_LOCAL_TAGS":
                    state.in_aoi_localtags = False
                    i += 1
                    continue

            # --- Data parsing
            if state.in_udt and isinstance(current_struct, models.UDT):
                # Hidden SINT word (10 'Z' prefix) acts as parent for following BIT aliases
                m = RE_UDT_TYPEFIRST.match(stripped)
                if m and m.group('dtype') == 'SINT' and m.group('name').startswith('Z' * 10):
                    name = m.group('name')
                    definition, i_next = capture_block(i)
                    member = current_struct.members.get(name)
                    if member is None:
                        member = models.UDTMember(
                            name, 'SINT',
                            description=get_desc(definition),
                            definition=definition.strip(),
                            is_hidden_parent=True # type: ignore[arg-type]
                        )
                        current_struct.add_member(member)
                    else:
                        member.data_type = 'SINT'
                        member.definition = definition.strip()
                        member.is_hidden_parent = True
                    i = i_next
                    continue

                # BIT alias line: BIT Alias WordName : <bit>;
                m = RE_UDT_BIT_ALIAS.match(stripped)
                if m:
                    alias = m.group('alias')
                    word = m.group('word')
                    bit = int(m.group('bit'))
                    definition, i_next = capture_block(i)
                    child = models.UDTMember(
                        alias, 'BOOL',
                        description=get_desc(definition),
                        definition=definition.strip(),
                        is_bit=True,
                        parent_word=word,
                        bit_index=bit # type: ignore[arg-type]
                    )
                    current_struct.add_member(child)
                    parent = current_struct.members.get(word)
                    if parent is None:
                        parent = models.UDTMember(
                            word, 'SINT',
                            description=get_desc(definition),
                            definition=None,
                            is_hidden_parent=True # type: ignore[arg-type]
                        )
                        current_struct.add_member(parent)
                    parent.add_child(child)
                    i = i_next
                    continue

                # UDT Type-first
                m = RE_UDT_TYPEFIRST.match(stripped)
                if m:
                    dtype, name = m.group('dtype'), m.group('name')
                    name_dims = m.group('name_dims') or ""
                    definition, i_next = capture_block(i)
                    current_struct.add_member(models.UDTMember(
                            name, dtype,
                            description=get_desc(definition),
                            definition=definition.strip(),
                            name_dims=name_dims,
                    ))  # type: ignore[arg-type]
                    i = i_next
                    continue

            elif state.in_aoi_params and isinstance(current_struct, models.AOI):
                m = RE_AOI_PARAM.match(stripped)
                if m:
                    name, dtype_or_path = m.groups()
                    definition, i_next = capture_block(i)
                    definition = self._strip_attrs(definition)
                    current_struct.add_parameter(
                        models.AOIParameter(
                            name,
                            dtype_or_path,
                            description=get_desc(definition),
                            definition=definition,
                        )
                    )  # type: ignore[arg-type]
                    i = i_next
                    continue
                i += 1
                continue

            elif state.in_aoi_localtags and isinstance(current_struct, models.AOI):
                m = RE_AOI_LOCALTAG.match(stripped)
                if m:
                    name, dtype = m.groups()
                    definition, i_next = capture_block(i)
                    definition = self._strip_attrs(definition)
                    current_struct.add_localtag(
                        models.AOILocalTag(
                            name,
                            dtype,
                            description=get_desc(definition),
                            definition=definition,
                        )
                    )  # type: ignore[arg-type]
                    i = i_next
                    continue
                i += 1
                continue

            # default advance
            i += 1

    def _resolve_nested_types(self) -> None:
        """
        Second pass: resolve AOI parameter base types for 'OF' paths.
        Only the FIRST LINE of the definition is rewritten to ': BaseType'.
        """
        for aoi in getattr(self.project, "aois", {}).values():
            for param in aoi.parameters.values():
                original_type = param.data_type
                if '.' in original_type:
                    base_type = self._find_base_type(original_type, aoi)
                    if base_type and base_type != original_type:
                        param.data_type = base_type
                        param.is_corrected = True
                        # update just the first line of the stored definition
                        if getattr(param, "definition", None):
                            lines = param.definition.splitlines()
                            first = lines[0]
                            # Replace "Name OF X.Y" or "Name : T" with "Name : BaseType"
                            first = re.sub(
                                r'^(\s*' + re.escape(param.name) + r')\s+(?:OF\s+[\w\.]+|:\s*[\w\.]+)',
                                r'\1 : ' + base_type,
                                first
                            )
                            lines[0] = first
                            param.definition = "\n".join(lines)
                        self.corrected_tags_log.append(
                            f'Corrected {aoi.name}.{param.name}: from "{original_type}" to "{base_type}"'
                        )

    def _get_header_and_body(self) -> Tuple[str, List[str]]:
        """
        Return (header_text, body_lines) for export purposes.
        """
        header_text = ""
        hdr = getattr(self.project, "header", None)
        if hdr is not None and getattr(hdr, "content", None):
            header_text = hdr.content  # type: ignore[attr-defined]

        # Find starting point for body after header
        start_idx = 0
        if header_text:
            header_len = len(header_text.splitlines())
            # find the first CONTROLLER after the header
            for k in range(header_len, len(self.lines)):
                if self.lines[k].strip().startswith("CONTROLLER"):
                    start_idx = k
                    break
            else:
                start_idx = header_len
        return header_text, self.lines[start_idx:]

    def get_selected_content(self, selection: SelectionDict) -> str:
        """
        Build a filtered .l5k containing only selected structures.
        'selection' keys:
          - 'udts': set[str]
          - 'udt_members': dict[str, set[str]]
          - 'aois': set[str]
          - 'aoi_parameters': dict[str, set[str]]
          - 'aoi_localtags': dict[str, set[str]]
          - 'tags': set[str]
          - 'program_tags': dict[str, set[str]]
        Content outside of DATATYPE/AOI/TAG blocks is preserved.
        Always includes the header at the top.
        """
        header_text, body_lines = self._get_header_and_body()
        out: List[str] = []
        if header_text:
            out.append(header_text)

        state = ExportState()
        sel_udts = selection.get("udts", set())
        sel_udt_members = selection.get("udt_members", {})
        sel_aois = selection.get("aois", set())
        sel_aoi_params = selection.get("aoi_parameters", {})
        sel_aoi_locals = selection.get("aoi_localtags", {})
        sel_tags = selection.get("tags", set())
        sel_prog_tags = selection.get("program_tags", {})

        # Buffers for conditional inclusion (block-level)
        block_lines: List[str] = []
        kept_lines: List[str] = []  # if non-empty at block close → emit block_lines

        # When we inject a full multi-line AOI member definition, skip original source lines
        skip_until_block_end = False

        def flush_block(end_line: str) -> None:
            nonlocal block_lines, kept_lines
            block_lines.append(end_line)
            if kept_lines:
                out.extend(block_lines)
            block_lines = []
            kept_lines = []

        i = 0
        body_len = len(body_lines)
        while i < body_len:
            line = body_lines[i]
            s = line.strip()

            # honor skipping source lines after we've emitted a full block definition
            if skip_until_block_end:
                if s.endswith(');'):
                    skip_until_block_end = False
                i += 1
                continue

            # --- Skip entire ROUTINE...END_ROUTINE blocks in export ---
            if state.in_routine:
                if s.startswith("END_ROUTINE"):
                    state.in_routine = False
                i += 1
                continue
            if s.startswith("ROUTINE"):
                state.in_routine = True
                i += 1
                continue

            # ----- CONTROLLER start/end -----
            if s.startswith("CONTROLLER"):
                state.in_controller = True
                hdr = getattr(self, "controller_header_lines", None)
                if hdr:
                    out.extend(hdr)
                    # consume the same number of source lines we just emitted
                    i += len(hdr)
                    continue
                else:
                    # fallback if header wasn't captured for some reason
                    out.append(line)
                    i += 1
                    continue
            if s.startswith("END_CONTROLLER"):
                state.in_controller = False
                if not state.in_routine:
                    if "DefaultData :=" not in s:
                        out.append(line)
                i += 1
                continue

            # ----- TAGS start/end -----
            if state.in_controller and s == "TAG":
                state.in_tags = True
                block_lines = [line]
                kept_lines = []
                i += 1
                continue
            if state.in_controller and s == "END_TAG":
                # finish TAG block; only emit if we kept any tag lines
                block_lines.append(line)
                if kept_lines:
                    out.extend(block_lines)
                block_lines = []
                kept_lines = []
                state.in_tags = False
                i += 1
                continue

            # Inside TAGS: rebuild only selected tags (omit values)
            if state.in_controller and state.in_tags:
                mm = re.match(r'^([\w\.]+)\s*:\s*', s)
                if mm:
                    tag_name = mm.group(1)
                    if tag_name in sel_tags:
                        # Mark that this TAG block has content to emit
                        kept_lines.append("")  # just a marker

                        # Reconstruct a clean, value-free tag definition from the parsed model
                        tag_obj = getattr(self.project, "tags", {}).get(tag_name)
                        indent = line[:len(line) - len(line.lstrip())]
                        if tag_obj and getattr(tag_obj, "definition", None):
                            for def_line in tag_obj.definition.splitlines():
                                block_lines.append(indent + def_line)
                        else:
                            # Fallback: chop off := value; keep prefix + attrs; end with ';'
                            idx_assign = self._first_outside_parens(s, ":=")
                            prefix = s if idx_assign == -1 else s[:idx_assign].rstrip()
                            block_lines.append(indent + prefix + ";")

                    # Always consume the source line; we never append the original line
                    i += 1
                    continue

            # ----- UDT start/end -----
            if s.startswith("DATATYPE"):
                state.in_udt = True
                m = re.search(r'^DATATYPE\s+([^\s(]+)', s)
                state.current_udt = m.group(1) if m else None
                udt_obj = self.project.udts.get(state.current_udt) if state.current_udt else None
                header_line = self._render_udt_header_line(udt_obj) if udt_obj else line
                block_lines = [header_line]
                kept_lines = []
                i += 1
                continue
            if s.startswith("END_DATATYPE"):
                flush_block(line)
                state.in_udt = False
                state.current_udt = None
                i += 1
                continue

            # ----- AOI start/end -----
            if s.startswith("ADD_ON_INSTRUCTION_DEFINITION"):
                state.in_aoi = True
                m = re.search(r'^ADD_ON_INSTRUCTION_DEFINITION\s+([^\s(]+)', s)
                state.current_aoi = m.group(1) if m else None
                state.in_params = False
                state.in_locals = False
                block_lines = [line]
                kept_lines = []
                i += 1
                continue
            if s.startswith("END_ADD_ON_INSTRUCTION_DEFINITION"):
                flush_block(line)
                state.in_aoi = False
                state.current_aoi = None
                state.in_params = False
                state.in_locals = False
                i += 1
                continue

            # ----- AOI start (ENCODED_DATA) -----
            if s.startswith("ENCODED_DATA"):
                # gather metadata block to extract name
                meta_lines = [line]
                j = i + 1
                body_len_inner = len(body_lines)
                while j < body_len_inner:
                    meta_line = body_lines[j]
                    meta_lines.append(meta_line)
                    if ')' in meta_line:
                        j += 1
                        break
                    j += 1
                meta_blob = " ".join(l.strip() for l in meta_lines)
                aoi_name = None
                if "EncodedType := ADD_ON_INSTRUCTION_DEFINITION" in meta_blob:
                    mname = re.search(r'Name\s*:=\s*"([^"]+)"', meta_blob)
                    aoi_name = mname.group(1) if mname else None

                state.in_aoi = True
                state.current_aoi = aoi_name
                state.in_params = False
                state.in_locals = False
                block_lines = meta_lines[:]  # include the metadata lines as part of the AOI block
                kept_lines = []
                i = j
                continue

            # ----- AOI end (ENCODED_DATA) -----
            if s.startswith("END_ENCODED_DATA"):
                flush_block(line)
                state.in_aoi = False
                state.current_aoi = None
                state.in_params = False
                state.in_locals = False
                i += 1
                continue

            # ----- Within UDT -----
            if state.in_udt and state.current_udt:
                # Detect UDT member name on this line
                member_name: Optional[str] = None
                # Type-first
                m = re.match(r'^(?P<dtype>\w+(?:\[\d+(?:,\d+)*\])?)\s+(?P<name>\w+)\b', s)
                if m:
                    member_name = m.group('name')
                # Name-first
                if member_name is None:
                    m = re.match(r'^(?P<name>\w+)\s*:\s*(?P<dtype>[\w\[\]\.]+);?', s)
                    if m:
                        member_name = m.group('name')
                # BIT alias
                if member_name is None:
                    m = re.match(r'^BIT\s+(?P<alias>\w+)\s+(?P<word>\w+)\s*:\s*(?P<bit>\d+)\b', s)
                    if m:
                        member_name = m.group('alias')

                if member_name is not None:
                    udt_selected = state.current_udt in sel_udts
                    members_sel = sel_udt_members.get(state.current_udt, set())
                    keep_line = False
                    if udt_selected or self._udt_member_should_keep(state.current_udt, member_name, members_sel):
                        keep_line = True

                    if keep_line:
                        kept_lines.append(line)

                block_lines.append(line)
                i += 1
                continue

            # ----- Within AOI -----
            if state.in_aoi and state.current_aoi:
                # Track section state
                if s == "PARAMETERS":
                    state.in_params = True
                    state.in_locals = False
                    block_lines.append(line)
                    i += 1
                    continue
                elif s == "END_PARAMETERS":
                    state.in_params = False
                    block_lines.append(line)
                    i += 1
                    continue
                elif s == "LOCAL_TAGS":
                    state.in_locals = True
                    state.in_params = False
                    block_lines.append(line)
                    i += 1
                    continue
                elif s == "END_LOCAL_TAGS":
                    state.in_locals = False
                    block_lines.append(line)
                    i += 1
                    continue

                aoi_selected = state.current_aoi in sel_aois
                keep_this_line = False

                if state.in_params:
                    handled, keep_this_line, skip_until_block_end = self._process_aoi_param_line(
                        state.current_aoi, s, sel_aoi_params, kept_lines, block_lines
                    )
                    if handled and skip_until_block_end:
                        i += 1
                        continue

                elif state.in_locals:
                    handled, keep_this_line, skip_until_block_end = self._process_aoi_local_line(
                        state.current_aoi, s, sel_aoi_locals, kept_lines, block_lines
                    )
                    if handled and skip_until_block_end:
                        i += 1
                        continue

                if keep_this_line:
                    kept_lines.append(line)

                block_lines.append(line)
                i += 1
                continue

            # ----- Outside any block -----
            if not state.in_routine:
                if "DefaultData :=" not in s:
                    out.append(line)
            i += 1

        return "\n".join(out)

    def export_whitelist(self, selection: SelectionDict) -> str:
        return exporter.export_whitelist(self, selection)

    def _parse_tag_fields(self, buf: str, strip_paren_from_dtype: bool = False) -> Optional[tuple[str, str, str, str]]:
        """
        Shared parser for controller/program TAG statements.
        Returns (name, dtype, desc, definition) or None if malformed.
        """
        stmt = buf.strip()

        idx_assign = self._first_outside_parens(stmt, ":=")
        left = stmt if idx_assign == -1 else stmt[:idx_assign].rstrip()

        idx_force = self._first_outside_parens(left, ",")
        if idx_force != -1:
            left = left[:idx_force].rstrip()

        prefix, attrs = self._split_outer_attrs(left)

        m = RE_TAG_PREFIX.match(prefix)
        if not m:
            return None

        name = m.group(1)
        dtype = (m.group(3) or "").strip()
        if strip_paren_from_dtype and '(' in dtype:
            dtype = dtype.split('(', 1)[0].strip()

        desc = get_desc(attrs) if attrs else ""

        definition = prefix
        if attrs:
            definition = f"{prefix} ({attrs})"
        if not definition.endswith(";"):
            definition = definition.rstrip() + ";"

        return name, dtype, desc, definition

    def _emit_tag_spec(self, buf: str) -> None:
        """Parse a controller TAG statement (ignores := values and force data)."""
        fields = self._parse_tag_fields(buf, strip_paren_from_dtype=False)
        if not fields:
            return
        name, dtype, desc, definition = fields

        self.project.tags[name] = models.Tag(
            name=name,
            data_type=dtype,
            description=desc,
            definition=definition
        )

    def _emit_prog_tag_spec(self, prog: Optional[str], buf: str) -> None:
        """Parse a PROGRAM TAG statement and attach it to the owning Program."""
        if not prog or prog not in getattr(self.project, "programs", {}):
            return

        fields = self._parse_tag_fields(buf, strip_paren_from_dtype=True)
        if not fields:
            return
        name, dtype, desc, definition = fields

        self.project.programs[prog].tags[name] = models.Tag(
            name=name,
            data_type=dtype,
            description=desc,
            definition=definition,
        )

    # ---------- Helpers ----------
    @staticmethod
    def _dedent_lines(def_text: str) -> list[str]:
        """
        Remove common leading whitespace from a stored multi-line definition while
        preserving relative indentation between its lines.
        """
        return dedent_lines(def_text)

    @staticmethod
    def _extract_block_name(header_line: str, header: str) -> Optional[str]:
        """
        Extracts the name from lines like:
          'DATATYPE  DateTime (Description := "...")'
          'ADD_ON_INSTRUCTION_DEFINITION  MyAOI (Version := 1.0)'
        """
        m = re.search(r'^' + re.escape(header) + r'\s+([^\s(]+)', header_line)
        return m.group(1) if m else None

    @staticmethod
    def _match_aoi_param_name(stripped_line: str) -> Optional[str]:
        m = re.match(r'^([\w]+)\s+(?:OF|:)\s+([\w\.]+)', stripped_line)
        return m.group(1) if m else None

    @staticmethod
    def _match_aoi_local_name(stripped_line: str) -> Optional[str]:
        m = re.match(r'^([\w]+)\s*:\s*([\w]+)', stripped_line)
        return m.group(1) if m else None

    def _encode_l5k_string(self, s: str) -> str:
        """
        Encode a Python string as an L5K string literal:
        - $ escapes the next character, so escape $ itself
        - escape double- and single-quotes
        (You can expand this later for $N, $R if you need CR/LF.)
        """
        return encode_l5k_string(s)

    def _emit_param_as_plain_bool(self, p, base_indent: str) -> list[str]:
        """
        Rewrite a bit-of-word alias parameter (marked p.is_bit_alias) to a plain ': BOOL'
        parameter while preserving the original attribute list.
        Output shape:
            <name> : BOOL (
                ...attrs...
            );
        Falls back to a minimal ': BOOL ();' if parsing fails or attrs are missing.
        """
        lines: list[str] = []
        if not getattr(p, "definition", None):
            # Minimal fallback
            lines.append(f"{base_indent}{p.name} : BOOL ();")
            return lines

        # The captured definition is a full multi-line header like:
        #   Name OF Com_AE.0 ( ...attrs... );
        m = RE_AOI_PARAM_DEF.match(p.definition.strip())
        if not m:
            # Couldn't parse—fallback, but keep Description if we have it
            if getattr(p, "description", ""):
                lines.append(f'{base_indent}{p.name} : BOOL (')
                lines.append(f'{base_indent}    Description := "{p.description}"')
                lines.append(f'{base_indent});')
            else:
                lines.append(f"{base_indent}{p.name} : BOOL ();")
            return lines

        attrs_blob = m.group("attrs") or ""
        attr_lines = self._dedent_lines(attrs_blob)

        lines.append(f"{base_indent}{p.name} : BOOL (")
        for a in attr_lines:
            if a:  # skip blank lines
                lines.append(f"{base_indent}    {a.rstrip()}")
        lines.append(f"{base_indent});")
        return lines

    def _capture_controller_header(self, lines: list[str], i: int) -> tuple[list[str], int, str | None]:
        """
        Capture the CONTROLLER header lines exactly:
        - Always include the 'CONTROLLER <name>' line.
        - If an attribute list is present, include lines until the matching ')'.
        - Also accept styles where the '(' begins on the next line.
        Returns (header_lines, next_index_after_header, controller_name).
        """
        n = len(lines)
        first = lines[i].rstrip("\n")
        header = [first]

        # Name + whether '(' started on this line
        m = RE_CONTROLLER_HDR.match(first.strip())
        name = m.group(1) if m else None

        # Track parentheses depth across possible multi-lines
        depth = utils.paren_delta(first)
        j = i + 1

        # If no '(' on the first line, but the very next line starts an attribute list, include it
        if depth == 0 and j < n and lines[j].lstrip().startswith("("):
            header.append(lines[j].rstrip("\n"))
            depth += utils.paren_delta(lines[j])
            j += 1

        # If attribute list started, include lines until depth returns to zero
        while j < n and depth > 0:
            header.append(lines[j].rstrip("\n"))
            depth += utils.paren_delta(lines[j])
            j += 1

        return header, j, name

    def _get_family_type(self, text: str) -> Optional[str]:
        """
        Extract FamilyType from a DATATYPE header blob.
        Example: 'DATATYPE MyType (Description := "x", FamilyType := NoFamily)'
        """
        m = RE_FAMILYTYPE.search(text)
        return m.group(1) if m else None

    def _find_base_type(self, path: str, context_aoi) -> str:
        """
        Attempt to resolve a base type when a parameter references something like
        LocalTag.Param or AOI.Param via 'OF' or direct ':' type paths.
        """
        base_data_types = {'BOOL', 'SINT', 'INT', 'DINT', 'LINT', 'REAL'}
        if path in base_data_types:
            return path
        if '.' not in path:
            return path

        root_name, member_name = path.split('.', 1)

        if root_name in context_aoi.localtags and member_name.isdigit():
            word_dt = context_aoi.localtags[root_name].data_type.upper()
            if word_dt in ("SINT", "INT", "DINT", "LINT"):
                return "BOOL"

        # Resolve via local tag reference into another AOI, if present
        if root_name in context_aoi.localtags:
            parent_aoi_name = context_aoi.localtags[root_name].data_type
            parent = getattr(self.project, "aois", {}).get(parent_aoi_name)
            if parent and member_name in parent.parameters:
                return self._find_base_type(parent.parameters[member_name].data_type, parent)
        return path

    def _name_for_display(self, obj) -> str:
        return utils.name_for_display(obj)

    def _udt_member_should_keep(self, udt_name: str, member_name: str, members_sel: set[str]) -> bool:
        """
        Decide whether to keep a UDT member line when exporting with selection.
        Keeps the member if explicitly selected, or if it is a hidden SINT 'word' whose
        selected bit-children need to be retained.
        """
        if member_name in members_sel:
            return True
        udt_obj = self.project.udts.get(udt_name) if hasattr(self.project, "udts") else None
        parent = udt_obj.members.get(member_name) if udt_obj else None
        if parent and getattr(parent, "children", None):
            child_names = set(parent.children.keys())
            return bool(child_names & members_sel)
        return False

    def _process_aoi_param_line(self, aoi_name: str, stripped_line: str, params_sel_map: dict[str, set[str]],
                                kept_lines: list[str], block_lines: list[str]) -> tuple[bool, bool, bool]:
        """
        Handle AOI parameter lines during export.
        Returns (handled, keep_this_line, skip_until_block_end)
        """
        name = self._match_aoi_param_name(stripped_line)
        if name is None:
            return False, False, False

        params_sel = params_sel_map.get(aoi_name, set())
        keep_this_line = name in params_sel

        aoi_obj = self.project.aois.get(aoi_name) if hasattr(self.project, "aois") else None
        param_obj = aoi_obj.parameters.get(name) if aoi_obj else None
        if param_obj and param_obj.definition:
            def_lines = param_obj.definition.splitlines()
            kept_lines.extend(def_lines)
            block_lines.extend(def_lines)
            return True, keep_this_line, True
        return True, keep_this_line, False

    def _process_aoi_local_line(self, aoi_name: str, stripped_line: str, locals_sel_map: dict[str, set[str]],
                                kept_lines: list[str], block_lines: list[str]) -> tuple[bool, bool, bool]:
        """
        Handle AOI local tag lines during export.
        Returns (handled, keep_this_line, skip_until_block_end)
        """
        name = self._match_aoi_local_name(stripped_line)
        if name is None:
            return False, False, False

        locals_sel = locals_sel_map.get(aoi_name, set())
        keep_this_line = name in locals_sel
        aoi_obj = self.project.aois.get(aoi_name) if hasattr(self.project, "aois") else None
        local_obj = aoi_obj.localtags.get(name) if aoi_obj else None
        if local_obj and local_obj.definition:
            def_lines = local_obj.definition.splitlines()
            kept_lines.extend(def_lines)
            block_lines.extend(def_lines)
            return True, keep_this_line, True
        return True, keep_this_line, False

    # --- TAG parsing helpers (spec-compliant) ---
    def _first_outside_parens(self, s: str, target: str) -> int:
        """
        Return the index of the first occurrence of `target` that is outside (), [], {}
        and outside both single- and double-quoted strings. -1 if none.
        """
        return first_outside_parens(s, target)

    def _split_outer_attrs(self, left: str) -> tuple[str, str]:
        """
        If `left` ends with a single, balanced '(...)' at top level, split and return (prefix, attrs_inside).
        Else return (left, "").
        """
        return split_outer_attrs(left)

    def _strip_attrs(self, definition: str, names: tuple[str, ...] = ('DefaultData',)) -> str:
        """
        Remove any attributes listed in 'names' (case-insensitive) from the (...) attribute list
        of a single AOI PARAMETER/LOCAL_TAG definition. Currently optimized for 'DefaultData'.
        """
        return strip_attrs(definition, names)

    def _stmt_has_terminating_semicolon(self, buf: str) -> bool:
        """True if there is a ';' outside (...) and "..." (end of statement)."""
        return self._first_outside_parens(buf, ';') != -1
    
    def _render_udt_header_line(self, udt: models.UDT, indent: str = "\t") -> str:
        """
        Emit: DATATYPE <name> (Description := "x", FamilyType := Y)
        Only includes Description if present.
        """
        attrs = []
        if getattr(udt, "description", ""):
            # keep original quotes and escapes in description as-is
            attrs.append(f'Description := "{udt.description}"')
        ft = getattr(udt, "family_type", None) or "NoFamily"
        attrs.append(f"FamilyType := {ft}")
        inside = ", ".join(attrs)
        return f'{indent}DATATYPE {udt.name} ({inside})'

    def _render_program_header_line(self, program: models.Program, indent: str = "\t") -> str:
        """
        Emit a PROGRAM header line, including Description when present.
        """
        desc = getattr(program, "description", "")
        if isinstance(desc, str) and desc.strip():
            enc = self._encode_l5k_string(desc)
            return f'{indent}PROGRAM {program.name} (Description := "{enc}")'
        return f"{indent}PROGRAM {program.name}"

    def _ensure_header_for_export(self) -> None:
        """
        Make sure self.header_text is populated before export.
        Prefer the already-parsed project.header; if missing, rescan the file.
        """
        if getattr(self, "header_text", ""):
            return
        hdr = getattr(self.project, "header", None)
        if hdr is not None and getattr(hdr, "content", None):
            self.header_text = hdr.content  # keep a string on the parser
            return
        # last resort: parse the header from self.lines
        self._parse_header()

    def _ensure_controller_header(self) -> None:
        """
        Ensure controller header lines (CONTROLLER ... [attrs]) are available on the parser.
        If they weren’t captured during parse (e.g. different instance), capture them now.
        """
        if getattr(self, "controller_header_lines", None):
            return
        # find first CONTROLLER and capture its header block
        for idx, ln in enumerate(self.lines):
            if ln.strip().startswith("CONTROLLER"):
                hdr, j, ctrl_name = self._capture_controller_header(self.lines, idx)
                self.controller_header_lines = hdr
                self.controller_name = ctrl_name
                break

    def _pad_local_tags(self, aoi) -> str:
        """
        Generate a unique placeholder local tag name that won’t collide
        with existing AOI local tag names.
        """
        base = "__Pad"
        name = base
        existing = set(getattr(aoi, "localtags", {}).keys())
        suffix = 1
        while name in existing:
            suffix += 1
            name = f"{base}{suffix}"
        return name

# ---- Worker helper for multiprocessing ----
def parse_text_worker(file_content: str):
    """Run the L5KParser in a separate process and return (project, corrected_log)."""
    parser_inst = L5KParser(file_content)
    return parser_inst.parse()
