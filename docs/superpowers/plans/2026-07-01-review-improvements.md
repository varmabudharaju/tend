# Review Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every finding from the 2026-07-01 project review: make the benchmark claims reproducible and honestly framed, fix README contradictions and bloat, add offload retention (`tend clean` + auto-sweep), gate CI on the mechanical invariants, and run the two missing experiments (OFF-arm discovery, Sonnet A/B).

**Architecture:** Benchmark fixes live in `bench/` (frozen corpus dir, word-boundary scoring, new `discovery` workload, CI exit code). The retention feature is a new `tend/retention.py` module wired into `sessionstart.py` (throttled auto-sweep) and `cli.py` (`tend clean`), with a `retention_days` config key. Docs work extracts README's "Under the hood" into `docs/architecture.md` and rewrites the claim framing in README + `docs/benchmark-results.md` using numbers produced by the experiment task.

**Tech Stack:** Python 3.11 stdlib only (tend is dependency-free), pytest, GitHub Actions, `claude -p` headless sessions for behavioral runs.

## Global Constraints

- tend must stay **dependency-free** (stdlib only) — no new packages.
- Every hook path must stay **fail-open**: a retention bug must never break a session or the STATE.md restore.
- Work happens on the existing `benchmarks` branch (clean tree); commit after every task.
- Live behavioral runs use the user's `claude` CLI + API key; total new spend budget ≈ **$3–5**.
- Committed corpus files must contain **no secrets, usernames, emails, or home paths** (enforced by test).
- All 172 existing tests must keep passing: `python3 -m pytest tests/ -q`.

---

### Task 1: Frozen, scrubbed benchmark corpus

The headline reduction number currently depends on the runner's private `~/.claude/tend/sessions` — it doesn't reproduce for anyone else. Freeze a scrubbed copy into `bench/corpus/` and make it the default; keep the live corpus behind `--live-corpus`.

**Files:**
- Create: `bench/corpus/README.md`, `bench/corpus/real-*.txt` (generated), `tests/test_bench_corpus.py`
- Modify: `bench/mechanical.py:27-37` (corpus loaders, `run()` signature), `bench/__main__.py:12-15` (flag)

**Interfaces:**
- Produces: `mechanical.load_real_corpus() -> list[tuple[str, str]]` now reads `bench/corpus/*.txt`; `mechanical.load_live_corpus()` is the old behavior; `mechanical.run(out_dir, stamp, iters=40, live_corpus=False)`.

- [ ] **Step 1: Generate the scrubbed corpus**

Write and run this one-time script (scratchpad, not committed):

```python
# /private/tmp/claude-501/-Users-varma-tend/4d636dbf-4d02-4ba4-9782-cea94b948f2e/scratchpad/freeze_corpus.py
import getpass, re
from pathlib import Path

SRC = Path.home() / ".claude" / "tend" / "sessions"
DST = Path("/Users/varma/tend/bench/corpus")
DST.mkdir(parents=True, exist_ok=True)
USER = getpass.getuser()
HOME = str(Path.home())

PATTERNS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"), "[REDACTED-KEY]"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}"), "[REDACTED-KEY]"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"), "[REDACTED-KEY]"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{8,}"), "[REDACTED-KEY]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED-KEY]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{20,}"), "[REDACTED-JWT]"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._-]{16,}"), r"\1[REDACTED]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "redacted@example.com"),
]

n = 0
for f in sorted(SRC.glob("*/outputs/*.txt")):
    text = f.read_text(encoding="utf-8", errors="replace")
    text = text.replace(HOME, "/home/user").replace(USER, "user")
    for pat, rep in PATTERNS:
        text = pat.sub(rep, text)
    n += 1
    (DST / f"real-{n:02d}.txt").write_text(text, encoding="utf-8")
    print(f"real-{n:02d}.txt  {len(text):>8,} chars  from {f}")
print(f"froze {n} outputs")
```

Run: `python3 <scratchpad>/freeze_corpus.py`
Expected: ~15 `real-NN.txt` files listed with sizes 11–94 KB.

- [ ] **Step 2: Manually review the corpus for anything sensitive**

Run: `grep -lEi "password|secret|token=|api[_-]?key|varma|@gmail" /Users/varma/tend/bench/corpus/*.txt`; also skim `head -c 400` of each file.
Expected: no hits. If a file still looks sensitive after scrubbing, delete it and note the reduced count in `bench/corpus/README.md`.

- [ ] **Step 3: Write `bench/corpus/README.md`**

```markdown
# Frozen benchmark corpus

Real tool outputs that tend offloaded in the author's production Claude Code
sessions (June 2026), frozen here so `python3 -m bench mechanical` reproduces
the same numbers for everyone. Scrubbed before committing: home paths and the
username normalized to `user`, emails to `redacted@example.com`, anything
key-shaped to `[REDACTED-*]` (enforced by `tests/test_bench_corpus.py`).
Sizes and structure are otherwise untouched — these are the outputs exactly as
tend saw them. To benchmark against your own history instead:
`python3 -m bench mechanical --live-corpus`.
```

