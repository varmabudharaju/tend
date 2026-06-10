"""Pillar 4 safety net: snapshot before compaction; block a stale auto-compact once."""
import time

from . import config, ctxmetrics, flags, ledger, paths, state

BLOCK_REASON = (
    "tend: STATE.md is stale. Update .claude/tend/STATE.md (Goal/Now/Decisions/Dead-ends), "
    "then run /compact. This block fires only once."
)


def handle(event):
    sid = event.get("session_id")
    if not sid:
        return None
    cfg = config.load(event.get("cwd"))
    _snapshot(sid)
    if event.get("trigger") == "auto":
        fl = flags.load(sid)
        if not fl.get("blocked_once") and _is_stale(event, cfg):
            fl["blocked_once"] = True
            flags.save(sid, fl)
            return {"decision": "block", "reason": BLOCK_REASON}
    return None


def _is_stale(event, cfg) -> bool:
    sp = state.path_for(event.get("cwd") or ".")
    if not sp.exists():
        return True
    summary = ledger.load_summary(event.get("session_id"))
    mark = summary.get("state_mark")
    if mark and mark.get("mtime") != sp.stat().st_mtime:
        return False  # updated since our last mark: fresh
    since = ledger.tokens_since_state_mark(summary)
    return since is not None and since > cfg.state_stale_tokens


def _snapshot(sid) -> None:
    snap = {
        "summary": ledger.load_summary(sid),
        "ctx": ctxmetrics.read_ctx(sid),
        "ts": time.time(),
    }
    paths.write_json_atomic(paths.session_dir(sid) / f"precompact-{int(time.time())}.json", snap)
