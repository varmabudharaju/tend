import os
import time
from pathlib import Path

from conftest import make_event

from tend import sessionstart, state


def ev(tmp_path, source="startup"):
    return make_event(hook_event_name="SessionStart", source=source, cwd=str(tmp_path))


def test_seeds_template_and_explains_convention(tmp_path):
    out = sessionstart.handle(ev(tmp_path))
    assert state.path_for(str(tmp_path)).exists()
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "STATE.md" in ctx and "Dead-ends" in ctx


def test_fresh_state_injected(tmp_path):
    sp = state.path_for(str(tmp_path))
    sp.parent.mkdir(parents=True)
    sp.write_text("## Goal\nShip it\n")
    ctx = sessionstart.handle(ev(tmp_path, "clear"))["hookSpecificOutput"]["additionalContext"]
    assert "State restored" in ctx and "Ship it" in ctx


def test_old_state_not_injected(tmp_path):
    sp = state.path_for(str(tmp_path))
    sp.parent.mkdir(parents=True)
    sp.write_text("## Goal\nold\n")
    old = time.time() - 100 * 3600
    os.utime(sp, (old, old))
    assert sessionstart.handle(ev(tmp_path)) is None


def test_resume_and_compact_sources_ignored(tmp_path):
    assert sessionstart.handle(ev(tmp_path, "resume")) is None
    assert sessionstart.handle(ev(tmp_path, "compact")) is None


def test_home_directory_never_seeded():
    out = sessionstart.handle(make_event(
        hook_event_name="SessionStart", source="startup", cwd=str(Path.home())
    ))
    assert out is None
    assert not state.path_for(str(Path.home())).exists()
