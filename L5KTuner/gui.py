# gui.py
# Copyright (c) 2025 Alex Prochot
#
# Tkinter GUI for inspecting and filtering L5K content.
"""Tkinter GUI for inspecting, filtering, and exporting L5K content."""


import atexit
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext
from typing import Dict, Optional, Any, Set
import os
import logging
import concurrent.futures

from . import models
from .models import MemberType
from . import l5k_parser as l5kp
from .tree_state import TreeState, TreeNodeMeta
from .view_filter import apply_filter
from .utils import get_log_path

logger = logging.getLogger(__name__)


class L5KTunerApp:
    """
    GUI for parsing, viewing, selecting, and exporting subsets of L5K content.
    Left panel: Tree (Header, TAGS, UDTs, AOIs and their members)
    Right panel: Messages + Details + selection toggle for the current node
    """
    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        # Async parsing executor (keeps UI responsive)
        self._executor: Optional[concurrent.futures.Executor] = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._parse_future = None

        master.title("L5K File Processor")
        screen_w = master.winfo_screenwidth()
        screen_h = master.winfo_screenheight()
        if screen_w <= 1024 and screen_h <= 768:
            master.state("zoomed")
        else:
            master.geometry("1120x740")

        self.project: Optional[models.L5KProject] = None
        self.parser: Optional[l5kp.L5KParser] = None

        # Selection bookkeeping
        self.tree_state = TreeState()
        self.selected_item_id: Optional[str] = None

        self._last_project_path: Optional[str] = None
        self._last_source_label: str = ""
        self._filter_mode: str = "all"  # 'all' | 'enabled' | 'disabled'
        self._filter_var = tk.StringVar(value=self._filter_mode)
        self._saved_snapshot: Optional[str] = None
        self._dirty: bool = False

        self._create_widgets()
        self._set_selection_controls_enabled(False)

        self.master.protocol("WM_DELETE_WINDOW", self._on_close)
        atexit.register(self._cleanup_executor)

    # ---------------- UI Setup ----------------
    def _create_widgets(self) -> None:
        # Top bar
        top = tk.Frame(self.master, padx=10, pady=8)
        top.pack(side=tk.TOP, fill=tk.X)

        self.load_btn = ttk.Button(top, text="Import L5K", command=self._load_file)
        self.load_btn.pack(side=tk.LEFT, padx=5)
        self.save_btn = ttk.Button(top, text="Export L5K", command=self._save_file)
        self.save_btn.pack(side=tk.LEFT, padx=5)
        self._build_menubar()

        # Split panes
        main = tk.PanedWindow(self.master, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=1)

        # Left: Tree
        left = tk.Frame(main)
        self.tree = ttk.Treeview(left, show='tree headings')
        self.tree.heading("#0", text="Tag / Component", anchor='w')
        self.tree.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)

        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)

        # Use select event to update right panel
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        main.add(left, stretch="always")

        # Right: Info
        self.info = tk.Frame(main, padx=12, pady=12)
        self.title_var = tk.StringVar(value="Select an item in the tree")
        ttk.Label(self.info, textvariable=self.title_var, anchor='w', font=("TkDefaultFont", 11, "bold")).pack(fill=tk.X)

        # Messages area (status / corrections log) above the details window
        ttk.Label(self.info, text="Messages", anchor='w').pack(fill=tk.X, pady=(8, 2))
        self.messages_text = scrolledtext.ScrolledText(self.info, height=6, wrap="word", state="disabled")
        self.messages_text.pack(fill=tk.BOTH, expand=False)

        # Details area
        ttk.Label(self.info, text="Details", anchor='w').pack(fill=tk.X, pady=(10, 2))
        self.detail_text = tk.Text(self.info, height=14, wrap="word")
        self.detail_text.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        self.select_var = tk.BooleanVar(value=True)
        self.select_checkbox = ttk.Checkbutton(self.info, text="Include this item in export",
                                               variable=self.select_var, command=self._toggle_selection)
        self.select_checkbox.pack(anchor='w', pady=(0, 6))

        # helper controls
        helper = tk.Frame(self.info)
        helper.pack(fill=tk.X, pady=(6, 0))
        self.btn_include_selected = ttk.Button(helper, text="Include Selected", command=self._select_all)
        self.btn_include_selected.pack(side=tk.LEFT, padx=4)
        self.btn_exclude_selected = ttk.Button(helper, text="Exclude Selected", command=self._deselect_all)
        self.btn_exclude_selected.pack(side=tk.LEFT, padx=4)

        main.add(self.info, stretch="always")

        # Status
        bottom = tk.Frame(self.master, padx=10, pady=6)
        bottom.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_label = ttk.Label(bottom, text="Ready", anchor='w')
        self.status_label.pack(fill=tk.X)

    def _build_menubar(self) -> None:
        menubar = tk.Menu(self.master)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open", command=self._open_project_json)
        file_menu.add_command(label="Save", command=self._save_project_json)
        file_menu.add_command(label="Save As...", command=self._save_project_json_as)
        file_menu.add_separator()
        file_menu.add_command(label="Import", command=self._load_file)
        file_menu.add_command(label="Export", command=self._save_file)
        file_menu.add_command(label="Merge Updated L5K...", command=self._merge_updated_l5k)
        file_menu.add_separator()
        file_menu.add_command(label="Close", command=self._close_project)
        file_menu.add_command(label="Exit", command=self._on_close)
        view_menu = tk.Menu(menubar, tearoff=0)
        show_sub = tk.Menu(view_menu, tearoff=0)
        show_sub.add_radiobutton(label="Show All", value="all", variable=self._filter_var,
                                 command=lambda: self._set_filter_mode("all"))
        show_sub.add_radiobutton(label="Show Enabled", value="enabled", variable=self._filter_var,
                                 command=lambda: self._set_filter_mode("enabled"))
        show_sub.add_radiobutton(label="Show Disabled", value="disabled", variable=self._filter_var,
                                 command=lambda: self._set_filter_mode("disabled"))
        view_menu.add_cascade(label="Show", menu=show_sub)

        menubar.add_cascade(label="File", menu=file_menu)
        menubar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Show Log", command=self._show_log)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.master.config(menu=menubar)

    def _log_message(self, msg: str) -> None:
        """Append a line to the messages panel and update status bar."""
        try:
            self.messages_text.configure(state="normal")
            self.messages_text.insert("end", msg.rstrip() + "\n")
            self.messages_text.see("end")
        finally:
            self.messages_text.configure(state="disabled")

    def _current_logical_keys(self) -> set[tuple[str, str, Optional[str]]]:
        keys: set[tuple[str, str, Optional[str]]] = set()
        for iid in self.tree_state.meta:
            key = self.tree_state.logical_key_for_iid(iid)
            if key:
                keys.add(key)
        return keys

    def _keys_for_project(self, project: models.L5KProject) -> set[tuple[str, str, Optional[str]]]:
        keys: set[tuple[str, str, Optional[str]]] = set()
        for name in project.udts.keys():
            keys.add(("UDT", name, None))
            for member in project.udts[name].members.values():
                keys.add(("UDT_MEMBER", member.name, name))
                for child in getattr(member, "children", {}).values():
                    keys.add(("UDT_MEMBER", child.name, name))
        for name in project.aois.keys():
            keys.add(("AOI", name, None))
            for param in project.aois[name].parameters.values():
                keys.add(("AOI_PARAMETER", param.name, name))
            for local in project.aois[name].localtags.values():
                keys.add(("AOI_LOCAL_TAG", local.name, name))
        for name in project.tags.keys():
            keys.add(("TAG", name, None))
        for pname, prog in project.programs.items():
            for tname in prog.tags.keys():
                keys.add(("PROGRAM_TAG", tname, pname))
        return keys

    def _show_merge_preview(self, file_path: str, new_project: models.L5KProject, new_parser: l5kp.L5KParser,
                            corrected_log: list[str], saved_states: list[dict[str, Any]],
                            added: list[tuple[str, str, Optional[str]]], removed: list[tuple[str, str, Optional[str]]]) -> None:
        """
        Present a simple modal preview with added/removed counts. Apply only on user confirmation.
        """
        win = tk.Toplevel(self.master)
        win.title("Merge Preview")
        win.geometry("640x420")
        win.transient(self.master)
        win.grab_set()

        # Center over the main window
        try:
            win.update_idletasks()
            mw, mh = self.master.winfo_width(), self.master.winfo_height()
            if mw <= 1 or mh <= 1:  # fallback before the main window is drawn
                mw, mh = self.master.winfo_reqwidth(), self.master.winfo_reqheight()
            mx, my = self.master.winfo_rootx(), self.master.winfo_rooty()
            w, h = win.winfo_width(), win.winfo_height()
            x = mx + max((mw - w) // 2, 0)
            y = my + max((mh - h) // 2, 0)
            win.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

        tk.Label(win, text=f"Updated file: {os.path.basename(file_path)}", anchor="w").pack(fill=tk.X, padx=8, pady=(8, 4))
        summary_var = tk.StringVar()
        summary_label = tk.Label(win, textvariable=summary_var, anchor="w", font=("TkDefaultFont", 10, "bold"))
        summary_label.pack(fill=tk.X, padx=8, pady=(0, 6))

        frame = tk.Frame(win)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        added_box = tk.Listbox(frame, height=8, selectmode=tk.MULTIPLE, exportselection=False)
        for k in added:
            added_box.insert(tk.END, " / ".join(filter(None, k)))
        removed_box = tk.Listbox(frame, height=8, selectmode=tk.MULTIPLE, exportselection=False)
        for k in removed:
            removed_box.insert(tk.END, " / ".join(filter(None, k)))
        # preselect all by default
        added_box.selection_set(0, tk.END)
        removed_box.selection_set(0, tk.END)

        tk.Label(frame, text="Added").grid(row=0, column=0, sticky="w")
        tk.Label(frame, text="Removed").grid(row=0, column=1, sticky="w")
        added_box.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        removed_box.grid(row=1, column=1, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(1, weight=1)

        def update_counts(event: Optional[tk.Event] = None) -> None:  # noqa: ARG001
            summary_var.set(
                f"Added: {len(added_box.curselection())}/{len(added)}    "
                f"Removed: {len(removed_box.curselection())}/{len(removed)}"
            )

        added_box.bind("<<ListboxSelect>>", update_counts)
        removed_box.bind("<<ListboxSelect>>", update_counts)

        tk.Label(win, text="Select items to add/remove", anchor="w").pack(fill=tk.X, padx=8, pady=(4, 2))

        btns = tk.Frame(win)
        btns.pack(fill=tk.X, padx=8, pady=8)

        def apply_merge():
            selected_added = [added[i] for i in added_box.curselection()]
            selected_removed = [removed[i] for i in removed_box.curselection()]
            self._apply_merge_changes(new_project, selected_added, selected_removed)
            base = os.path.basename(file_path)
            self._last_source_label = base
            self._set_window_title(file_path)
            self._populate_tree(saved_states=saved_states)
            self._show_summary(corrected_log)
            self._set_selection_controls_enabled(True)
            self._update_dirty_flag()
            self._filter_mode = "all"
            self._filter_var.set("all")
            self._set_status("Merged updated L5K", base)
            self._log_message(f"Merged updated L5K. Added: {len(selected_added)}, Removed: {len(selected_removed)}.")
            logger.info("Merged updated L5K file: %s (added %s, removed %s)", file_path, len(selected_added), len(selected_removed))
            win.destroy()

        update_counts()

        tk.Button(btns, text="Apply", command=apply_merge).pack(side=tk.RIGHT, padx=4)
        tk.Button(btns, text="Cancel", command=win.destroy).pack(side=tk.RIGHT, padx=4)

    def _apply_merge_changes(self, new_project: models.L5KProject,
                              selected_added: list[tuple[str, str, Optional[str]]],
                              selected_removed: list[tuple[str, str, Optional[str]]]) -> None:
        """
        Apply selected additions/removals from an updated project into the current project.
        """
        project = self.project
        if project is None:
            return

        # Additions
        for kind, name, parent in selected_added:
            if kind == "UDT" and name in new_project.udts:
                project.udts[name] = new_project.udts[name]
            elif kind == "UDT_MEMBER" and parent and parent in new_project.udts and parent in project.udts:
                member = new_project.udts[parent].members.get(name)
                if member:
                    project.udts[parent].members[name] = member
            elif kind == "AOI" and name in new_project.aois:
                project.aois[name] = new_project.aois[name]
            elif kind == "AOI_PARAMETER" and parent and parent in new_project.aois and parent in project.aois:
                param = new_project.aois[parent].parameters.get(name)
                if param:
                    project.aois[parent].parameters[name] = param
            elif kind == "AOI_LOCAL_TAG" and parent and parent in new_project.aois and parent in project.aois:
                local = new_project.aois[parent].localtags.get(name)
                if local:
                    project.aois[parent].localtags[name] = local
            elif kind == "TAG" and name in new_project.tags:
                project.tags[name] = new_project.tags[name]
            elif kind == "PROGRAM_TAG" and parent and parent in new_project.programs:
                if parent not in project.programs:
                    project.programs[parent] = new_project.programs[parent]
                else:
                    tag_obj = new_project.programs[parent].tags.get(name)
                    if tag_obj:
                        project.programs[parent].tags[name] = tag_obj

        # Removals
        for kind, name, parent in selected_removed:
            if kind == "UDT":
                project.udts.pop(name, None)
            elif kind == "UDT_MEMBER" and parent and parent in project.udts:
                project.udts[parent].members.pop(name, None)
                # also remove child from any hidden parent if present
                for m in project.udts[parent].members.values():
                    if getattr(m, "children", None):
                        m.children.pop(name, None)
            elif kind == "AOI":
                project.aois.pop(name, None)
            elif kind == "AOI_PARAMETER" and parent and parent in project.aois:
                project.aois[parent].parameters.pop(name, None)
            elif kind == "AOI_LOCAL_TAG" and parent and parent in project.aois:
                project.aois[parent].localtags.pop(name, None)
            elif kind == "TAG":
                project.tags.pop(name, None)
            elif kind == "PROGRAM_TAG" and parent and parent in project.programs:
                project.programs[parent].tags.pop(name, None)

    def _build_project_state(self) -> Optional[dict[str, Any]]:
        if not self.parser or not self.project:
            return None
        return {
            "controller_header_lines": getattr(self.parser, "controller_header_lines", []),
            "controller_name": getattr(self.parser, "controller_name", None),
            "header_text": getattr(self.parser, "header_text", ""),
            "project": self._project_to_dict(self.project),
            "checkbox_states": self._serialize_checkbox_states(),
        }

    def _snapshot_state(self) -> Optional[str]:
        state = self._build_project_state()
        if state is None:
            return None
        return json.dumps(state, sort_keys=True)

    def _set_saved_snapshot(self, state: Optional[dict[str, Any]] = None) -> None:
        snapshot = json.dumps(state, sort_keys=True) if state is not None else self._snapshot_state()
        self._saved_snapshot = snapshot
        self._dirty = False
        self._refresh_window_title()

    def _update_dirty_flag(self) -> None:
        was_dirty = self._dirty
        snapshot = self._snapshot_state()
        if snapshot is None:
            self._dirty = False
        elif self._saved_snapshot is None:
            self._dirty = True
        else:
            self._dirty = snapshot != self._saved_snapshot
        if self._dirty != was_dirty:
            self._refresh_window_title()

    def _confirm_discard_changes(self, action: str) -> bool:
        self._update_dirty_flag()
        if not self._dirty:
            return True
        response = messagebox.askyesnocancel(
            "Unsaved changes",
            f"You have unsaved changes. Save before {action}?",
        )
        if response is None:
            return False
        if response:
            return self._save_project_json()
        return True

    # ---------------- File I/O ----------------
    def _load_file(self) -> None:
        if not self._confirm_discard_changes("importing a new file"):
            return
        file_path = filedialog.askopenfilename(filetypes=[("L5K Files", "*.l5k;*.L5K"), ("All Files", "*.*")])
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                file_content = f.read()
            base = os.path.basename(file_path)
            self._last_source_label = base
            self._last_project_path = None
            self._set_status("Loaded file", base)
            self._set_window_title(file_path)
            self._set_filter_mode("all")
            logger.info("Imported L5K file: %s", file_path)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Error", f"Failed to read file: {e}")
            return

        # Kick off async parse in a separate process to keep UI responsive
        self.parser = l5kp.L5KParser(file_content)  # keep local instance for later get_corrected_content()
        fut = self._parse_future
        if fut is not None and not fut.done():
            # We only allow one job at a time; ignore/cancel if possible
            try:
                fut.cancel()
            except Exception:
                pass

        if getattr(self, "load_btn", None):
            self.load_btn.config(state="disabled")

        self.status_label.config(text="Parsing…")
        executor = self._ensure_executor()
        self._parse_future = executor.submit(l5kp.parse_text_worker, file_content)
        self.master.after(50, self._poll_parse_future)
        return

    def _save_file(self) -> None:
        if not self.parser:
            messagebox.showwarning("Warning", "No file loaded.")
            return
        file_path = filedialog.asksaveasfilename(defaultextension=".l5k",
                                                 filetypes=[("L5K Files", "*.l5k")])
        if not file_path:
            return
        try:
            selection = self._build_selection_structure()
            filtered = self.parser.export_whitelist(selection)
#           filtered = self.parser.get_selected_content(selection)  # type: ignore[union-attr]
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(filtered)
            base = os.path.basename(file_path)
            self._last_source_label = base
            self._set_status("Saved file", base)
            self._set_window_title(file_path)
            self._log_message("Filtered file saved successfully.")
            logger.info("Exported L5K file: %s", file_path)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Error", f"Failed to save file: {e}")

    def _save_project_json(self) -> bool:
        if not self.parser or not self.project:
            messagebox.showwarning("Warning", "No file loaded.")
            return False
        file_path = self._last_project_path
        if not file_path:
            file_path = self._prompt_save_path()
            if not file_path:
                return False
            logger.info("Save As project file: %s", file_path)
        try:
            data = self._build_project_state()
            if data is None:
                messagebox.showwarning("Warning", "No file loaded.")
                return False
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self._last_project_path = file_path
            base = os.path.basename(file_path)
            self._last_source_label = base
            self._set_status("Saved project", base)
            self._set_window_title(file_path)
            self._log_message("Project saved.")
            logger.info("Saved project file: %s", file_path)
            self._set_saved_snapshot(data)
            return True
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Error", f"Failed to save project: {e}")
            return False

    def _save_project_json_as(self) -> bool:
        if not self.parser or not self.project:
            messagebox.showwarning("Warning", "No file loaded.")
            return False
        file_path = self._prompt_save_path()
        if not file_path:
            return False
        self._last_project_path = file_path
        return self._save_project_json()

    def _open_project_json(self) -> None:
        if not self._confirm_discard_changes("opening another project"):
            return
        initialdir = os.path.dirname(self._last_project_path) if self._last_project_path else None
        file_path = filedialog.askopenfilename(filetypes=[("L5K Project", "*.l5kproj;*.json"), ("All Files", "*.*")],
                                               initialdir=initialdir)
        if not file_path:
            return
        self.open_project_file(file_path)

    def open_project_file(self, file_path: str) -> None:
        if not os.path.isfile(file_path):
            messagebox.showerror("Error", f"Project file not found: {file_path}")
            return
        if not self._confirm_discard_changes("opening another project"):
            return
        self._open_project_json_path(file_path)

    def _open_project_json_path(self, file_path: str) -> None:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            project_dict = data.get("project", {})
            project = self._project_from_dict(project_dict)

            parser = l5kp.L5KParser("")
            parser.project = project
            parser.corrected_tags_log = []
            parser.header_text = data.get("header_text", "")
            parser.controller_header_lines = data.get("controller_header_lines", [])
            parser.controller_name = data.get("controller_name", None)

            self.project = project
            self.parser = parser
            self._populate_tree()
            self._restore_checkbox_states(data.get("checkbox_states", []))
            base = os.path.basename(file_path)
            self._last_source_label = base
            self._set_status("Loaded project", base)
            self._log_message("Project loaded.")
            self._last_project_path = file_path
            self._set_window_title(file_path)
            logger.info("Opened project file: %s", file_path)
            self._set_filter_mode("all")
            self._set_selection_controls_enabled(True)
            self._set_saved_snapshot(data)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Error", f"Failed to open project: {e}")

    def _prompt_save_path(self) -> Optional[str]:
        initialdir = os.path.dirname(self._last_project_path) if self._last_project_path else None
        return filedialog.asksaveasfilename(defaultextension=".l5kproj",
                                            filetypes=[("L5K Project", "*.l5kproj"), ("JSON Files", "*.json"), ("All Files", "*.*")],
                                            initialdir=initialdir)

    def _show_log(self) -> None:
        log_path = get_log_path()
        content = ""
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            content = "(Log file not found.)"
        except Exception as e:  # noqa: BLE001
            content = f"(Failed to read log: {e})"

        win = tk.Toplevel(self.master)
        win.title("Log Viewer")
        win.geometry("700x500")
        container = tk.Frame(win)
        container.pack(fill=tk.BOTH, expand=True)
        txt = tk.Text(container, wrap="word", state="normal")
        txt.insert("1.0", content)
        txt.config(state="disabled")
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Add scrollbar on the right
        ysb = ttk.Scrollbar(container, orient="vertical", command=txt.yview)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        txt.configure(yscrollcommand=ysb.set)
        status = ttk.Label(win, text=f"Log file: {log_path}", anchor="w")
        status.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(0, 6))

    def _close_project(self) -> None:
        if not self._confirm_discard_changes("closing the project"):
            return
        self._discard_project_state()

    def _discard_project_state(self) -> None:
        # Reset in-memory state and UI to initial
        self.project = None
        self.parser = None
        self.tree_state.reset()
        self.selected_item_id = None
        self.tree.delete(*self.tree.get_children())
        self.detail_text.delete("1.0", tk.END)
        self.messages_text.configure(state="normal")
        self.messages_text.delete("1.0", tk.END)
        self.messages_text.configure(state="disabled")
        closed_label = self._last_source_label or "(unnamed)"
        self._last_source_label = ""
        self._last_project_path = None
        self._saved_snapshot = None
        self._dirty = False
        self._set_status("Ready", None)
        self._set_window_title(None)
        logger.info("Closed file/project: %s", closed_label)
        self._set_selection_controls_enabled(False)

    # Polls the background parse, handles errors, adopts the results, and refreshes the UI
    def _poll_parse_future(self):
        fut = self._parse_future
        if fut is None:
            return

        if fut.done():
            self._parse_future = None

            # Handle cancelled jobs cleanly
            if fut.cancelled():
                self._set_status("File parsing cancelled", self._last_source_label)
                if getattr(self, "load_btn", None):
                    self.load_btn.config(state="normal")
                return
            
            try:
                project, corrected_tags_log = fut.result()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to parse file:\n{e}")
                self._set_status("Parse failed", self._last_source_label)
                if getattr(self, "load_btn", None):
                    self.load_btn.config(state="normal")
                return
            
            # Adopt the new project so the UI repopulates with fresh data
            self.project = project

            # Keep self.parser in sync so export/save paths keep working
            parser_inst = self.parser
            if parser_inst is not None:
                parser_inst.project = project
                parser_inst.corrected_tags_log = corrected_tags_log

            # Refresh UI
            self._populate_tree()
            self._show_summary(corrected_tags_log)
            self._set_status("File parsing complete", self._last_source_label)
            if getattr(self, "load_btn", None):
                self.load_btn.config(state="normal")
            self._set_selection_controls_enabled(True)
            self._set_saved_snapshot()
            logger.info("Parsed L5K file: %s", self._last_source_label)
        else:
            # keep polling until the worker finishes
            self.master.after(75, self._poll_parse_future)


    # ---------------- Tree Building ----------------
    def _populate_tree(self, saved_states: Optional[list[dict[str, Any]]] = None) -> None:
        # Reset
        self.tree.delete(*self.tree.get_children())
        self.tree_state.reset()
        self.selected_item_id = None

        if not self.project:
            return

        self._add_header_node()
        self._add_udt_nodes()
        self._add_aoi_nodes()
        self._add_controller_tag_nodes()
        self._add_program_tag_nodes()

        if saved_states:
            self._restore_checkbox_states(saved_states)
        self._apply_filter()

    def _add_header_node(self) -> None:
        header_id = self.tree.insert("", "end", text="L5K Header", open=False)
        self.tree_state.set_meta(header_id, TreeNodeMeta(MemberType.HEADER, "L5K Header"))
        self.tree_state.set_checked(header_id, True)

    def _add_udt_nodes(self) -> None:
        project = self.project
        if not project:
            return
        udt_root = self.tree.insert("", "end", text="User-Defined Types", open=False)
        self.tree_state.set_meta(udt_root, TreeNodeMeta(MemberType.ROOT_UDT, "User-Defined Types"))
        self.tree_state.set_checked(udt_root, True)

        for udt in project.udts.values():
            udt_id = self.tree.insert(udt_root, "end", text=udt.name, open=False)
            self.tree_state.set_meta(udt_id, TreeNodeMeta(MemberType.UDT, udt.name))
            self.tree_state.set_checked(udt_id, True)

            for member in udt.members.values():
                if getattr(member, "parent_word", None):
                    continue
                mlabel = member.display_name() if hasattr(member, "display_name") else member.name
                m_id = self.tree.insert(udt_id, "end", text=f"{mlabel} : {member.data_type}", open=False)
                self.tree_state.set_meta(m_id, TreeNodeMeta(MemberType.UDT_MEMBER, member.name, parent=udt.name))
                self.tree_state.set_checked(m_id, (member.name not in ("EnableIn", "EnableOut")))

                for child in getattr(member, "children", {}).values():
                    clabel = child.display_name() if hasattr(child, "display_name") else child.name
                    c_id = self.tree.insert(m_id, "end", text=f"{clabel} : {child.data_type}", open=False)
                    self.tree_state.set_meta(c_id, TreeNodeMeta(MemberType.UDT_MEMBER, child.name, parent=udt.name))
                    self.tree_state.set_checked(c_id, (child.name not in ("EnableIn", "EnableOut")))

    def _add_aoi_nodes(self) -> None:
        project = self.project
        if not project:
            return
        aoi_root = self.tree.insert("", "end", text="Add-On Instructions", open=False)
        self.tree_state.set_meta(aoi_root, TreeNodeMeta(MemberType.ROOT_AOI, "Add-On Instructions"))
        self.tree_state.set_checked(aoi_root, True)

        for aoi in project.aois.values():
            aoi_id = self.tree.insert(aoi_root, "end", text=aoi.name, open=False)
            self.tree_state.set_meta(aoi_id, TreeNodeMeta(MemberType.AOI, aoi.name))
            self.tree_state.set_checked(aoi_id, True)

            if aoi.parameters:
                params_head = self.tree.insert(aoi_id, "end", text="Parameters", open=False)
                self.tree_state.set_meta(params_head, TreeNodeMeta(MemberType.PARAMS_HEADER, f"{aoi.name} Parameters"))
                self.tree_state.set_checked(params_head, True)

                for param in aoi.parameters.values():
                    pid = self.tree.insert(params_head, "end", text=f"{param.name} : {param.data_type}", open=False)
                    self.tree_state.set_meta(pid, TreeNodeMeta(MemberType.AOI_PARAMETER, param.name, parent=aoi.name))
                    self.tree_state.set_checked(pid, (param.name not in ("EnableIn", "EnableOut")))

            if aoi.localtags:
                locals_head = self.tree.insert(aoi_id, "end", text="Local Tags", open=False)
                self.tree_state.set_meta(locals_head, TreeNodeMeta(MemberType.LOCALS_HEADER, f"{aoi.name} Local Tags"))
                self.tree_state.set_checked(locals_head, False)

                for local in aoi.localtags.values():
                    lid = self.tree.insert(locals_head, "end", text=f"{local.name} : {local.data_type}", open=False)
                    self.tree_state.set_meta(lid, TreeNodeMeta(MemberType.AOI_LOCAL_TAG, local.name, parent=aoi.name))
                    self.tree_state.set_checked(lid, False)

    def _add_controller_tag_nodes(self) -> None:
        project = self.project
        if not project:
            return
        tag_root = self.tree.insert("", "end", text="Controller Tags", open=False)
        self.tree_state.set_meta(tag_root, TreeNodeMeta(MemberType.ROOT_CONTROLLER_TAGS, "Controller Tags"))
        self.tree_state.set_checked(tag_root, True)

        for tag in project.tags.values():
            tag_id = self.tree.insert(tag_root, "end", text=f"{tag.name} : {tag.data_type}", open=False)
            self.tree_state.set_meta(tag_id, TreeNodeMeta(MemberType.TAG, tag.name))
            self.tree_state.set_checked(tag_id, True)

    def _add_program_tag_nodes(self) -> None:
        project = self.project
        if not project:
            return
        for prog_name, prog in project.programs.items():
            if not prog.tags:
                continue
            prog_root = self.tree.insert("", "end", text=f"{prog_name} Tags", open=False)
            self.tree_state.set_meta(prog_root, TreeNodeMeta(MemberType.ROOT_PROGRAM_TAGS, prog_name))
            self.tree_state.set_checked(prog_root, True)

            for tag in prog.tags.values():
                pid = self.tree.insert(prog_root, "end", text=f"{tag.name} : {tag.data_type}", open=False)
                self.tree_state.set_meta(pid, TreeNodeMeta(MemberType.TAG, tag.name, parent=prog_name))
                self.tree_state.set_checked(pid, True)

        # Compute number of number of each type of object
    def _counts_for_item(self, item_id: str) -> list[str]:
        lines: list[str] = []
        if not self.project:
            return lines

        meta = self.tree_state.get_meta(item_id)
        if meta and meta.node_type in (
            MemberType.ROOT_UDT,
            MemberType.ROOT_AOI,
            MemberType.ROOT_CONTROLLER_TAGS,
            MemberType.ROOT_PROGRAM_TAGS,
        ):
            if meta.node_type == MemberType.ROOT_UDT:
                n_udt = len(self.project.udts)
                total_members = sum(len(u.members) for u in self.project.udts.values())
                lines.append(f"UDTs: {n_udt}")
                lines.append(f"Total members across UDTs: {total_members}")
                return lines
            if meta.node_type == MemberType.ROOT_AOI:
                n_aoi = len(self.project.aois)
                total_params = sum(len(a.parameters) for a in self.project.aois.values())
                total_locals = sum(len(a.localtags) for a in self.project.aois.values())
                lines.append(f"Add-On Instructions: {n_aoi}")
                lines.append(f"Total parameters: {total_params}")
                lines.append(f"Total local tags: {total_locals}")
                return lines
            if meta.node_type == MemberType.ROOT_CONTROLLER_TAGS:
                lines.append(f"Controller tags: {len(self.project.tags)}")
                return lines
            if meta.node_type == MemberType.ROOT_PROGRAM_TAGS:
                prog_name = meta.name
                prog = self.project.programs.get(str(prog_name)) if prog_name else None
                lines.append(f"Program tags: {len(prog.tags) if prog else 0}")
                return lines

        # Object nodes
        k = meta.node_type if meta else None
        name = str(meta.name) if meta else ""

        if k == MemberType.UDT:
            udt = self.project.udts.get(name)
            if udt:
                lines.append(f"Members: {len(udt.members)}")
            return lines

        if k == MemberType.AOI:
            aoi = self.project.aois.get(name)
            if aoi:
                lines.append(f"Parameters: {len(aoi.parameters)}")
                lines.append(f"Local tags: {len(aoi.localtags)}")
            return lines

        if k == MemberType.TAG:
            lines.append("Program tag item" if meta and meta.parent else "Tag item")
            return lines

        return lines

    # ---------------- Selection / Info ----------------
    def _on_tree_select(self, _event: tk.Event) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        item_id = sel[0]
        self.selected_item_id = item_id

        text = self.tree.item(item_id, "text")
        meta = self.tree_state.get_meta(item_id)
        self.title_var.set(text)

        # Sync checkbox with state
        if meta and meta.node_type == MemberType.HEADER:
            # Header is always included and not toggleable
            self.select_var.set(True)
            self.select_checkbox.configure(state=tk.DISABLED)
        else:
            self.select_checkbox.configure(state=tk.NORMAL)
            self.select_var.set(self.tree_state.get_checked(item_id, True))

        # Render details
        self.detail_text.delete("1.0", tk.END)
        lines: list[str] = [
            f"Type: {meta.node_type if meta else '?'}",
            f"Name: {meta.name if meta else '?'}"
        ]
        if meta and meta.parent:
            lines.append(f"Parent: {meta.parent}")
        if " : " in text:
            _, ttype = text.split(" : ", 1)
            lines.append(f"Data Type: {ttype.strip()}")

        # If header, show full header text and return
        if meta and meta.node_type == MemberType.HEADER:
            lines.append("")
            lines.append("Header:")
            header_text = ""
            if self.project and self.project.header and getattr(self.project.header, "content", None):
                header_text = str(self.project.header.content)
            lines.append(header_text if header_text else "(No header found)")
            count_lines = self._counts_for_item(item_id)
            if count_lines:
                lines = ["Counts:"] + [f"\t{ln}" for ln in count_lines] + [""] + lines
            self.detail_text.insert(tk.END, "\n".join(lines))
            return

        # Append definition / extra properties when available
        obj = self._get_model_object(meta)
        if obj is not None:
            # Show Description when available
            desc = getattr(obj, 'description', None)
            if isinstance(desc, str) and desc:
                lines.append(f"Description: {desc}")
            # Show stored definition text if present
            definition = getattr(obj, 'definition', None)
            if isinstance(definition, str) and definition:
                lines.append("")
                lines.append("Definition:")
                lines.append(definition)
            # Bit/parent info for UDTMember-only
            if meta and meta.node_type == MemberType.UDT_MEMBER:
                bit_index = getattr(obj, 'bit_index', None)
                parent_word = getattr(obj, 'parent_word', None)
                if bit_index is not None:
                    lines.append(f"Bit Index: {bit_index}")
                if isinstance(parent_word, str) and parent_word:
                    lines.append(f"Parent Word: {parent_word}")

        count_lines = self._counts_for_item(item_id)
        if count_lines:
            lines = ["Counts:"] + [f"\t{ln}" for ln in count_lines] + [""] + lines

        self.detail_text.insert(tk.END, "\n".join(lines))

    def _get_model_object(self, meta: Optional[TreeNodeMeta]) -> Optional[Any]:
        if not self.project:
            return None
        if not meta:
            return None
        node_type = meta.node_type
        name = meta.name
        if node_type == MemberType.TAG:
            if meta.parent:
                prog = self.project.programs.get(str(meta.parent)) if meta.parent else None
                return prog.tags.get(str(name)) if prog else None
            return self.project.tags.get(str(name))
        if node_type == MemberType.UDT:
            return self.project.udts.get(str(name))
        if node_type == MemberType.UDT_MEMBER:
            udt = self.project.udts.get(str(meta.parent)) if meta.parent else None
            if udt:
                # Prefer direct member; else search children under hidden words
                if str(name) in udt.members:
                    return udt.members[str(name)]
                for m in udt.members.values():
                    if getattr(m, "children", None) and str(name) in m.children:
                        return m.children[str(name)]
        if node_type == MemberType.AOI:
            return self.project.aois.get(str(name))
        if node_type == MemberType.AOI_PARAMETER:
            aoi = self.project.aois.get(str(meta.parent)) if meta.parent else None
            return aoi.parameters.get(str(name)) if aoi else None
        if node_type == MemberType.AOI_LOCAL_TAG:
            aoi = self.project.aois.get(str(meta.parent)) if meta.parent else None
            return aoi.localtags.get(str(name)) if aoi else None
        return None

    def _set_state(self, item_id: str, state: bool, bubble_up: bool = True) -> None:
        """Set state for item, propagate down to children, and bubble upwards if requested."""
        self.tree_state.set_checked(item_id, state)
        # Downward propagation
        for child in self.tree.get_children(item_id):
            self._set_state(child, state, bubble_up=False)
        # Upward propagation
        if bubble_up:
            new_state = self.tree_state.update_parent_states(self.tree, self.selected_item_id)
            if new_state is not None and self.selected_item_id:
                self.select_var.set(new_state)

    def _toggle_selection(self) -> None:
        if self.selected_item_id is None:
            return
        # Do not allow toggling header
        meta = self.tree_state.get_meta(self.selected_item_id)
        if meta and meta.node_type == MemberType.HEADER:
            self.select_var.set(True)
            return
        state = bool(self.select_var.get())
        self._set_state(self.selected_item_id, state, bubble_up=True)
        self._update_dirty_flag()

    def _select_all(self) -> None:
        targets = tuple(self.tree.selection())
        if not targets:
            return
        seen = set()
        for iid in targets:
            if iid in seen:
                continue
            seen.add(iid)
            self._set_state(iid, True, bubble_up=True)
        # keep the checkbox aligned with the first selected item (or current)
        anchor = self.selected_item_id or targets[0]
        self.select_var.set(self.tree_state.get_checked(anchor, False))
        self._log_message("Selected chosen items (and children).")
        self._update_dirty_flag()

    def _deselect_all(self) -> None:
        targets = tuple(self.tree.selection())
        if not targets:
            return
        seen = set()
        for iid in targets:
            if iid in seen:
                continue
            seen.add(iid)
            self._set_state(iid, False, bubble_up=True)
        anchor = self.selected_item_id or targets[0]
        self.select_var.set(self.tree_state.get_checked(anchor, False))
        self._log_message("Deselected chosen items (and children).")
        self._update_dirty_flag()

    # Build a structured selection to pass into parser
    def _build_selection_structure(self) -> l5kp.SelectionDict:
        # Typed empty dicts so Pylance knows the shapes
        udt_members: Dict[str, Set[str]] = {}
        aoi_parameters: Dict[str, Set[str]] = {}
        aoi_localtags: Dict[str, Set[str]] = {}
        program_tags: Dict[str, Set[str]] = {}

        sel: l5kp.SelectionDict = {
            "udts": set(),
            "udt_members": udt_members,         # Dict[str, Set[str]]
            "aois": set(),
            "aoi_parameters": aoi_parameters,   # Dict[str, Set[str]]
            "aoi_localtags": aoi_localtags,     # Dict[str, Set[str]]
            "tags": set(),                      # global tags
            "program_tags": program_tags,
        }

        for iid, checked in self.tree_state.checks.items():
            if not checked:
                continue
            meta = self.tree_state.get_meta(iid)
            if not meta:
                continue
            node_type = meta.node_type
            name = str(meta.name)
            parent = meta.parent

            if node_type == MemberType.TAG and not parent:
                sel["tags"].add(name)

            elif node_type == MemberType.UDT:
                sel["udts"].add(name)

            elif node_type == MemberType.UDT_MEMBER and parent:
                sel["udt_members"].setdefault(str(parent), set()).add(name)
                sel["udts"].add(str(parent))

            elif node_type == MemberType.AOI:
                sel["aois"].add(name)

            elif node_type == MemberType.AOI_PARAMETER and parent:
                sel["aoi_parameters"].setdefault(str(parent), set()).add(name)
                sel["aois"].add(str(parent))

            elif node_type == MemberType.AOI_LOCAL_TAG and parent:
                sel["aoi_localtags"].setdefault(str(parent), set()).add(name)
                sel["aois"].add(str(parent))

            elif node_type == MemberType.TAG and parent:
                sel["program_tags"].setdefault(str(parent), set()).add(name)

        return sel

    # ---------------- Summary ----------------
    def _show_summary(self, corrected_tags_log: list[str]) -> None:
        summary = (
            "File parsed successfully.\n"
            f"Number of tags corrected: {len(corrected_tags_log)}\n"
            f"Corrections have been logged to '{get_log_path()}'."
        )
        for entry in corrected_tags_log:
            logger.info(entry)
        self._log_message(summary)

    # ---------------- Serialization helpers ----------------
    def _serialize_checkbox_states(self) -> list[dict[str, Any]]:
        return self.tree_state.serialize()

    def _restore_checkbox_states(self, saved: list[dict[str, Any]]) -> None:
        self.tree_state.restore(saved)
        # reconcile parent states once across the whole tree
        self.tree_state.update_parent_states(self.tree, None)
        if self.selected_item_id:
            self.select_var.set(self.tree_state.get_checked(self.selected_item_id, False))

    def _merge_updated_l5k(self) -> None:
        if not self.project:
            messagebox.showwarning("Warning", "Load a project before merging an updated L5K.")
            return

        file_path = filedialog.askopenfilename(filetypes=[("L5K Files", "*.l5k;*.L5K"), ("All Files", "*.*")])
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                file_content = f.read()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Error", f"Failed to read file: {e}")
            return

        previous_keys = self._keys_for_project(self.project)
        saved_states = self._serialize_checkbox_states()

        try:
            new_parser = l5kp.L5KParser(file_content)
            new_project, corrected_log = new_parser.parse()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Error", f"Failed to parse updated L5K:\n{e}")
            return

        new_keys = self._keys_for_project(new_project)
        added = sorted(new_keys - previous_keys)
        removed = sorted(previous_keys - new_keys)
        self._show_merge_preview(
            file_path=file_path,
            new_project=new_project,
            new_parser=new_parser,
            corrected_log=corrected_log,
            saved_states=saved_states,
            added=added,
            removed=removed,
        )

    def _project_to_dict(self, project: models.L5KProject) -> dict[str, Any]:
        data: dict[str, Any] = {
            "header": project.header.content if project.header else "",
            "udts": [],
            "aois": [],
            "tags": [],
            "programs": [],
        }
        for udt in project.udts.values():
            members = []
            for m in udt.members.values():
                members.append({
                    "name": m.name,
                    "data_type": m.data_type,
                    "description": m.description,
                    "definition": m.definition,
                    "is_hidden_parent": m.is_hidden_parent,
                    "is_bit": m.is_bit,
                    "parent_word": m.parent_word,
                    "bit_index": m.bit_index,
                    "name_dims": m.name_dims,
                    "children": [
                        {
                            "name": c.name,
                            "data_type": c.data_type,
                            "description": c.description,
                            "definition": c.definition,
                            "is_hidden_parent": c.is_hidden_parent,
                            "is_bit": c.is_bit,
                            "parent_word": c.parent_word,
                            "bit_index": c.bit_index,
                            "name_dims": c.name_dims,
                        }
                        for c in getattr(m, "children", {}).values()
                    ]
                })
            data["udts"].append({
                "name": udt.name,
                "description": udt.description,
                "family_type": udt.family_type,
                "members": members,
            })

        for aoi in project.aois.values():
            params = []
            for p in aoi.parameters.values():
                params.append({
                    "name": p.name,
                    "data_type": p.data_type,
                    "description": p.description,
                    "definition": p.definition,
                    "is_bit_alias": getattr(p, "is_bit_alias", False),
                })
            locals_ = []
            for t in aoi.localtags.values():
                locals_.append({
                    "name": t.name,
                    "data_type": t.data_type,
                    "description": t.description,
                    "definition": t.definition,
                })
            data["aois"].append({
                "name": aoi.name,
                "description": aoi.description,
                "parameters": params,
                "localtags": locals_,
            })

        for tag in project.tags.values():
            data["tags"].append({
                "name": tag.name,
                "data_type": tag.data_type,
                "description": tag.description,
                "definition": tag.definition,
            })

        for prog in project.programs.values():
            prog_tags = []
            for t in prog.tags.values():
                prog_tags.append({
                    "name": t.name,
                    "data_type": t.data_type,
                    "description": t.description,
                    "definition": t.definition,
                })
            data["programs"].append({
                "name": prog.name,
                "description": prog.description,
                "tags": prog_tags,
            })
        return data

    def _project_from_dict(self, data: dict[str, Any]) -> models.L5KProject:
        proj = models.L5KProject()
        header = data.get("header")
        if header:
            proj.header = models.L5KHeader(header)

        for udt_data in data.get("udts", []):
            udt = models.UDT(udt_data["name"], udt_data.get("description", ""))
            udt.family_type = udt_data.get("family_type", "NoFamily")
            for m in udt_data.get("members", []):
                member = models.UDTMember(
                    m["name"],
                    m["data_type"],
                    description=m.get("description", ""),
                    definition=m.get("definition"),
                    is_hidden_parent=m.get("is_hidden_parent", False),
                    is_bit=m.get("is_bit", False),
                    parent_word=m.get("parent_word"),
                    bit_index=m.get("bit_index"),
                    name_dims=m.get("name_dims", ""),
                )
                for c in m.get("children", []):
                    child = models.UDTMember(
                        c["name"],
                        c["data_type"],
                        description=c.get("description", ""),
                        definition=c.get("definition"),
                        is_hidden_parent=c.get("is_hidden_parent", False),
                        is_bit=c.get("is_bit", False),
                        parent_word=c.get("parent_word"),
                        bit_index=c.get("bit_index"),
                        name_dims=c.get("name_dims", ""),
                    )
                    member.add_child(child)
                udt.add_member(member)
            proj.udts[udt.name] = udt

        for aoi_data in data.get("aois", []):
            aoi = models.AOI(aoi_data["name"], aoi_data.get("description", ""))
            for p in aoi_data.get("parameters", []):
                param = models.AOIParameter(
                    p["name"],
                    p["data_type"],
                    description=p.get("description", ""),
                    definition=p.get("definition"),
                    is_bit_alias=p.get("is_bit_alias", False),
                )
                aoi.add_parameter(param)
            for t in aoi_data.get("localtags", []):
                lt = models.AOILocalTag(
                    t["name"],
                    t["data_type"],
                    description=t.get("description", ""),
                    definition=t.get("definition"),
                )
                aoi.add_localtag(lt)
            proj.aois[aoi.name] = aoi

        for tag_data in data.get("tags", []):
            proj.tags[tag_data["name"]] = models.Tag(
                name=tag_data["name"],
                data_type=tag_data["data_type"],
                description=tag_data.get("description", ""),
                definition=tag_data.get("definition"),
            )

        for prog_data in data.get("programs", []):
            prog = models.Program(prog_data["name"], prog_data.get("description", ""))
            for t in prog_data.get("tags", []):
                prog.tags[t["name"]] = models.Tag(
                    name=t["name"],
                    data_type=t["data_type"],
                    description=t.get("description", ""),
                    definition=t.get("definition"),
                )
            proj.programs[prog.name] = prog
        return proj

    # Ensure clean shutdown for the background process
    def _on_close(self):
        if not self._confirm_discard_changes("exiting"):
            return
        # Try to cancel a running parse cleanly
        self._cleanup_executor()
        # Close the window
        self.master.destroy()

    def _cleanup_executor(self):
        """Best-effort shutdown to avoid interpreter teardown warnings."""
        fut = getattr(self, "_parse_future", None)
        if fut is not None and not fut.done():
            try:
                fut.cancel()
            except Exception:
                pass
            self._parse_future = None

        exec_ = getattr(self, "_executor", None)
        if exec_ is not None:
            try:
                exec_.shutdown(wait=True, cancel_futures=True)
            except TypeError:
                exec_.shutdown(wait=True)
            except Exception:
                pass
            self._executor = None

    def _ensure_executor(self) -> concurrent.futures.Executor:
        """Return a live executor, recreating if it was shut down."""
        exec_ = self._executor
        if exec_ is None or getattr(exec_, "_shutdown", False):
            exec_ = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            self._executor = exec_
        return exec_

    def _set_window_title(self, path: Optional[str]) -> None:
        base = os.path.basename(path) if path else ""
        title = "L5K File Processor"
        if base:
            title = f"{title} - {base}"
        if self._dirty:
            title = f"{title} *"
        self.master.title(title)

    def _refresh_window_title(self) -> None:
        path = self._last_project_path or self._last_source_label or None
        self._set_window_title(path)

    def _set_status(self, text: str, source: Optional[str]) -> None:
        label = text
        src = source or self._last_source_label
        if src:
            label = f"{text} ... {src}"
        self.status_label.config(text=label)

    def _set_filter_mode(self, mode: str) -> None:
        saved = self._serialize_checkbox_states()
        self._filter_mode = mode
        self._filter_var.set(mode)
        self._populate_tree(saved_states=saved)

    def _apply_filter(self) -> None:
        apply_filter(self.tree, self.tree_state, self._filter_mode)

    def _set_selection_controls_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        if hasattr(self, "select_checkbox") and self.select_checkbox:
            self.select_checkbox.configure(state=state)
        if hasattr(self, "btn_include_selected") and self.btn_include_selected:
            self.btn_include_selected.configure(state=state)
        if hasattr(self, "btn_exclude_selected") and self.btn_exclude_selected:
            self.btn_exclude_selected.configure(state=state)
        
if __name__ == "__main__":
    root = tk.Tk()
    app = L5KTunerApp(root)
    root.mainloop()
