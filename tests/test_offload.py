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
