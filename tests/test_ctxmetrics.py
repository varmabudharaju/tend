from tend import ctxmetrics, paths


def test_used_pct_from_ctx_json(tend_home):
    paths.write_json_atomic(
        paths.session_dir("s1") / "ctx.json",
        {"context_window": {"used_percentage": 61.2}},
    )
    assert ctxmetrics.used_pct("s1") == 61.2


def test_used_pct_none_when_missing(tend_home):
    assert ctxmetrics.used_pct("nope") is None


def test_used_pct_none_when_field_absent(tend_home):
    paths.write_json_atomic(paths.session_dir("s1") / "ctx.json", {"context_window": {}})
    assert ctxmetrics.used_pct("s1") is None


def test_session_model_tier_mapping(tend_home):
    from tend import ctxmetrics, paths

    cases = {"Fable 5": "fable", "Opus 4.8": "opus", "claude-sonnet-4-6": "sonnet",
             "Haiku 4.5": "haiku", "Mystery Model": None}
    for name, tier in cases.items():
        paths.write_json_atomic(paths.session_dir("sm") / "ctx.json",
                                {"model": {"display_name": name}})
        assert ctxmetrics.session_model_tier("sm") == tier, name


def test_session_model_tier_no_ctx(tend_home):
    from tend import ctxmetrics

    assert ctxmetrics.session_model_tier("nope") is None
