"""Back-compat: legacy tend env vars, data/state dirs, install markers, and the
tend.* import shim - so pre-rename installs keep working until users re-install."""
import json
import os
import subprocess
import sys
from pathlib import Path

from carryover import config, install, paths, state

WORKTREE_ROOT = Path(__file__).resolve().parents[1]


def _no_home_env(monkeypatch, fake_home):
    monkeypatch.delenv("CARRYOVER_HOME", raising=False)
    monkeypatch.delenv("TEND_HOME", raising=False)
    monkeypatch.setattr(paths.Path, "home", staticmethod(lambda: fake_home))


# ---- paths.home() resolution order: CARRYOVER_HOME > TEND_HOME > new dir > legacy dir ----

def test_home_prefers_carryover_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CARRYOVER_HOME", str(tmp_path / "co"))
    monkeypatch.setenv("TEND_HOME", str(tmp_path / "legacy"))
    assert paths.home() == tmp_path / "co"


def test_home_falls_back_to_legacy_tend_env(monkeypatch, tmp_path):
    monkeypatch.delenv("CARRYOVER_HOME", raising=False)
    monkeypatch.setenv("TEND_HOME", str(tmp_path / "legacy"))
    assert paths.home() == tmp_path / "legacy"


def test_home_defaults_to_carryover_dir(monkeypatch, tmp_path):
    _no_home_env(monkeypatch, tmp_path)
    (tmp_path / ".claude" / "carryover").mkdir(parents=True)
    assert paths.home() == tmp_path / ".claude" / "carryover"


def test_home_uses_legacy_dir_when_only_it_exists(monkeypatch, tmp_path):
    _no_home_env(monkeypatch, tmp_path)
    (tmp_path / ".claude" / "tend").mkdir(parents=True)  # legacy dir, no carryover dir
    assert paths.home() == tmp_path / ".claude" / "tend"


def test_home_prefers_new_dir_when_both_exist(monkeypatch, tmp_path):
    _no_home_env(monkeypatch, tmp_path)
    (tmp_path / ".claude" / "carryover").mkdir(parents=True)
    (tmp_path / ".claude" / "tend").mkdir(parents=True)
    assert paths.home() == tmp_path / ".claude" / "carryover"


def test_home_defaults_new_when_neither_dir_exists(monkeypatch, tmp_path):
    _no_home_env(monkeypatch, tmp_path)
    assert paths.home() == tmp_path / ".claude" / "carryover"


# ---- state.py: read falls back to legacy .claude/tend/STATE.md; seed uses the new path ----

def test_path_for_new_when_neither_exists(tmp_path):
    assert state.path_for(str(tmp_path)) == tmp_path / ".claude" / "carryover" / "STATE.md"


def test_path_for_falls_back_to_legacy(tmp_path):
    legacy = tmp_path / ".claude" / "tend" / "STATE.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy", encoding="utf-8")
    assert state.path_for(str(tmp_path)) == legacy


def test_path_for_prefers_new_over_legacy(tmp_path):
    new = tmp_path / ".claude" / "carryover" / "STATE.md"
    new.parent.mkdir(parents=True)
    new.write_text("new", encoding="utf-8")
    legacy = tmp_path / ".claude" / "tend" / "STATE.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy", encoding="utf-8")
    assert state.path_for(str(tmp_path)) == new


def test_resolve_ancestor_finds_legacy_state(tmp_path):
    proj = tmp_path / "proj"
    legacy = proj / ".claude" / "tend" / "STATE.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy", encoding="utf-8")
    sub = proj / "a" / "b"
    sub.mkdir(parents=True)
    assert state.resolve(str(sub), None) == legacy


def test_seed_writes_new_path_when_nothing_exists(tmp_path):
    sp = state.path_for(str(tmp_path))
    assert sp == tmp_path / ".claude" / "carryover" / "STATE.md"
    state.seed(sp)
    assert sp.is_file()
    assert not (tmp_path / ".claude" / "tend" / "STATE.md").exists()


# ---- config.py: legacy project config honored, canonical wins ----

def test_config_reads_legacy_project_config(tmp_path):
    d = tmp_path / ".claude" / "tend"
    d.mkdir(parents=True)
    (d / "config.yaml").write_text("offload_threshold_tokens: 999\n", encoding="utf-8")
    assert config.load(str(tmp_path)).offload_threshold_tokens == 999


def test_config_new_project_config_overrides_legacy(tmp_path):
    legacy = tmp_path / ".claude" / "tend"
    legacy.mkdir(parents=True)
    (legacy / "config.yaml").write_text("offload_threshold_tokens: 111\n", encoding="utf-8")
    new = tmp_path / ".claude" / "carryover"
    new.mkdir(parents=True)
    (new / "config.yaml").write_text("offload_threshold_tokens: 222\n", encoding="utf-8")
    assert config.load(str(tmp_path)).offload_threshold_tokens == 222


# ---- install.py: recognize + clean up legacy -m tend.hook / -m tend.statusline ----

def test_uninstall_removes_legacy_hook_entry(tmp_path):
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({"hooks": {
        "Stop": [{"hooks": [{"type": "command", "command": '"py" -m tend.hook'}]}]}}))
    install.uninstall(str(sp))
    assert "Stop" not in json.loads(sp.read_text()).get("hooks", {})


def test_install_replaces_legacy_hook_without_duplicating(tmp_path):
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({"hooks": {
        "Stop": [{"hooks": [{"type": "command", "command": '"oldpy" -m tend.hook'}]}]}}))
    install.install(str(sp))
    cmds = [h["command"] for e in json.loads(sp.read_text())["hooks"]["Stop"] for h in e["hooks"]]
    assert len(cmds) == 1
    assert "-m carryover.hook" in cmds[0]
    assert "-m tend.hook" not in cmds[0]


def test_is_statusline_detects_legacy_marker():
    assert install._is_carryover_statusline({"type": "command", "command": '"py" -m tend.statusline'})


# ---- tend.* import shim ----

def test_shim_import_resolves_to_carryover():
    import tend.anchor
    from carryover import anchor as real
    assert tend.anchor.handle is real.handle


def test_shim_reexports_underscore_prefixed_names():
    from tend.state import _ancestor_with_state
    from carryover.state import _ancestor_with_state as real
    assert _ancestor_with_state is real


def test_shim_module_runs_as_main(tmp_path):
    """python3 -m tend.hook (as old settings.json invoke it) still resolves and runs."""
    env = {**os.environ, "CARRYOVER_HOME": str(tmp_path / "home")}
    r = subprocess.run(
        [sys.executable, "-m", "tend.hook"],
        input='{"hook_event_name":"Stop","session_id":"shim1","cwd":"' + str(tmp_path) + '"}',
        capture_output=True, text=True, cwd=str(WORKTREE_ROOT), env=env,
    )
    assert r.returncode == 0, r.stderr
