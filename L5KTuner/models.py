# models.py
# Copyright (c) 2025 Alex Prochot
#
# Data models representing L5K headers, tags, UDTs, AOIs, and programs.
"""Domain models for L5K headers, UDTs, AOIs, tags, and programs."""


from __future__ import annotations
from collections import OrderedDict
from typing import Dict, Optional, Iterable, List
from enum import Enum, auto
from dataclasses import dataclass, field
import re

_RE_PARAM_HDR = re.compile(
    r'^\s*(?P<name>\w+)\s+(?P<cat>OF|:)\s+(?P<rhs>[\w\.\:]+)\s*\((?P<attrs>.*)\)\s*;?\s*$',
    re.DOTALL
)

TAB = "\t"

class MemberType(Enum):
    # Tree/meta identifiers
    HEADER = auto()
    ROOT_UDT = auto()
    ROOT_AOI = auto()
    ROOT_CONTROLLER_TAGS = auto()
    ROOT_PROGRAM_TAGS = auto()
    UDT = auto()
    AOI = auto()
    UDT_MEMBER = auto()
    AOI_PARAMETER = auto()
    AOI_LOCAL_TAG = auto()
    PARAMS_HEADER = auto()
    LOCALS_HEADER = auto()
    TAG = auto()
    
    
@dataclass
class L5KHeader:
    """Raw header text (always included at top of exports)."""
    content: str

    def __repr__(self) -> str:
        return f"L5KHeader(lines={len(self.content.splitlines())})"


class L5KProject:
    """Container for parsed L5K data."""
    def __init__(self) -> None:
        self.header: Optional[L5KHeader] = None
        self.tags: Dict[str, Tag] = OrderedDict()
        self.udts: Dict[str, UDT] = OrderedDict()
        self.aois: Dict[str, AOI] = OrderedDict()
        self.programs: Dict[str, 'Program'] = {}

    def __repr__(self) -> str:
        return (
            f"L5KProject(tags={len(self.tags)}, "
            f"udts={len(self.udts)}, "
            f"aois={len(self.aois)}, "
            f"programs={len(self.programs)})"
        )


class UDT:
    """Represents a user-defined type with members."""
    def __init__(self, name: str, description: Optional[str] = None) -> None:
        self.name = name
        self.description = description or ""
        self.family_type: str = "NoFamily"
        self.members: Dict[str, UDTMember] = OrderedDict()

    def add_member(self, member: UDTMember) -> None:
        self.members[member.name] = member

    def to_l5k(self, indent: str = TAB) -> List[str]:
        attrs = []
        if getattr(self, "description", ""):
            attrs.append(f'Description := "{self.description}"')
        ft = getattr(self, "family_type", None) or "NoFamily"
        attrs.append(f"FamilyType := {ft}")
        header = f"{indent}DATATYPE {self.name} ({', '.join(attrs)})"
        lines: List[str] = [header]
        for m in self.members.values():
            lines.extend(m.to_l5k(level=2, indent=indent))
        lines.append(f"{indent}END_DATATYPE")
        return lines

    def __repr__(self) -> str:
        return f"UDT(name={self.name!r}, members={len(self.members)})"


@dataclass
class UDTMember:
    """Represents a member within a UDT; supports hidden SINT word and BIT children nesting."""
    name: str
    data_type: str
    description: str = ""
    definition: Optional[str] = None
    is_hidden_parent: bool = False
    is_bit: bool = False
    parent_word: Optional[str] = None
    bit_index: Optional[int] = None
    name_dims: str = ""
    children: Dict[str, "UDTMember"] = field(default_factory=OrderedDict)

    def add_child(self, child: 'UDTMember') -> None:
        self.children[child.name] = child

    def display_name(self) -> str:
        """Base name plus any array declarator captured on the name"""
        return f"{self.name}{self.name_dims}"

    def to_l5k(self, level: int = 1, indent: str = TAB) -> List[str]:
        if self.definition:
            return _indent_lines(_dedent_lines(self.definition), level, indent)
        # fallback (type-first)
        line = f"{self.data_type} {self.name};"
        return _indent_lines([line], level, indent)

    def __repr__(self) -> str:
        return f"UDTMember(name={self.name!r}, data_type={self.data_type!r})"


