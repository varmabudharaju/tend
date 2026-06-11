"""Pillar 4: lossless continuation - restore STATE.md into fresh sessions; seed convention."""
from pathlib import Path

from . import config, state

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
    if event.get("source") not in ("startup", "clear"):
        return None
    cwd = event.get("cwd") or "."
    if Path(cwd).resolve() == Path.home().resolve():
        return None  # never seed the home directory
    cfg = config.load(cwd)
    sp = state.path_for(cwd)
    if not sp.exists():
        state.seed(sp)
        return _ctx(CONVENTION)
    if state.is_fresh(sp, cfg.state_fresh_hours):
        text = sp.read_text(encoding="utf-8")
        if len(text) > MAX_INJECT_CHARS:
            cut = text.rfind("\n", 0, MAX_INJECT_CHARS)
            text = text[: cut if cut > 0 else MAX_INJECT_CHARS]
            text += f"\n[tend] STATE.md truncated for injection - read the rest at {sp}"
        return _ctx(PREAMBLE + text)
    return None


def _ctx(text):
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }
