from conftest import make_event

from tend import readguard


def test_large_unbounded_read_gets_nudge(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("x" * 100_000)
    ev = make_event(hook_event_name="PreToolUse", tool_name="Read",
                    tool_input={"file_path": str(f)})
    out = readguard.handle(ev)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "offset/limit" in ctx
    assert "permissionDecision" not in out["hookSpecificOutput"]  # never alter permissions


def test_bounded_read_ignored(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("x" * 100_000)
    ev = make_event(tool_name="Read", tool_input={"file_path": str(f), "limit": 100})
    assert readguard.handle(ev) is None


def test_small_file_ignored(tmp_path):
    f = tmp_path / "small.txt"
    f.write_text("x")
    assert readguard.handle(make_event(tool_name="Read", tool_input={"file_path": str(f)})) is None


def test_other_tools_and_missing_files_ignored(tmp_path):
    assert readguard.handle(make_event(tool_name="Bash", tool_input={})) is None
    assert readguard.handle(
        make_event(tool_name="Read", tool_input={"file_path": str(tmp_path / "nope")})
    ) is None
