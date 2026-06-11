from conftest import make_event

from tend import anchor, flags, paths, state


def seed_state(tmp_path, goal="Ship tend", now="Writing anchor"):
    sp = state.path_for(str(tmp_path))
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(f"## Goal\n{goal}\n\n## Now\n{now}\n")
    return sp


def seed_ctx(pct):
    paths.write_json_atomic(
        paths.session_dir("s1") / "ctx.json",
        {"context_window": {"used_percentage": pct}},
    )


def ev(tmp_path):
    return make_event(hook_event_name="UserPromptSubmit", cwd=str(tmp_path))


def test_anchor_contains_goal_now_health(tmp_path):
    seed_state(tmp_path)
    seed_ctx(30)
    out = anchor.handle(ev(tmp_path))
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "Goal: Ship tend" in ctx
    assert "Now: Writing anchor" in ctx
    assert "context 30%" in ctx
    assert "/compact" not in ctx  # below advise threshold


def test_anchor_includes_reminder_when_flagged(tmp_path):
    seed_state(tmp_path)
    flags.save("s1", {"state_reminder": True})
    ctx = anchor.handle(ev(tmp_path))["hookSpecificOutput"]["additionalContext"]
    assert "STATE.md is stale" in ctx


def test_anchor_escalates_at_advise(tmp_path):
    seed_state(tmp_path)
    seed_ctx(60)
    ctx = anchor.handle(ev(tmp_path))["hookSpecificOutput"]["additionalContext"]
    assert "/compact" in ctx


def test_anchor_truncated_to_budget(tmp_path):
    seed_state(tmp_path, goal="g" * 10000)
    ctx = anchor.handle(ev(tmp_path))["hookSpecificOutput"]["additionalContext"]
    assert len(ctx) <= 400 * 4


def test_anchor_works_without_state_or_metrics(tmp_path):
    flags.save("s1", {"state_reminder": True})
    ctx = anchor.handle(ev(tmp_path))["hookSpecificOutput"]["additionalContext"]
    assert "context usage unknown" in ctx
    assert "STATE.md is stale" in ctx


def test_anchor_keeps_urgent_tail_over_goal(tmp_path):
    """M9: a huge Goal must never evict Health and the compaction urge."""
    seed_state(tmp_path, goal="g" * 1700)
    seed_ctx(85)
    ctx = anchor.handle(ev(tmp_path))["hookSpecificOutput"]["additionalContext"]
    assert "Health:" in ctx
    assert "run now: /compact" in ctx
    assert len(ctx) <= 400 * 4


def test_anchor_emitted_for_bloat_only_state(tmp_path):
    """L6: 9k tokens of oversized results alone must produce an anchor that says so."""
    paths.write_json_atomic(paths.session_dir("s1") / "summary.json", {
        "context_total": 0, "output_total": 0,
        "results": {"big": {"tool": "Bash", "tokens": 9000, "file": None, "stale": False}},
        "reads": {}, "pending": {}, "agents": {}, "state_mark": None, "degraded": False,
    })
    out = anchor.handle(ev(tmp_path))
    assert out is not None
    assert "oversized results" in out["hookSpecificOutput"]["additionalContext"]
