import json
import os
import stat

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


# ── Fix 5 (this PR): statusline-original.json lifecycle ──────────────────────

def test_uninstall_removes_statusline_original(tmp_path, tend_home):
    """Install (with existing statusLine) saves original; uninstall must delete it."""
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps(EXISTING))
    install.install(sp)
    orig_file = tend_home / "statusline-original.json"
    assert orig_file.exists(), "original should be saved on install"
    install.uninstall(sp)
    assert not orig_file.exists(), "original should be deleted after uninstall"


def test_reinstall_preserves_saved_original_when_statusline_removed(tmp_path, tend_home):
    """L13: the saved original may be the only copy of the user's statusline - keep it."""
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps(EXISTING))
    install.install(sp)                     # saves the user's statusline.sh original
    s = json.loads(sp.read_text())
    del s["statusLine"]                     # user (or another tool) removed the wrapper
    sp.write_text(json.dumps(s))
    install.install(sp)                     # reinstall must NOT destroy the original
    orig = paths.read_json(tend_home / "statusline-original.json")
    assert orig and "statusline.sh" in orig["command"]
    install.uninstall(sp)                   # and uninstall can still restore it
    assert "statusline.sh" in json.loads(sp.read_text())["statusLine"]["command"]


def test_uninstall_preserves_user_hook_in_shared_entry(tmp_path):
    """M10: prune tend's inner command, keep the user's, keep entry metadata."""
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({"hooks": {"PostToolUse": [{"matcher": "*", "hooks": [
        {"type": "command", "command": "python3 -m other.hook"},
        {"type": "command", "command": '"/usr/bin/python3" -m tend.hook'},
    ]}]}}))
    install.uninstall(sp)
    s = json.loads(sp.read_text())
    entry = s["hooks"]["PostToolUse"][0]
    assert [h["command"] for h in entry["hooks"]] == ["python3 -m other.hook"]
    assert entry["matcher"] == "*"


def test_reinstall_repairs_dead_interpreter(tmp_path, tend_home):
    """M11: a stale '/old/dead/python' must be rewritten to the current interpreter."""
    dead_hook = '"/old/dead/python" -m tend.hook'
    settings = {"hooks": {ev: [{"hooks": [{"type": "command", "command": dead_hook}]}]
                          for ev in install.HOOK_EVENTS},
                "statusLine": {"type": "command",
                               "command": '"/old/dead/python" -m tend.statusline'}}
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps(settings))
    install.install(sp)
    s = json.loads(sp.read_text())
    for ev in install.HOOK_EVENTS:
        cmds = [h["command"] for e in s["hooks"][ev] for h in e["hooks"]]
        assert cmds == [install.hook_command()], ev   # repaired, not duplicated
    assert s["statusLine"]["command"] == install.statusline_command()
    # repairing our own statusline must not overwrite the saved original
    assert not (tend_home / "statusline-original.json").exists()


def test_null_hooks_and_string_statusline_handled(tmp_path, tend_home):
    """L14: malformed-but-parseable settings must round-trip, not AttributeError."""
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({"hooks": None, "statusLine": "echo hi"}))
    install.install(sp)
    s = json.loads(sp.read_text())
    assert "-m tend.statusline" in s["statusLine"]["command"]
    assert paths.read_json(tend_home / "statusline-original.json") == "echo hi"
    install.uninstall(sp)
    assert json.loads(sp.read_text())["statusLine"] == "echo hi"


def test_top_level_array_raises_settings_error(tmp_path):
    sp = tmp_path / "settings.json"
    sp.write_text("[1, 2]")
    with pytest.raises(install.SettingsError):
        install.install(sp)
    with pytest.raises(install.SettingsError):
        install.uninstall(sp)
    assert sp.read_text() == "[1, 2]"


def test_backup_and_settings_keep_restrictive_mode(tmp_path):
    """L17: a 0600 settings file must yield a 0600 backup and stay 0600 itself."""
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps(EXISTING))
    os.chmod(sp, 0o600)
    install.install(sp)
    assert stat.S_IMODE(os.stat(tmp_path / "settings.json.bak-tend").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(sp).st_mode) == 0o600


def test_wrap_statusline_touches_only_statusline(tmp_path, tend_home):
    """Plugin installs: hooks come from the plugin; this wraps just the statusline."""
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps(EXISTING))
    install.wrap_statusline(sp)
    s = json.loads(sp.read_text())
    assert "-m tend.statusline" in s["statusLine"]["command"]
    cmds = [h["command"] for e in s["hooks"]["PostToolUse"] for h in e["hooks"]]
    assert cmds == ["python3 -m agent_pd.hook"]          # hooks untouched
    orig = paths.read_json(tend_home / "statusline-original.json")
    assert "statusline.sh" in orig["command"]            # original saved
    assert cli.main(["wrap-statusline", "--settings", str(sp)]) == 0