- [ ] **Step 4: Write the failing test**

```python
# tests/test_bench_corpus.py
"""The committed corpus must exist, be big enough to exercise offloading,
and contain nothing sensitive (this is the scrub regression gate)."""
import re
from pathlib import Path

CORPUS = Path(__file__).resolve().parent.parent / "bench" / "corpus"

FORBIDDEN = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{8,}"),
    re.compile(r"[A-Za-z0-9._%+-]+@(?!example\.com)[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"/Users/varma|varmabudharaju"),
]


def corpus_files():
    return sorted(CORPUS.glob("*.txt"))


def test_corpus_present_and_offload_sized():
    files = corpus_files()
    assert len(files) >= 5
    # at least one file above the 2500-token (~10k char) offload threshold
    assert any(f.stat().st_size > 2500 * 4 for f in files)


def test_corpus_contains_no_secrets():
    for f in corpus_files():
        text = f.read_text(encoding="utf-8", errors="replace")
        for pat in FORBIDDEN:
            assert not pat.search(text), f"{f.name} matches {pat.pattern}"


def test_load_real_corpus_reads_frozen_dir():
    from bench import mechanical
    items = mechanical.load_real_corpus()
    assert len(items) >= 5
    assert all(name.startswith("real:") for name, _ in items)
```

- [ ] **Step 5: Run tests to verify the loader test fails**

Run: `python3 -m pytest tests/test_bench_corpus.py -v`
Expected: `test_load_real_corpus_reads_frozen_dir` FAILS (loader still reads `~/.claude/tend/sessions`, names look like `real:<sid>/NNNN.txt`); the two scrub tests PASS (corpus already generated).

- [ ] **Step 6: Rewrite the corpus loaders in `bench/mechanical.py`**

Replace the existing `load_real_corpus()` (lines 27–37) with:

```python
CORPUS_DIR = REPO / "bench" / "corpus"


def load_real_corpus():
    """Frozen, scrubbed real outputs committed in bench/corpus (reproducible)."""
    items = []
    for f in sorted(CORPUS_DIR.glob("*.txt")):
        items.append((f"real:{f.name}", f.read_text(encoding="utf-8", errors="replace")))
    return items


def load_live_corpus():
    """Opt-in: the runner's own offloaded outputs from ~/.claude/tend/sessions."""
    root = Path.home() / ".claude" / "tend" / "sessions"
    items = []
    for f in sorted(root.glob("*/outputs/*.txt")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        items.append((f"live:{f.parent.parent.name[:8]}/{f.name}", text))
    return items
```

And in `run()` (line 293) change the signature and corpus selection:

```python
def run(out_dir, stamp, iters=40, live_corpus=False):
    ...
    real = load_live_corpus() if live_corpus else load_real_corpus()
```

- [ ] **Step 7: Wire the flag in `bench/__main__.py`**

After line 15 (`--iters`) add:

```python
    m.add_argument("--live-corpus", action="store_true",
                   help="benchmark your own ~/.claude/tend offloaded outputs "
                        "instead of the frozen corpus")
```

And pass it through in the `mechanical` branch:

```python
        _results, md = mechanical.run(args.out, stamp, iters=args.iters,
                                      live_corpus=args.live_corpus)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_bench_corpus.py -v && python3 -m pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add bench/corpus tests/test_bench_corpus.py bench/mechanical.py bench/__main__.py
git commit -m "bench: frozen scrubbed corpus - mechanical benchmark reproduces for everyone"
```

---

### Task 2: Word-boundary recall scoring

`score_recall` substring-matches; `"137"` inside `"13750"` would false-positive. Use boundary lookarounds.

**Files:**
- Modify: `bench/behavioral.py:153-156`
- Test: `tests/test_bench_behavioral.py` (create)

**Interfaces:**
- Produces: `behavioral.score_recall(answer: str) -> tuple[dict[str, bool], int]` (unchanged signature, stricter matching).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bench_behavioral.py
"""Pure-function tests for the behavioral bench harness (no subprocesses)."""
from bench import behavioral


def test_score_recall_full_hit():
    ans = ("(a) Saffron-Quill (b) pgx-v5.2 (c) 137 (d) never use turbo-merge")
    hits, n = behavioral.score_recall(ans)
    assert n == 4 and all(hits.values())


def test_score_recall_rejects_embedded_number():
    # "137" inside a larger number must not count
    hits, n = behavioral.score_recall("the budget might be 13750 or 2137")
    assert not hits["retry_budget"] and n == 0


def test_score_recall_case_insensitive_and_empty():
    hits, n = behavioral.score_recall("codename SAFFRON-QUILL")
    assert hits["codename"] and n == 1
    assert behavioral.score_recall(None)[1] == 0
