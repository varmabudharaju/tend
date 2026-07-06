"""Pillar 1: replace oversized tool outputs with head+tail excerpt; full text on disk."""
import json
import os
import time

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
    sid = event.get("session_id", "unknown")
    path = _save(sid, text)
    omitted = max(0, n - cfg.offload_head_tokens - cfg.offload_tail_tokens)
    excerpt = (
        f"{head}\n\n[tend: ~{omitted} tokens offloaded]\n\n{tail}\n\n"
        f"[tend] Full output saved to {path} - Read it (with offset/limit) "
        f"or search filed outputs with `tend find <regex>`."
    )
    if len(excerpt) >= len(text):
        os.unlink(path)  # banner overhead would inflate, not shrink
        return None
    try:
        _index_append(sid, path.name, tool, n, text)
    except Exception:
        pass  # index is advisory: never let it break offloading (fail-open)
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


def _index_path(sid):
    return paths.session_dir(sid) / "outputs" / "index.jsonl"


def _hint(text):
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s[:80]
    return ""


def _index_append(sid, filename, tool, tokens_, text) -> None:
    """Append one newline-terminated JSON record via a single O_APPEND write."""
    line = json.dumps(
        {"file": filename, "ts": time.time(), "tool": tool,
         "tokens": tokens_, "hint": _hint(text)},
        ensure_ascii=False,
    ) + "\n"
    fd = os.open(_index_path(sid), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def read_index(sid) -> list:
    """Parsed index records. Drops a torn trailing line (no newline) and any
    line that fails to parse — same partial-line guard as the ledger."""
    try:
        data = _index_path(sid).read_bytes()
    except OSError:
        return []
    nl = data.rfind(b"\n")
    if nl < 0:
        return []
    out = []
    for raw in data[: nl + 1].splitlines():
        try:
            obj = json.loads(raw.decode("utf-8"))
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out
