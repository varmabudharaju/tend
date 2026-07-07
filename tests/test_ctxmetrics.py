from carryover import ctxmetrics, paths


def test_used_pct_from_ctx_json(carryover_home):
    paths.write_json_atomic(
        paths.session_dir("s1") / "ctx.json",
        {"context_window": {"used_percentage": 61.2}},
    )
    assert ctxmetrics.used_pct("s1") == 61.2


def test_used_pct_none_when_missing(carryover_home):
    assert ctxmetrics.used_pct("nope") is None


def test_used_pct_none_when_field_absent(carryover_home):
    paths.write_json_atomic(paths.session_dir("s1") / "ctx.json", {"context_window": {}})
    assert ctxmetrics.used_pct("s1") is None


def test_session_model_tier_mapping(carryover_home):
    from carryover import ctxmetrics, paths

    cases = {"Fable 5": "fable", "Opus 4.8": "opus", "claude-sonnet-4-6": "sonnet",
             "Haiku 4.5": "haiku", "Mystery Model": None}
    for name, tier in cases.items():
        paths.write_json_atomic(paths.session_dir("sm") / "ctx.json",
                                {"model": {"display_name": name}})
        assert ctxmetrics.session_model_tier("sm") == tier, name


def test_session_model_tier_no_ctx(carryover_home):
    from carryover import ctxmetrics

    assert ctxmetrics.session_model_tier("nope") is None
