from conftest import make_event

from carryover import agentguard, paths


def seed_model(name, sid="s1"):
    paths.write_json_atomic(paths.session_dir(sid) / "ctx.json",
                            {"model": {"display_name": name}})


def spawn_event(**kw):
    base = dict(hook_event_name="PreToolUse", tool_name="Agent",
                tool_input={"prompt": "do a thing", "subagent_type": "Explore"})
    base.update(kw)
    return make_event(**base)


def test_nudges_when_model_absent():
    seed_model("Fable 5")
    out = agentguard.handle(spawn_event())
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "inherit fable" in ctx
    assert "lowest tier that fits" in ctx


def test_task_tool_name_also_guarded():
    seed_model("Opus 4.8")
    ctx = agentguard.handle(spawn_event(tool_name="Task"))["hookSpecificOutput"]["additionalContext"]
    assert "inherit opus" in ctx


def test_silent_when_model_set():
    seed_model("Fable 5")
    ev = spawn_event(tool_input={"prompt": "x", "model": "haiku"})
    assert agentguard.handle(ev) is None


def test_silent_for_other_tools():
    assert agentguard.handle(spawn_event(tool_name="Read")) is None


def test_silent_when_session_is_haiku():
    seed_model("Haiku 4.5")
    assert agentguard.handle(spawn_event()) is None


def test_generic_wording_when_model_unknown():
    ctx = agentguard.handle(spawn_event())["hookSpecificOutput"]["additionalContext"]
    assert "the session model" in ctx


def test_config_toggle_disables(carryover_home):
    seed_model("Fable 5")
    carryover_home.mkdir(parents=True, exist_ok=True)
    (carryover_home / "config.yaml").write_text("delegation_guard: false\n")
    assert agentguard.handle(spawn_event()) is None


def test_dispatched_from_hook(carryover_home):
    from carryover import hook

    seed_model("Fable 5")
    out = hook.dispatch(spawn_event())
    assert "additionalContext" in out["hookSpecificOutput"]
