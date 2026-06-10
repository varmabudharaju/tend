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
