import io
import json

from tend import hookio, paths


def run(handler, stdin_text, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_text))
    code = hookio.run_fail_open(handler)
    return code, capsys.readouterr().out


def test_handler_output_emitted(monkeypatch, capsys):
    code, out = run(lambda e: {"ok": e["session_id"]}, '{"session_id": "s1"}', monkeypatch, capsys)
    assert code == 0
    assert json.loads(out) == {"ok": "s1"}


def test_none_output_emits_nothing(monkeypatch, capsys):
    code, out = run(lambda e: None, "{}", monkeypatch, capsys)
    assert code == 0 and out == ""


def test_exception_is_swallowed_and_logged(monkeypatch, capsys, tend_home):
    def boom(e):
        raise RuntimeError("boom")

    code, out = run(boom, "{}", monkeypatch, capsys)
    assert code == 0 and out == ""
    assert "boom" in paths.log_path().read_text()


def test_garbage_stdin_is_swallowed(monkeypatch, capsys):
    code, out = run(lambda e: {"x": 1}, "not json", monkeypatch, capsys)
    assert code == 0 and out == ""


def test_disabled_short_circuits(monkeypatch, capsys, tend_home):
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "disabled").touch()
    called = []
    code, out = run(lambda e: called.append(1), "{}", monkeypatch, capsys)
    assert code == 0 and out == "" and not called
