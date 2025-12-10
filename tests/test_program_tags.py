import L5KTuner.l5k_parser as lp

def test_program_tags_parsed_and_exported():
    sample = """(*******)
CONTROLLER C ()
TAG
    CtrlTag : DINT;
END_TAG
PROGRAM P1 ()
    TAG
        PT1 : BOOL;
        PT2 : DINT (Description := "prog tag");
    END_TAG
END_PROGRAM
END_CONTROLLER
"""
    parser = lp.L5KParser(sample)
    project, _ = parser.parse()

    # Parsed
    assert "PT1" in project.programs["P1"].tags
    assert project.programs["P1"].tags["PT2"].description == "prog tag"

    # Export filtered to only PT2
    selection = {
        "udts": set(),
        "udt_members": {},
        "aois": set(),
        "aoi_parameters": {},
        "aoi_localtags": {},
        "tags": set(),
        "program_tags": {"P1": {"PT2"}},
    }
    out = parser.export_whitelist(selection)
    assert "PROGRAM P1" in out
    assert "PT2 : DINT" in out
    assert "PT1" not in out
    assert "CtrlTag" not in out  # not selected
