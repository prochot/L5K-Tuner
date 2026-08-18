from L5KTuner.gui import L5KTunerApp


def test_merge_items_follow_tree_group_order():
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

    assert sorted(items, key=L5KTunerApp._merge_item_sort_key) == [
        ("UDT", "MotorData", None),
        ("UDT_MEMBER", "MemberA", "MotorData"),
        ("UDT_MEMBER", "MemberB", "MotorData"),
        ("AOI", "P_LLS", None),
        ("AOI_PARAMETER", "EnableIn", "P_LLS"),
        ("AOI_LOCAL_TAG", "CantStart", "P_LLS"),
        ("TAG", "ControllerTag", None),
        ("PROGRAM_TAG", "ProgramTag", "MainProgram"),
    ]


def test_merge_child_display_uses_parent_type_name_order():
    item = ("AOI_LOCAL_TAG", "CantStart", "P_LLS")

    assert L5KTunerApp._format_merge_item(item) == "P_LLS / AOI_LOCAL_TAG / CantStart"
    assert L5KTunerApp._format_merge_item(("AOI", "P_LLS", None)) == "AOI / P_LLS"
