import os

from conftest import make_event

from carryover import readguard


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


def test_file_deleted_between_isfile_and_getsize_returns_none(tmp_path, monkeypatch):
    """TOCTOU: file disappears between isfile check and getsize — must return None."""
    f = tmp_path / "big.txt"
    f.write_text("x" * 100_000)

    def getsize_that_raises(path):
        raise OSError("file vanished")

    monkeypatch.setattr(os.path, "getsize", getsize_that_raises)
    ev = make_event(hook_event_name="PreToolUse", tool_name="Read",
                    tool_input={"file_path": str(f)})
    # With the TOCTOU fix, OSError from getsize must be caught and return None
    result = readguard.handle(ev)
    assert result is None, "OSError from getsize must be caught and return None"


def test_binary_file_not_nudged(tmp_path):
    """L5: bytes//4 'tokens' and offset/limit advice are meaningless for a PNG."""
    big = tmp_path / "img.png"
    big.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 70000)
    out = readguard.handle(make_event(
        hook_event_name="PreToolUse", tool_name="Read",
        tool_input={"file_path": str(big)}))
    assert out is None
