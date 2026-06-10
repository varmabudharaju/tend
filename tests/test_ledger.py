from conftest import make_event, write_transcript

from tend import ledger


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
    assert s["state_mark"] == {"mtime": 123.0, "context_total": 2502}
    assert ledger.tokens_since_state_mark(s) == 0


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
    # agents and state_mark are preserved across the reset
    assert s["state_mark"] is not None
    assert s["agents"]["a99"]["type"] == "Search"
