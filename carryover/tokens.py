"""Cheap token estimation: ~4 chars per token. Exact counts come from transcripts."""
import json


def to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("stdout"), str):
        # Command-style payload (Bash et al.): render the streams themselves so
        # offloaded files stay line-addressable for Read offset/limit.
        text = value["stdout"]
        err = value.get("stderr")
        if isinstance(err, str) and err.strip():
            if text and not text.endswith("\n"):
                text += "\n"
            text += "--- stderr ---\n" + err
        return text
    try:
        return json.dumps(value, indent=2, ensure_ascii=False)
    except Exception:
        return str(value)


def estimate(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)
