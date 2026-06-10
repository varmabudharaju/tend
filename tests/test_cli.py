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
