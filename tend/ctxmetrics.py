"""Read the statusline tee for exact context usage."""
from . import paths


def read_ctx(sid):
    return paths.read_json(paths.session_dir(sid) / "ctx.json")


def used_pct(sid):
    ctx = read_ctx(sid)
    if not ctx:
        return None
    pct = (ctx.get("context_window") or {}).get("used_percentage")
    return float(pct) if pct is not None else None
