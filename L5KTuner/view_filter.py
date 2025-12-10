# view_filter.py
# Copyright (c) 2025 Alex Prochot
#
# Helpers for applying tree filters (all/enabled/disabled) in the GUI.
"""Treeview filtering helpers used by the GUI."""


from __future__ import annotations
from typing import Set

from .tree_state import TreeState


def apply_filter(tree, state: TreeState, mode: str) -> None:
    """
    Filter a ttk.Treeview in-place based on checkbox state.
    Keeps enabled/disabled nodes and their ancestors, pruning everything else.
    """
    if mode == "all":
        return

    keep: Set[str] = set()

    def dfs(iid: str) -> bool:
        checked = state.get_checked(iid, False)
        child_ids = list(tree.get_children(iid))
        child_keeps = [dfs(ch) for ch in child_ids]
        if mode == "enabled":
            keep_me = checked or any(child_keeps)
        else:
            keep_me = (not checked) or any(child_keeps)
        if keep_me:
            keep.add(iid)
        return keep_me

    for root in tree.get_children(""):
        dfs(root)

    def prune(iid: str) -> None:
        for ch in list(tree.get_children(iid)):
            prune(ch)
        if iid not in keep:
            tree.delete(iid)
            state.meta.pop(iid, None)
            state.checks.pop(iid, None)

    for root in list(tree.get_children("")):
        prune(root)
