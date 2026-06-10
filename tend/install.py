"""Merge tend into ~/.claude/settings.json non-destructively; reversible."""
import json
import os
import sys
from pathlib import Path

from . import paths

HOOK_EVENTS = [
    "PreToolUse",
    "PostToolUse",
    "UserPromptSubmit",
    "Stop",
    "SessionStart",
    "PreCompact",
    "SubagentStart",
    "SubagentStop",
]

HOOK_MARKER = "-m tend.hook"
STATUSLINE_MARKER = "-m tend.statusline"


class SettingsError(RuntimeError):
    pass


def _load_settings(sp: Path) -> dict:
    if not sp.exists():
        return {}
    try:
        return json.loads(sp.read_text(encoding="utf-8")) or {}
    except json.JSONDecodeError as e:
        raise SettingsError(
            f"{sp} exists but is not valid JSON ({e}). Fix it manually or restore "
            f"{sp.name}.bak-tend before running tend install-hook/uninstall-hook."
        ) from e


def hook_command() -> str:
    return f'"{sys.executable}" {HOOK_MARKER}'


def statusline_command() -> str:
    return f'"{sys.executable}" {STATUSLINE_MARKER}'


def install(settings_path) -> None:
    sp = Path(settings_path).resolve()
    settings = _load_settings(sp)
    hooks = settings.setdefault("hooks", {})
    for ev in HOOK_EVENTS:
        entries = hooks.setdefault(ev, [])
        if not _has_marker(entries, HOOK_MARKER):
            entries.append({"hooks": [{"type": "command", "command": hook_command()}]})
    sl = settings.get("statusLine")
    if sl and STATUSLINE_MARKER not in (sl.get("command") or ""):
        paths.write_json_atomic(paths.home() / "statusline-original.json", sl)
        settings["statusLine"] = {"type": "command", "command": statusline_command()}
    elif not sl:
        settings["statusLine"] = {"type": "command", "command": statusline_command()}
    _write_settings(sp, settings)


def uninstall(settings_path) -> None:
    sp = Path(settings_path).resolve()
    settings = _load_settings(sp)
    changed = False
    hooks = settings.get("hooks", {})
    for ev in list(hooks):
        filtered = [e for e in hooks[ev] if not _has_marker([e], HOOK_MARKER)]
        if len(filtered) != len(hooks[ev]):
            changed = True
            hooks[ev] = filtered
            if not hooks[ev]:
                del hooks[ev]
    sl = settings.get("statusLine") or {}
    if STATUSLINE_MARKER in (sl.get("command") or ""):
        changed = True
        orig = paths.read_json(paths.home() / "statusline-original.json")
        if orig:
            settings["statusLine"] = orig
        else:
            settings.pop("statusLine", None)
    if not changed:
        return
    _write_settings(sp, settings)


def _has_marker(entries, marker) -> bool:
    return any(
        marker in (h.get("command") or "")
        for e in entries
        for h in (e.get("hooks") or [])
    )


def _write_settings(sp, settings) -> None:
    backup = sp.with_name(sp.name + ".bak-tend")
    # Capture file mode if sp exists (for chmod later)
    mode = None
    if sp.exists():
        mode = sp.stat().st_mode
        # Refresh backup with the current (valid) content before overwriting
        current_text = sp.read_text(encoding="utf-8")
        backup.write_text(current_text, encoding="utf-8")
        if mode is not None:
            os.chmod(backup, mode)
    paths.write_json_atomic(sp, settings, indent=2)
    if mode is not None:
        os.chmod(sp, mode)
