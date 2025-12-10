import json
import pytest

import L5KTuner.models as models
from L5KTuner.tree_state import TreeState, TreeNodeMeta
from L5KTuner.l5k_parser import L5KParser


def test_project_roundtrip_without_gui(tmp_path):
    pytest.importorskip("tkinter")
    # Build minimal project
    proj = models.L5KProject()
    proj.header = models.L5KHeader("(* header *)")
    proj.tags["T1"] = models.Tag("T1", "DINT", definition="T1 : DINT;")
    proj.tags["T2"] = models.Tag("T2", "BOOL", definition="T2 : BOOL;")

    # Fake parser for save
    parser = L5KParser("")
    parser.project = proj
    parser.corrected_tags_log = []
    parser.header_text = ""
    parser.controller_header_lines = []
    parser.controller_name = None

    # Build checkbox state snapshot
    ts = TreeState()
    ts.set_meta("header", TreeNodeMeta(models.MemberType.HEADER, "L5K Header"))
    ts.set_checked("header", True)
    ts.set_meta("tags_root", TreeNodeMeta(models.MemberType.ROOT_CONTROLLER_TAGS, "Controller Tags"))
    ts.set_checked("tags_root", True)
    ts.set_meta("t1", TreeNodeMeta(models.MemberType.TAG, "T1"))
    ts.set_checked("t1", True)
    ts.set_meta("t2", TreeNodeMeta(models.MemberType.TAG, "T2"))
    ts.set_checked("t2", False)

    payload = {
        "controller_header_lines": parser.controller_header_lines,
        "controller_name": parser.controller_name,
        "header_text": parser.header_text,
        "project": {
            "header": proj.header.content if proj.header else "",
            "udts": [],
            "aois": [],
            "tags": [
                {"name": t.name, "data_type": t.data_type, "description": t.description, "definition": t.definition}
                for t in proj.tags.values()
            ],
            "programs": [],
        },
        "checkbox_states": ts.serialize(),
    }
    path = tmp_path / "roundtrip.l5kproj"
    path.write_text(json.dumps(payload))

    # Load payload without Tk and rebuild project/state
    data = json.loads(path.read_text())
    parser2 = L5KParser("")
    project_dict = data["project"]
    project = models.L5KProject()
    project.header = models.L5KHeader(project_dict.get("header", ""))
    for tag in project_dict.get("tags", []):
        project.tags[tag["name"]] = models.Tag(
            tag["name"], tag["data_type"], tag.get("description", ""), tag.get("definition")
        )
    parser2.project = project
    parser2.corrected_tags_log = []
    parser2.header_text = data.get("header_text", "")
    parser2.controller_header_lines = data.get("controller_header_lines", [])
    parser2.controller_name = data.get("controller_name", None)

    ts2 = TreeState()
    ts2.set_meta("header", TreeNodeMeta(models.MemberType.HEADER, "L5K Header"))
    ts2.set_meta("tags_root", TreeNodeMeta(models.MemberType.ROOT_CONTROLLER_TAGS, "Controller Tags"))
    ts2.set_meta("t1", TreeNodeMeta(models.MemberType.TAG, "T1"))
    ts2.set_meta("t2", TreeNodeMeta(models.MemberType.TAG, "T2"))
    ts2.restore(data["checkbox_states"])

    # Ensure state survives
    assert ts2.get_checked("t1") is True
    assert ts2.get_checked("t2") is False
