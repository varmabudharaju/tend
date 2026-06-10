"""Incremental transcript ledger: exact context totals, tool-result sizes, staleness."""
import json
from pathlib import Path

from . import paths, tokens

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def _cursor_path(sid):
    return paths.session_dir(sid) / "cursor.json"


def _summary_path(sid):
    return paths.session_dir(sid) / "summary.json"


def _empty():
    return {
        "context_total": 0,
        "output_total": 0,
        "results": {},
        "reads": {},
        "pending": {},
        "agents": {},
        "state_mark": None,
        "degraded": False,
    }


def load_summary(sid) -> dict:
    return paths.read_json(_summary_path(sid), _empty())


def ingest(event) -> None:
    sid = event.get("session_id")
    tp = event.get("transcript_path")
    if not sid or not tp or not Path(tp).exists():
        return
    cur = paths.read_json(_cursor_path(sid), {"offset": 0})
    summary = load_summary(sid)
    with open(tp, "r", encoding="utf-8") as f:
        f.seek(cur["offset"])
        for line in f:
            _ingest_line(summary, line)
        cur["offset"] = f.tell()
    paths.write_json_atomic(_summary_path(sid), summary)
    paths.write_json_atomic(_cursor_path(sid), cur)


def _ingest_line(summary, line) -> None:
    line = line.strip()
    if not line:
        return
    try:
        obj = json.loads(line)
    except Exception:
        summary["degraded"] = True
        return
    msg = obj.get("message") or {}
    usage = msg.get("usage") or {}
    if usage:
        total = (
            usage.get("input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
        )
        if total:
            summary["context_total"] = total
        summary["output_total"] = summary.get("output_total", 0) + usage.get("output_tokens", 0)
    content = msg.get("content")
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "tool_use":
            fp = (block.get("input") or {}).get("file_path")
            summary["pending"][block.get("id")] = {"tool": block.get("name"), "file": fp}
            if block.get("name") in EDIT_TOOLS and fp:
                for rid in summary["reads"].get(fp, []):
                    if rid in summary["results"]:
                        summary["results"][rid]["stale"] = True
        elif btype == "tool_result":
            tid = block.get("tool_use_id")
            meta = summary["pending"].pop(tid, {"tool": None, "file": None})
            size = tokens.estimate(tokens.to_text(block.get("content")))
            summary["results"][tid] = {
                "tool": meta["tool"],
                "tokens": size,
                "file": meta["file"],
                "stale": False,
            }
            if meta["tool"] == "Read" and meta["file"]:
                summary["reads"].setdefault(meta["file"], []).append(tid)


def set_state_mark(sid, mtime) -> None:
    s = load_summary(sid)
    s["state_mark"] = {"mtime": mtime, "context_total": s.get("context_total", 0)}
    paths.write_json_atomic(_summary_path(sid), s)


def tokens_since_state_mark(summary):
    mark = summary.get("state_mark")
    if not mark:
        return None
    return summary.get("context_total", 0) - mark.get("context_total", 0)


def top_results(summary, n=5):
    items = [dict(id=k, **v) for k, v in summary.get("results", {}).items()]
    return sorted(items, key=lambda r: r["tokens"], reverse=True)[:n]


def stale_tokens(summary) -> int:
    return sum(r["tokens"] for r in summary.get("results", {}).values() if r.get("stale"))


def record_agent(event) -> None:
    sid = event.get("session_id")
    aid = event.get("agent_id")
    if not sid or not aid:
        return
    s = load_summary(sid)
    rec = s["agents"].setdefault(aid, {"type": None, "stopped": False})
    if event.get("hook_event_name") == "SubagentStart":
        rec["type"] = event.get("agent_type")
    else:
        rec["stopped"] = True
    paths.write_json_atomic(_summary_path(sid), s)
