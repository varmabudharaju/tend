"""Pillar 4: when and how to recommend a curated /compact."""
from . import state

MAX_LINE_CHARS = 200


def clip(s):
    return s if len(s) <= MAX_LINE_CHARS else s[: MAX_LINE_CHARS - 1] + "…"


def level(pct, cfg):
    if pct is None:
        return None
    if pct >= cfg.urge_pct:
        return "urge"
    if pct >= cfg.advise_pct:
        return "advise"
    return None


def compact_instructions(state_path) -> str:
    base = (
        "preserve the Goal, Now and Decisions from .claude/tend/STATE.md and the intent of "
        "the current change; drop exploration detail, raw tool outputs and dead-end attempts "
        "(they are recorded in STATE.md)"
    )
    goal, _ = state.goal_now(state_path)
    return f"{base}. Goal: {clip(goal)}" if goal else base


def advice(pct, cfg, state_path, fl):
    lv = level(pct, cfg)
    if lv is None:
        return None
    instr = compact_instructions(state_path)
    if lv == "urge":
        return f"Context at {pct:.0f}% - run now: /compact {instr}"
    if fl.get("boundary"):
        return f"Task boundary and context at {pct:.0f}% - good moment for: /compact {instr}"
    return f"Context at {pct:.0f}% - at the next task boundary, run: /compact {instr}"
