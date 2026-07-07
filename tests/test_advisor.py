from carryover import advisor, config, state


def cfg():
    return config.load()


def test_levels():
    c = cfg()
    assert advisor.level(None, c) is None
    assert advisor.level(40, c) is None
    assert advisor.level(60, c) == "advise"
    assert advisor.level(75, c) == "urge"


def test_advice_none_below_threshold(tmp_path):
    assert advisor.advice(40, cfg(), tmp_path / "STATE.md", {}) is None


def test_advise_with_boundary(tmp_path):
    sp = state.path_for(str(tmp_path))
    state.seed(sp)
    text = advisor.advice(60, cfg(), sp, {"boundary": True})
    assert text.startswith("Task boundary")
    assert "/compact" in text


def test_urge_includes_run_now(tmp_path):
    text = advisor.advice(80, cfg(), tmp_path / "STATE.md", {})
    assert "run now" in text and "/compact" in text


def test_instructions_include_goal(tmp_path):
    sp = state.path_for(str(tmp_path))
    sp.parent.mkdir(parents=True)
    sp.write_text("## Goal\nShip carryover v1\n## Now\nx\n")
    assert "Ship carryover v1" in advisor.compact_instructions(sp)
