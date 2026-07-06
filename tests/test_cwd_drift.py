"""U2 regression: hook cwd drifts mid-session; STATE.md must stay pinned to the project."""
from conftest import make_event

from tend import anchor, flags, ledger, precompact, sessionstart, state


def ss(cwd, source="startup", sid="s1"):
    return make_event(hook_event_name="SessionStart", source=source, cwd=str(cwd), session_id=sid)


def test_sessionstart_pins_project_root(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    sessionstart.handle(ss(proj))
    assert flags.load("s1")["project_root"] == str(proj.resolve())


def test_pin_happens_for_ignored_sources_too(tmp_path):
    """resume/compact still early-return, but the project root is pinned first."""
    proj = tmp_path / "proj"
    proj.mkdir()
    assert sessionstart.handle(ss(proj, source="resume")) is None
    assert flags.load("s1")["project_root"] == str(proj.resolve())


def test_compact_never_overwrites_pin(tmp_path):
    """A compact fires mid-session with a possibly-drifted cwd; the startup pin wins."""
    proj, other = tmp_path / "proj", tmp_path / "other"
    proj.mkdir(), other.mkdir()
    sessionstart.handle(ss(proj))
    sessionstart.handle(ss(other, source="compact"))
    assert flags.load("s1")["project_root"] == str(proj.resolve())


def test_compact_fills_missing_pin(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    sessionstart.handle(ss(proj, source="compact"))
    assert flags.load("s1")["project_root"] == str(proj.resolve())


def test_no_pin_without_cwd(tmp_path):
    sessionstart.handle(make_event(hook_event_name="SessionStart", source="resume",
                                   cwd="", session_id="s1"))
    assert "project_root" not in flags.load("s1")


def test_anchor_uses_pinned_root_after_cwd_drift(tmp_path):
    """U2 core: anchor arrives with a drifted cwd but still injects project A's Goal;
    no STATE.md is seeded in the unrelated directory."""
    proj = tmp_path / "proj"
    proj.mkdir()
    sp = state.path_for(str(proj))
    sp.parent.mkdir(parents=True)
    sp.write_text("## Goal\nShip project A\n\n## Now\nstep one\n")
    sessionstart.handle(ss(proj))  # pins proj

    other = tmp_path / "unrelated"
    other.mkdir()
    out = anchor.handle(make_event(hook_event_name="UserPromptSubmit",
                                   cwd=str(other), session_id="s1"))
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "Ship project A" in ctx
    assert not (other / ".claude" / "tend" / "STATE.md").exists()


def test_precompact_staleness_uses_pinned_root_after_drift(tmp_path):
    """Precompact must evaluate the pinned project's (fresh) STATE.md, not the drifted cwd
    where STATE.md is absent - otherwise a false stale-block fires."""
    proj = tmp_path / "proj"
    proj.mkdir()
    sessionstart.handle(ss(proj))  # seeds proj STATE.md + pins
    sp = state.path_for(str(proj))
    assert sp.exists()
    ledger.set_state_mark("s1", sp.stat().st_mtime)  # fresh

    other = tmp_path / "unrelated"
    other.mkdir()
    out = precompact.handle(make_event(hook_event_name="PreCompact", trigger="auto",
                                       cwd=str(other), session_id="s1"))
    assert out is None


def test_resolve_uses_session_pin(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    flags.update("s1", project_root=str(proj))
    other = tmp_path / "other"
    other.mkdir()
    assert state.resolve(str(other), "s1") == state.path_for(str(proj))


def test_pin_to_deleted_dir_falls_back(tmp_path):
    """A pin at a directory that no longer exists must degrade to the event cwd, not crash."""
    gone = tmp_path / "gone"  # never created
    flags.update("s1", project_root=str(gone))
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    assert state.resolve(str(cwd), "s1") == state.path_for(str(cwd))
