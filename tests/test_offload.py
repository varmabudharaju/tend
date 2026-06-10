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
