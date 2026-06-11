"""Pillar 1c: advisory model-tier nudge for subagent spawns. Never blocks."""
from . import config, ctxmetrics

SPAWN_TOOLS = {"Task", "Agent"}

LADDER_TEXT = (
    "Pick the lowest tier that fits: haiku = mechanical (verify outputs/extract/"
    "format/capture); sonnet = clear-goal bounded work (scan/review/simple edits); "
    "opus = real coding; inherit = design/synthesis/judgment."
)


def handle(event):
    if event.get("tool_name") not in SPAWN_TOOLS:
        return None
    cfg = config.load(event.get("cwd"))
    if not cfg.delegation_guard:
        return None
    if (event.get("tool_input") or {}).get("model"):
        return None
    tier = ctxmetrics.session_model_tier(event.get("session_id"))
    if tier == "haiku":
        return None  # already the floor; nothing to save
    inherit = tier or "the session model"
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"[tend] This subagent has no model set - it will inherit {inherit}. "
                + LADDER_TEXT
            ),
        }
    }
