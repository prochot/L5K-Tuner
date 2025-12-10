import json
import tkinter as tk
import pytest

import L5KTuner.gui as gui
import L5KTuner.models as models


def _build_app_with_project() -> gui.L5KTunerApp:
    pytest.importorskip("tkinter")
    # Build a minimal project in memory
    proj = models.L5KProject()
    proj.header = models.L5KHeader("(* header *)")
    proj.tags["T1"] = models.Tag("T1", "DINT", definition="T1 : DINT;")
    proj.tags["T2"] = models.Tag("T2", "BOOL", definition="T2 : BOOL;")

    udt = models.UDT("U")
    udt.add_member(models.UDTMember("M1", "INT"))
    proj.udts["U"] = udt

    prog = models.Program("P1")
    prog.tags["PT1"] = models.Tag("PT1", "REAL", definition="PT1 : REAL;")
    proj.programs["P1"] = prog

    try:
        root = tk.Tk()
        root.withdraw()  # no visible window during tests
    except tk.TclError:
        pytest.skip("Tk not available in this environment")
    app = gui.L5KTunerApp(root)
    app.project = proj
    app.parser = None
    app._populate_tree()
    return app


def test_filter_modes_all_enabled_disabled():
    app = _build_app_with_project()

    # Ensure default is "all"
    assert app._filter_mode == "all"
    total_items = len(app.tree.get_children(""))

    # Disable a tag and apply "enabled" filter
    for iid, meta in app.tree_state.meta.items():
        if meta.node_type == models.MemberType.TAG and meta.name == "T2":
            app.tree_state.set_checked(iid, False)
            break

    # Disabled filter first: should show items that include unchecked nodes
    app._set_filter_mode("disabled")
    disabled_roots = set(app.tree.get_children(""))
    assert disabled_roots  # at least one root remains

    # Enabled filter: should show items that are checked
    app._set_filter_mode("enabled")
    enabled_roots = set(app.tree.get_children(""))
    assert enabled_roots

    # Back to all restores everything
    app._set_filter_mode("all")
    assert len(app.tree.get_children("")) == total_items


def test_project_save_load_round_trip(tmp_path):
    app = _build_app_with_project()
    # Uncheck one node to track persistence
    unchecked = None
    for iid, meta in app.tree_state.meta.items():
        if meta.node_type == models.MemberType.TAG and meta.name == "T2":
            app.tree_state.set_checked(iid, False)
            unchecked = (meta.node_type.name, meta.name, meta.parent)
            break
    payload = {
        "project": app._project_to_dict(app.project),
        "checkbox_states": app._serialize_checkbox_states(),
        "header_text": getattr(app.parser, "header_text", "") if app.parser else "",
        "controller_header_lines": getattr(app.parser, "controller_header_lines", []) if app.parser else [],
        "controller_name": getattr(app.parser, "controller_name", None) if app.parser else None,
    }
    path = tmp_path / "proj.l5kproj"
    path.write_text(json.dumps(payload))

    # New app instance, load payload without original L5K
    try:
        root2 = tk.Tk()
        root2.withdraw()
    except tk.TclError:
        pytest.skip("Tk not available in this environment")
    app2 = gui.L5KTunerApp(root2)
    data = json.loads(path.read_text())
    project = app2._project_from_dict(data["project"])
    app2.project = project
    parser = gui.l5kp.L5KParser("")
    parser.project = project
    parser.corrected_tags_log = []
    parser.header_text = data.get("header_text", "")
    parser.controller_header_lines = data.get("controller_header_lines", [])
    parser.controller_name = data.get("controller_name", None)
    app2.parser = parser
    app2._populate_tree()
    app2._restore_checkbox_states(data["checkbox_states"])

    # Ensure the unchecked state survived
    found = False
    for iid, meta in app2.tree_state.meta.items():
        key = (meta.node_type.name, meta.name, meta.parent)
        if key == unchecked:
            assert app2.tree_state.get_checked(iid) is False
            found = True
    assert found
