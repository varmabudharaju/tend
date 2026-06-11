import os

from conftest import make_event

from tend import boundary, flags, ledger, paths, state


def setup_summary(total, output=0):
    paths.write_json_atomic(
        paths.session_dir("s1") / "summary.json",
        {"context_total": total, "output_total": output, "results": {}, "reads": {},
         "pending": {}, "agents": {}, "state_mark": None, "degraded": False},
    )


def test_first_stop_baselines_without_boundary(tmp_path):
    """L7: the first Stop has nothing to compare against - mark, but no boundary."""
    sp = state.path_for(str(tmp_path))
    state.seed(sp)
    setup_summary(50_000, output=2_000)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))
    fl = flags.load("s1")
    assert fl["boundary"] is False and fl["state_reminder"] is False
    assert ledger.load_summary("s1")["state_mark"]["output_total"] == 2_000


def test_state_update_sets_boundary(tmp_path):
    sp = state.path_for(str(tmp_path))
    state.seed(sp)
    setup_summary(50_000)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))  # baseline
    os.utime(sp, (sp.stat().st_atime, sp.stat().st_mtime + 5))              # STATE.md updated
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))
    assert flags.load("s1")["boundary"] is True


def test_stale_state_sets_reminder(tmp_path):
    sp = state.path_for(str(tmp_path))
    state.seed(sp)
    setup_summary(10_000, output=500)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))  # marks at 500
    setup_summary(40_000, output=9_500)  # 9k output tokens later, STATE.md untouched
    s = ledger.load_summary("s1")
    s["state_mark"] = {"mtime": sp.stat().st_mtime, "output_total": 500}
    paths.write_json_atomic(paths.session_dir("s1") / "summary.json", s)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))
    fl = flags.load("s1")
    assert fl["state_reminder"] is True and fl["boundary"] is False


def test_boundary_remarks_legacy_mark(tmp_path):
    """A pre-v0.2 mark (context_total) is re-baselined on the next Stop, quietly."""
    sp = state.path_for(str(tmp_path))
    state.seed(sp)
    setup_summary(50_000, output=4_000)
    s = ledger.load_summary("s1")
    s["state_mark"] = {"mtime": sp.stat().st_mtime, "context_total": 140_000}
    paths.write_json_atomic(paths.session_dir("s1") / "summary.json", s)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))
    fl = flags.load("s1")
    assert fl["boundary"] is False and fl["state_reminder"] is False
    assert ledger.load_summary("s1")["state_mark"]["output_total"] == 4_000


def test_missing_state_reminds_after_threshold(tmp_path):
    setup_summary(30_000, output=9_000)   # > 3000 default
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))
    assert flags.load("s1")["state_reminder"] is True


def test_missing_state_quiet_early(tmp_path):
    setup_summary(5_000, output=200)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))
    assert flags.load("s1")["state_reminder"] is False


def test_blocked_once_survives_stop(tmp_path):
    flags.save("s1", {"blocked_once": True})
    setup_summary(5_000)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))
    assert flags.load("s1").get("blocked_once") is True
