import L5KTuner.models as models
from L5KTuner.gui import L5KTunerApp


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
