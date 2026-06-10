import io
import json

from tend import paths, statusline


STATUS_JSON = json.dumps({
    "session_id": "s9",
    "model": {"display_name": "Fable"},
    "context_window": {"used_percentage": 42.5},
})


def test_tee_writes_ctx_json(monkeypatch, capsys, tend_home):
    monkeypatch.setattr("sys.stdin", io.StringIO(STATUS_JSON))
    statusline.main()
    saved = paths.read_json(paths.session_dir("s9") / "ctx.json")
    assert saved["context_window"]["used_percentage"] == 42.5


def test_exec_original_passthrough(monkeypatch, capsys, tend_home):
    paths.write_json_atomic(
        tend_home / "statusline-original.json",
        {"type": "command", "command": "echo ORIGINAL-LINE"},
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(STATUS_JSON))
    statusline.main()
    assert "ORIGINAL-LINE" in capsys.readouterr().out


def test_fallback_line_without_original(monkeypatch, capsys, tend_home):
    monkeypatch.setattr("sys.stdin", io.StringIO(STATUS_JSON))
    statusline.main()
    out = capsys.readouterr().out
    assert "Fable" in out and "42" in out


def test_garbage_input_never_raises(monkeypatch, capsys, tend_home):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    statusline.main()  # must not raise


def test_failing_original_falls_through_to_fallback(monkeypatch, capsys, tend_home):
    """If statusline-original.json command exits non-zero, use the built-in fallback."""
    paths.write_json_atomic(
        tend_home / "statusline-original.json",
        {"type": "command", "command": "exit 3"},
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(STATUS_JSON))
    statusline.main()
    out = capsys.readouterr().out
    assert "Fable" in out
