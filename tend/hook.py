"""Hook entry point: python3 -m tend.hook (registered for all tend events)."""
import sys

from . import hookio

INGEST = {"PostToolUse", "UserPromptSubmit", "Stop", "PreCompact"}


def dispatch(event):
    from . import anchor, boundary, ledger, offload, precompact, readguard, sessionstart

    name = event.get("hook_event_name")
    if name in INGEST:
        ledger.ingest(event)
    if name in ("SubagentStart", "SubagentStop"):
        ledger.record_agent(event)
        return None
    handlers = {
        "PostToolUse": offload.handle,
        "PreToolUse": readguard.handle,
        "UserPromptSubmit": anchor.handle,
        "Stop": boundary.handle,
        "SessionStart": sessionstart.handle,
        "PreCompact": precompact.handle,
    }
    fn = handlers.get(name)
    return fn(event) if fn else None


def main() -> int:
    return hookio.run_fail_open(dispatch)


if __name__ == "__main__":
    sys.exit(main())
