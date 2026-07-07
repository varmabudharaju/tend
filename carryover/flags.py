"""Per-session flags shared between hook invocations."""
import fcntl

from . import paths


def load(sid) -> dict:
    return paths.read_json(paths.session_dir(sid) / "flags.json", {})


def save(sid, fl) -> None:
    paths.write_json_atomic(paths.session_dir(sid) / "flags.json", fl)


def update(sid, **changes) -> dict:
    """Atomically merge changes into the session's flags (lock held across read+write)."""
    lock_path = paths.session_dir(sid) / "flags.lock"
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        fl = load(sid)
        fl.update(changes)
        save(sid, fl)
        return fl
