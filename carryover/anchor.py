"""Pillar 3: small end-of-context anchor, injected only when it meaningfully changes."""
import hashlib
import json

from . import advisor, config, ctxmetrics, flags, ledger, state


def handle(event):
    sid = event.get("session_id")
    if not sid:
        return None
    cwd = event.get("cwd") or "."
    cfg = config.load(cwd)
    summary = ledger.load_summary(sid)
    fl = flags.load(sid)
    sp = state.resolve(cwd, sid)
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
            "STATE.md is stale - update .claude/carryover/STATE.md "
            "(Now/Decisions/Dead-ends) before continuing."
        )
    adv = advisor.advice(pct, cfg, sp, fl)
    if adv:
        lines.append(adv)
    result = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": _fit(lines, cfg.anchor_max_tokens * 4),
        }
    }
    try:
        fp = _fingerprint(goal, now, pct, stale, bloat, fl.get("state_reminder"), adv)
        if _suppress(sid, fl, cfg, fp):
            return None  # an identical anchor is still in context; re-injecting is waste
    except Exception:
        pass  # fail open: a fingerprint/flags hiccup must never drop the anchor
    return result


def _fingerprint(goal, now, pct, stale, bloat, reminder, adv):
    """Stable digest of what the anchor renders. pct/stale/bloat are banded so
    continuous drift alone (a percent here, a few hundred tokens there) does not
    force a fresh injection every prompt."""
    key = [
        goal or "", now or "",
        None if pct is None else int(pct // 10),
        (stale or 0) // 5000, (bloat or 0) // 5000,
        bool(reminder), adv or "",
    ]
    return hashlib.sha256(json.dumps(key).encode("utf-8")).hexdigest()


def _suppress(sid, fl, cfg, fp) -> bool:
    """True => inject nothing this turn. The full anchor is re-sent when the
    fingerprint changes or once every cfg.anchor_refresh_turns prompts (1 = always)."""
    since = int(fl.get("anchor_since_full", 0)) + 1
    if fp == fl.get("anchor_fp") and since < cfg.anchor_refresh_turns:
        flags.update(sid, anchor_since_full=since)
        return True
    flags.update(sid, anchor_fp=fp, anchor_since_full=0)
    return False


def _render(lines):
    return "[carryover anchor]\n" + "\n".join(lines)


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