```

- [ ] **Step 2: Run test to verify the embedded-number case fails**

Run: `python3 -m pytest tests/test_bench_behavioral.py -v`
Expected: `test_score_recall_rejects_embedded_number` FAILS (substring match hits "13750"); others PASS.

- [ ] **Step 3: Implement boundary matching**

Replace `score_recall` in `bench/behavioral.py` (add `import re` to the imports):

```python
def score_recall(answer):
    text = answer or ""
    hits = {k: bool(re.search(rf"(?<![\w-]){re.escape(v)}(?![\w-])", text, re.IGNORECASE))
            for k, v in FACTS.items()}
    return hits, sum(hits.values())
```

Note the lookarounds include `-` so `"137"` doesn't match inside `"pre-1370"` — but check this doesn't break real facts: `Saffron-Quill` and `turbo-merge` contain hyphens *internally*, which is fine (lookarounds only guard the ends), and `(a) Saffron-Quill,` still matches.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_bench_behavioral.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add bench/behavioral.py tests/test_bench_behavioral.py
git commit -m "bench: word-boundary recall scoring - no substring false positives"
```

---

### Task 3: `discovery` workload — does vanilla Claude find STATE.md on its own?

The current handoff OFF-arm scores 0/4 *by construction* (tools blocked). The missing experiment: STATE.md on disk, tools **allowed**, probe that names no file. If OFF still fails, tend's claim strengthens; if OFF sometimes succeeds, the claim honestly becomes reliability + tokens.

**Files:**
- Modify: `bench/behavioral.py` (new probe + session fn + `run_pilot` dispatch + `render_markdown` description), `bench/__main__.py:22-25` (workload choice)
- Test: `tests/test_bench_behavioral.py` (extend)

**Interfaces:**
- Consumes: `arm_env`, `make_sandbox`, `run_turn`, `score_recall`, `HANDOFF_STATE`, `peak_ctx_in` from `bench/behavioral.py`.
- Produces: `behavioral.run_discovery_session(arm, run_dir, model, repeat, log=print) -> dict` (same result schema as `run_handoff_session`, `kind="discovery"`); workload name `"discovery"` accepted by `run_pilot` and the CLI.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bench_behavioral.py`:

```python
def test_discovery_probe_allows_tools():
    # the probe must not forbid tools and must not name STATE.md or any path
    p = behavioral.DISCOVERY_PROBE.lower()
    assert "without using any tools" not in p
    assert "state.md" not in p and ".claude" not in p


def test_render_markdown_discovery_kind():
    r = {"stamp": "t", "model": "m", "repeats": 1, "kind": "discovery",
         "sessions": [], "summary": {}}
    md = behavioral.render_markdown(r, ("on", "off"))
    assert "discovery" in md and "tools ALLOWED" in md
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_bench_behavioral.py -v`
Expected: both new tests FAIL (`DISCOVERY_PROBE` undefined).

- [ ] **Step 3: Implement the workload**

In `bench/behavioral.py`, after `PROBE` (line 55) add:

```python
DISCOVERY_PROBE = (
    "You're picking this project back up after a break. From what you know or can "
    "find in this project, answer concisely:\n"
    "  (a) the project codename,\n"
    "  (b) the database driver,\n"
    "  (c) the retry budget number,\n"
    "  (d) the flag we must never use.")
```

After `run_handoff_session` add:

```python
def run_discovery_session(arm, run_dir, model, repeat, log=print):
    """The fair OFF arm: STATE.md is on disk in BOTH arms, tools are ALLOWED,
    and the probe names no file. tend ON injects STATE.md at SessionStart;
    tend OFF must spontaneously discover it. Measures whether tend's restore
    is load-bearing or mere convenience."""
    env, home = arm_env(run_dir, arm, f"r{repeat}")
    sb = make_sandbox(home, n_logs=1, log_tokens=200)
    st = Path(sb) / ".claude" / "tend" / "STATE.md"
    st.parent.mkdir(parents=True, exist_ok=True)
    st.write_text(HANDOFF_STATE, encoding="utf-8")
    t0 = time.time()
    d = run_turn(DISCOVERY_PROBE, sb, env, model, resume_sid=None,
                 allowed="Read Grep Glob Bash", disallowed=None, timeout=300)
    answer = d.get("result", "") if not d.get("_parse_error") else ""
    hits, recall = score_recall(answer)
    cost = d.get("total_cost_usd", 0.0) or 0.0
    log(f"    [{arm} r{repeat} discovery] recall={recall}/4 cost=${cost:.3f}")
    return {
        "arm": arm, "repeat": repeat, "model": model, "kind": "discovery",
        "recall": recall, "recall_hits": hits,
        "peak_ctx_tokens": peak_ctx_in(d.get("usage", {})),
        "total_cost_usd": round(cost, 4),
        "total_output_tokens": d.get("usage", {}).get("output_tokens", 0),
        "offload_files": 0, "snapshots": 0, "compacted": False,
        "errored": bool(d.get("_parse_error")),
        "seconds": round(time.time() - t0, 1),
        "turns_ctx": [],
        "probe_answer": answer[:400],
    }
