"""Merge tend into ~/.claude/settings.json non-destructively; reversible."""
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


def hook_command() -> str:
    return f"{sys.executable} {HOOK_MARKER}"


def statusline_command() -> str:
    return f"{sys.executable} {STATUSLINE_MARKER}"


def install(settings_path) -> None:
    sp = Path(settings_path)
    settings = paths.read_json(sp, {}) or {}
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
    sp = Path(settings_path)
    settings = paths.read_json(sp, {}) or {}
    hooks = settings.get("hooks", {})
    for ev in list(hooks):
        hooks[ev] = [e for e in hooks[ev] if not _has_marker([e], HOOK_MARKER)]
        if not hooks[ev]:
            del hooks[ev]
    sl = settings.get("statusLine") or {}
    if STATUSLINE_MARKER in (sl.get("command") or ""):
        orig = paths.read_json(paths.home() / "statusline-original.json")
        if orig:
            settings["statusLine"] = orig
        else:
            settings.pop("statusLine", None)
    _write_settings(sp, settings)


def _has_marker(entries, marker) -> bool:
    return any(
        marker in (h.get("command") or "")
        for e in entries
        for h in (e.get("hooks") or [])
    )


def _write_settings(sp, settings) -> None:
    backup = sp.with_name(sp.name + ".bak-tend")
    if sp.exists() and not backup.exists():
        backup.write_text(sp.read_text())
    paths.write_json_atomic(sp, settings, indent=2)
