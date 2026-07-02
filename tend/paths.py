"""TEND_HOME resolution, session dirs, kill switch, atomic JSON I/O."""
import json
import os
from pathlib import Path


def home() -> Path:
    return Path(os.environ.get("TEND_HOME", str(Path.home() / ".claude" / "tend")))


def session_dir(session_id: str) -> Path:
    d = home() / "sessions" / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def newest_mtime(d) -> float:
    """Newest file mtime in d, tolerating files that vanish mid-scan; 0.0 on error."""
    times = []
    try:
        with os.scandir(d) as it:
            for entry in it:
                try:
                    if entry.is_file():
                        times.append(entry.stat().st_mtime)
                except OSError:
                    continue
    except OSError:
        return 0.0
    if times:
        return max(times)
    try:
        return Path(d).stat().st_mtime
    except OSError:
        return 0.0


def disabled() -> bool:
    return (home() / "disabled").exists()


def log_path() -> Path:
    return home() / "tend.log"


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json_atomic(path, obj, indent=None, mode=None) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, indent=indent), encoding="utf-8")
    if mode is not None:
        os.chmod(tmp, mode)
    tmp.replace(p)