```

In `run_pilot`, extend the dispatch:

```python
            if kind == "handoff":
                s = run_handoff_session(arm, run_dir, model, repeat, log=log)
            elif kind == "discovery":
                s = run_discovery_session(arm, run_dir, model, repeat, log=log)
            else:
```

In `render_markdown`, extend the description block:

```python
    if kind == "handoff":
        desc = (...)  # unchanged
    elif kind == "discovery":
        desc = ("STATE.md sits on disk in **both** arms, tools ALLOWED, and the probe "
                "names no file. tend ON auto-injects it; tend OFF must spontaneously "
                "discover it. Tests whether the restore is load-bearing.")
    else:
```

In `bench/__main__.py` line 23 change choices to:

```python
                   choices=["recall", "highload", "handoff", "discovery"],
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_bench_behavioral.py -v && python3 -m pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add bench/behavioral.py bench/__main__.py tests/test_bench_behavioral.py
git commit -m "bench: discovery workload - OFF arm with tools allowed, the fair control"
```

---

### Task 4: Retention — `tend/retention.py`, `tend clean`, throttled auto-sweep

Offloaded outputs are raw tool output (may contain secrets) accumulating forever under `~/.claude/tend/sessions/`. Add an age-capped GC: `retention_days` config (default 30), a `tend clean` command, and an at-most-daily sweep at SessionStart. Fail-open: retention errors must never touch the restore path.

**Files:**
- Create: `tend/retention.py`, `tests/test_retention.py`
- Modify: `tend/paths.py` (add `newest_mtime`), `tend/cli.py` (use it; add `clean`), `tend/config.py:7-34` (`retention_days`), `tend/sessionstart.py:22-33` (sweep call), `tests/test_config.py` (default), `tests/test_cli.py` (clean cmd)

**Interfaces:**
- Produces: `paths.newest_mtime(d: Path) -> float` (0.0 on error); `retention.sweep(days, now=None, dry_run=False) -> dict` with keys `removed`, `kept`, `freed_bytes`; `retention.maybe_sweep(days, min_interval_s=86400) -> dict | None` (never raises); config field `Config.retention_days: int` (default 30, `0` disables); CLI `tend clean [--days N] [--dry-run] [--cwd DIR]`.

- [ ] **Step 1: Move `_session_mtime` into paths as `newest_mtime`**

Add to `tend/paths.py`:

```python
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
```

In `tend/cli.py` delete `_session_mtime` (lines 10-28) and replace its two call sites (`latest_session`, `cmd_status`) with `paths.newest_mtime`. Drop the now-unused `import os`.

Run: `python3 -m pytest tests/test_cli.py tests/test_paths.py -q` — Expected: PASS.

- [ ] **Step 2: Write the failing retention tests**

```python
# tests/test_retention.py
"""Age-capped GC of per-session state. Old sessions go, fresh ones stay,
and nothing outside sessions/ is ever touched."""
import os
import time

from tend import paths, retention

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


def test_sweep_removes_old_keeps_fresh(tend_home):
    old = make_session("old", age_days=40)
    fresh = make_session("fresh", age_days=1)
    stats = retention.sweep(30)
    assert stats["removed"] == 1 and stats["kept"] == 1
    assert stats["freed_bytes"] >= 1000
    assert not old.exists() and fresh.exists()


def test_sweep_dry_run_deletes_nothing(tend_home):
    old = make_session("old", age_days=40)
    stats = retention.sweep(30, dry_run=True)
    assert stats["removed"] == 1 and old.exists()


def test_sweep_zero_days_disables(tend_home):
    old = make_session("old", age_days=400)
    assert retention.sweep(0) == {"removed": 0, "kept": 0, "freed_bytes": 0}
    assert old.exists()


def test_sweep_leaves_non_session_files_alone(tend_home):
    make_session("old", age_days=40)
    keep = paths.home() / "statusline-original.json"
    keep.write_text("{}")
    old_cfg = time.time() - 400 * DAY
    os.utime(keep, (old_cfg, old_cfg))
    retention.sweep(30)
    assert keep.exists()


def test_maybe_sweep_throttles(tend_home):
    make_session("old", age_days=40)
    assert retention.maybe_sweep(30)["removed"] == 1
    make_session("old2", age_days=40)
    assert retention.maybe_sweep(30) is None  # marker is fresh
    assert (paths.home() / "sessions" / "old2").exists()


def test_maybe_sweep_never_raises(tend_home, monkeypatch):
    monkeypatch.setattr(retention, "sweep", lambda *a, **k: 1 / 0)
    assert retention.maybe_sweep(30) is None
```

(`tend_home` is the existing conftest fixture that points `TEND_HOME` at a tmp dir — confirm its name in `tests/conftest.py` before writing and adjust if it differs.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_retention.py -v`
Expected: FAIL with `ModuleNotFoundError: tend.retention` (or ImportError).

- [ ] **Step 4: Implement `tend/retention.py`**

