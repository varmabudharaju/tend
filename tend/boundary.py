"""Stop handler: track STATE.md freshness, detect task boundaries."""
from . import config, flags, ledger, state


def handle(event):
    sid = event.get("session_id")
    if not sid:
        return None
    cwd = event.get("cwd") or "."
    cfg = config.load(cwd)
    summary = ledger.load_summary(sid)
    fl = flags.load(sid)
    sp = state.path_for(cwd)
    if sp.exists():
        mtime = sp.stat().st_mtime
        mark = summary.get("state_mark")
        if not mark or mark.get("mtime") != mtime:
            ledger.set_state_mark(sid, mtime)
            fl["state_reminder"] = False
            fl["boundary"] = True
        else:
            since = ledger.tokens_since_state_mark(summary)
            fl["state_reminder"] = since is not None and since > cfg.state_stale_tokens
            fl["boundary"] = False
    else:
        fl["state_reminder"] = summary.get("context_total", 0) > cfg.state_stale_tokens
        fl["boundary"] = False
    flags.save(sid, fl)
    return None
