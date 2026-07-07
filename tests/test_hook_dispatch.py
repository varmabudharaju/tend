from conftest import make_event, write_transcript

from carryover import hook, ledger


def test_posttooluse_ingests_and_offloads(tmp_path):
    tp = tmp_path / "t.jsonl"
    write_transcript(tp, [{"type": "assistant", "message": {"usage": {
        "input_tokens": 1, "cache_read_input_tokens": 2,
        "cache_creation_input_tokens": 3, "output_tokens": 4}, "content": []}}])
    ev = make_event(hook_event_name="PostToolUse", transcript_path=str(tp),
                    tool_name="Bash", tool_response="z" * 20000)
    out = hook.dispatch(ev)
    assert "updatedToolOutput" in out["hookSpecificOutput"]
    assert ledger.load_summary("s1")["context_total"] == 6


def test_subagent_events_recorded():
    hook.dispatch(make_event(hook_event_name="SubagentStart", agent_id="a1", agent_type="Explore"))
    hook.dispatch(make_event(hook_event_name="SubagentStop", agent_id="a1"))
    assert ledger.load_summary("s1")["agents"]["a1"]["stopped"] is True


def test_unknown_event_returns_none():
    assert hook.dispatch(make_event(hook_event_name="Notification")) is None


def test_userpromptsubmit_returns_anchor(tmp_path):
    from carryover import paths
    paths.write_json_atomic(paths.session_dir("s1") / "ctx.json",
                            {"context_window": {"used_percentage": 30.0}})
    out = hook.dispatch(make_event(hook_event_name="UserPromptSubmit", cwd=str(tmp_path)))
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"


def test_handler_still_runs_when_ingest_crashes(tmp_path, monkeypatch):
    """M3: a poisoned ledger must degrade the ledger, not kill offload."""
    from carryover import ledger as ledger_mod

    def boom(event):
        raise TypeError("'<' not supported between instances of 'str' and 'int'")

    monkeypatch.setattr(ledger_mod, "ingest", boom)
    ev = make_event(hook_event_name="PostToolUse", transcript_path="/nonexistent",
                    tool_name="Bash", tool_response="z" * 20000)
    out = hook.dispatch(ev)
    assert "updatedToolOutput" in out["hookSpecificOutput"]      # offload still ran
    assert ledger.load_summary("s1")["degraded"] is True         # and it's visible
