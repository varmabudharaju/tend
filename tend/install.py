"""Merge tend into ~/.claude/settings.json non-destructively; reversible."""
import json
import os
import stat
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
        loaded = json.loads(sp.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SettingsError(
            f"{sp} exists but is not valid JSON ({e}). Fix it manually or restore "
            f"{sp.name}.bak-tend before running tend install-hook/uninstall-hook."
        ) from e
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise SettingsError(
            f"{sp} must contain a JSON object at the top level, "
            f"not {type(loaded).__name__}."
        )
    return loaded


def hook_command() -> str:
    return f'"{sys.executable}" {HOOK_MARKER}'


def statusline_command() -> str:
    return f'"{sys.executable}" {STATUSLINE_MARKER}'


def install(settings_path) -> None:
    sp = Path(settings_path).resolve()
    settings = _load_settings(sp)
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = settings["hooks"] = {}
    for ev in HOOK_EVENTS:
        entries = hooks.get(ev)
        if not isinstance(entries, list):
            entries = hooks[ev] = []
        if not _refresh_marked(entries, HOOK_MARKER, hook_command()):
            entries.append({"hooks": [{"type": "command", "command": hook_command()}]})
    _wrap_statusline(settings)
    _write_settings(sp, settings)


def wrap_statusline(settings_path) -> None:
    """Statusline wrap only (no hooks) - the optional step for plugin installs,
    where hooks come from the plugin but the statusline tee needs settings.json."""
    sp = Path(settings_path).resolve()
    settings = _load_settings(sp)
    _wrap_statusline(settings)
    _write_settings(sp, settings)


def _wrap_statusline(settings) -> None:
    sl = settings.get("statusLine")
    if sl and not _is_tend_statusline(sl):
        paths.write_json_atomic(paths.home() / "statusline-original.json", sl)
    # Never delete a saved original here: after an external removal of our
    # wrapper it can be the only copy of the user's statusline.
    settings["statusLine"] = {"type": "command", "command": statusline_command()}


def uninstall(settings_path) -> None:
    sp = Path(settings_path).resolve()
    settings = _load_settings(sp)
    changed = False
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    for ev in list(hooks):
        if not isinstance(hooks[ev], list):
            continue
        pruned, ev_changed = _prune_entries(hooks[ev])
        if ev_changed:
            changed = True
            if pruned:
                hooks[ev] = pruned
            else:
                del hooks[ev]
    sl = settings.get("statusLine")
    if _is_tend_statusline(sl):
        changed = True
        orig = paths.read_json(paths.home() / "statusline-original.json")
        if orig:
            settings["statusLine"] = orig
        else:
            settings.pop("statusLine", None)
        (paths.home() / "statusline-original.json").unlink(missing_ok=True)
    if not changed:
        return
    _write_settings(sp, settings)


def _prune_entries(entries):
    """Remove tend's inner hook commands; drop an entry only when emptied (M10)."""
    pruned, changed = [], False
    for e in entries:
        inner = e.get("hooks") if isinstance(e, dict) else None
        if not isinstance(inner, list):
            pruned.append(e)
            continue
        kept = [h for h in inner
                if not (isinstance(h, dict) and HOOK_MARKER in (h.get("command") or ""))]
        if len(kept) == len(inner):
            pruned.append(e)
            continue
        changed = True
        if kept:
            pruned.append({**e, "hooks": kept})
    return pruned, changed


def _refresh_marked(entries, marker, command) -> bool:
    """Repoint existing tend hooks at the current interpreter; True if any found (M11)."""
    found = False
    for e in entries:
        if not isinstance(e, dict):
            continue
        for h in e.get("hooks") or []:
            if isinstance(h, dict) and marker in (h.get("command") or ""):
                h["command"] = command
                found = True
    return found


def _is_tend_statusline(sl) -> bool:
    return isinstance(sl, dict) and STATUSLINE_MARKER in (sl.get("command") or "")


def _write_settings(sp, settings) -> None:
    backup = sp.with_name(sp.name + ".bak-tend")
    mode = None
    if sp.exists():
        mode = stat.S_IMODE(sp.stat().st_mode)
        current_text = sp.read_text(encoding="utf-8")
        # Born with the source's mode: no window where 0600 content sits at 0644 (L17)
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            os.fchmod(fd, mode)  # O_CREAT mode is masked by umask; pin it exactly
            f.write(current_text)
    paths.write_json_atomic(sp, settings, indent=2, mode=mode)
