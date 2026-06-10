"""Pillar 1: replace oversized tool outputs with head+tail excerpt; full text on disk."""
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
    p = d / f"{n:04d}.txt"
    p.write_text(text)
    p.chmod(0o600)
    return p
