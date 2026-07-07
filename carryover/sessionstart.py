"""Pillar 4: lossless continuation - restore STATE.md into fresh sessions; seed convention."""
from pathlib import Path

from . import config, flags, paths, retention, state

CONVENTION = (
    "[carryover] This project uses .claude/carryover/STATE.md as the session's external state file "
    "(template just created). Maintain it as you work: Goal (stable), Now (current step), "
    "Decisions (append-only), Dead-ends (failed approaches - never retry), Files touched. "
    "Update it whenever you finish a step or make a decision; it survives compaction and "
    "new sessions."
)

PREAMBLE = (
    "[carryover] State restored from previous session (.claude/carryover/STATE.md below). "
    "Verify 'Files touched' against current disk before relying on it.\n\n"
)

MAX_INJECT_CHARS = 16000

COMPACT_PREAMBLE = (
    "[carryover] Context was just compacted. Durable state below survived on disk "
    "(.claude/carryover/STATE.md); filed outputs and snapshots are under {sdir}.\n\n"
)

MAX_COMPACT_CHARS = 8000
COMPACT_ORDER = ("Goal", "Now", "Decisions", "Dead-ends", "Files touched")


def handle(event):
    sid = event.get("session_id")
    _pin_project_root(event.get("cwd"), sid, event.get("source"))
    if sid:
        flags.update(sid, anchor_fp=None)  # rebuilt context needs a fresh anchor
    if event.get("source") == "compact":
        return _reanchor(event)
    if event.get("source") not in ("startup", "clear"):
        return None
    cwd = event.get("cwd") or "."
    cfg = config.load(cwd)
    retention.maybe_sweep(cfg.retention_days)  # never raises; never blocks restore
    if Path(cwd).resolve() == Path.home().resolve():
        return None  # never seed the home directory
    sp = state.resolve(cwd, sid)
    if not sp.exists():
        state.seed(sp)
        return _ctx(CONVENTION, f"carryover: seeded {_rel(sp, cwd)} - Claude will maintain it")
    if state.is_fresh(sp, cfg.state_fresh_hours):
        text = sp.read_text(encoding="utf-8")
        if len(text) > MAX_INJECT_CHARS:
            cut = text.rfind("\n", 0, MAX_INJECT_CHARS)
            text = text[: cut if cut > 0 else MAX_INJECT_CHARS]
            text += f"\n[carryover] STATE.md truncated for injection - read the rest at {sp}"
        return _ctx(PREAMBLE + text,
                    f"carryover: restored session state from STATE.md ({len(text.splitlines())} lines)")
    return None


def _pin_project_root(cwd, sid, source=None) -> None:
    """Pin the session's project root so later hooks survive a persistent cd (U2).
    A compact fires mid-session with a possibly-drifted cwd: never overwrite an
    existing pin there, only fill a missing one."""
    if not cwd or not sid:
        return
    try:
        if source == "compact" and flags.load(sid).get("project_root"):
            return
        flags.update(sid, project_root=str(Path(cwd).resolve()))
    except Exception:
        pass  # fail-open: a missed pin only forgoes drift protection


def _rel(sp, cwd):
    try:
        return sp.relative_to(cwd)
    except ValueError:
        return sp


def _reanchor(event):
    """source=compact: re-inject durable STATE.md so a compaction can't drop
    decisions Claude Code's own summary missed. Never seeds; ignores freshness."""
    cwd = event.get("cwd") or "."
    sid = event.get("session_id")
    if Path(cwd).resolve() == Path.home().resolve():
        return None  # $HOME is never seeded; never act there
    sp = state.resolve(cwd, sid)  # pin-aware: a drifted compact still finds the project
    if not sp.exists():
        return None  # nothing on disk to re-anchor; do NOT seed on compact
    sections = state.read_sections(sp)
    if _is_pristine(sections):
        return None  # untouched template: nothing worth re-anchoring
    sdir = paths.session_dir(sid) if sid else paths.home() / "sessions"
    text = COMPACT_PREAMBLE.format(sdir=sdir) + _compact_body(sections, sp)
    return _ctx(text, "carryover: re-anchored durable state after compaction")


def _is_pristine(sections) -> bool:
    return all(_placeholder(sections.get(k)) for k in ("Goal", "Now", "Decisions"))


def _placeholder(text) -> bool:
    """True when a section has no real content - blank or only (...) template lines."""
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("("):
            return False
    return True


def _compact_body(sections, sp) -> str:
    order = list(COMPACT_ORDER)
    body = _join(sections, order)
    for low in ("Files touched", "Dead-ends"):  # shed lowest priority first
        if len(body) <= MAX_COMPACT_CHARS:
            break
        if low in order:
            order.remove(low)
            body = _join(sections, order)
    if len(body) > MAX_COMPACT_CHARS:
        cut = body.rfind("\n", 0, MAX_COMPACT_CHARS)
        body = body[: cut if cut > 0 else MAX_COMPACT_CHARS]
        body += f"\n[carryover] STATE.md truncated for injection - read the rest at {sp}"
    return body


def _join(sections, order) -> str:
    return "\n\n".join(f"## {k}\n{sections[k]}" for k in order
                       if sections.get(k) and not _placeholder(sections.get(k)))


def _ctx(text, note=None):
    out = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }
    if note:
        out["systemMessage"] = note  # the one user-visible line per session
    return out
