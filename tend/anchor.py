"""Pillar 3: small end-of-context anchor injected on every user prompt."""
from . import advisor, config, ctxmetrics, flags, ledger, state


def handle(event):
    sid = event.get("session_id")
    if not sid:
        return None
    cwd = event.get("cwd") or "."
    cfg = config.load(cwd)
    summary = ledger.load_summary(sid)
    fl = flags.load(sid)
    sp = state.path_for(cwd)
    goal, now = state.goal_now(sp)
    pct = ctxmetrics.used_pct(sid)

    lines = []
    if goal:
        lines.append(f"Goal: {goal}")
    if now:
        lines.append(f"Now: {now}")
    lines.append(_health_line(pct, summary))
    if fl.get("state_reminder"):
        lines.append(
            "STATE.md is stale - update .claude/tend/STATE.md "
            "(Now/Decisions/Dead-ends) before continuing."
        )
    adv = advisor.advice(pct, cfg, sp, fl)
    if adv:
        lines.append(adv)
    text = "[tend anchor]\n" + "\n".join(lines)
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": text[: cfg.anchor_max_tokens * 4],
        }
    }


def _health_line(pct, summary):
    parts = [f"context {pct:.0f}% used" if pct is not None else "context usage unknown"]
    st = ledger.stale_tokens(summary)
    if st:
        parts.append(f"~{st:,} tok of stale tool results")
    return "Health: " + ", ".join(parts)