class AOI:
    """Represents an Add-On Instruction (AOI)."""
    def __init__(self, name: str, description: Optional[str] = None) -> None:
        self.name = name
        self.description = description or ""
        self.parameters: Dict[str, AOIParameter] = OrderedDict()
        self.localtags: Dict[str, AOILocalTag] = OrderedDict()

    def add_parameter(self, param: AOIParameter) -> None:
        self.parameters[param.name] = param

    def add_localtag(self, localtag: AOILocalTag) -> None:
        self.localtags[localtag.name] = localtag

    def to_l5k(self, indent: str = TAB, ensure_local_placeholder: bool = True) -> List[str]:
        lines: List[str] = [f"ADD_ON_INSTRUCTION_DEFINITION {self.name}"]
        # PARAMETERS
        if getattr(self, "parameters", {}):
            lines.append(f"{indent}PARAMETERS")
            for p in self.parameters.values():
                lines.extend(p.to_l5k(level=2, indent=indent))
            lines.append(f"{indent}END_PARAMETERS")
        # LOCAL_TAGS (Edge likes it non-empty; we can pad)
        lines.append(f"{indent}LOCAL_TAGS")
        locals_emitted = 0
        for t in getattr(self, "localtags", {}).values():
            lines.extend(t.to_l5k(level=2, indent=indent))
            locals_emitted += 1
        if ensure_local_placeholder and locals_emitted == 0:
            lines.append(f'{indent*2}__EdgePad : BOOL (Description := "Edge placeholder");')
        lines.append(f"{indent}END_LOCAL_TAGS")
        lines.append("END_ADD_ON_INSTRUCTION_DEFINITION")
        return lines

    def __repr__(self) -> str:
        return f"AOI(name={self.name!r}, params={len(self.parameters)}, locals={len(self.localtags)})"


@dataclass
class AOIParameter:
    """Represents an AOI parameter; stores full definition for export and correction status."""
    name: str
    data_type: str
    description: str = ""
    definition: Optional[str] = None
    is_bit_alias: bool = False
    is_corrected: bool = False  # True if OF path was resolved to a base type

    def _emit_plain_bool(self, level: int, indent: str) -> List[str]:
        # Try to salvage attributes from captured definition
        attrs = ""
        if self.definition:
            m = _RE_PARAM_HDR.match(self.definition.strip())
            if m:
                attrs = m.group("attrs") or ""
        body = _dedent_lines(attrs)
        out: List[str] = []
        out.append(f"{indent*level}{self.name} : BOOL (")
        for a in body:
            if a:
                out.append(f"{indent*(level+1)}{a.rstrip()}")
        out.append(f"{indent*level});")
        return out

    def to_l5k(self, level: int = 2, indent: str = TAB) -> List[str]:
        if getattr(self, "is_bit_alias", False):
            return self._emit_plain_bool(level, indent)
        if self.definition:
            return _indent_lines(_dedent_lines(self.definition), level, indent)
        # fallback minimal
        return _indent_lines([f"{self.name} : {self.data_type} ();"], level, indent)

    def __repr__(self) -> str:
        return f"AOIParameter(name={self.name!r}, data_type={self.data_type!r})"


@dataclass
class AOILocalTag:
    """Represents an AOI local tag; stores full definition for export."""
    name: str
    data_type: str
    description: str = ""
    definition: Optional[str] = None

    def to_l5k(self, level: int = 2, indent: str = TAB) -> List[str]:
        if self.definition:
            return _indent_lines(_dedent_lines(self.definition), level, indent)
        return _indent_lines([f"{self.name} : {self.data_type} ();"], level, indent)

    def __repr__(self) -> str:
        return f"AOILocalTag(name={self.name!r}, data_type={self.data_type!r})"


@dataclass
class Tag:
    """Represents a single global tag (CONTROLLER/TAG)."""
    name: str
    data_type: str
    description: str = ""
    definition: Optional[str] = None  # full line as-is

    def to_l5k(self, level: int = 1, indent: str = TAB) -> List[str]:
        # Export w/o values; keep description if present
        desc = getattr(self, "description", "")
        if desc:
            line = f'{self.name} : {self.data_type} (Description := "{desc}");'
        else:
            line = f"{self.name} : {self.data_type};"
        return _indent_lines([line], level, indent)
    
    def __repr__(self) -> str:
        return f"Tag(name={self.name!r}, data_type={self.data_type!r}, description={self.description!r})"


@dataclass
class Program:
    name: str
    description: str = ""
    tags: Dict[str, Tag] = field(default_factory=dict)

    def display_name(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"Program(name={self.name!r}, description={self.description!r})"


def _dedent_lines(def_text: str) -> List[str]:
    # Keep simple for now; parser already normalizes member lines well
    return [ln.rstrip("\n") for ln in (def_text or "").splitlines() if ln.strip() != ""]

def _indent_lines(lines: Iterable[str], level: int = 0, indent: str = TAB) -> List[str]:
    pref = indent * level
    return [f"{pref}{ln.rstrip()}" for ln in lines]
