import json

from tend import cli, paths


def seed_session(sid="s1", total=50000, pct=42.0):
    paths.write_json_atomic(paths.session_dir(sid) / "summary.json", {
        "context_total": total, "output_total": 100,
        "results": {"t1": {"tool": "Bash", "tokens": 3000, "file": None, "stale": True}},
        "reads": {}, "pending": {}, "agents": {}, "state_mark": None, "degraded": False,
    })
    paths.write_json_atomic(paths.session_dir(sid) / "ctx.json",
                            {"context_window": {"used_percentage": pct}})


def test_status_prints_summary(capsys, tend_home):
    seed_session()
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "42%" in out and "50,000" in out and "3,000" in out and "STALE" in out


def test_status_no_sessions(capsys, tend_home):
    assert cli.main(["status"]) == 0
    assert "no tend sessions" in capsys.readouterr().out


def test_report_lists_results(capsys, tend_home):
    seed_session()
    assert cli.main(["report"]) == 0
    assert "Bash" in capsys.readouterr().out


def test_on_off(tend_home):
    assert cli.main(["off"]) == 0
    assert paths.disabled()
    assert cli.main(["on"]) == 0
    assert not paths.disabled()


def test_handoff_prints_state(capsys, tmp_path, tend_home):
    sp = tmp_path / ".claude" / "tend" / "STATE.md"
    sp.parent.mkdir(parents=True)
    sp.write_text("## Goal\nShip it\n")
    assert cli.main(["handoff", "--cwd", str(tmp_path)]) == 0
    assert "Ship it" in capsys.readouterr().out


def test_handoff_warns_when_missing(capsys, tmp_path, tend_home):
    assert cli.main(["handoff", "--cwd", str(tmp_path)]) == 1
    assert "No STATE.md" in capsys.readouterr().out


def test_install_hook_via_cli(tmp_path, tend_home):
    sp = tmp_path / "settings.json"
    sp.write_text("{}")
    assert cli.main(["install-hook", "--settings", str(sp)]) == 0
    assert "-m tend.hook" in sp.read_text()


def test_status_contains_bloat(capsys, tend_home):
    seed_session()  # seeds a 3000-tok result, threshold default 2500
    cli.main(["status"])
    out = capsys.readouterr().out
    assert "bloat" in out


def test_report_lists_compaction_snapshots(capsys, tend_home):
    seed_session()
    snap = paths.session_dir("s1") / "precompact-123.json"
    snap.write_text("{}")
    cli.main(["report"])
    out = capsys.readouterr().out
    assert "compaction snapshots" in out
    assert "precompact-123.json" in out


def test_status_contains_last_hook_activity(capsys, tend_home):
    seed_session()
    cli.main(["status"])
    out = capsys.readouterr().out
    assert "last hook activity" in out


def test_status_ghost_session_returns_1(capsys, tend_home):
    result = cli.main(["status", "--session", "ghost"])
    assert result == 1
    assert "no such session: ghost" in capsys.readouterr().out
    assert not (paths.home() / "sessions" / "ghost").exists()


def test_report_ghost_session_returns_1(capsys, tend_home):
    result = cli.main(["report", "--session", "ghost"])
    assert result == 1
    assert "no such session: ghost" in capsys.readouterr().out
    assert not (paths.home() / "sessions" / "ghost").exists()


def test_newest_mtime_tolerates_vanishing_files(tmp_path, monkeypatch):
    """L16: a .tmp file deleted between listing and stat must not crash status."""
    import contextlib

    d = tmp_path / "sess"
    d.mkdir()

    class Vanished:
        name = "summary.json.123.tmp"

        def is_file(self):
            return True

        def stat(self):
            raise FileNotFoundError("vanished between listing and stat")

    @contextlib.contextmanager
    def fake_scandir(path):
        yield iter([Vanished()])

    monkeypatch.setattr(paths.os, "scandir", fake_scandir)
    assert paths.newest_mtime(d) == d.stat().st_mtime


def _ancient_session(sid="ancient", days=90):
    import os, time
    d = paths.session_dir(sid)
    (d / "summary.json").write_text("{}")
    old = time.time() - days * 86400
    os.utime(d / "summary.json", (old, old))
    os.utime(d, (old, old))
    return d


def test_clean_removes_old_sessions(capsys, tend_home):
    d = _ancient_session()
    assert cli.main(["clean", "--days", "30"]) == 0
    assert "removed 1 session(s)" in capsys.readouterr().out
    assert not d.exists()


def test_clean_dry_run(capsys, tend_home):
    d = _ancient_session()
    assert cli.main(["clean", "--days", "30", "--dry-run"]) == 0
    assert "would remove 1" in capsys.readouterr().out
    assert d.exists()
