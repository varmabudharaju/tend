import json
import os

from tend import cli, paths


def file_output(sid, name, text, tool="Bash", hint="hint"):
    d = paths.session_dir(sid) / "outputs"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")
    with open(d / "index.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(
            {"file": name, "ts": 1.0, "tool": tool, "tokens": 100, "hint": hint}
        ) + "\n")
    return d / name


def _age(sid, ts):
    d = paths.session_dir(sid) / "outputs"
    for p in d.iterdir():
        os.utime(p, (ts, ts))
    os.utime(d, (ts, ts))


def test_find_reports_path_and_lineno(capsys, tend_home):
    p = file_output("s1", "0001.txt", "alpha\nbeta ERROR here\ngamma\n")
    assert cli.main(["find", "ERROR"]) == 0
    out = capsys.readouterr().out
    assert f"{p}:2: beta ERROR here" in out


def test_find_case_insensitive_by_default(capsys, tend_home):
    file_output("s1", "0001.txt", "the Error occurred\n")
    assert cli.main(["find", "error"]) == 0
    assert ":1: the Error occurred" in capsys.readouterr().out


def test_find_case_sensitive_flag(capsys, tend_home):
    file_output("s1", "0001.txt", "the Error occurred\n")
    assert cli.main(["find", "error", "-s"]) == 0
    out = capsys.readouterr().out
    assert "occurred" not in out
    assert "no matches" in out


def test_find_max_cap_and_clipped_note(capsys, tend_home):
    file_output("s1", "0001.txt", "".join(f"match {i}\n" for i in range(10)))
    assert cli.main(["find", "match", "--max", "3"]) == 0
    out = capsys.readouterr().out
    assert len([l for l in out.splitlines() if "0001.txt:" in l]) == 3
    assert "clipped, 3+ matches" in out


def test_find_all_searches_two_sessions(capsys, tend_home):
    file_output("s1", "0001.txt", "needle in s1\n")
    file_output("s2", "0001.txt", "needle in s2\n")
    assert cli.main(["find", "needle", "--all"]) == 0
    out = capsys.readouterr().out
    assert "needle in s1" in out
    assert "needle in s2" in out


def test_find_default_targets_newest_outputs(capsys, tend_home):
    file_output("s1", "0001.txt", "needle old\n")
    file_output("s2", "0001.txt", "needle new\n")
    _age("s1", 1_000_000)
    _age("s2", 2_000_000)
    assert cli.main(["find", "needle"]) == 0
    out = capsys.readouterr().out
    assert "needle new" in out
    assert "needle old" not in out


def test_find_session_flag_targets_one(capsys, tend_home):
    file_output("s1", "0001.txt", "needle s1\n")
    file_output("s2", "0001.txt", "needle s2\n")
    assert cli.main(["find", "needle", "--session", "s1"]) == 0
    out = capsys.readouterr().out
    assert "needle s1" in out
    assert "needle s2" not in out


def test_find_ghost_session_returns_1(capsys, tend_home):
    file_output("s1", "0001.txt", "x\n")
    assert cli.main(["find", "x", "--session", "ghost"]) == 1
    assert "no such session: ghost" in capsys.readouterr().out


def test_find_no_outputs_exits_0(capsys, tend_home):
    assert cli.main(["find", "anything"]) == 0
    assert "no filed outputs" in capsys.readouterr().out


def test_find_header_names_tool_and_hint(capsys, tend_home):
    file_output("s1", "0001.txt", "boom\n", tool="Grep", hint="ran grep on foo")
    assert cli.main(["find", "boom"]) == 0
    out = capsys.readouterr().out
    assert "Grep" in out
    assert "ran grep on foo" in out


def test_find_clips_matched_line_to_200(capsys, tend_home):
    file_output("s1", "0001.txt", "needle" + "B" * 400 + "\n")
    assert cli.main(["find", "needle"]) == 0
    line = [l for l in capsys.readouterr().out.splitlines() if "0001.txt:1:" in l][0]
    content = line.split(":1: ", 1)[1]
    assert len(content) == 200


def test_find_bad_pattern_returns_1(capsys, tend_home):
    file_output("s1", "0001.txt", "x\n")
    assert cli.main(["find", "(unclosed"]) == 1
    assert "bad pattern" in capsys.readouterr().out
