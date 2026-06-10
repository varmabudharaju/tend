"""Pillar 1: replace oversized tool outputs with head+tail excerpt; full text on disk."""
import os

from . import config, paths, tokens


def handle(event):
    cfg = config.load(event.get("cwd"))
    if event.get("tool_name") not in cfg.offload_tools:
        return None
    raw = event.get("tool_response", event.get("tool_result", ""))
    text = tokens.to_text(raw)
    n = tokens.estimate(text)
    if n < cfg.offload_threshold_tokens:
        return None
    if (cfg.offload_head_tokens + cfg.offload_tail_tokens) * 4 >= len(text):
        return None
    path = _save(event.get("session_id", "unknown"), text)
    head = text[: cfg.offload_head_tokens * 4]
    tail = text[-cfg.offload_tail_tokens * 4 :]
    omitted = max(0, n - cfg.offload_head_tokens - cfg.offload_tail_tokens)
    excerpt = (
        f"{head}\n\n[tend: ~{omitted} tokens offloaded]\n\n{tail}\n\n"
        f"[tend] Full output saved to {path} - Read it (with offset/limit) only if needed."
    )
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
