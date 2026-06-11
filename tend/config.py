"""Config: baked defaults < ~/.claude/tend/config.yaml < <project>/.claude/tend/config.yaml."""
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
    "state_stale_tokens": 3000,  # OUTPUT tokens since the last STATE.md mark (monotonic)
    "state_fresh_hours": 48,
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
    state_stale_tokens: int
    state_fresh_hours: int
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


def load(cwd=None) -> Config:
    data = dict(DEFAULTS)
    candidates = [paths.home() / "config.yaml"]
    if cwd:
        candidates.append(Path(cwd) / ".claude" / "tend" / "config.yaml")
    for p in candidates:
        if not p.is_file():
            continue
        import yaml  # lazy: keeps hook startup fast when no config exists

        try:
            loaded = yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception:
            continue  # unparseable config must never kill the hooks
        if not isinstance(loaded, dict):
            continue
        for k, v in loaded.items():
            if k in DEFAULTS:
                v = _coerce(k, v)
                if v is not None:
                    data[k] = v
    data["offload_tools"] = tuple(data["offload_tools"])
    return Config(**data)
