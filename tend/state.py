"""STATE.md: the session's external source of truth, maintained by Claude."""
import time
from pathlib import Path

TEMPLATE = """# Session state

## Goal
(What this session is building - one paragraph. Keep stable.)

## Now
(Current step. Update often.)

## Decisions
(Settled choices. Append-only.)

## Dead-ends
(Approaches tried and abandoned, with why. Do NOT retry these.)

## Files touched
(path - one line on what/why)
"""


def path_for(cwd) -> Path:
    return Path(cwd) / ".claude" / "tend" / "STATE.md"


def seed(path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(TEMPLATE)


def read_sections(path) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    sections, current = {}, None
    for line in path.read_text().splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def goal_now(path):
    s = read_sections(path)

    def first_line(text):
        for ln in (text or "").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("("):
                return ln
        return ""

    return first_line(s.get("Goal")), first_line(s.get("Now"))


def is_fresh(path, hours) -> bool:
    path = Path(path)
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < hours * 3600
