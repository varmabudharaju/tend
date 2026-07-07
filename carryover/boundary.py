"""Stop handler: track STATE.md freshness, detect task boundaries."""
from . import config, flags, ledger, state


def handle(event):
    sid = event.get("session_id")
    if not sid:
        return None
    cwd = event.get("cwd") or "."
    cfg = config.load(cwd)
    summary = ledger.load_summary(sid)
    sp = state.resolve(cwd, sid)
    if sp.exists():
        mtime = sp.stat().st_mtime
        mark = summary.get("state_mark")
        is_update = bool(mark) and mark.get("mtime") != mtime
        if not mark or is_update or "output_total" not in mark:
            ledger.set_state_mark(sid, mtime)
            flags.update(sid, state_reminder=False, boundary=is_update)
        else:
            since = ledger.tokens_since_state_mark(summary)
            flags.update(
                sid,
                state_reminder=since is not None and since > cfg.state_stale_tokens,
                boundary=False,
            )
    else:
        flags.update(
            sid,
            state_reminder=summary.get("output_total", 0) > cfg.state_stale_tokens,
            boundary=False,
        )
    return None
