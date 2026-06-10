import json

import pytest

from tend import install, paths, cli


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


# ── Fix 1: corrupted settings → parse-or-refuse ──────────────────────────────

def test_corrupted_settings_raises_settings_error(tmp_path):
    sp = tmp_path / "settings.json"
    bad_content = '{"hooks": [BROKEN'
    sp.write_text(bad_content)
    with pytest.raises(install.SettingsError):
        install.install(sp)
    # file must be left untouched
    assert sp.read_text() == bad_content


def test_cli_surfaces_settings_error_returns_1(tmp_path):
    sp = tmp_path / "settings.json"
    sp.write_text('{"hooks": [BROKEN')
    result = cli.main(["install-hook", "--settings", str(sp)])
    assert result == 1


def test_cli_uninstall_surfaces_settings_error_returns_1(tmp_path):
    sp = tmp_path / "settings.json"
    sp.write_text('{"hooks": [BROKEN')
    result = cli.main(["uninstall-hook", "--settings", str(sp)])
    assert result == 1


# ── Fix 2: backup refreshes on every good parse ───────────────────────────────

def test_backup_refreshes_on_reinstall(tmp_path, tend_home):
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps(EXISTING))
    install.install(sp)
    # Now modify the installed settings (simulate external change)
    current = json.loads(sp.read_text())
    current["newKey"] = 1
    sp.write_text(json.dumps(current))
    # Install again — backup should reflect the latest content (with newKey)
    install.install(sp)
    bak = tmp_path / "settings.json.bak-tend"
    assert bak.exists()
    bak_content = json.loads(bak.read_text())
    assert bak_content.get("newKey") == 1


# ── Fix 4: uninstall no-op detection ─────────────────────────────────────────

def test_uninstall_noop_leaves_file_identical(tmp_path):
    """Settings without any tend entries and a non-tend statusline: uninstall
    must leave file bytes identical and create no backup."""
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps(EXISTING))
    original_bytes = sp.read_bytes()
    install.uninstall(sp)
    assert sp.read_bytes() == original_bytes
    bak = tmp_path / "settings.json.bak-tend"
    assert not bak.exists()
