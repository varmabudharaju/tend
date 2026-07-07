"""Adaptive anchor: fingerprint suppression + refresh turns."""
from conftest import make_event

from carryover import anchor, config, flags, paths, precompact, sessionstart, state


def seed_state(tmp_path, goal="Ship carryover", now="Writing anchor"):
    sp = state.path_for(str(tmp_path))
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(f"## Goal\n{goal}\n\n## Now\n{now}\n")
    return sp


def seed_ctx(pct):
    paths.write_json_atomic(
        paths.session_dir("s1") / "ctx.json",
        {"context_window": {"used_percentage": pct}},
    )


def seed_stale(*sizes):
    """Stale tool results; each < offload_threshold so bloat stays put."""
    results = {
        f"r{i}": {"tool": "Read", "tokens": t, "file": None, "stale": True}
        for i, t in enumerate(sizes)
    }
    paths.write_json_atomic(paths.session_dir("s1") / "summary.json", {
        "context_total": 0, "output_total": 0, "results": results,
        "reads": {}, "pending": {}, "agents": {}, "state_mark": None, "degraded": False,
    })


def seed_config(tmp_path, **kv):
    p = tmp_path / ".claude" / "carryover" / "config.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(f"{k}: {v}\n" for k, v in kv.items()))


def ev(tmp_path):
    return make_event(hook_event_name="UserPromptSubmit", cwd=str(tmp_path))


def has_anchor(out):
    return out is not None and "additionalContext" in out["hookSpecificOutput"]


def test_suppressed_on_identical_prompt(tmp_path):
    seed_state(tmp_path)
    seed_ctx(30)
    e = ev(tmp_path)
    first = anchor.handle(e)
    assert "Goal: Ship carryover" in first["hookSpecificOutput"]["additionalContext"]
    assert anchor.handle(e) is None  # identical anchor already in context


def test_reinject_on_goal_change(tmp_path):
    seed_state(tmp_path)
    seed_ctx(30)
    e = ev(tmp_path)
    anchor.handle(e)
    seed_state(tmp_path, goal="Ship v2")
    out = anchor.handle(e)
    assert has_anchor(out)
    assert "Goal: Ship v2" in out["hookSpecificOutput"]["additionalContext"]


def test_reinject_on_now_change(tmp_path):
    seed_state(tmp_path)
    seed_ctx(30)
    e = ev(tmp_path)
    anchor.handle(e)
    seed_state(tmp_path, now="Wiring flags")
    out = anchor.handle(e)
    assert has_anchor(out)
    assert "Now: Wiring flags" in out["hookSpecificOutput"]["additionalContext"]


def test_pct_band_suppresses_within_reinjects_across(tmp_path):
    seed_config(tmp_path, advise_pct=95, urge_pct=99)  # keep advice out of the fingerprint
    seed_state(tmp_path)
    e = ev(tmp_path)
    seed_ctx(52)
    assert has_anchor(anchor.handle(e))       # first full anchor (band 5)
    seed_ctx(58)
    assert anchor.handle(e) is None           # still the 50s band -> suppressed
    seed_ctx(62)
    assert has_anchor(anchor.handle(e))        # crosses into the 60s band -> re-injected


def test_reinject_on_stale_band_jump(tmp_path):
    seed_config(tmp_path, advise_pct=95, urge_pct=99)
    e = ev(tmp_path)
    seed_stale(2000)
    assert has_anchor(anchor.handle(e))        # stale band 0
    seed_stale(2000)
    assert anchor.handle(e) is None            # unchanged -> suppressed
    seed_stale(2000, 2000, 2000, 2000)         # 8000 tok -> band 1
    assert has_anchor(anchor.handle(e))


def test_forced_refresh_after_refresh_turns(tmp_path):
    seed_config(tmp_path, anchor_refresh_turns=3)
    seed_state(tmp_path)
    seed_ctx(30)
    e = ev(tmp_path)
    assert has_anchor(anchor.handle(e))        # P1 full
    assert anchor.handle(e) is None            # P2 suppressed
    assert anchor.handle(e) is None            # P3 suppressed
    assert has_anchor(anchor.handle(e))        # P4 forced refresh


def test_refresh_turns_one_injects_every_prompt(tmp_path):
    seed_config(tmp_path, anchor_refresh_turns=1)  # legacy: never suppress
    seed_state(tmp_path)
    seed_ctx(30)
    e = ev(tmp_path)
    for _ in range(4):
        assert has_anchor(anchor.handle(e))


def test_sessionstart_clears_fingerprint(tmp_path):
    seed_state(tmp_path)
    seed_ctx(30)
    e = ev(tmp_path)
    assert has_anchor(anchor.handle(e))
    assert anchor.handle(e) is None            # suppressed
    sessionstart.handle(make_event(
        hook_event_name="SessionStart", source="resume", cwd=str(tmp_path)))
    assert has_anchor(anchor.handle(e))        # rebuilt context -> fresh anchor


def test_precompact_clears_fingerprint(tmp_path):
    seed_state(tmp_path)
    seed_ctx(30)
    e = ev(tmp_path)
    assert has_anchor(anchor.handle(e))
    assert anchor.handle(e) is None
    precompact.handle(make_event(
        hook_event_name="PreCompact", trigger="manual", cwd=str(tmp_path)))
    assert has_anchor(anchor.handle(e))


def test_corrupt_flags_injects_full_anchor(tmp_path):
    seed_state(tmp_path)
    seed_ctx(30)
    (paths.session_dir("s1") / "flags.json").write_text("{ not json")
    out = anchor.handle(ev(tmp_path))
    assert has_anchor(out)
    assert "Goal: Ship carryover" in out["hookSpecificOutput"]["additionalContext"]


def test_config_anchor_refresh_turns_validation(tmp_path):
    assert config.load(str(tmp_path)).anchor_refresh_turns == 8  # default
    seed_config(tmp_path, anchor_refresh_turns=3)
    assert config.load(str(tmp_path)).anchor_refresh_turns == 3
    seed_config(tmp_path, anchor_refresh_turns=0)  # < 1 is invalid
    assert config.load(str(tmp_path)).anchor_refresh_turns == 8
    seed_config(tmp_path, anchor_refresh_turns="nope")
    assert config.load(str(tmp_path)).anchor_refresh_turns == 8
