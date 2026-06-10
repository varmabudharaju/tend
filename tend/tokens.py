"""Cheap token estimation: ~4 chars per token. Exact counts come from transcripts."""
import json


def to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value)
    except Exception:
        return str(value)


def estimate(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)
