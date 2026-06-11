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
    stale = ledger.stale_tokens(summary)
    bloat = ledger.bloat_tokens(summary, cfg.offload_threshold_tokens)

    if not goal and not now and pct is None and not stale and not bloat \
            and not fl.get("state_reminder"):
        return None

    lines = []
    if goal:
        lines.append(f"Goal: {advisor.clip(goal)}")
    if now:
        lines.append(f"Now: {advisor.clip(now)}")
    lines.append(_health_line(pct, stale, bloat))
    if fl.get("state_reminder"):
        lines.append(
            "STATE.md is stale - update .claude/tend/STATE.md "
            "(Now/Decisions/Dead-ends) before continuing."
        )
    adv = advisor.advice(pct, cfg, sp, fl)
    if adv:
        lines.append(adv)
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": _fit(lines, cfg.anchor_max_tokens * 4),
        }
    }


def _render(lines):
    return "[tend anchor]\n" + "\n".join(lines)


def _fit(lines, budget):
    """Later lines (health, staleness, compaction urge) outrank Goal/Now: when over
    budget, drop whole lines from the front, never truncate the tail."""
    out = list(lines)
    while len(out) > 1 and len(_render(out)) > budget:
        out.pop(0)
    return _render(out)[:budget]


def _health_line(pct, stale, bloat):
    parts = [f"context {pct:.0f}% used" if pct is not None else "context usage unknown"]
    if stale:
        parts.append(f"~{stale:,} tok of stale tool results")
    if bloat:
        parts.append(f"~{bloat:,} tok in oversized results")
    return "Health: " + ", ".join(parts)
