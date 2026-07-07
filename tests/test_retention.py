"""Age-capped GC of per-session state. Old sessions go, fresh ones stay,
and nothing outside sessions/ is ever touched."""
import os
import time

from carryover import paths, retention

DAY = 86400


def make_session(sid, age_days, payload=b"x" * 1000):
    d = paths.session_dir(sid)
    f = d / "outputs"
    f.mkdir(exist_ok=True)
    p = f / "0001.txt"
    p.write_bytes(payload)
    old = time.time() - age_days * DAY
    for path in (p, d):
        os.utime(path, (old, old))
    return d


def test_sweep_removes_old_keeps_fresh(carryover_home):
    old = make_session("old", age_days=40)
    fresh = make_session("fresh", age_days=1)
    stats = retention.sweep(30)
    assert stats["removed"] == 1 and stats["kept"] == 1
    assert stats["freed_bytes"] >= 1000
    assert not old.exists() and fresh.exists()


def test_sweep_dry_run_deletes_nothing(carryover_home):
    old = make_session("old", age_days=40)
    stats = retention.sweep(30, dry_run=True)
    assert stats["removed"] == 1 and old.exists()


def test_sweep_zero_days_disables(carryover_home):
    old = make_session("old", age_days=400)
    assert retention.sweep(0) == {"removed": 0, "kept": 0, "freed_bytes": 0}
    assert old.exists()


def test_sweep_leaves_non_session_files_alone(carryover_home):
    make_session("old", age_days=40)
    keep = paths.home() / "statusline-original.json"
    keep.write_text("{}")
    old_cfg = time.time() - 400 * DAY
    os.utime(keep, (old_cfg, old_cfg))
    retention.sweep(30)
    assert keep.exists()


def test_maybe_sweep_throttles(carryover_home):
    make_session("old", age_days=40)
    assert retention.maybe_sweep(30)["removed"] == 1
    make_session("old2", age_days=40)
    assert retention.maybe_sweep(30) is None  # marker is fresh
    assert (paths.home() / "sessions" / "old2").exists()


def test_maybe_sweep_never_raises(carryover_home, monkeypatch):
    monkeypatch.setattr(retention, "sweep", lambda *a, **k: 1 / 0)
    assert retention.maybe_sweep(30) is None
