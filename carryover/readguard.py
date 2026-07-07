"""Pillar 1b: nudge (never block) unbounded Reads of large files."""
import os

from . import config


def handle(event):
    if event.get("tool_name") != "Read":
        return None
    ti = event.get("tool_input") or {}
    if "limit" in ti or "offset" in ti:
        return None
    fp = ti.get("file_path")
    if not fp or not os.path.isfile(fp):
        return None
    cfg = config.load(event.get("cwd"))
    try:
        size = os.path.getsize(fp)
    except OSError:
        return None
    if size <= cfg.read_guard_bytes:
        return None
    try:
        with open(fp, "rb") as fh:
            if b"\0" in fh.read(4096):
                return None  # binary: token math and offset/limit advice don't apply
    except OSError:
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"[carryover] {fp} is ~{size // 4:,} tokens. Prefer Read with offset/limit on the "
                "relevant range, or delegate scanning to an Explore subagent, instead of "
                "loading the whole file into context."
            ),
        }
    }
