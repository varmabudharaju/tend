import os
import time

from tend import state


def test_path_for(tmp_path):
    assert state.path_for(str(tmp_path)) == tmp_path / ".claude" / "tend" / "STATE.md"


def test_seed_creates_template_once(tmp_path):
    p = state.path_for(str(tmp_path))
    state.seed(p)
    assert "## Dead-ends" in p.read_text()
    p.write_text("custom")
    state.seed(p)  # must not overwrite
    assert p.read_text() == "custom"


def test_goal_now_skips_placeholders(tmp_path):
    p = state.path_for(str(tmp_path))
    p.parent.mkdir(parents=True)
    p.write_text(
        "# Session state\n\n## Goal\n(placeholder)\nShip the harness\n\n"
        "## Now\nWriting ledger tests\n\n## Decisions\n- yaml config\n"
    )
    goal, now = state.goal_now(p)
    assert goal == "Ship the harness"
    assert now == "Writing ledger tests"


def test_goal_now_missing_file(tmp_path):
    assert state.goal_now(tmp_path / "nope.md") == ("", "")


def test_is_fresh(tmp_path):
    p = tmp_path / "STATE.md"
    p.write_text("x")
    assert state.is_fresh(p, hours=1)
    old = time.time() - 3 * 3600
    os.utime(p, (old, old))
    assert not state.is_fresh(p, hours=1)
    assert not state.is_fresh(tmp_path / "nope.md", hours=1)
