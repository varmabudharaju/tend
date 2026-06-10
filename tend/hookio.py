"""Hook stdin/stdout plumbing. Fail-open: a tend bug must never break a session."""
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


def log_error() -> None:
    try:
        paths.home().mkdir(parents=True, exist_ok=True)
        with open(paths.log_path(), "a") as f:
            f.write(f"--- {datetime.datetime.now().isoformat()}\n{traceback.format_exc()}\n")
    except Exception:
        pass


def run_fail_open(handler) -> int:
    try:
        if paths.disabled():
            return 0
        event = read_event()
        out = handler(event)
        if out is not None:
            emit(out)
    except BaseException:
        log_error()
    return 0
