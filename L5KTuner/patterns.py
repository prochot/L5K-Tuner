# patterns.py
# Copyright (c) 2025 Alex Prochot
#
# Regex patterns used by the L5K parser.
"""Compiled regex patterns used throughout the L5K parser."""


import re

# CONTROLLER <name> [ ( ...attrs... ) ]
RE_CONTROLLER_HDR = re.compile(
    r'^CONTROLLER\s+([A-Za-z_]\w*)\s*(\(|$)'
)

# UDT members
RE_UDT_TYPEFIRST = re.compile(
    r'^(?P<dtype>[A-Za-z_]\w*) '             # type
    r'(?P<name>[A-Za-z_]\w*)'                # base member name
    r'(?P<name_dims>\[\d+(?:,\d+)*\])?'      # optional [N] or [n,m,...] on the NAME
)
RE_UDT_BIT_ALIAS = re.compile(
    r'^BIT\s+(?P<alias>\w+)\s+(?P<word>\w+)\s*:\s*(?P<bit>\d+)\b'
)
RE_FAMILYTYPE = re.compile(r'\bFamilyType\s*:=\s*([A-Za-z_]\w*)', re.IGNORECASE)

RE_AOI_PARAM_DEF = re.compile(
    r'^\s*(?P<name>\w+)\s+(?P<cat>OF|:)\s+(?P<rhs>[\w\.\:]+)\s*\((?P<attrs>.*)\)\s*;?\s*$',
    re.DOTALL
)
RE_AOI_PARAM = re.compile(r'^([\w]+)\s+(?:OF|:)\s+([\w\.]+)')
RE_AOI_LOCALTAG = re.compile(r'^([\w]+)\s*:\s*([\w]+)')

# Tag prefix: <name> [OF alias] : <type...>  (DOTALL so we don't need to normalize newlines)
RE_TAG_PREFIX = re.compile(
    r'^\s*([A-Za-z_][\w\.]*)\s*(?:(?i:OF)\s+([A-Za-z_][\w\.\[\]:]*))?\s*:\s*(.+?)\s*$',
    re.DOTALL
)
