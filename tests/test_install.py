import json

from tend import install, paths


EXISTING = {
    "hooks": {
        "PostToolUse": [{"hooks": [{"type": "command", "command": "python3 -m agent_pd.hook"}]}],
    },
    "statusLine": {"type": "command", "command": "bash /Users/varma/.claude/statusline.sh"},
    "model": "claude-fable-5[1m]",
}


def test_install_merges_preserving_existing(tmp_path, tend_home):
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps(EXISTING))
    install.install(sp)
    s = json.loads(sp.read_text())
    cmds = [h["command"] for e in s["hooks"]["PostToolUse"] for h in e["hooks"]]
    assert any("agent_pd" in c for c in cmds)          # preserved
    assert any("-m tend.hook" in c for c in cmds)      # added
    for ev in install.HOOK_EVENTS:
        assert any("-m tend.hook" in h["command"] for e in s["hooks"][ev] for h in e["hooks"])
    assert s["model"] == "claude-fable-5[1m]"          # untouched
    # statusline wrapped, original preserved
    assert "-m tend.statusline" in s["statusLine"]["command"]
    orig = paths.read_json(tend_home / "statusline-original.json")
    assert "statusline.sh" in orig["command"]
    # backup written
    assert (tmp_path / "settings.json.bak-tend").exists()


def test_install_idempotent(tmp_path):
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps(EXISTING))
    install.install(sp)
    once = json.loads(sp.read_text())
    install.install(sp)
    assert json.loads(sp.read_text()) == once


def test_uninstall_restores(tmp_path, tend_home):
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps(EXISTING))
    install.install(sp)
    install.uninstall(sp)
    s = json.loads(sp.read_text())
    cmds = [h["command"] for e in s["hooks"].get("PostToolUse", []) for h in e["hooks"]]
    assert cmds == ["python3 -m agent_pd.hook"]
    assert s["statusLine"]["command"] == "bash /Users/varma/.claude/statusline.sh"
    assert "PreCompact" not in s["hooks"]


def test_install_into_empty_settings(tmp_path):
    sp = tmp_path / "settings.json"
    install.install(sp)
    s = json.loads(sp.read_text())
    assert "-m tend.statusline" in s["statusLine"]["command"]
