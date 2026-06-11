from conftest import make_event

from tend import offload, paths


def big_event(**kw):
    return make_event(
        tool_name="Bash",
        tool_response="HEAD" + ("m" * 20000) + "TAIL",  # ~5k tokens
        **kw,
    )


def test_big_bash_output_offloaded(tend_home):
    out = offload.handle(big_event())
    repl = out["hookSpecificOutput"]["updatedToolOutput"]
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert repl.startswith("HEAD")
    assert "TAIL" in repl
    assert "tokens offloaded" in repl
    files = list((paths.session_dir("s1") / "outputs").glob("*.txt"))
    assert len(files) == 1
    assert files[0].read_text().startswith("HEAD")
    assert str(files[0]) in repl


def test_small_output_untouched():
    assert offload.handle(make_event(tool_name="Bash", tool_response="small")) is None


def test_read_tool_never_offloaded():
    assert offload.handle(make_event(tool_name="Read", tool_response="x" * 20000)) is None


def test_dict_response_serialized(tend_home):
    out = offload.handle(make_event(tool_name="Bash", tool_response={"stdout": "y" * 20000}))
    assert out is not None


def test_sequential_output_numbering(tend_home):
    offload.handle(big_event())
    offload.handle(big_event())
    names = sorted(p.name for p in (paths.session_dir("s1") / "outputs").glob("*.txt"))
    assert names == ["0001.txt", "0002.txt"]


def test_save_skips_to_0002_when_0001_exists(tend_home):
    """_save must use O_EXCL retry: pre-existing 0001.txt forces name to 0002.txt."""
    d = paths.session_dir("s1") / "outputs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "0001.txt").write_text("original content")
    out = offload.handle(big_event())
    assert out is not None
    new_file = d / "0002.txt"
    assert new_file.exists(), "new output must land at 0002.txt"
    assert (d / "0001.txt").read_text() == "original content", "0001.txt must be untouched"


def test_overlap_guard_skips_offload_when_excerpt_not_smaller(tend_home):
    """If head+tail tokens * 4 >= len(text), offloading saves nothing — return None."""
    # Write a config where head+tail tokens together cover the text
    cfg_path = tend_home / "config.yaml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        "offload_threshold_tokens: 500\n"
        "offload_head_tokens: 300\n"
        "offload_tail_tokens: 300\n"
    )
    # ~550 tokens of text (2200 chars), but head+tail * 4 = (300+300)*4 = 2400 >= 2200
    text = "x" * 2200
    ev = make_event(tool_name="Bash", tool_response=text)
    result = offload.handle(ev)
    assert result is None, "overlap guard must return None when excerpt wouldn't save tokens"


def test_tail_zero_offloads_head_only(tend_home):
    """M6: tail=0 must mean 'no tail', never 'the whole string'."""
    (tend_home / "config.yaml").parent.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text(
        "offload_threshold_tokens: 500\noffload_head_tokens: 100\noffload_tail_tokens: 0\n"
    )
    text = "H" * 400 + "m" * 4000
    out = offload.handle(make_event(tool_name="Bash", tool_response=text))
    repl = out["hookSpecificOutput"]["updatedToolOutput"]
    assert len(repl) < len(text)
    assert repl.startswith("H" * 400)
    assert "m" * 1000 not in repl          # the body is actually gone


def test_banner_overhead_never_inflates(tend_home):
    """L4: head+tail just under len(text), but banner pushes it over - skip, no file."""
    (tend_home / "config.yaml").parent.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text(
        "offload_threshold_tokens: 500\noffload_head_tokens: 300\noffload_tail_tokens: 300\n"
    )
    text = "x" * 2500                       # head+tail = 2400 < 2500, banner makes it bigger
    assert offload.handle(make_event(tool_name="Bash", tool_response=text)) is None
    assert list((paths.session_dir("s1") / "outputs").glob("*.txt")) == []


def test_mcp_structured_response_not_offloaded(tend_home):
    """M8: schema'd MCP outputs would be silently rejected by Claude Code - don't pretend."""
    (tend_home / "config.yaml").parent.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text('offload_tools: ["mcp__db__query"]\n')
    ev = make_event(tool_name="mcp__db__query", tool_response={"rows": ["x" * 20000]})
    assert offload.handle(ev) is None
    assert list((paths.session_dir("s1") / "outputs").glob("*.txt")) == []


def test_mcp_plain_string_response_still_offloaded(tend_home):
    (tend_home / "config.yaml").parent.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text('offload_tools: ["mcp__db__query"]\n')
    ev = make_event(tool_name="mcp__db__query", tool_response="x" * 20000)
    assert offload.handle(ev) is not None


def test_bash_dict_offload_file_is_line_addressable(tend_home):
    """M7 live-artifact repro: the saved file must have real newlines, not escaped JSON."""
    resp = {"stdout": "line\n" * 4000, "stderr": ""}
    out = offload.handle(make_event(tool_name="Bash", tool_response=resp))
    assert out is not None
    saved = next((paths.session_dir("s1") / "outputs").glob("*.txt")).read_text()
    assert saved.startswith("line\nline\n")
    assert '"stdout"' not in saved
