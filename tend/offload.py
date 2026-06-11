"""Pillar 1: replace oversized tool outputs with head+tail excerpt; full text on disk."""
import os

from . import config, paths, tokens


def handle(event):
    cfg = config.load(event.get("cwd"))
    tool = event.get("tool_name") or ""
    if tool not in cfg.offload_tools:
        return None
    raw = event.get("tool_response", event.get("tool_result", ""))
    if tool.startswith("mcp__") and not isinstance(raw, str):
        # Structured MCP outputs may carry an outputSchema; Claude Code silently
        # rejects a plain-text replacement, so offloading would save nothing.
        return None
    text = tokens.to_text(raw)
    n = tokens.estimate(text)
    if n < cfg.offload_threshold_tokens:
        return None
    head = text[: cfg.offload_head_tokens * 4] if cfg.offload_head_tokens else ""
    tail = text[-cfg.offload_tail_tokens * 4 :] if cfg.offload_tail_tokens else ""
    if len(head) + len(tail) >= len(text):
        return None
    path = _save(event.get("session_id", "unknown"), text)
    omitted = max(0, n - cfg.offload_head_tokens - cfg.offload_tail_tokens)
    excerpt = (
        f"{head}\n\n[tend: ~{omitted} tokens offloaded]\n\n{tail}\n\n"
        f"[tend] Full output saved to {path} - Read it (with offset/limit) only if needed."
    )
    if len(excerpt) >= len(text):
        os.unlink(path)  # banner overhead would inflate, not shrink
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "updatedToolOutput": excerpt,
        }
    }


def _save(sid, text):
    d = paths.session_dir(sid) / "outputs"
    d.mkdir(parents=True, exist_ok=True)
    n = len(list(d.glob("*.txt"))) + 1
    while True:
        p = d / f"{n:04d}.txt"
        try:
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError:
            n += 1
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return p
