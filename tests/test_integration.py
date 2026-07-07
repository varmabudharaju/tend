import json
import os
import subprocess
import sys


def run_hook(payload, env_home):
    env = dict(os.environ, CARRYOVER_HOME=str(env_home))
    return subprocess.run(
        [sys.executable, "-m", "carryover.hook"],
        input=payload, capture_output=True, text=True, env=env, timeout=30,
    )


def test_posttooluse_offload_end_to_end(tmp_path):
    payload = json.dumps({
        "hook_event_name": "PostToolUse",
        "session_id": "int1",
        "cwd": str(tmp_path),
        "transcript_path": "",
        "tool_name": "Bash",
        "tool_response": "B" * 20000,
    })
    res = run_hook(payload, tmp_path / "home")
    assert res.returncode == 0
    out = json.loads(res.stdout)
    assert "tokens offloaded" in out["hookSpecificOutput"]["updatedToolOutput"]


def test_garbage_stdin_exits_zero_silently(tmp_path):
    res = run_hook("NOT JSON AT ALL", tmp_path / "home")
    assert res.returncode == 0
    assert res.stdout == ""


def test_statusline_end_to_end(tmp_path):
    payload = json.dumps({
        "session_id": "int2",
        "model": {"display_name": "Fable"},
        "context_window": {"used_percentage": 33.0},
    })
    env = dict(os.environ, CARRYOVER_HOME=str(tmp_path / "home"))
    res = subprocess.run(
        [sys.executable, "-m", "carryover.statusline"],
        input=payload, capture_output=True, text=True, env=env, timeout=30,
    )
    assert res.returncode == 0
    assert "Fable" in res.stdout
    ctx = json.loads((tmp_path / "home" / "sessions" / "int2" / "ctx.json").read_text())
    assert ctx["context_window"]["used_percentage"] == 33.0
