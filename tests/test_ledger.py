import json

from conftest import make_event, write_transcript

from tend import ledger, paths


def fixture_lines():
    big = "x" * 2000  # ~500 tokens
    return [
        {"type": "assistant", "message": {"usage": {
            "input_tokens": 10, "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 1000, "output_tokens": 50},
            "content": [{"type": "tool_use", "id": "t1", "name": "Read",
                         "input": {"file_path": "/tmp/proj/a.py"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": big}]}},
        {"type": "assistant", "message": {"usage": {
            "input_tokens": 5, "cache_read_input_tokens": 1500,
            "cache_creation_input_tokens": 600, "output_tokens": 80},
            "content": [{"type": "tool_use", "id": "t2", "name": "Edit",
                         "input": {"file_path": "/tmp/proj/a.py"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t2", "content": "ok"}]}},
        {"type": "assistant", "message": {"usage": {
            "input_tokens": 2, "cache_read_input_tokens": 2200,
            "cache_creation_input_tokens": 300, "output_tokens": 40},
            "content": []}},
    ]


def test_ingest_full_transcript(tmp_path):
    tp = tmp_path / "t.jsonl"
    write_transcript(tp, fixture_lines())
    ev = make_event(transcript_path=str(tp))
    ledger.ingest(ev)
    s = ledger.load_summary("s1")
    assert s["context_total"] == 2 + 2200 + 300
    assert s["output_total"] == 50 + 80 + 40
    assert s["results"]["t1"]["tool"] == "Read"
    assert s["results"]["t1"]["tokens"] == 500
    assert s["results"]["t1"]["stale"] is True  # a.py edited after the read
    assert s["results"]["t2"]["stale"] is False
    assert ledger.stale_tokens(s) == 500


def test_ingest_is_incremental(tmp_path):
    tp = tmp_path / "t.jsonl"
    lines = fixture_lines()
    write_transcript(tp, lines[:2])
    ev = make_event(transcript_path=str(tp))
    ledger.ingest(ev)
    write_transcript(tp, lines)  # rewrite longer file; cursor continues from old offset
    ledger.ingest(ev)
    s = ledger.load_summary("s1")
    assert s["context_total"] == 2502
    assert len(s["results"]) == 2


def test_bad_lines_set_degraded(tmp_path):
    tp = tmp_path / "t.jsonl"
    tp.write_text('{"type": "assistant", "message": {"usage": {"input_tokens": 1}}}\nNOT JSON\n')
    ledger.ingest(make_event(transcript_path=str(tp)))
    assert ledger.load_summary("s1")["degraded"] is True


def test_top_results_sorted(tmp_path):
    tp = tmp_path / "t.jsonl"
    write_transcript(tp, fixture_lines())
    ledger.ingest(make_event(transcript_path=str(tp)))
    top = ledger.top_results(ledger.load_summary("s1"), 1)
    assert top[0]["id"] == "t1" and top[0]["tokens"] == 500


def test_state_mark_roundtrip(tmp_path):
    tp = tmp_path / "t.jsonl"
    write_transcript(tp, fixture_lines())
    ledger.ingest(make_event(transcript_path=str(tp)))
    ledger.set_state_mark("s1", 123.0)
    s = ledger.load_summary("s1")
    assert s["state_mark"] == {"mtime": 123.0, "output_total": 170}  # 50+80+40
    assert ledger.tokens_since_state_mark(s) == 0


def test_since_never_negative_after_context_shrink():
    """H2: compaction shrinks context_total; output-based since stays correct."""
    summary = {"context_total": 30_000, "output_total": 5_000,
               "state_mark": {"mtime": 1.0, "output_total": 2_000}}
    assert ledger.tokens_since_state_mark(summary) == 3_000


def test_legacy_context_total_mark_returns_none():
    """Pre-v0.2 marks lack output_total: report unknown, never a bogus number."""
    summary = {"context_total": 10_000, "output_total": 100,
               "state_mark": {"mtime": 1.0, "context_total": 140_000}}
    assert ledger.tokens_since_state_mark(summary) is None


def test_record_agent():
    ledger.record_agent(make_event(hook_event_name="SubagentStart", agent_id="a1", agent_type="Explore"))
    ledger.record_agent(make_event(hook_event_name="SubagentStop", agent_id="a1"))
    s = ledger.load_summary("s1")
    assert s["agents"]["a1"]["type"] == "Explore"
    assert s["agents"]["a1"]["stopped"] is True


def test_bloat_tokens(tmp_path):
    """One 3000-tok result + one 100-tok result; threshold 2500 → bloat = 3000."""
    summary = {
        "results": {
            "big": {"tool": "Bash", "tokens": 3000, "file": None, "stale": False},
            "small": {"tool": "Read", "tokens": 100, "file": "/f", "stale": False},
        }
    }
    assert ledger.bloat_tokens(summary, 2500) == 3000


def test_cursor_past_eof_reset(tmp_path):
    """Ingest full fixture, set state mark, then truncate to first line only; verify recovery."""
    tp = tmp_path / "t.jsonl"
    write_transcript(tp, fixture_lines())
    ev = make_event(transcript_path=str(tp))
    ledger.ingest(ev)
    # Set a state mark so we can verify it survives truncation
    ledger.set_state_mark("s1", 999.0)
    ledger.record_agent(make_event(hook_event_name="SubagentStart", agent_id="a99", agent_type="Search"))

    # Truncate the transcript to only the first line
    first_line = fixture_lines()[0]
    import json as _json
    tp.write_text(_json.dumps(first_line) + "\n")

    ledger.ingest(ev)
    s = ledger.load_summary("s1")

    # Cursor reset → file re-parsed from beginning; degraded flag set
    assert s["degraded"] is True
    # First line: input_tokens=10, cache_read=0, cache_creation=1000 → context_total=1010
    assert s["context_total"] == 1010
    # agents survive the reset; the state_mark baseline is dropped with the
    # counters it was measured against (re-marked on the next Stop)
    assert s["state_mark"] is None
    assert s["agents"]["a99"]["type"] == "Search"


# ── v0.2: H1 partial-line race ────────────────────────────────────────────────

def test_partial_trailing_line_deferred_not_lost(tmp_path):
    """A writer mid-append leaves a partial line; it must be re-read later, not skipped."""
    tp = tmp_path / "t.jsonl"
    lines = fixture_lines()
    line1 = json.dumps(lines[0]) + "\n"
    full = line1 + json.dumps(lines[1]) + "\n"
    tp.write_text(line1 + full[len(line1):len(line1) + 40])  # line 2 cut at 40 chars
    ev = make_event(transcript_path=str(tp))
    ledger.ingest(ev)
    s = ledger.load_summary("s1")
    assert s["degraded"] is False          # fragment is deferred, not judged corrupt
    assert "t1" in s["pending"]            # line 1 fully ingested
    assert s["results"] == {}              # line 2 not consumed yet
    tp.write_text(full)                    # writer finishes the append
    ledger.ingest(ev)
    s = ledger.load_summary("s1")
    assert s["results"]["t1"]["tokens"] == 500   # nothing lost
    assert s["degraded"] is False


def test_invalid_utf8_line_skipped_cursor_advances(tmp_path):
    """M1: bad bytes degrade that line only; later lines parse and re-ingest is stable."""
    tp = tmp_path / "t.jsonl"
    good = json.dumps(fixture_lines()[0]).encode("utf-8")
    tp.write_bytes(b"\xff\xfe garbage\n" + good + b"\n")
    ev = make_event(transcript_path=str(tp))
    ledger.ingest(ev)
    s = ledger.load_summary("s1")
    assert s["degraded"] is True
    assert s["context_total"] == 1010      # the good line after the bad bytes parsed
    before = s["output_total"]
    ledger.ingest(ev)                       # cursor advanced past the bad line
    assert ledger.load_summary("s1")["output_total"] == before


def test_non_dict_json_lines_skipped(tmp_path):
    """M2: null / list / str / number lines must not stall the cursor or crash."""
    tp = tmp_path / "t.jsonl"
    good = json.dumps(fixture_lines()[0])
    tp.write_text('null\n[1, 2]\n"str"\n123\n' + good + "\n")
    ev = make_event(transcript_path=str(tp))
    ledger.ingest(ev)
    s = ledger.load_summary("s1")
    assert s["context_total"] == 1010
    before = s["output_total"]
    ledger.ingest(ev)
    assert ledger.load_summary("s1")["output_total"] == before


def test_notebookedit_staleness_uses_notebook_path(tmp_path):
    """L1: live NotebookEdit schema sends notebook_path, not file_path."""
    tp = tmp_path / "t.jsonl"
    nb = "/tmp/proj/nb.ipynb"
    write_transcript(tp, [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "r1", "name": "Read", "input": {"file_path": nb}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "r1", "content": "cells"}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "e1", "name": "NotebookEdit",
             "input": {"notebook_path": nb}}]}},
    ])
    ledger.ingest(make_event(transcript_path=str(tp)))
    assert ledger.load_summary("s1")["results"]["r1"]["stale"] is True


def test_poisoned_cursor_repaired(tmp_path):
    """L2: cursor.json of null / {} / {"offset":"0"} must reset to 0, not crash forever."""
    tp = tmp_path / "t.jsonl"
    write_transcript(tp, [fixture_lines()[0]])
    ev = make_event(transcript_path=str(tp))
    for poison in ("null", "{}", '{"offset": "0"}', '{"offset": -5}'):
        sdir = paths.session_dir("s1")
        for f in sdir.glob("*.json"):
            f.unlink()
        (sdir / "cursor.json").write_text(poison)
        ledger.ingest(ev)
        assert ledger.load_summary("s1")["context_total"] == 1010, poison


def test_cursor_lives_in_summary_single_atomic_write(tmp_path):
    """L3: cursor is stored inside summary.json; legacy cursor.json is consumed and removed."""
    tp = tmp_path / "t.jsonl"
    write_transcript(tp, fixture_lines())
    ev = make_event(transcript_path=str(tp))
    ledger.ingest(ev)
    s = ledger.load_summary("s1")
    assert s["cursor"]["offset"] == tp.stat().st_size
    assert not (paths.session_dir("s1") / "cursor.json").exists()


def test_legacy_cursor_json_migrated(tmp_path):
    """Upgrade path: an old separate cursor.json must seed the offset (no double-count)."""
    tp = tmp_path / "t.jsonl"
    lines = fixture_lines()
    write_transcript(tp, lines[:2])
    first_two = tp.stat().st_size
    write_transcript(tp, lines)
    # Simulate a v0.1 session: summary without "cursor", offset in separate file
    paths.write_json_atomic(paths.session_dir("s1") / "cursor.json", {"offset": first_two})
    paths.write_json_atomic(paths.session_dir("s1") / "summary.json", {
        "context_total": 2502, "output_total": 130, "results": {}, "reads": {},
        "pending": {}, "agents": {}, "state_mark": None, "degraded": False,
    })
    ledger.ingest(make_event(transcript_path=str(tp)))
    s = ledger.load_summary("s1")
    assert s["output_total"] == 130 + 80 + 40   # only lines 3-5 ingested, not re-counted
    assert not (paths.session_dir("s1") / "cursor.json").exists()
