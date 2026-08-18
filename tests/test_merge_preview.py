import L5KTuner.models as models
from L5KTuner.gui import L5KTunerApp
from L5KTuner.tree_state import TreeNodeMeta, TreeState


def test_merge_items_omit_parents_and_follow_tree_group_order():
    items = [
        ("PROGRAM_TAG", "ProgramTag", "MainProgram"),
        ("AOI_LOCAL_TAG", "CantStart", "P_LLS"),
        ("TAG", "ControllerTag", None),
        ("UDT_MEMBER", "MemberB", "MotorData"),
        ("AOI", "P_LLS", None),
        ("UDT", "MotorData", None),
        ("AOI_PARAMETER", "EnableIn", "P_LLS"),
        ("UDT_MEMBER", "MemberA", "MotorData"),
    ]

    assert L5KTunerApp._merge_preview_items(set(items)) == [
        ("UDT_MEMBER", "MemberA", "MotorData"),
        ("UDT_MEMBER", "MemberB", "MotorData"),
        ("AOI_PARAMETER", "EnableIn", "P_LLS"),
        ("AOI_LOCAL_TAG", "CantStart", "P_LLS"),
        ("TAG", "ControllerTag", None),
        ("PROGRAM_TAG", "ProgramTag", "MainProgram"),
    ]


def test_merge_child_display_uses_parent_type_name_order():
    item = ("AOI_LOCAL_TAG", "CantStart", "P_LLS")

    assert L5KTunerApp._format_merge_item(item) == "P_LLS / AOI_LOCAL_TAG / CantStart"
    assert L5KTunerApp._format_merge_item(("AOI", "P_LLS", None)) == "AOI / P_LLS"


def test_merge_export_defaults_match_main_tree_defaults():
    assert not L5KTunerApp._default_merge_export_state(("AOI_LOCAL_TAG", "Local", "P_LLS"))
    assert not L5KTunerApp._default_merge_export_state(("AOI_PARAMETER", "EnableIn", "P_LLS"))
    assert not L5KTunerApp._default_merge_export_state(("UDT_MEMBER", "EnableOut", "MotorData"))
    assert L5KTunerApp._default_merge_export_state(("AOI_PARAMETER", "Run", "P_LLS"))
    assert L5KTunerApp._default_merge_export_state(("PROGRAM_TAG", "EnableIn", "MainProgram"))


def test_merge_export_requires_item_to_be_added():
    assert L5KTunerApp._effective_merge_export_state(True, True)
    assert not L5KTunerApp._effective_merge_export_state(True, False)
    assert not L5KTunerApp._effective_merge_export_state(False, True)
    assert not L5KTunerApp._effective_merge_export_state(False, False)


def test_merge_export_states_map_program_tags_to_main_tree_keys():
    class FlatTree:
        def parent(self, _item_id):
            return ""

        def item(self, _item_id, **_kwargs):
            return None

    app = L5KTunerApp.__new__(L5KTunerApp)
    app.tree = FlatTree()
    app.tree_state = TreeState()
    app._newly_merged_keys = set()
    app.tree_state.set_meta(
        "program-tag",
        TreeNodeMeta(models.MemberType.TAG, "Alarm", parent="MainProgram"),
    )
    app.tree_state.set_checked("program-tag", True)

    app._apply_merged_export_states({("PROGRAM_TAG", "Alarm", "MainProgram"): False})

    assert not app.tree_state.get_checked("program-tag")


def test_new_highlight_combines_with_excluded_text_and_clears():
    class FlatTree:
        def __init__(self):
            self.tags = {}

        def item(self, item_id, **kwargs):
            self.tags[item_id] = kwargs.get("tags")

    item_key = ("AOI_LOCAL_TAG", "CantStart", "P_LLS")
    app = L5KTunerApp.__new__(L5KTunerApp)
    app.tree = FlatTree()
    app.tree_state = TreeState()
    app.tree_state.set_meta(
        "local-tag",
        TreeNodeMeta(models.MemberType.AOI_LOCAL_TAG, "CantStart", parent="P_LLS"),
    )
    app.tree_state.set_checked("local-tag", False)
    app._newly_merged_keys = {item_key}

    app._apply_tree_tags()

    assert app.tree.tags["local-tag"] == ("excluded", "new")

    app._clear_newly_merged_highlights()

    assert not app._newly_merged_keys
    assert app.tree.tags["local-tag"] == ("excluded",)


def test_selected_children_create_only_their_required_parents():
    current_project = models.L5KProject()
    updated_project = models.L5KProject()

    udt = models.UDT("MotorData", "Motor information")
    udt.family_type = "InputFamily"
    udt.add_member(models.UDTMember("SelectedMember", "BOOL"))
    udt.add_member(models.UDTMember("UnselectedMember", "DINT"))
    updated_project.udts[udt.name] = udt

    aoi = models.AOI("P_LLS", "Low-level switch")
    aoi.add_parameter(models.AOIParameter("SelectedParameter", "BOOL"))
    aoi.add_localtag(models.AOILocalTag("UnselectedLocal", "DINT"))
    updated_project.aois[aoi.name] = aoi

    program = models.Program("MainProgram", "Main program")
    program.tags["SelectedTag"] = models.Tag("SelectedTag", "BOOL")
    program.tags["UnselectedTag"] = models.Tag("UnselectedTag", "DINT")
    updated_project.programs[program.name] = program

    app = L5KTunerApp.__new__(L5KTunerApp)
    app.project = current_project
    app._apply_merge_changes(
        updated_project,
        [
            ("UDT_MEMBER", "SelectedMember", "MotorData"),
            ("AOI_PARAMETER", "SelectedParameter", "P_LLS"),
            ("PROGRAM_TAG", "SelectedTag", "MainProgram"),
        ],
        [],
    )

    assert list(current_project.udts["MotorData"].members) == ["SelectedMember"]
    assert current_project.udts["MotorData"].family_type == "InputFamily"
    assert list(current_project.aois["P_LLS"].parameters) == ["SelectedParameter"]
    assert not current_project.aois["P_LLS"].localtags
    assert list(current_project.programs["MainProgram"].tags) == ["SelectedTag"]


def test_removing_last_child_removes_empty_parent():
    current_project = models.L5KProject()
    updated_project = models.L5KProject()

    udt = models.UDT("MotorData")
    udt.add_member(models.UDTMember("LastMember", "BOOL"))
    current_project.udts[udt.name] = udt

    aoi = models.AOI("P_LLS")
    aoi.add_localtag(models.AOILocalTag("LastLocal", "BOOL"))
    current_project.aois[aoi.name] = aoi

    program = models.Program("MainProgram")
    program.tags["LastTag"] = models.Tag("LastTag", "BOOL")
    current_project.programs[program.name] = program

    app = L5KTunerApp.__new__(L5KTunerApp)
    app.project = current_project
    app._apply_merge_changes(
        updated_project,
        [],
        [
            ("UDT_MEMBER", "LastMember", "MotorData"),
            ("AOI_LOCAL_TAG", "LastLocal", "P_LLS"),
            ("PROGRAM_TAG", "LastTag", "MainProgram"),
        ],
    )

    assert "MotorData" not in current_project.udts
    assert "P_LLS" not in current_project.aois
    assert "MainProgram" not in current_project.programs
