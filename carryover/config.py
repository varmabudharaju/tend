"""Config: baked defaults < ~/.claude/carryover/config.yaml < <project>/.claude/carryover/config.yaml."""
from dataclasses import dataclass
from pathlib import Path

from . import paths

DEFAULTS = {
    "offload_threshold_tokens": 2500,
    "offload_tools": ["Bash", "Grep", "Glob", "WebFetch"],
    "offload_head_tokens": 600,
    "offload_tail_tokens": 600,
    "read_guard_bytes": 65536,
    "anchor_max_tokens": 400,
    "anchor_refresh_turns": 8,  # re-inject an unchanged anchor at most once every N prompts; 1 = every prompt
    "state_stale_tokens": 3000,  # OUTPUT tokens since the last STATE.md mark (monotonic)
    "state_fresh_hours": 48,
    "retention_days": 30,  # sweep sessions/<id> older than this at SessionStart; 0 disables
    "advise_pct": 55,
    "urge_pct": 70,
    "delegation_guard": True,
}


@dataclass(frozen=True)
class Config:
    offload_threshold_tokens: int
    offload_tools: tuple
    offload_head_tokens: int
    offload_tail_tokens: int
    read_guard_bytes: int
    anchor_max_tokens: int
    anchor_refresh_turns: int
    state_stale_tokens: int
    state_fresh_hours: int
    retention_days: int
    advise_pct: float
    urge_pct: float
    delegation_guard: bool


def _coerce(key, value):
    """Return a usable value for key, or None to keep the current/default value."""
    if key == "offload_tools":
        if isinstance(value, str):
            return [value]
        if isinstance(value, list) and all(isinstance(t, str) for t in value):
            return value  # [] is legal: disables offloading
        return None
    if key == "anchor_refresh_turns":
        if isinstance(value, bool):
            return None
        try:
            n = int(value)
        except (TypeError, ValueError):
            return None
        return n if n >= 1 else None  # must be a positive whole number of turns
    if isinstance(DEFAULTS[key], bool):
        return value if isinstance(value, bool) else None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value if value >= 0 else None
    if isinstance(value, str):
        try:
            return _coerce(key, int(value))
        except ValueError:
            try:
                return _coerce(key, float(value))
            except ValueError:
                return None
    return None


def _parse_value(v: str):
    if v == "":
        return None
    if v.startswith("["):
        if not v.endswith("]"):
            return v  # malformed: _coerce will reject it
        return [i.strip().strip("'\"") for i in v[1:-1].split(",") if i.strip()]
    if v.lower() in ("true", "yes", "on"):
        return True
    if v.lower() in ("false", "no", "off"):
        return False
    s = v.strip("'\"")
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return s


def _parse_config(text: str) -> dict:
    """Flat `key: value` parser (a YAML subset). carryover's whole config is flat
    scalars and string lists; stdlib-only keeps the plugin dependency-free."""
    data = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        if not k or " " in k:
            continue
        data[k] = _parse_value(v.strip())
    return data


def load(cwd=None) -> Config:
    data = dict(DEFAULTS)
    candidates = [paths.home() / "config.yaml"]
    if cwd:
        candidates.append(Path(cwd) / ".claude" / "carryover" / "config.yaml")
    for p in candidates:
        if not p.is_file():
            continue
        try:
            loaded = _parse_config(p.read_text(encoding="utf-8"))
        except Exception:
            continue  # unreadable config must never kill the hooks
        for k, v in loaded.items():
            if k in DEFAULTS:
                v = _coerce(k, v)
                if v is not None:
                    data[k] = v
    data["offload_tools"] = tuple(data["offload_tools"])
    return Config(**data)
