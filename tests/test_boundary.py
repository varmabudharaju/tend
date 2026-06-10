from conftest import make_event

from tend import boundary, flags, ledger, paths, state


def setup_summary(total):
    paths.write_json_atomic(
        paths.session_dir("s1") / "summary.json",
        {"context_total": total, "output_total": 0, "results": {}, "reads": {},
         "pending": {}, "agents": {}, "state_mark": None, "degraded": False},
    )


def test_fresh_state_marks_and_sets_boundary(tmp_path):
    sp = state.path_for(str(tmp_path))
    state.seed(sp)
    setup_summary(50_000)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))
    fl = flags.load("s1")
    assert fl["boundary"] is True and fl["state_reminder"] is False
    assert ledger.load_summary("s1")["state_mark"]["context_total"] == 50_000


def test_stale_state_sets_reminder(tmp_path):
    sp = state.path_for(str(tmp_path))
    state.seed(sp)
    setup_summary(10_000)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))  # marks at 10k
    setup_summary(40_000)  # 30k tokens later, STATE.md untouched
    # keep the recorded mark when rewriting summary
    s = ledger.load_summary("s1")
    s["state_mark"] = {"mtime": sp.stat().st_mtime, "context_total": 10_000}
    paths.write_json_atomic(paths.session_dir("s1") / "summary.json", s)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))
    fl = flags.load("s1")
    assert fl["state_reminder"] is True and fl["boundary"] is False


def test_missing_state_reminds_after_threshold(tmp_path):
    setup_summary(30_000)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))
    assert flags.load("s1")["state_reminder"] is True


def test_missing_state_quiet_early(tmp_path):
    setup_summary(5_000)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))
    assert flags.load("s1")["state_reminder"] is False
