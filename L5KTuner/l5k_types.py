# l5k_types.py
# Copyright (c) 2025 Alex Prochot
#
# Shared typing aliases for selection structures.
"""Shared typing aliases for selection dictionaries used in export/filter."""


from __future__ import annotations
from typing import Set, Dict, TypedDict


class SelectionDict(TypedDict, total=False):
    udts: Set[str]
    udt_members: Dict[str, Set[str]]
    aois: Set[str]
    aoi_parameters: Dict[str, Set[str]]
    aoi_localtags: Dict[str, Set[str]]
    tags: Set[str]
    program_tags: Dict[str, Set[str]]
