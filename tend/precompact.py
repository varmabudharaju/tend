"""Pillar 4 safety net: snapshot before compaction; block a stale auto-compact once."""
import time
from pathlib import Path

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
    _snapshot(sid, event.get("cwd"))
    flags.update(sid, anchor_fp=None)  # post-compaction context needs a fresh anchor
    if event.get("trigger") == "auto":
        fl = flags.load(sid)
        if not fl.get("blocked_once") and _is_stale(event, cfg):
            flags.update(sid, blocked_once=True)
            return {"decision": "block", "reason": BLOCK_REASON}
    return None


def _is_stale(event, cfg) -> bool:
    sid = event.get("session_id")
    root = state.resolve_root(event.get("cwd") or ".", sid)
    if root.resolve() == Path.home().resolve():
        return False  # $HOME is never seeded (see sessionstart); never block there
    sp = state.path_for(root)
    if not sp.exists():
        return True
    summary = ledger.load_summary(sid)
    mark = summary.get("state_mark")
    if mark and mark.get("mtime") != sp.stat().st_mtime:
        return False  # updated since our last mark: fresh
    # No mark ever set (no Stop yet): tokens_since returns None -> treat as not stale.
    since = ledger.tokens_since_state_mark(summary)
    return since is not None and since > cfg.state_stale_tokens


def _snapshot(sid, cwd) -> None:
    snap = {
        "summary": ledger.load_summary(sid),
        "ctx": ctxmetrics.read_ctx(sid),
        "ts": time.time(),
    }
    try:  # STATE.md capture is best-effort: a bad read must not lose the snapshot
        sp = state.path_for(cwd)
        snap["cwd"] = str(cwd)
        snap["state_path"] = str(sp)
        snap["state_sections"] = state.read_sections(sp)
    except Exception:
        pass
    paths.write_json_atomic(paths.session_dir(sid) / f"precompact-{time.time_ns()}.json", snap)
