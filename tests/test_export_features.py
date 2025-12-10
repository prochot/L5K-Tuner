import L5KTuner.l5k_parser as lp


def _run_export(sample: str, selection):
    parser = lp.L5KParser(sample)
    project, _ = parser.parse()
    parser.project = project
    return parser.export_whitelist(selection)


def test_program_tag_export_shape():
    sample = """(*******)
CONTROLLER C ()
TAG
    CtrlTag : DINT;
END_TAG
PROGRAM P1 (Description := "prog desc")
    TAG
        PT1 : BOOL;
        PT2 : DINT (Description := "prog tag");
    END_TAG
END_PROGRAM
END_CONTROLLER
"""
    parser = lp.L5KParser(sample)
    project, _ = parser.parse()
    sel = {
        "udts": set(),
        "udt_members": {},
        "aois": set(),
        "aoi_parameters": {},
        "aoi_localtags": {},
        "tags": set(),  # no controller tags
        "program_tags": {"P1": {"PT2"}},
    }
    out = parser.export_whitelist(sel)
    assert "CONTROLLER" in out
    assert "PROGRAM P1" in out
    assert "PT2 : DINT" in out
    assert "PT1" not in out
    assert "CtrlTag" not in out


def test_controller_tag_attrs_and_value_stripped():
    sample = """(*******)
CONTROLLER C ()
TAG
    MyTag : DINT (Description := "desc", ExternalAccess := ReadOnly) := 5;
    BadTag this will be skipped
END_TAG
END_CONTROLLER
"""
    parser = lp.L5KParser(sample)
    project, _ = parser.parse()
    tag = project.tags["MyTag"]
    assert tag.description == "desc"
    assert ":= 5" not in tag.definition  # value removed
    assert "Description :=" in tag.definition  # attrs preserved
    assert "BadTag" not in project.tags


def test_aoi_defaultdata_stripped():
    sample = """(*******)
CONTROLLER C ()
ADD_ON_INSTRUCTION_DEFINITION A ()
PARAMETERS
    P1 : DINT (DefaultData := 123, Description := "keep me");
END_PARAMETERS
LOCAL_TAGS
    L1 : DINT (DefaultData := 0);
END_LOCAL_TAGS
END_ADD_ON_INSTRUCTION_DEFINITION
END_CONTROLLER
"""
    parser = lp.L5KParser(sample)
    project, _ = parser.parse()
    aoi = project.aois["A"]
    assert "DefaultData" not in aoi.parameters["P1"].definition
    assert "DefaultData" not in aoi.localtags["L1"].definition


def test_nested_bit_alias_correction():
    sample = """(*******)
CONTROLLER C ()
ADD_ON_INSTRUCTION_DEFINITION Inner ()
PARAMETERS
    P OF Word.3 ();
END_PARAMETERS
LOCAL_TAGS
    Word : DINT ();
END_LOCAL_TAGS
END_ADD_ON_INSTRUCTION_DEFINITION

ADD_ON_INSTRUCTION_DEFINITION Outer ()
PARAMETERS
    Alias OF InnerInst.P ();
END_PARAMETERS
LOCAL_TAGS
    InnerInst : Inner ();
END_LOCAL_TAGS
END_ADD_ON_INSTRUCTION_DEFINITION
END_CONTROLLER
"""
    parser = lp.L5KParser(sample)
    project, corrections = parser.parse()
    inner = project.aois["Inner"]
    assert inner.parameters["P"].data_type == "BOOL"
    outer = project.aois["Outer"]
    assert outer.parameters["Alias"].data_type == "BOOL"
    assert any("Inner.P" in c for c in corrections)
    assert any("Outer.Alias" in c for c in corrections)


def test_udt_hidden_word_bit_children_parsed():
    sample = """(*******)
CONTROLLER C ()
DATATYPE U ()
    SINT ZZZZZZZZZZHidden (Hidden := 1);
        BIT A ZZZZZZZZZZHidden : 0;
        BIT B ZZZZZZZZZZHidden : 1;
END_DATATYPE
END_CONTROLLER
"""
    parser = lp.L5KParser(sample)
    project, _ = parser.parse()
    udt = project.udts["U"]
    assert "ZZZZZZZZZZHidden" in udt.members
    parent = udt.members["ZZZZZZZZZZHidden"]
    assert parent.is_hidden_parent
    assert set(parent.children.keys()) == {"A", "B"}


def test_program_description_captured_and_exported():
    sample = """(*******)
CONTROLLER C ()
PROGRAM P1 (Description := "hello")
    TAG
        T1 : DINT;
    END_TAG
END_PROGRAM
END_CONTROLLER
"""
    parser = lp.L5KParser(sample)
    project, _ = parser.parse()
    assert project.programs["P1"].description == "hello"
    out = parser.export_whitelist({
        "udts": set(),
        "udt_members": {},
        "aois": set(),
        "aoi_parameters": {},
        "aoi_localtags": {},
        "tags": set(),
        "program_tags": {"P1": {"T1"}},
    })
    assert 'PROGRAM P1 (Description := "hello")' in out


def test_get_selected_content_skips_routines():
    sample = """(*******)
CONTROLLER C ()
ROUTINE ShouldSkip
END_ROUTINE
TAG
    KeepMe : DINT;
END_TAG
END_CONTROLLER
"""
    parser = lp.L5KParser(sample)
    project, _ = parser.parse()
    parser.project = project
    out = parser.get_selected_content({
        "udts": set(),
        "udt_members": {},
        "aois": set(),
        "aoi_parameters": {},
        "aoi_localtags": {},
        "tags": {"KeepMe"},
    })
    assert "ROUTINE" not in out
    assert "KeepMe" in out
