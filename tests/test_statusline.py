import io
import json

from carryover import paths, statusline


STATUS_JSON = json.dumps({
    "session_id": "s9",
    "model": {"display_name": "Fable"},
    "context_window": {"used_percentage": 42.5},
})


def test_tee_writes_ctx_json(monkeypatch, capsys, carryover_home):
    monkeypatch.setattr("sys.stdin", io.StringIO(STATUS_JSON))
    statusline.main()
    saved = paths.read_json(paths.session_dir("s9") / "ctx.json")
    assert saved["context_window"]["used_percentage"] == 42.5


def test_exec_original_passthrough(monkeypatch, capsys, carryover_home):
    paths.write_json_atomic(
        carryover_home / "statusline-original.json",
        {"type": "command", "command": "echo ORIGINAL-LINE"},
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(STATUS_JSON))
    statusline.main()
    assert "ORIGINAL-LINE" in capsys.readouterr().out


def test_fallback_line_without_original(monkeypatch, capsys, carryover_home):
    monkeypatch.setattr("sys.stdin", io.StringIO(STATUS_JSON))
    statusline.main()
    out = capsys.readouterr().out
    assert "Fable" in out and "42" in out


def test_garbage_input_never_raises(monkeypatch, capsys, carryover_home):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    statusline.main()  # must not raise


def test_failing_original_falls_through_to_fallback(monkeypatch, capsys, carryover_home):
    """If statusline-original.json command exits non-zero, use the built-in fallback."""
    paths.write_json_atomic(
        carryover_home / "statusline-original.json",
        {"type": "command", "command": "exit 3"},
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(STATUS_JSON))
    statusline.main()
    out = capsys.readouterr().out
    assert "Fable" in out


def test_non_numeric_pct_never_blanks_the_bar(monkeypatch, capsys, carryover_home):
    """L15: a weird used_percentage must degrade to a line without ctx, not crash."""
    bad = json.dumps({"session_id": "s9", "model": {"display_name": "Fable"},
                      "context_window": {"used_percentage": "??"}})
    monkeypatch.setattr("sys.stdin", io.StringIO(bad))
    assert statusline.main() == 0
    out = capsys.readouterr().out
    assert "Fable" in out


def test_disabled_skips_tee_but_keeps_passthrough(monkeypatch, capsys, carryover_home):
    """L18: carryover off = no carryover writes; the user's statusline still renders."""
    carryover_home.mkdir(parents=True, exist_ok=True)
    (carryover_home / "disabled").touch()
    paths.write_json_atomic(
        carryover_home / "statusline-original.json",
        {"type": "command", "command": "echo ORIGINAL-LINE"},
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(STATUS_JSON))
    statusline.main()
    assert "ORIGINAL-LINE" in capsys.readouterr().out
    assert not (carryover_home / "sessions" / "s9" / "ctx.json").exists()


def test_statusline_appends_carryover_segment(monkeypatch, capsys, carryover_home):
    """The user-visible heartbeat: offload count + stale tokens after the original line."""
    paths.write_json_atomic(
        carryover_home / "statusline-original.json",
        {"type": "command", "command": "echo ORIGINAL-LINE"},
    )
    outputs = carryover_home / "sessions" / "s9" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "0001.txt").write_text("x")
    (outputs / "0002.txt").write_text("y")
    paths.write_json_atomic(carryover_home / "sessions" / "s9" / "summary.json", {
        "context_total": 1000, "output_total": 10,
        "results": {"t1": {"tool": "Read", "tokens": 29352, "file": "/f", "stale": True}},
        "reads": {}, "pending": {}, "agents": {}, "state_mark": None, "degraded": False,
    })
    monkeypatch.setattr("sys.stdin", io.StringIO(STATUS_JSON))
    statusline.main()
    out = capsys.readouterr().out
    assert "ORIGINAL-LINE" in out
    assert "carryover: 2 filed, 29k stale" in out
    assert out.count("\n") == 1          # still a single statusline


def test_statusline_segment_quiet_when_nothing_to_report(monkeypatch, capsys, carryover_home):
    monkeypatch.setattr("sys.stdin", io.StringIO(STATUS_JSON))
    statusline.main()
    assert "carryover: on" in capsys.readouterr().out


def test_statusline_no_segment_when_disabled(monkeypatch, capsys, carryover_home):
    carryover_home.mkdir(parents=True, exist_ok=True)
    (carryover_home / "disabled").touch()
    monkeypatch.setattr("sys.stdin", io.StringIO(STATUS_JSON))
    statusline.main()
    assert "carryover:" not in capsys.readouterr().out
