"""Per-session flags shared between hook invocations."""
from . import paths


def load(sid) -> dict:
    return paths.read_json(paths.session_dir(sid) / "flags.json", {})


def save(sid, fl) -> None:
    paths.write_json_atomic(paths.session_dir(sid) / "flags.json", fl)
