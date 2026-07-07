"""Retention: age-capped GC of per-session state (offloaded outputs, ledgers).

Offloaded outputs are raw tool output and can contain anything a tool printed;
they must not accumulate forever. Only sessions/<id> dirs are swept — never
config, the kill switch, the log, or the saved statusline."""
import shutil
import time

from . import paths

MARKER = "last-gc"


def sweep(days, now=None, dry_run=False):
    """Remove session dirs whose newest file is older than `days`. 0 disables."""
    stats = {"removed": 0, "kept": 0, "freed_bytes": 0}
    if not days or days <= 0:
        return stats
    root = paths.home() / "sessions"
    if not root.is_dir():
        return stats
    cutoff = (time.time() if now is None else now) - days * 86400
    for d in root.iterdir():
        if not d.is_dir():
            continue
        if paths.newest_mtime(d) >= cutoff:
            stats["kept"] += 1
            continue
        try:
            stats["freed_bytes"] += sum(
                f.stat().st_size for f in d.rglob("*") if f.is_file())
        except OSError:
            pass
        if not dry_run:
            shutil.rmtree(d, ignore_errors=True)
        stats["removed"] += 1
    return stats


def maybe_sweep(days, min_interval_s=86400):
    """At most one sweep per interval, and never raises (hook-path safe)."""
    try:
        marker = paths.home() / MARKER
        if marker.exists() and time.time() - marker.stat().st_mtime < min_interval_s:
            return None
        paths.home().mkdir(parents=True, exist_ok=True)
        marker.touch()
        return sweep(days)
    except Exception:
        return None
