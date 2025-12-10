# tree_state.py
# Copyright (c) 2025 Alex Prochot
#
# Tree metadata, checkbox state, and serialization helpers.
"""Tree metadata and checkbox state management used by the GUI."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional, Any

from .models import MemberType


@dataclass
class TreeNodeMeta:
    """Metadata for a tree item: logical type/name and optional parent key."""
    node_type: MemberType
    name: str
    parent: Optional[str] = None


class TreeState:
    """
    Wrapper for tree metadata and checkbox states so we don't juggle parallel dicts.
    """
    def __init__(self) -> None:
        self.meta: Dict[str, TreeNodeMeta] = {}
        self.checks: Dict[str, bool] = {}
        self._key_index: Dict[tuple[str, str, Optional[str]], str] = {}

    def reset(self) -> None:
        self.meta.clear()
        self.checks.clear()
        self._key_index.clear()

    def set_meta(self, iid: str, meta: TreeNodeMeta) -> None:
        self.meta[iid] = meta
        key = self.logical_key_for_iid(iid)
        if key:
            self._key_index[key] = iid

    def get_meta(self, iid: str) -> Optional[TreeNodeMeta]:
        return self.meta.get(iid)

    def set_checked(self, iid: str, state: bool) -> None:
        self.checks[iid] = state

    def get_checked(self, iid: str, default: bool = False) -> bool:
        return self.checks.get(iid, default)

    def logical_key_for_iid(self, iid: str) -> Optional[tuple[str, str, Optional[str]]]:
        """Return a stable (node_type, name, parent) key for an item."""
        meta = self.get_meta(iid)
        if not meta:
            return None
        return (meta.node_type.name, meta.name, meta.parent)

    def serialize(self) -> list[dict[str, Any]]:
        """Serialize checkbox state with logical keys for persistence."""
        out: list[dict[str, Any]] = []
        for iid, state in self.checks.items():
            key = self.logical_key_for_iid(iid)
            if not key:
                continue
            node_type_name, name, parent = key
            out.append(
                {
                    "node_type": node_type_name,
                    "name": name,
                    "parent": parent,
                    "state": bool(state),
                }
            )
        return out

    def restore(self, saved: list[dict[str, Any]]) -> None:
        """Restore checkbox state from a serialized payload."""
        target = {
            (entry.get("node_type"), entry.get("name"), entry.get("parent")): bool(entry.get("state", False))
            for entry in saved
        }
        for iid, meta in self.meta.items():
            key = self.logical_key_for_iid(iid)
            if key and key in target:
                self.checks[iid] = target[key]

    def update_parent_states(self, tree, selected_item_id: Optional[str]) -> Optional[bool]:
        """
        Bubble up selection states: a parent is selected if any child is selected.
        Returns the new state of the selected item, if any.
        """
        if selected_item_id:
            anchor = selected_item_id
        else:
            anchor = None

        for iid in list(self.meta.keys()):
            parent = tree.parent(iid)
            while parent:
                child_states = [self.get_checked(ch, False) for ch in tree.get_children(parent)]
                new_state = any(child_states)
                if self.get_checked(parent, False) != new_state:
                    self.set_checked(parent, new_state)
                parent = tree.parent(parent)

        if anchor:
            return self.get_checked(anchor, False)
        return None
