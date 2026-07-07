"""Hook stdin/stdout plumbing. Fail-open: a carryover bug must never break a session."""
import datetime
import json
import sys
import traceback

from . import paths


def read_event() -> dict:
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")


MAX_LOG_BYTES = 1_000_000


def append_log(text: str) -> None:
    try:
        paths.home().mkdir(parents=True, exist_ok=True)
        lp = paths.log_path()
        try:
            if lp.stat().st_size > MAX_LOG_BYTES:
                lp.replace(lp.with_name(lp.name + ".1"))
        except OSError:
            pass
        with open(lp, "a", encoding="utf-8") as f:
            f.write(text)
    except BaseException:
        pass


def log_error() -> None:
    append_log(f"--- {datetime.datetime.now().isoformat()}\n{traceback.format_exc()}\n")


def run_fail_open(handler) -> int:
    try:
        if paths.disabled():
            return 0
        event = read_event()
        out = handler(event)
        if out is not None:
            emit(out)
    except KeyboardInterrupt:
        pass  # routine Ctrl-C: not a carryover error, nothing to log
    except BaseException:
        log_error()
    return 0
