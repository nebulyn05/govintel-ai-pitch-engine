from scripts.orchestrator import construct_local_pitch, load_blueprints


def test_blueprints_load_from_project_root():
    matrix=load_blueprints()
    assert "default" in matrix
    assert "236220" in matrix


def test_unknown_naics_is_hypothesis_not_fact():
    matrix=load_blueprints()
    channel,bottleneck,solution,pitch=construct_local_pitch({"Legal Business Name":"Example Co","NAICS Code":"999999"},matrix)
    assert channel=="review_required"
    assert "not a verified issue" in pitch.lower()


def test_matrix_keys_match_orchestrator():
    for item in load_blueprints().values():
        assert "sector" in item
        assert "core_bottleneck" in item
        assert "on_prem_solution" in item