```python
"""Retention: age-capped GC of per-session state (offloaded outputs, ledgers).

Offloaded outputs are raw tool output and can contain anything a tool printed;
they must not accumulate forever. Only sessions/<id> dirs are swept — never
config, the kill switch, the log, or the saved statusline."""
import shutil
import time
from pathlib import Path

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
```

- [ ] **Step 5: Run retention tests**

Run: `python3 -m pytest tests/test_retention.py -v`
Expected: 6 PASS.

- [ ] **Step 6: Add the config key (test-first)**

Add to `tests/test_config.py`:

```python
def test_retention_days_default_and_override(tmp_path, tend_home):
    from tend import config
    assert config.load().retention_days == 30
    p = tmp_path / ".claude" / "tend"
    p.mkdir(parents=True)
    (p / "config.yaml").write_text("retention_days: 7\n")
    assert config.load(str(tmp_path)).retention_days == 7
```

Run to see it fail, then in `tend/config.py` add to `DEFAULTS`:

```python
    "retention_days": 30,  # sweep sessions/<id> older than this at SessionStart; 0 disables
```

and to the dataclass:

```python
    retention_days: int
```

Run: `python3 -m pytest tests/test_config.py -v` — Expected: PASS (the existing `_coerce` handles ints, `0` is legal).

- [ ] **Step 7: Wire the auto-sweep into SessionStart (test-first)**

