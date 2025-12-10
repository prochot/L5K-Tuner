import L5KTuner.l5k_parser as lp

def test_aoi_base_type_correction_resolves_bit_alias():
    sample = """(*******)
CONTROLLER C ()
ADD_ON_INSTRUCTION_DEFINITION Parent ()
PARAMETERS
    BoolWord : DINT ();
END_PARAMETERS
LOCAL_TAGS
END_LOCAL_TAGS
END_ADD_ON_INSTRUCTION_DEFINITION

ADD_ON_INSTRUCTION_DEFINITION Child ()
PARAMETERS
    BitParam OF LocWord.3 (Description := "bit ref");
END_PARAMETERS
LOCAL_TAGS
    LocWord : DINT ();
END_LOCAL_TAGS
END_ADD_ON_INSTRUCTION_DEFINITION
END_CONTROLLER
"""
    parser = lp.L5KParser(sample)
    project, corrections = parser.parse()

    child = project.aois["Child"]
    assert child.parameters["BitParam"].data_type == "BOOL"
    assert any("Child.BitParam" in c for c in corrections)

def test_aoi_base_type_correction_through_localtag():
    sample = """(*******)
CONTROLLER C ()
ADD_ON_INSTRUCTION_DEFINITION Inner ()
PARAMETERS
    X : DINT ();
END_PARAMETERS
LOCAL_TAGS
    Dummy : BOOL ();
END_LOCAL_TAGS
END_ADD_ON_INSTRUCTION_DEFINITION

ADD_ON_INSTRUCTION_DEFINITION Outer ()
PARAMETERS
    Ref OF InnerInst.X ();
END_PARAMETERS
LOCAL_TAGS
    InnerInst : Inner ();
END_LOCAL_TAGS
END_ADD_ON_INSTRUCTION_DEFINITION
END_CONTROLLER
"""
    parser = lp.L5KParser(sample)
    project, corrections = parser.parse()

    outer = project.aois["Outer"]
    assert outer.parameters["Ref"].data_type == "DINT"
    assert any("Outer.Ref" in c for c in corrections)
