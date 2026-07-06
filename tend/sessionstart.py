"""Pillar 4: lossless continuation - restore STATE.md into fresh sessions; seed convention."""
from pathlib import Path

from . import config, flags, retention, state

CONVENTION = (
    "[tend] This project uses .claude/tend/STATE.md as the session's external state file "
    "(template just created). Maintain it as you work: Goal (stable), Now (current step), "
    "Decisions (append-only), Dead-ends (failed approaches - never retry), Files touched. "
    "Update it whenever you finish a step or make a decision; it survives compaction and "
    "new sessions."
)

PREAMBLE = (
    "[tend] State restored from previous session (.claude/tend/STATE.md below). "
    "Verify 'Files touched' against current disk before relying on it.\n\n"
)

MAX_INJECT_CHARS = 16000


def handle(event):
    sid = event.get("session_id")
    _pin_project_root(event.get("cwd"), sid, event.get("source"))
    if event.get("source") not in ("startup", "clear"):
        return None
    cwd = event.get("cwd") or "."
    cfg = config.load(cwd)
    retention.maybe_sweep(cfg.retention_days)  # never raises; never blocks restore
    if Path(cwd).resolve() == Path.home().resolve():
        return None  # never seed the home directory
    sp = state.resolve(cwd, sid)
    if not sp.exists():
        state.seed(sp)
        return _ctx(CONVENTION, f"tend: seeded {_rel(sp, cwd)} - Claude will maintain it")
    if state.is_fresh(sp, cfg.state_fresh_hours):
        text = sp.read_text(encoding="utf-8")
        if len(text) > MAX_INJECT_CHARS:
            cut = text.rfind("\n", 0, MAX_INJECT_CHARS)
            text = text[: cut if cut > 0 else MAX_INJECT_CHARS]
            text += f"\n[tend] STATE.md truncated for injection - read the rest at {sp}"
        return _ctx(PREAMBLE + text,
                    f"tend: restored session state from STATE.md ({len(text.splitlines())} lines)")
    return None


def _pin_project_root(cwd, sid, source=None) -> None:
    """Pin the session's project root so later hooks survive a persistent cd (U2).
    A compact fires mid-session with a possibly-drifted cwd: never overwrite an
    existing pin there, only fill a missing one."""
    if not cwd or not sid:
        return
    try:
        if source == "compact" and flags.load(sid).get("project_root"):
            return
        flags.update(sid, project_root=str(Path(cwd).resolve()))
    except Exception:
        pass  # fail-open: a missed pin only forgoes drift protection


def _rel(sp, cwd):
    try:
        return sp.relative_to(cwd)
    except ValueError:
        return sp


def _ctx(text, note=None):
    out = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }
    if note:
        out["systemMessage"] = note  # the one user-visible line per session
    return out