Add to `tests/test_sessionstart.py` (match the file's existing event-building idiom when writing it):

```python
def test_sessionstart_triggers_retention_sweep(tmp_path, tend_home, monkeypatch):
    from tend import retention, sessionstart
    called = {}
    monkeypatch.setattr(retention, "maybe_sweep", lambda days: called.setdefault("days", days))
    sessionstart.handle({"source": "startup", "cwd": str(tmp_path)})
    assert called["days"] == 30
```

Run to see it fail, then in `tend/sessionstart.py`: add `retention` to the import (`from . import config, retention, state`) and restructure `handle` so config loads once and the sweep runs before the home-dir early-return:

```python
def handle(event):
    if event.get("source") not in ("startup", "clear"):
        return None
    cwd = event.get("cwd") or "."
    cfg = config.load(cwd)
    retention.maybe_sweep(cfg.retention_days)  # never raises; never blocks restore
    if Path(cwd).resolve() == Path.home().resolve():
        return None  # never seed the home directory
    sp = state.path_for(cwd)
    ...
```

(Delete the now-duplicate `cfg = config.load(cwd)` further down.)

Run: `python3 -m pytest tests/test_sessionstart.py -v` — Expected: PASS.

- [ ] **Step 8: Add `tend clean` (test-first)**

Add to `tests/test_cli.py`:

```python
def test_clean_removes_old_sessions(capsys, tend_home):
    import os, time
    d = paths.session_dir("ancient")
    (d / "summary.json").write_text("{}")
    old = time.time() - 90 * 86400
    os.utime(d / "summary.json", (old, old))
    os.utime(d, (old, old))
    assert cli.main(["clean", "--days", "30"]) == 0
    assert "removed 1 session(s)" in capsys.readouterr().out
    assert not d.exists()


def test_clean_dry_run(capsys, tend_home):
    import os, time
    d = paths.session_dir("ancient")
    (d / "summary.json").write_text("{}")
    old = time.time() - 90 * 86400
    os.utime(d / "summary.json", (old, old))
    os.utime(d, (old, old))
    assert cli.main(["clean", "--days", "30", "--dry-run"]) == 0
    assert "would remove 1" in capsys.readouterr().out
    assert d.exists()
```

Run to see them fail, then in `tend/cli.py` add:

```python
def cmd_clean(args) -> int:
    from . import retention

    days = args.days if args.days is not None else config.load(args.cwd).retention_days
    stats = retention.sweep(days, dry_run=args.dry_run)
    verb = "would remove" if args.dry_run else "removed"
    print(f"{verb} {stats['removed']} session(s) older than {days}d "
          f"({stats['freed_bytes'] / 1e6:.1f} MB); kept {stats['kept']}")
    return 0
```

Register it in `main()`'s command list as `("clean", cmd_clean, ["cwd", "clean"])` and extend the option loop:

```python
        if "clean" in opts:
            p.add_argument("--days", type=int, default=None)
            p.add_argument("--dry-run", action="store_true")
```

Run: `python3 -m pytest tests/test_cli.py -v` — Expected: PASS.

- [ ] **Step 9: Full suite + commit**

Run: `python3 -m pytest tests/ -q` — Expected: all PASS (~180 tests).

```bash
git add tend/retention.py tend/paths.py tend/cli.py tend/config.py tend/sessionstart.py tests/
git commit -m "feat: retention - age-capped GC of session state, tend clean, daily auto-sweep"
```

---

### Task 5: CI gates on the mechanical invariants

Phase 1 is deterministic and free — make CI run it against the frozen corpus and fail on any invariant regression.

**Files:**
- Modify: `bench/__main__.py:39-43` (exit code), `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `mechanical.run(...)[0]["invariants"]` — list of dicts with a `pass` bool (from Task 1's `run`).
- Produces: `python3 -m bench mechanical` exits 1 when any invariant fails.

- [ ] **Step 1: Exit nonzero on invariant failure**

In `bench/__main__.py`, replace the `mechanical` branch body:

```python
    if args.cmd == "mechanical":
        results, md = mechanical.run(args.out, stamp, iters=args.iters,
                                     live_corpus=args.live_corpus)
        print(md)
        print(f"\n[bench] wrote {args.out}/mechanical-{stamp}.{{json,md}}")
        failed = [c["invariant"] for c in results["invariants"] if not c["pass"]]
        if failed:
            print(f"[bench] INVARIANT FAILURES: {failed}", file=sys.stderr)
            return 1
        return 0
```

- [ ] **Step 2: Verify locally**

Run: `python3 -m bench mechanical --iters 3 --out /private/tmp/claude-501/-Users-varma-tend/4d636dbf-4d02-4ba4-9782-cea94b948f2e/scratchpad/bench-ci; echo "exit=$?"`
Expected: report prints, `exit=0`, and the headline reduction reflects the frozen corpus (record this number — the docs tasks use it).

- [ ] **Step 3: Add the CI step**

`.github/workflows/ci.yml` becomes:

```yaml
name: tests
on:
  push:
    branches: [master]
  pull_request:

jobs:
  tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: python -m pip install -e . pytest
      - run: python -m pytest tests/ -q
      - name: mechanical benchmark (invariant gate)
        run: python -m bench mechanical --iters 3 --out /tmp/bench-ci
```

- [ ] **Step 4: Commit**

```bash
git add bench/__main__.py .github/workflows/ci.yml
git commit -m "ci: run the mechanical benchmark as an invariant regression gate"
```

---

### Task 6: Run the experiments (live API — ~$3–5 total)

Produce the numbers Tasks 7–8 will cite. All artifacts auto-save under `.benchmarks/`.

**Files:**
- Create (generated): `.benchmarks/mechanical-<stamp>.{json,md}`, `.benchmarks/behavioral-<stamp>.{json,md}` × 3 runs

**Interfaces:**
- Produces: for the docs tasks — (1) the frozen-corpus mechanical headline (reduction %, invariant count now 6/6 or 7/7 per the "never inflates" appended check), (2) discovery recall per arm (Haiku, 5 repeats), (3) Sonnet handoff recall per arm (3 repeats), (4) Sonnet recall-workload overhead deltas (2 repeats).

- [ ] **Step 1: Regenerate the mechanical results on the frozen corpus**

Run: `python3 -m bench mechanical` (default `--out .benchmarks`, full 40 iters)
Expected: exit 0; note the new headline `overall_reduction_pct` and footprint numbers.

- [ ] **Step 2: Discovery A/B (Haiku, 5 repeats/arm)**

Run: `python3 -m bench behavioral --workload discovery --repeats 5`
Expected: ~10 one-turn sessions, ≲$0.30 total. Record per-arm recall — **do not assume the OFF result**; whatever it is goes in the docs verbatim. If any session shows `⚠err`, rerun that configuration once before accepting the tally.

- [ ] **Step 3: Sonnet handoff A/B (3 repeats/arm)**

Run: `python3 -m bench behavioral --workload handoff --repeats 3 --model claude-sonnet-5`
Expected: ~6 one-turn sessions, ≲$1. (If the model id is rejected, check `claude -p "ok" --model claude-sonnet-5` and use the alias `sonnet` as fallback.)

- [ ] **Step 4: Sonnet recall/overhead A/B (2 repeats/arm)**

Run: `python3 -m bench behavioral --workload recall --repeats 2 --model claude-sonnet-5`
Expected: ~4 multi-turn sessions, ≲$2.5. This re-measures the "+14% overhead" finding on a realistic model; record the cost and peak-context deltas as a **range**, not a point.

- [ ] **Step 5: Verify the anchor-accumulation explanation against data**

Read `turns_ctx` in the existing `.benchmarks/behavioral-2026-06-18-084350.json` (the recall pilot) and the new Sonnet recall JSON: confirm the ON−OFF context gap grows roughly per-turn (anchors persist in the transcript, so turn N carries ~N anchors). The reconciliation sentence in Task 7 must match what the data shows — if it doesn't, write what the data does show.

- [ ] **Step 6: Commit the artifacts**

```bash
git add .benchmarks/
git commit -m "bench: frozen-corpus rerun, discovery A/B, Sonnet handoff + overhead runs"
```

---

### Task 7: README restructure + claim fixes + architecture extraction

**Files:**
- Create: `docs/architecture.md`
- Modify: `README.md`, `.capture.yaml` (refresh shots)

**Interfaces:**
- Consumes: Task 6's numbers (frozen-corpus reduction %, discovery tally, Sonnet results).

- [ ] **Step 1: Extract `docs/architecture.md`**

Move README.md:221-349 (everything from `## Under the hood` through the end of the `### Modules` block, **verbatim**) into a new `docs/architecture.md` that opens with:

```markdown
# tend architecture

How tend plugs into Claude Code: no daemon, one short-lived process per hook
event, everything durable in plain files. (Extracted from the README; this is
the deep-dive companion to [../README.md](../README.md).)
```

Add `retention.py  age-capped GC of session state (tend clean + daily auto-sweep)` to the Modules listing while moving it. In the README, replace the moved block with:

```markdown
## Under the hood

No daemon, no background process: Claude Code fires an event, a tiny tend
process wakes, reads its state from disk, acts, and exits. Everything durable
lives in plain files. Full diagrams — system design, module layers, and the
advisor's whole decision tree — are in [docs/architecture.md](docs/architecture.md).

172 tests (`python3 -m pytest`). Every bug fixed in v0.2 carries a regression
test written from the bug's reproduction.
```

(Update the test count to the real number after Task 4 — run `python3 -m pytest tests/ -q | tail -1`.)

- [ ] **Step 2: Fix the hero install block**

Replace README.md:17-19:

```markdown
```
/plugin marketplace add varmabudharaju/tend
/plugin install tend@tend       # 30 seconds, fully reversible, no daemon
```
```

- [ ] **Step 3: Cut the repeated metaphor diagrams**

Delete: the without/with flowchart at README.md:59-75 (prose above it already carries the desk metaphor), and both mini-diagrams at README.md:92-108 ("The first habit, in one picture" and "And the notebook habit…" including their intro sentences). Keep the hero flowchart and the session sequence diagram.

- [ ] **Step 4: Reframe the results table**

Replace the "Results at a glance" table rows (README.md:38-44) with (fill `N/5` from Task 6):

```markdown
| What we measured | Result |
|---|---|
| In-context size of the outputs tend offloads | **~89% smaller** (frozen corpus of real recorded outputs; up to 95% on the largest) |
| Recall across a context reset, given a maintained STATE.md | **4/4 with tend → 0/4 without** — every run |
| Does a fresh session find STATE.md *without* tend? | **N/5 runs** (tools allowed, file unnamed) — with tend: injection makes it 5/5 and ~free |
| tend's own per-event overhead | **~9 ms** (the handler itself is <0.3 ms) |
| Correctness invariants | **all held** — enforced in CI on every push |
| Install footprint | daemon-less, fully reversible, fails open |
```

(Use the exact reduction % from Task 6 Step 1 if it isn't ~89.)

- [ ] **Step 5: Add the preconditions + reconciliation to the proof section**

In "Does it actually work?": append to the §2 paragraph (after "recalls **nothing**"):

```markdown
Two honest preconditions: this isolates the *restore* leg (STATE.md was maintained
— tend nudges the model to keep it current, but that step is model-dependent), and
the tools-blocked OFF arm is a floor. The fairer control — tools **allowed**, file
unnamed — is the discovery run above: without tend the model found STATE.md in
N of 5 runs; with tend, restore is deterministic and costs no tool calls.
```

And extend the "Honest boundary" callout with the reconciliation sentence verified in Task 6 Step 5:

```markdown
> (Each anchor is ≤400 tokens, but anchors persist in the transcript, so an
> N-turn session carries all N of them — that accumulation, plus the one-time
> restore, is the whole gap in the stress test.)
```

- [ ] **Step 6: Add Privacy & disk use + teardown docs**

Insert before `## Limitations`:

```markdown
## Privacy & disk use

- **Offloaded outputs are raw tool output** — anything a command printed
  (including a secret it echoed) is saved as plaintext under
  `~/.claude/tend/sessions/<id>/outputs/`. tend sweeps sessions older than
  `retention_days` (default 30, `0` disables) once a day at session start;
  `tend clean [--days N] [--dry-run]` purges on demand.
- **STATE.md is plain text in your repo.** Commit it if you want shared,
  reviewable handoffs across the team; add `.claude/tend/STATE.md` to
  `.gitignore` if task reasoning shouldn't enter history. tend works either way.
- Nothing ever leaves your machine: no network calls, no telemetry.
```

In the Install section, after the reversibility paragraph, add:

```markdown
**Removing it:** pip installs — `tend uninstall-hook` restores your previous
hooks and statusline exactly (they were backed up at install). Plugin installs —
`/plugin uninstall tend@tend` removes the hooks; if you ran `tend wrap-statusline`,
run `tend uninstall-hook` once to restore the original statusline (it only touches
tend-marked entries).
```

Add to the Commands table:

```markdown
| `tend clean` | Purge session state older than `retention_days` (`--days N`, `--dry-run`) |
```

And in Configuration, after the first sentence, append: `Notable: retention_days (default 30) age-caps stored session state.`

- [ ] **Step 7: Refresh the stale-number screenshots**

The submission/bench screenshots embed the old 88.8% corpus numbers. Re-capture via the existing shot list: inspect `.capture.yaml`, update the bench-related shots to rerun `python3 -m bench mechanical` output and `tend status`/`report`/`handoff`, then `capture run`. Verify the regenerated PNGs under `docs/screenshots/` show the new numbers before replacing.

- [ ] **Step 8: Render-check and commit**

Run: `grep -n "88.8" README.md docs/benchmark-results.md | cat` — Expected: no hits left in README (benchmark-results.md is handled in Task 8). Preview the README (e.g. `gh markdown-preview` if available, else visual skim) for broken anchors — the in-page link `#does-it-actually-work` must still resolve.

```bash
git add README.md docs/architecture.md docs/screenshots .capture.yaml
git commit -m "docs: honest claim framing, plugin-first install, architecture extracted, privacy section"
```

---

### Task 8: benchmark-results.md — new runs, provenance, and the unmeasured-outcome note

**Files:**
- Modify: `docs/benchmark-results.md`

**Interfaces:**
- Consumes: Task 6 artifacts in `.benchmarks/` (read the actual JSON/MD — never cite from memory).

- [ ] **Step 1: Update provenance + reproduce block**

In the Phase 1 section, replace the corpus sentence with: real outputs now come from **the frozen, scrubbed corpus committed at `bench/corpus/`** (provenance in its README; `--live-corpus` benchmarks your own history instead), and update the headline numbers from the Task 6 rerun. Update the reproduce block to include:

```bash
python3 -m bench behavioral --workload discovery --repeats 5   # fair OFF control
```

Also update the "Caveat" line to note CI runs the invariant gate on every push.

- [ ] **Step 2: Add the discovery section**

After Phase 2b, insert (numbers from the actual run):

```markdown
### The fair control — tools allowed, file unnamed (discovery)

The tools-blocked OFF arm above is a floor: it *cannot* score. So we also ran
the fairer control — STATE.md on disk in both arms, tools **allowed**, probe
naming no file. Without tend the model found STATE.md in **N/5** runs
(<one-line description of what it actually did>); with tend, **5/5**, zero tool
calls spent. <One sentence interpreting: restore is load-bearing / restore is
reliability+tokens, whichever the data shows.>
```

- [ ] **Step 3: Add the Sonnet section**

After the discovery section:

```markdown
## Sonnet check — overhead on a realistic model

Everything above ran on Haiku, which *amplifies* tend's per-turn anchor cost
(a ~250-token anchor is a big fraction of a cheap short turn). Rerunning on
Sonnet 5: handoff **X/4 vs Y/4** (3 repeats/arm); recall-workload overhead
**±A–B%** cost, **±C–D%** peak context (2 repeats/arm — a range, not a point;
n is small). <One sentence: does the overhead shrink relative to Haiku, as
predicted?>
```

Fill every X/Y/A–D from the actual `.benchmarks` JSON; also revise the TL;DR table's overhead row to cite the range and its n, e.g. `+14% (Haiku, n=2) / <Sonnet range> (Sonnet, n=2)`.

- [ ] **Step 4: Add the unmeasured-outcome section**

Before "Artifacts & cost":

```markdown
## What we have NOT measured

The pitch is "stays smart ten hours in" — an *outcome* claim. These benchmarks
prove the mechanisms (offloading shrinks context; restore survives resets) but
not the outcome: that an agent with tend completes long, decision-heavy tasks
better than one without. That needs a task-level A/B — a multi-step job with a
forced mid-task reset, scored on completion quality — which is expensive to run
credibly (many repeats, blind scoring) and is the next benchmark we want to
build. Until it exists, the outcome claim is an argument from mechanism, and
you should read it that way.
```

- [ ] **Step 5: Sample-size honesty pass + preconditions**

In the TL;DR and Phase 2b sections: annotate every result with its n (e.g. "4/4 vs 0/4, 5 repeats/arm"), and add to the Phase 2b intro the same two preconditions sentence used in the README (maintained STATE.md; tools-blocked OFF is a floor — see discovery for the fair control). Update the Artifacts & cost section with the new spend total and the added artifact files.

- [ ] **Step 6: Full check + commit**

Run: `python3 -m pytest tests/ -q && python3 -m bench mechanical --iters 3 --out /private/tmp/claude-501/-Users-varma-tend/4d636dbf-4d02-4ba4-9782-cea94b948f2e/scratchpad/bench-final`
Expected: tests pass, bench exits 0.

```bash
git add docs/benchmark-results.md
git commit -m "docs: discovery + Sonnet results, corpus provenance, unmeasured-outcome note"
```

---

## Execution notes

- Task order matters: 1→2→3 (bench code), 4 (retention), 5 (CI), 6 (live runs need 1–3 merged), 7–8 (docs consume 6's numbers).
- Task 6 spends real API money (~$3–5) on the user's key — it was explicitly approved in the review conversation.
- The final README/results numbers **must** come from the Task 6 artifacts, not from this plan or the old docs.
