from conftest import make_event

from tend import flags, paths, precompact


def ev(trigger, tmp_path):
    return make_event(hook_event_name="PreCompact", trigger=trigger, cwd=str(tmp_path))


def test_auto_blocks_once_when_state_missing(tmp_path):
    out = precompact.handle(ev("auto", tmp_path))
    assert out == {"decision": "block", "reason": precompact.BLOCK_REASON}
    assert flags.load("s1")["blocked_once"] is True
    # second auto-compact must pass
    assert precompact.handle(ev("auto", tmp_path)) is None


def test_manual_never_blocked(tmp_path):
    assert precompact.handle(ev("manual", tmp_path)) is None


def test_snapshot_written(tmp_path):
    precompact.handle(ev("manual", tmp_path))
    snaps = list(paths.session_dir("s1").glob("precompact-*.json"))
    assert len(snaps) == 1


def test_two_snapshots_are_unique(tmp_path):
    precompact.handle(ev("manual", tmp_path))
    precompact.handle(ev("manual", tmp_path))
    snaps = list(paths.session_dir("s1").glob("precompact-*.json"))
    assert len(snaps) == 2


def test_fresh_state_not_blocked(tmp_path):
    from tend import ledger, state

    sp = state.path_for(str(tmp_path))
    state.seed(sp)
    ledger.set_state_mark("s1", sp.stat().st_mtime)  # mark matches: fresh, 0 tokens since
    assert precompact.handle(ev("auto", tmp_path)) is None


def test_stale_auto_compact_blocked_even_after_context_shrink(tmp_path):
    """H2 repro: mark at high output, context shrank - the block must still fire."""
    from tend import paths, state

    sp = state.path_for(str(tmp_path))
    state.seed(sp)
    paths.write_json_atomic(paths.session_dir("s1") / "summary.json", {
        "context_total": 30_000, "output_total": 9_000, "results": {}, "reads": {},
        "pending": {}, "agents": {},
        "state_mark": {"mtime": sp.stat().st_mtime, "output_total": 1_000},
        "degraded": False,
    })
    out = precompact.handle(ev("auto", tmp_path))
    assert out == {"decision": "block", "reason": precompact.BLOCK_REASON}
