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
    "state_stale_tokens": 25000,
    "state_fresh_hours": 48,
    "advise_pct": 55,
    "urge_pct": 70,
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


def load(cwd=None) -> Config:
    data = dict(DEFAULTS)
    candidates = [paths.home() / "config.yaml"]
    if cwd:
        candidates.append(Path(cwd) / ".claude" / "tend" / "config.yaml")
    for p in candidates:
        if p.is_file():
            import yaml  # lazy: keeps hook startup fast when no config exists

            loaded = yaml.safe_load(p.read_text()) or {}
            data.update({k: v for k, v in loaded.items() if k in DEFAULTS})
    if isinstance(data["offload_tools"], str):
        data["offload_tools"] = [data["offload_tools"]]
    data["offload_tools"] = tuple(data["offload_tools"])
    return Config(**data)
