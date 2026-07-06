"""STATE.md: the session's external source of truth, maintained by Claude."""
import os
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


def resolve(cwd, sid=None) -> Path:
    """STATE.md path, robust to mid-session cwd drift (U2). See resolve_root."""
    return path_for(resolve_root(cwd, sid))


def resolve_root(cwd, sid=None) -> Path:
    """Project root for STATE.md, resolved in priority order and always fail-open:
    1. the session's pinned project root (if it still exists),
    2. the nearest ancestor of cwd holding .claude/tend/STATE.md, not walking past a
       .git boundary nor above $HOME,
    3. the event cwd itself (current behaviour)."""
    try:
        if sid:
            from . import flags
            pinned = flags.load(sid).get("project_root")
            if pinned and Path(pinned).is_dir():
                return Path(pinned)
        found = _ancestor_with_state(cwd)
        if found is not None:
            return found
    except Exception:
        pass
    return Path(cwd)


def _ancestor_with_state(cwd):
    try:
        cur = Path(cwd).resolve()
        home = Path.home().resolve()
    except OSError:
        return None
    while True:
        if (cur / ".claude" / "tend" / "STATE.md").is_file():
            return cur
        if cur == home or (cur / ".git").exists():
            return None  # project/home boundary: never adopt state from across it
        parent = cur.parent
        if parent == cur:
            return None  # filesystem root
        cur = parent


def seed(path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        return  # another session seeded first; theirs wins
    except OSError:
        return
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(TEMPLATE)


def read_sections(path) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    sections, current = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
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
