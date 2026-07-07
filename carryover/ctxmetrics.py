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


TIERS = ("haiku", "sonnet", "opus", "fable")


def session_model_tier(sid):
    """Best-effort tier of the session's model, from the statusline tee."""
    ctx = read_ctx(sid) or {}
    name = ((ctx.get("model") or {}).get("display_name") or "").lower()
    for tier in TIERS:
        if tier in name:
            return tier
    return None
