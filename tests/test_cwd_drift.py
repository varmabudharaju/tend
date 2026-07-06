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


def test_no_pin_without_cwd(tmp_path):
    sessionstart.handle(make_event(hook_event_name="SessionStart", source="resume",
                                   cwd="", session_id="s1"))
    assert "project_root" not in flags.load("s1")


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
