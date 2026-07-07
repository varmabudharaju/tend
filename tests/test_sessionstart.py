import os
import time
from pathlib import Path

from conftest import make_event

from carryover import sessionstart, state


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


def test_home_directory_never_seeded(tmp_path, monkeypatch):
    # hermetic: a real ~/.claude/carryover/STATE.md on the host must not fail this
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    out = sessionstart.handle(make_event(
        hook_event_name="SessionStart", source="startup", cwd=str(fake_home)
    ))
    assert out is None
    assert not state.path_for(str(fake_home)).exists()


def test_oversized_state_truncated_with_visible_marker(tmp_path):
    """L10: a >16k STATE.md must say it was cut and where to read the rest."""
    sp = state.path_for(str(tmp_path))
    sp.parent.mkdir(parents=True)
    sp.write_text("## Goal\nShip it\n" + ("filler line\n" * 2000), encoding="utf-8")
    ctx = sessionstart.handle(ev(tmp_path))["hookSpecificOutput"]["additionalContext"]
    assert "truncated" in ctx
    assert str(sp) in ctx
    assert len(ctx) < 17000
    # cut lands on a line boundary: no half line right before the marker
    body = ctx.split("\n[carryover] STATE.md truncated")[0]
    assert body.endswith("filler line")


def test_seed_shows_user_visible_notice(tmp_path):
    out = sessionstart.handle(ev(tmp_path))
    assert "seeded" in out["systemMessage"]
    assert "STATE.md" in out["systemMessage"]


def test_restore_shows_user_visible_notice(tmp_path):
    sp = state.path_for(str(tmp_path))
    sp.parent.mkdir(parents=True)
    sp.write_text("## Goal\nShip it\n")
    out = sessionstart.handle(ev(tmp_path, "clear"))
    assert "restored" in out["systemMessage"]


def test_sessionstart_triggers_retention_sweep(tmp_path, monkeypatch):
    from carryover import retention
    called = {}
    monkeypatch.setattr(retention, "maybe_sweep",
                        lambda days: called.setdefault("days", days))
    sessionstart.handle(ev(tmp_path))
    assert called["days"] == 30


# --- compaction insurance: re-anchor STATE.md after source=compact ---

def _write_state(tmp_path, text):
    sp = state.path_for(str(tmp_path))
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(text, encoding="utf-8")
    return sp


def test_compact_reanchors_real_state(tmp_path):
    _write_state(tmp_path,
                 "## Goal\nShip the parser\n\n## Now\nWriting the lexer\n\n"
                 "## Decisions\nChose recursive descent over a table-driven parser\n")
    out = sessionstart.handle(ev(tmp_path, "compact"))
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "compacted" in ctx
    assert "Chose recursive descent over a table-driven parser" in ctx
    assert out["systemMessage"] == "carryover: re-anchored durable state after compaction"


def test_compact_skips_pristine_template(tmp_path):
    _write_state(tmp_path, state.TEMPLATE)
    assert sessionstart.handle(ev(tmp_path, "compact")) is None


def test_compact_missing_state_returns_none_and_seeds_nothing(tmp_path):
    assert sessionstart.handle(ev(tmp_path, "compact")) is None
    assert not state.path_for(str(tmp_path)).exists()


def test_compact_never_acts_in_home(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    _write_state(fake_home, "## Goal\nreal goal\n\n## Decisions\nreal choice\n")
    out = sessionstart.handle(make_event(
        hook_event_name="SessionStart", source="compact", cwd=str(fake_home)))
    assert out is None


def test_compact_injects_even_when_state_is_old(tmp_path):
    sp = _write_state(tmp_path, "## Goal\nShip it\n\n## Decisions\nChose sqlite\n")
    old = time.time() - 100 * 3600
    os.utime(sp, (old, old))
    ctx = sessionstart.handle(ev(tmp_path, "compact"))["hookSpecificOutput"]["additionalContext"]
    assert "Chose sqlite" in ctx


def test_compact_over_budget_keeps_core_drops_files_touched(tmp_path):
    big = "filler decision line\n" * 600  # ~12.6k of real, line-broken content
    _write_state(tmp_path,
                 "## Goal\nShip the parser\n\n## Now\nStep five\n\n"
                 "## Decisions\nDECISION_KEEP chose recursive descent\n" + big + "\n"
                 "## Dead-ends\ntried redis\n\n"
                 "## Files touched\nsrc/x.py FILESMARKER\n")
    ctx = sessionstart.handle(ev(tmp_path, "compact"))["hookSpecificOutput"]["additionalContext"]
    assert "DECISION_KEEP" in ctx          # Decisions retained (first line survives)
    assert "Ship the parser" in ctx        # Goal retained
    assert "Step five" in ctx              # Now retained
    assert "FILESMARKER" not in ctx        # Files touched shed first
    assert "truncated" in ctx and str(state.path_for(str(tmp_path))) in ctx
    assert len(ctx) < 8500
