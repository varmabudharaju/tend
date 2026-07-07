import os
import time

from carryover import state


def test_path_for(tmp_path):
    assert state.path_for(str(tmp_path)) == tmp_path / ".claude" / "carryover" / "STATE.md"


def _seed_state(root):
    p = state.path_for(str(root))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("## Goal\nx\n", encoding="utf-8")
    return p


def test_resolve_falls_back_to_cwd_without_pin_or_state(tmp_path):
    assert state.resolve(str(tmp_path), None) == state.path_for(str(tmp_path))


def test_resolve_ancestor_walk_finds_state(tmp_path):
    """U2 walk: cwd = proj/sub/dir resolves to proj's STATE.md."""
    proj = tmp_path / "proj"
    _seed_state(proj)
    sub = proj / "sub" / "dir"
    sub.mkdir(parents=True)
    assert state.resolve(str(sub), None) == state.path_for(str(proj))


def test_resolve_walk_stops_at_git_boundary(tmp_path):
    """A STATE.md above a .git root must NOT be adopted across the project boundary."""
    outer = tmp_path / "outer"
    _seed_state(outer)
    proj = outer / "proj"
    (proj / ".git").mkdir(parents=True)
    sub = proj / "sub"
    sub.mkdir()
    # walk from sub stops at proj's .git -> outer's STATE.md is unreachable -> fall back to cwd
    assert state.resolve(str(sub), None) == state.path_for(str(sub))


def test_resolve_finds_state_at_git_root(tmp_path):
    """STATE.md living at the git root itself is found (checked before the boundary stop)."""
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    _seed_state(proj)
    sub = proj / "sub"
    sub.mkdir()
    assert state.resolve(str(sub), None) == state.path_for(str(proj))


def test_resolve_root_returns_directory(tmp_path):
    proj = tmp_path / "proj"
    _seed_state(proj)
    sub = proj / "sub"
    sub.mkdir()
    assert state.resolve_root(str(sub), None) == proj


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


def test_duplicate_goal_sections_preserve_first_content(tmp_path):
    """When STATE.md has two ## Goal sections, first non-placeholder line is from first section."""
    p = state.path_for(str(tmp_path))
    p.parent.mkdir(parents=True)
    p.write_text(
        "# Session state\n\n"
        "## Goal\n"
        "Ship the harness\n\n"
        "## Now\n"
        "Writing tests\n\n"
        "## Goal\n"
        "Second duplicate goal section\n"
    )
    goal, now = state.goal_now(p)
    assert goal == "Ship the harness", "first Goal section content must be preserved"
    assert now == "Writing tests"


def test_seed_is_atomic_o_excl(tmp_path, monkeypatch):
    """L11: two concurrent seeds must not clobber - second open(O_EXCL) loses quietly."""
    import os as os_mod

    p = state.path_for(str(tmp_path))
    real_open = os_mod.open
    calls = {}

    def racing_open(path, flags, *a, **kw):
        if str(path) == str(p) and not calls:
            calls["raced"] = True
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("winner", encoding="utf-8")  # the rival session wins the race
        return real_open(path, flags, *a, **kw)

    monkeypatch.setattr(state.os, "open", racing_open)
    state.seed(p)  # must not raise, must not overwrite
    assert p.read_text(encoding="utf-8") == "winner"


def test_unicode_state_roundtrip(tmp_path):
    """L12: explicit utf-8 - non-ASCII goals survive regardless of locale."""
    p = state.path_for(str(tmp_path))
    p.parent.mkdir(parents=True)
    p.write_bytes("## Goal\nnaïve café ✓\n".encode("utf-8"))
    goal, _ = state.goal_now(p)
    assert goal == "naïve café ✓"
