# tend v0.2 Bug-Fix Round Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 31 confirmed findings from the swarm adversarial review (`docs/swarm-review-2026-06-10.md`) with a regression test per finding.

**Architecture:** tend is a fail-open hook harness (`tend/` package, ~1,100 lines, 110 green tests). Fixes are grouped per module so commits stay coherent: ledger core (H1/M1/M2/L1/L2/L3), staleness metric (H2/L7), hook isolation (M3), config validation (M4), offload+tokens (M6/M7/M8/L4), anchor (M9/L6), precompact (M5), install (M10/M11/L13/L14/L17), hookio (L8/L9), state/sessionstart (L10/L11/L12), readguard (L5), statusline (L15/L18), CLI (L16). Settled design decisions from STATE.md are binding: the staleness mark moves to monotonic `output_total` (clamping `context_total` deltas is a recorded dead-end), the ledger cursor only advances past byte data ending in `\n`, uninstall prunes inner hook commands (never whole entries), and PreCompact never blocks in `$HOME`.

**Tech Stack:** Python 3.11 (`python3` on this machine), pytest (`python3 -m pytest`), no new dependencies.

**Conventions:**
- Run tests from `/Users/varma/tend` with `python3 -m pytest tests/ -q` (full) or `python3 -m pytest tests/test_X.py -q` (file).
- Commit messages: conventional prefix (`fix:`, `test:`), **no Co-Authored-By lines ever** (user rule).
- Every test gets an isolated `TEND_HOME` via the autouse `tend_home` fixture in `tests/conftest.py`; `make_event(**kw)` and `write_transcript(path, lines)` helpers live there too.
- After each task: run the FULL suite, not just the new file — these modules interlock.

---

### Task 1: Ledger ingest core — H1, M1, M2, L1, L2, L3

The big one. Five findings share one root area: `_ingest_locked` reads text lines through a moving file and keeps its cursor in a second file.

- **H1**: `for line in f` consumes a partial trailing line mid-append; `f.tell()` lands at EOF, skipping the fragment forever. Fix: read bytes, only consume through the last `\n`, leave the partial tail for the next ingest.
- **M1**: invalid UTF-8 raises from the text-mode file iterator, outside the per-line guard. Fix: read binary, decode per line inside the guard.
- **M2**: `'null'` parses as JSON, then `obj.get` raises AttributeError outside the try, stalling the cursor forever. Fix: `isinstance(obj, dict)` check inside the guard; non-dicts are skipped (they carry no data, so not `degraded`).
- **L1**: NotebookEdit staleness is dead code — live schema sends `notebook_path`, code reads only `file_path`. Fix: fall back to `notebook_path`.
- **L2**: poisoned `cursor.json` (`null`, `{}`, `{"offset":"0"}`) crashes every ingest before the rewrite that would fix it. Fix: validate the cursor shape and reset to `{"offset": 0}`.
- **L3**: crash between the summary write and the cursor write double-counts `output_total`. Fix: store the cursor INSIDE summary.json — one atomic write, no window at all. Legacy `cursor.json` is read once for migration, then unlinked.

**Files:**
- Modify: `tend/ledger.py:56-121` (`_ingest_locked`, `_ingest_line`)
- Test: `tests/test_ledger.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ledger.py` (add `import json` and `from tend import paths` to its imports):

```python
# ── v0.2: H1 partial-line race ────────────────────────────────────────────────

def test_partial_trailing_line_deferred_not_lost(tmp_path):
    """A writer mid-append leaves a partial line; it must be re-read later, not skipped."""
    tp = tmp_path / "t.jsonl"
    lines = fixture_lines()
    line1 = json.dumps(lines[0]) + "\n"
    full = line1 + json.dumps(lines[1]) + "\n"
    tp.write_text(line1 + full[len(line1):len(line1) + 40])  # line 2 cut at 40 chars
    ev = make_event(transcript_path=str(tp))
    ledger.ingest(ev)
    s = ledger.load_summary("s1")
    assert s["degraded"] is False          # fragment is deferred, not judged corrupt
    assert "t1" in s["pending"]            # line 1 fully ingested
    assert s["results"] == {}              # line 2 not consumed yet
    tp.write_text(full)                    # writer finishes the append
    ledger.ingest(ev)
    s = ledger.load_summary("s1")
    assert s["results"]["t1"]["tokens"] == 500   # nothing lost
    assert s["degraded"] is False


def test_invalid_utf8_line_skipped_cursor_advances(tmp_path):
    """M1: bad bytes degrade that line only; later lines parse and re-ingest is stable."""
    tp = tmp_path / "t.jsonl"
    good = json.dumps(fixture_lines()[0]).encode("utf-8")
    tp.write_bytes(b"\xff\xfe garbage\n" + good + b"\n")
    ev = make_event(transcript_path=str(tp))
    ledger.ingest(ev)
    s = ledger.load_summary("s1")
    assert s["degraded"] is True
    assert s["context_total"] == 1010      # the good line after the bad bytes parsed
    before = s["output_total"]
    ledger.ingest(ev)                       # cursor advanced past the bad line
    assert ledger.load_summary("s1")["output_total"] == before


def test_non_dict_json_lines_skipped(tmp_path):
    """M2: null / list / str / number lines must not stall the cursor or crash."""
    tp = tmp_path / "t.jsonl"
    good = json.dumps(fixture_lines()[0])
    tp.write_text('null\n[1, 2]\n"str"\n123\n' + good + "\n")
    ev = make_event(transcript_path=str(tp))
    ledger.ingest(ev)
    s = ledger.load_summary("s1")
    assert s["context_total"] == 1010
    before = s["output_total"]
    ledger.ingest(ev)
    assert ledger.load_summary("s1")["output_total"] == before


def test_notebookedit_staleness_uses_notebook_path(tmp_path):
    """L1: live NotebookEdit schema sends notebook_path, not file_path."""
    tp = tmp_path / "t.jsonl"
    nb = "/tmp/proj/nb.ipynb"
    write_transcript(tp, [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "r1", "name": "Read", "input": {"file_path": nb}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "r1", "content": "cells"}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "e1", "name": "NotebookEdit",
             "input": {"notebook_path": nb}}]}},
    ])
    ledger.ingest(make_event(transcript_path=str(tp)))
    assert ledger.load_summary("s1")["results"]["r1"]["stale"] is True


def test_poisoned_cursor_repaired(tmp_path):
    """L2: cursor.json of null / {} / {"offset":"0"} must reset to 0, not crash forever."""
    tp = tmp_path / "t.jsonl"
    write_transcript(tp, [fixture_lines()[0]])
    ev = make_event(transcript_path=str(tp))
    for poison in ("null", "{}", '{"offset": "0"}', '{"offset": -5}'):
        sdir = paths.session_dir("s1")
        for f in sdir.glob("*.json"):
            f.unlink()
        (sdir / "cursor.json").write_text(poison)
        ledger.ingest(ev)
        assert ledger.load_summary("s1")["context_total"] == 1010, poison


def test_cursor_lives_in_summary_single_atomic_write(tmp_path):
    """L3: cursor is stored inside summary.json; legacy cursor.json is consumed and removed."""
    tp = tmp_path / "t.jsonl"
    write_transcript(tp, fixture_lines())
    ev = make_event(transcript_path=str(tp))
    ledger.ingest(ev)
    s = ledger.load_summary("s1")
    assert s["cursor"]["offset"] == tp.stat().st_size
    assert not (paths.session_dir("s1") / "cursor.json").exists()


def test_legacy_cursor_json_migrated(tmp_path):
    """Upgrade path: an old separate cursor.json must seed the offset (no double-count)."""
    tp = tmp_path / "t.jsonl"
    lines = fixture_lines()
    write_transcript(tp, lines[:2])
    first_two = tp.stat().st_size
    write_transcript(tp, lines)
    # Simulate a v0.1 session: summary without "cursor", offset in separate file
    paths.write_json_atomic(paths.session_dir("s1") / "cursor.json", {"offset": first_two})
    paths.write_json_atomic(paths.session_dir("s1") / "summary.json", {
        "context_total": 2502, "output_total": 130, "results": {}, "reads": {},
        "pending": {}, "agents": {}, "state_mark": None, "degraded": False,
    })
    ledger.ingest(make_event(transcript_path=str(tp)))
    s = ledger.load_summary("s1")
    assert s["output_total"] == 130 + 40   # only line 3+ ingested, not re-counted
    assert not (paths.session_dir("s1") / "cursor.json").exists()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest tests/test_ledger.py -q`
Expected: the 7 new tests FAIL (`test_partial_trailing_line_deferred_not_lost` with results lost / KeyError "cursor", `test_poisoned_cursor_repaired` with TypeError, etc.); the 8 pre-existing tests still pass.

- [ ] **Step 3: Implement**

In `tend/ledger.py`, replace `_ingest_locked` and `_ingest_line` (keep `ingest` itself unchanged):

```python
def _ingest_locked(sid, tp) -> None:
    summary = load_summary(sid)
    cur = summary.get("cursor")
    if cur is None:
        # pre-v0.2 sessions kept the cursor in a separate file; migrate it once
        cur = paths.read_json(_cursor_path(sid), {"offset": 0})
    off = cur.get("offset") if isinstance(cur, dict) else None
    if type(off) is not int or off < 0:
        cur = {"offset": 0}
    # If the stored cursor exceeds the current file size, the transcript was
    # truncated/rewritten. Re-parse from the beginning, keeping only agents:
    # counters are rebuilt and the state_mark baseline is gone with them.
    if cur["offset"] > os.path.getsize(tp):
        summary = _empty() | {"agents": summary.get("agents", {})}
        summary["degraded"] = True  # signals a reset happened
        cur = {"offset": 0}
    with open(tp, "rb") as f:
        f.seek(cur["offset"])
        data = f.read()
    # Only consume through the last complete line; a partial trailing line
    # (a writer mid-append) stays unread until its newline arrives.
    nl = data.rfind(b"\n")
    if nl >= 0:
        for raw in data[: nl + 1].splitlines():
            _ingest_line(summary, raw)
        cur["offset"] += nl + 1
    summary["cursor"] = cur
    paths.write_json_atomic(_summary_path(sid), summary)
    _cursor_path(sid).unlink(missing_ok=True)


def _ingest_line(summary, raw: bytes) -> None:
    try:
        line = raw.decode("utf-8").strip()
        if not line:
            return
        obj = json.loads(line)
        if not isinstance(obj, dict):
            return  # valid JSON but not a transcript record: carries no data
        _ingest_record(summary, obj)
    except Exception:
        summary["degraded"] = True


def _ingest_record(summary, obj) -> None:
    msg = obj.get("message") or {}
    usage = msg.get("usage") or {}
    if usage:
        total = (
            usage.get("input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
        )
        if total:
            summary["context_total"] = total
        summary["output_total"] = summary.get("output_total", 0) + usage.get("output_tokens", 0)
    content = msg.get("content")
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "tool_use":
            inp = block.get("input") or {}
            fp = inp.get("file_path") or inp.get("notebook_path")
            summary["pending"][block.get("id")] = {"tool": block.get("name"), "file": fp}
            if block.get("name") in EDIT_TOOLS and fp:
                for rid in summary["reads"].get(fp, []):
                    if rid in summary["results"]:
                        summary["results"][rid]["stale"] = True
        elif btype == "tool_result":
            tid = block.get("tool_use_id")
            meta = summary["pending"].pop(tid, {"tool": None, "file": None})
            size = tokens.estimate(tokens.to_text(block.get("content")))
            summary["results"][tid] = {
                "tool": meta["tool"],
                "tokens": size,
                "file": meta["file"],
                "stale": False,
            }
            if meta["tool"] == "Read" and meta["file"]:
                summary["reads"].setdefault(meta["file"], []).append(tid)
```

Note: the reset branch no longer preserves `state_mark` — that is intentional and is asserted by Task 2's tests. Update `tests/test_ledger.py::test_cursor_past_eof_reset` in THIS task to stop asserting `state_mark is not None` (replace that assert with `assert s["state_mark"] is None`); Task 2 owns the rest of the mark semantics.

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass (110 old − adjusted + 7 new). If `test_cursor_past_eof_reset` fails, you missed the Step 3 note.

- [ ] **Step 5: Commit**

```bash
git add tend/ledger.py tests/test_ledger.py
git commit -m "fix: ledger ingest survives partial lines, bad bytes, non-dict JSON, poisoned cursors (H1, M1, M2, L1, L2, L3)"
```

---

### Task 2: Staleness metric on monotonic output_total — H2, L7

- **H2**: after `/compact` or a truncation reset, `mark.context_total > context_total` makes `tokens_since_state_mark` negative, silently disabling the staleness reminder AND the stale-auto-compact block. STATE.md dead-end: `max(0, since)` does NOT fix it (it disables staleness the same way). The metric itself must be monotonic: mark `output_total`, which only grows while the session lives and is re-baselined (mark dropped, Task 1) on truncation resets.
- **L7**: first Stop of a session has no mark, so `boundary=True` fires even for a 30-day-old STATE.md. Fix: first Stop only baselines; `boundary=True` requires an mtime CHANGE against an existing mark.
- Semantics change: `state_stale_tokens` now counts OUTPUT tokens (which grow ~10× slower than context totals), so the default drops from 25000 to 3000. The missing-STATE.md branch switches to `output_total` too, for one consistent metric.

**Files:**
- Modify: `tend/ledger.py:123-134` (`set_state_mark`, `tokens_since_state_mark`)
- Modify: `tend/boundary.py:13-31`
- Modify: `tend/config.py:14` (default)
- Test: `tests/test_ledger.py`, `tests/test_boundary.py`

- [ ] **Step 1: Update the two existing tests that encode the old metric**

In `tests/test_ledger.py` replace `test_state_mark_roundtrip` with:

```python
def test_state_mark_roundtrip(tmp_path):
    tp = tmp_path / "t.jsonl"
    write_transcript(tp, fixture_lines())
    ledger.ingest(make_event(transcript_path=str(tp)))
    ledger.set_state_mark("s1", 123.0)
    s = ledger.load_summary("s1")
    assert s["state_mark"] == {"mtime": 123.0, "output_total": 170}  # 50+80+40
    assert ledger.tokens_since_state_mark(s) == 0
```

In `tests/test_boundary.py`, change `setup_summary` to take an output count and rewrite the first two tests:

```python
def setup_summary(total, output=0):
    paths.write_json_atomic(
        paths.session_dir("s1") / "summary.json",
        {"context_total": total, "output_total": output, "results": {}, "reads": {},
         "pending": {}, "agents": {}, "state_mark": None, "degraded": False},
    )


def test_first_stop_baselines_without_boundary(tmp_path):
    """L7: the first Stop has nothing to compare against - mark, but no boundary."""
    sp = state.path_for(str(tmp_path))
    state.seed(sp)
    setup_summary(50_000, output=2_000)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))
    fl = flags.load("s1")
    assert fl["boundary"] is False and fl["state_reminder"] is False
    assert ledger.load_summary("s1")["state_mark"]["output_total"] == 2_000


def test_state_update_sets_boundary(tmp_path):
    import os
    sp = state.path_for(str(tmp_path))
    state.seed(sp)
    setup_summary(50_000)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))  # baseline
    os.utime(sp, (sp.stat().st_atime, sp.stat().st_mtime + 5))              # STATE.md updated
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))
    assert flags.load("s1")["boundary"] is True


def test_stale_state_sets_reminder(tmp_path):
    sp = state.path_for(str(tmp_path))
    state.seed(sp)
    setup_summary(10_000, output=500)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))  # marks at 500
    setup_summary(40_000, output=9_500)  # 9k output tokens later, STATE.md untouched
    s = ledger.load_summary("s1")
    s["state_mark"] = {"mtime": sp.stat().st_mtime, "output_total": 500}
    paths.write_json_atomic(paths.session_dir("s1") / "summary.json", s)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))
    fl = flags.load("s1")
    assert fl["state_reminder"] is True and fl["boundary"] is False
```

And update the missing-STATE tests to the output metric:

```python
def test_missing_state_reminds_after_threshold(tmp_path):
    setup_summary(30_000, output=9_000)   # > 3000 default
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))
    assert flags.load("s1")["state_reminder"] is True


def test_missing_state_quiet_early(tmp_path):
    setup_summary(5_000, output=200)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))
    assert flags.load("s1")["state_reminder"] is False
```

- [ ] **Step 2: Add the new regression tests**

Append to `tests/test_ledger.py`:

```python
def test_since_never_negative_after_context_shrink():
    """H2: compaction shrinks context_total; output-based since stays correct."""
    summary = {"context_total": 30_000, "output_total": 5_000,
               "state_mark": {"mtime": 1.0, "output_total": 2_000}}
    assert ledger.tokens_since_state_mark(summary) == 3_000


def test_legacy_context_total_mark_returns_none():
    """Pre-v0.2 marks lack output_total: report unknown, never a bogus number."""
    summary = {"context_total": 10_000, "output_total": 100,
               "state_mark": {"mtime": 1.0, "context_total": 140_000}}
    assert ledger.tokens_since_state_mark(summary) is None
```

Append to `tests/test_boundary.py`:

```python
def test_boundary_remarks_legacy_mark(tmp_path):
    """A pre-v0.2 mark (context_total) is re-baselined on the next Stop, quietly."""
    sp = state.path_for(str(tmp_path))
    state.seed(sp)
    setup_summary(50_000, output=4_000)
    s = ledger.load_summary("s1")
    s["state_mark"] = {"mtime": sp.stat().st_mtime, "context_total": 140_000}
    paths.write_json_atomic(paths.session_dir("s1") / "summary.json", s)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))
    fl = flags.load("s1")
    assert fl["boundary"] is False and fl["state_reminder"] is False
    assert ledger.load_summary("s1")["state_mark"]["output_total"] == 4_000
```

Also add the H2 end-to-end guard to `tests/test_precompact.py`:

```python
def test_stale_auto_compact_blocked_even_after_context_shrink(tmp_path):
    """H2 repro: mark at high output, context shrank - the block must still fire."""
    from tend import ledger, paths, state

    sp = state.path_for(str(tmp_path))
    state.seed(sp)
    paths.write_json_atomic(paths.session_dir("s1") / "summary.json", {
        "context_total": 30_000, "output_total": 9_000, "results": {}, "reads": {},
        "pending": {}, "agents": {},
        "state_mark": {"mtime": sp.stat().st_mtime, "output_total": 1_000},
        "degraded": False,
    })
    out = precompact.handle(ev("auto", tmp_path))
    assert out == {"decision": "block", "reason": precompact.BLOCK_REASON}
```

- [ ] **Step 3: Run to verify the new/updated tests fail**

Run: `python3 -m pytest tests/test_ledger.py tests/test_boundary.py tests/test_precompact.py -q`
Expected: FAIL on the mark-format asserts and `boundary is False`.

- [ ] **Step 4: Implement**

`tend/ledger.py` — replace `set_state_mark` and `tokens_since_state_mark`:

```python
def set_state_mark(sid, mtime) -> None:
    with _locked(sid):
        s = load_summary(sid)
        # output_total only grows while the session lives (compaction shrinks
        # context_total), so "work since the mark" can never go negative.
        s["state_mark"] = {"mtime": mtime, "output_total": s.get("output_total", 0)}
        paths.write_json_atomic(_summary_path(sid), s)


def tokens_since_state_mark(summary):
    mark = summary.get("state_mark")
    if not mark or "output_total" not in mark:
        return None  # no mark, or a pre-v0.2 mark awaiting re-baseline
    return max(0, summary.get("output_total", 0) - mark["output_total"])
```

`tend/boundary.py` — replace the `sp.exists()` branch of `handle`:

```python
    if sp.exists():
        mtime = sp.stat().st_mtime
        mark = summary.get("state_mark")
        is_update = bool(mark) and mark.get("mtime") != mtime
        if not mark or is_update or "output_total" not in mark:
            ledger.set_state_mark(sid, mtime)
            flags.update(sid, state_reminder=False, boundary=is_update)
        else:
            since = ledger.tokens_since_state_mark(summary)
            flags.update(
                sid,
                state_reminder=since is not None and since > cfg.state_stale_tokens,
                boundary=False,
            )
    else:
        flags.update(
            sid,
            state_reminder=summary.get("output_total", 0) > cfg.state_stale_tokens,
            boundary=False,
        )
```

`tend/config.py` — change the default and document the unit:

```python
    "state_stale_tokens": 3000,  # OUTPUT tokens since the last STATE.md mark (monotonic)
```

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add tend/ledger.py tend/boundary.py tend/config.py tests/test_ledger.py tests/test_boundary.py tests/test_precompact.py
git commit -m "fix: staleness mark uses monotonic output_total; first Stop only baselines (H2, L7)"
```

---

### Task 3: Isolate ledger.ingest so one crash can't kill every handler — M3

`hook.py:14` runs `ledger.ingest` before the handler inside one fail-open try: any ingest exception silently disables offload/anchor/boundary/precompact for the whole session.

**Files:**
- Modify: `tend/hook.py:13-14`
- Modify: `tend/ledger.py` (add `mark_degraded`)
- Test: `tests/test_hook_dispatch.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hook_dispatch.py`:

```python
def test_handler_still_runs_when_ingest_crashes(tmp_path, monkeypatch):
    """M3: a poisoned ledger must degrade the ledger, not kill offload."""
    from tend import ledger as ledger_mod

    def boom(event):
        raise TypeError("'<' not supported between instances of 'str' and 'int'")

    monkeypatch.setattr(ledger_mod, "ingest", boom)
    ev = make_event(hook_event_name="PostToolUse", transcript_path="/nonexistent",
                    tool_name="Bash", tool_response="z" * 20000)
    out = hook.dispatch(ev)
    assert "updatedToolOutput" in out["hookSpecificOutput"]      # offload still ran
    assert ledger.load_summary("s1")["degraded"] is True         # and it's visible
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_hook_dispatch.py -q`
Expected: FAIL with TypeError propagating out of `dispatch`.

- [ ] **Step 3: Implement**

`tend/ledger.py` — add after `load_summary`:

```python
def mark_degraded(sid) -> None:
    """Best-effort flag: counts may be incomplete. Must never raise."""
    if not sid:
        return
    try:
        with _locked(sid):
            s = load_summary(sid)
            s["degraded"] = True
            paths.write_json_atomic(_summary_path(sid), s)
    except Exception:
        pass
```

`tend/hook.py` — replace the INGEST block in `dispatch`:

```python
    if name in INGEST:
        try:
            ledger.ingest(event)
        except Exception:
            # The ledger is an amplifier: one crash here must degrade the
            # ledger, not silently disable every handler behind it.
            hookio.log_error()
            ledger.mark_degraded(event.get("session_id"))
```

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tend/hook.py tend/ledger.py tests/test_hook_dispatch.py
git commit -m "fix: a ledger.ingest crash degrades the ledger instead of disabling all handlers (M3)"
```

---

### Task 4: Config validation — M4

`config.load` trusts YAML completely: empty values poison `Config` with `None`, `advise_pct: '55'` later TypeErrors inside fail-open (all hooks silently dead), `offload_tools: 42` TypeErrors at load, a top-level list AttributeErrors. Five handlers + the CLI call `load`.

**Files:**
- Modify: `tend/config.py:35-49`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_invalid_values_fall_back_to_defaults(tend_home):
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text(
        "advise_pct:\n"            # empty -> None
        "offload_tools: 42\n"      # wrong type
        "state_stale_tokens: [1]\n"
        "urge_pct: notanumber\n"
        "read_guard_bytes: -1\n"   # negative
    )
    cfg = config.load()
    assert cfg.advise_pct == 55
    assert cfg.offload_tools == ("Bash", "Grep", "Glob", "WebFetch")
    assert cfg.state_stale_tokens == config.DEFAULTS["state_stale_tokens"]
    assert cfg.urge_pct == 70
    assert cfg.read_guard_bytes == 65536


def test_numeric_string_coerced(tend_home):
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text('advise_pct: "60"\n')
    assert config.load().advise_pct == 60


def test_top_level_list_ignored(tend_home):
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text("- a\n- b\n")
    assert config.load().advise_pct == 55


def test_unparseable_yaml_ignored(tend_home):
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text("advise_pct: [unclosed\n")
    assert config.load().advise_pct == 55


def test_empty_offload_tools_disables_offload(tend_home):
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text("offload_tools: []\n")
    assert config.load().offload_tools == ()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_config.py -q`
Expected: FAIL (TypeError on `offload_tools: 42`, `None` poisoning, etc.).

- [ ] **Step 3: Implement**

Replace `load` in `tend/config.py` and add `_coerce`:

```python
def _coerce(key, value):
    """Return a usable value for key, or None to keep the current/default value."""
    if key == "offload_tools":
        if isinstance(value, str):
            return [value]
        if isinstance(value, list) and all(isinstance(t, str) for t in value):
            return value  # [] is legal: disables offloading
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value if value >= 0 else None
    if isinstance(value, str):
        try:
            return _coerce(key, int(value))
        except ValueError:
            try:
                return _coerce(key, float(value))
            except ValueError:
                return None
    return None


def load(cwd=None) -> Config:
    data = dict(DEFAULTS)
    candidates = [paths.home() / "config.yaml"]
    if cwd:
        candidates.append(Path(cwd) / ".claude" / "tend" / "config.yaml")
    for p in candidates:
        if not p.is_file():
            continue
        import yaml  # lazy: keeps hook startup fast when no config exists

        try:
            loaded = yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception:
            continue  # unparseable config must never kill the hooks
        if not isinstance(loaded, dict):
            continue
        for k, v in loaded.items():
            if k in DEFAULTS:
                v = _coerce(k, v)
                if v is not None:
                    data[k] = v
    data["offload_tools"] = tuple(data["offload_tools"])
    return Config(**data)
```

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass (existing config tests unaffected: scalar-string offload_tools still works through `_coerce`).

- [ ] **Step 5: Commit**

```bash
git add tend/config.py tests/test_config.py
git commit -m "fix: validate config values; bad YAML falls back to defaults instead of killing hooks (M4)"
```

---

### Task 5: Offload correctness — M6, M7, M8, L4

- **M6**: `offload_tail_tokens: 0` makes `text[-0:]` the WHOLE string — the "excerpt" contains the complete original plus banner, inflating context while claiming savings.
- **M7**: dict tool responses are saved as one line of `ensure_ascii` JSON; the advertised line-based `Read offset/limit` recovery is useless. Fix in `tokens.to_text`: Bash-style dicts render `stdout` + a `--- stderr ---` section; other non-strings render as `json.dumps(..., indent=2, ensure_ascii=False)`.
- **M8**: Claude Code silently rejects a plain-string replacement for MCP tools that declare an `outputSchema` ("...using original output") — tend writes the file and believes it saved tokens. We cannot see the schema from a hook, so: skip offload for `mcp__*` tools whose response is not a plain string, and document the limitation (Task 15).
- **L4**: the size guard ignores the ~170-char banner: a 2,450-char output became a 2,610-char replacement. Fix: after building the real excerpt, bail (and remove the saved file) unless it is strictly smaller than the original.

**Files:**
- Modify: `tend/tokens.py:5-13` (`to_text`)
- Modify: `tend/offload.py:7-31` (`handle`)
- Test: `tests/test_tokens.py`, `tests/test_offload.py`

- [ ] **Step 1: Update the one existing test that encodes 1-line JSON**

In `tests/test_tokens.py`, replace `test_to_text_passthrough_and_json` with:

```python
def test_to_text_passthrough_and_json():
    assert tokens.to_text("hi") == "hi"
    assert tokens.to_text(None) == ""
    out = tokens.to_text({"a": 1, "b": [1, 2]})
    assert "\n" in out          # line-addressable, not one escaped line
    assert '"a": 1' in out
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_tokens.py`:

```python
def test_to_text_bash_dict_renders_streams():
    s = tokens.to_text({"stdout": "out line\n", "stderr": "boom", "interrupted": False})
    assert s == "out line\n--- stderr ---\nboom"


def test_to_text_bash_dict_stdout_only():
    assert tokens.to_text({"stdout": "just out\n", "stderr": ""}) == "just out\n"


def test_to_text_unicode_not_escaped():
    assert "héllo" in tokens.to_text({"k": "héllo"})
```

Append to `tests/test_offload.py`:

```python
def test_tail_zero_offloads_head_only(tend_home):
    """M6: tail=0 must mean 'no tail', never 'the whole string'."""
    (tend_home / "config.yaml").parent.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text(
        "offload_threshold_tokens: 500\noffload_head_tokens: 100\noffload_tail_tokens: 0\n"
    )
    text = "H" * 400 + "m" * 4000
    out = offload.handle(make_event(tool_name="Bash", tool_response=text))
    repl = out["hookSpecificOutput"]["updatedToolOutput"]
    assert len(repl) < len(text)
    assert repl.startswith("H" * 400)
    assert "m" * 1000 not in repl          # the body is actually gone


def test_banner_overhead_never_inflates(tend_home):
    """L4: head+tail just under len(text), but banner pushes it over - skip, no file."""
    (tend_home / "config.yaml").parent.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text(
        "offload_threshold_tokens: 500\noffload_head_tokens: 300\noffload_tail_tokens: 300\n"
    )
    text = "x" * 2500                       # head+tail = 2400 < 2500, banner makes it bigger
    assert offload.handle(make_event(tool_name="Bash", tool_response=text)) is None
    assert list((paths.session_dir("s1") / "outputs").glob("*.txt")) == []


def test_mcp_structured_response_not_offloaded(tend_home):
    """M8: schema'd MCP outputs would be silently rejected by Claude Code - don't pretend."""
    (tend_home / "config.yaml").parent.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text('offload_tools: ["mcp__db__query"]\n')
    ev = make_event(tool_name="mcp__db__query", tool_response={"rows": ["x" * 20000]})
    assert offload.handle(ev) is None
    assert list((paths.session_dir("s1") / "outputs").glob("*.txt")) == []


def test_mcp_plain_string_response_still_offloaded(tend_home):
    (tend_home / "config.yaml").parent.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text('offload_tools: ["mcp__db__query"]\n')
    ev = make_event(tool_name="mcp__db__query", tool_response="x" * 20000)
    assert offload.handle(ev) is not None


def test_bash_dict_offload_file_is_line_addressable(tend_home):
    """M7 live-artifact repro: the saved file must have real newlines, not escaped JSON."""
    resp = {"stdout": "line\n" * 4000, "stderr": ""}
    out = offload.handle(make_event(tool_name="Bash", tool_response=resp))
    assert out is not None
    saved = next((paths.session_dir("s1") / "outputs").glob("*.txt")).read_text()
    assert saved.startswith("line\nline\n")
    assert '"stdout"' not in saved
```

- [ ] **Step 3: Run to verify they fail**

Run: `python3 -m pytest tests/test_tokens.py tests/test_offload.py -q`
Expected: the new tests FAIL.

- [ ] **Step 4: Implement**

`tend/tokens.py` — replace `to_text`:

```python
def to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("stdout"), str):
        # Command-style payload (Bash et al.): render the streams themselves so
        # offloaded files stay line-addressable for Read offset/limit.
        text = value["stdout"]
        err = value.get("stderr")
        if isinstance(err, str) and err.strip():
            if text and not text.endswith("\n"):
                text += "\n"
            text += "--- stderr ---\n" + err
        return text
    try:
        return json.dumps(value, indent=2, ensure_ascii=False)
    except Exception:
        return str(value)
```

`tend/offload.py` — replace `handle`:

```python
def handle(event):
    cfg = config.load(event.get("cwd"))
    tool = event.get("tool_name") or ""
    if tool not in cfg.offload_tools:
        return None
    raw = event.get("tool_response", event.get("tool_result", ""))
    if tool.startswith("mcp__") and not isinstance(raw, str):
        # Structured MCP outputs may carry an outputSchema; Claude Code silently
        # rejects a plain-text replacement, so offloading would save nothing.
        return None
    text = tokens.to_text(raw)
    n = tokens.estimate(text)
    if n < cfg.offload_threshold_tokens:
        return None
    head = text[: cfg.offload_head_tokens * 4] if cfg.offload_head_tokens else ""
    tail = text[-cfg.offload_tail_tokens * 4 :] if cfg.offload_tail_tokens else ""
    if len(head) + len(tail) >= len(text):
        return None
    path = _save(event.get("session_id", "unknown"), text)
    omitted = max(0, n - cfg.offload_head_tokens - cfg.offload_tail_tokens)
    excerpt = (
        f"{head}\n\n[tend: ~{omitted} tokens offloaded]\n\n{tail}\n\n"
        f"[tend] Full output saved to {path} - Read it (with offset/limit) only if needed."
    )
    if len(excerpt) >= len(text):
        os.unlink(path)  # banner overhead would inflate, not shrink
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "updatedToolOutput": excerpt,
        }
    }
```

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass. Watch `test_overlap_guard_skips_offload_when_excerpt_not_smaller` (still passes: head+tail ≥ text short-circuits before any file write) and `test_dict_response_serialized` (stdout dict now renders as the raw string — still > threshold, still offloads).

- [ ] **Step 6: Commit**

```bash
git add tend/tokens.py tend/offload.py tests/test_tokens.py tests/test_offload.py
git commit -m "fix: offload honors tail=0, accounts banner size, renders dict outputs line-addressable, skips structured MCP outputs (M6, M7, M8, L4)"
```

---

### Task 6: Anchor keeps the urgent tail and reports bloat-only states — M9, L6

- **M9**: `text[:max_tokens*4]` truncates from the END — a 1,700-char Goal evicts `Health:` and the "run now: /compact" urge, the most urgent lines. Fix: clip Goal/Now to 200 chars each at assembly; if still over budget, drop whole lines from the FRONT (the tail is the urgent part).
- **L6**: the emit gate omits `bloat_tokens` — a bloat-only session suppresses the very anchor that would report it.

**Files:**
- Modify: `tend/anchor.py:5-51`
- Test: `tests/test_anchor.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_anchor.py`:

```python
def test_anchor_keeps_urgent_tail_over_goal(tmp_path):
    """M9: a huge Goal must never evict Health and the compaction urge."""
    seed_state(tmp_path, goal="g" * 1700)
    seed_ctx(85)
    ctx = anchor.handle(ev(tmp_path))["hookSpecificOutput"]["additionalContext"]
    assert "Health:" in ctx
    assert "run now: /compact" in ctx
    assert len(ctx) <= 400 * 4


def test_anchor_emitted_for_bloat_only_state(tmp_path):
    """L6: 9k tokens of oversized results alone must produce an anchor that says so."""
    paths.write_json_atomic(paths.session_dir("s1") / "summary.json", {
        "context_total": 0, "output_total": 0,
        "results": {"big": {"tool": "Bash", "tokens": 9000, "file": None, "stale": False}},
        "reads": {}, "pending": {}, "agents": {}, "state_mark": None, "degraded": False,
    })
    out = anchor.handle(ev(tmp_path))
    assert out is not None
    assert "oversized results" in out["hookSpecificOutput"]["additionalContext"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_anchor.py -q`
Expected: both FAIL (`run now` truncated away; bloat-only returns None).

- [ ] **Step 3: Implement**

Replace `tend/anchor.py` `handle` and helpers:

```python
MAX_LINE_CHARS = 200


def handle(event):
    sid = event.get("session_id")
    if not sid:
        return None
    cwd = event.get("cwd") or "."
    cfg = config.load(cwd)
    summary = ledger.load_summary(sid)
    fl = flags.load(sid)
    sp = state.path_for(cwd)
    goal, now = state.goal_now(sp)
    pct = ctxmetrics.used_pct(sid)
    stale = ledger.stale_tokens(summary)
    bloat = ledger.bloat_tokens(summary, cfg.offload_threshold_tokens)

    if not goal and not now and pct is None and not stale and not bloat \
            and not fl.get("state_reminder"):
        return None

    lines = []
    if goal:
        lines.append(f"Goal: {_clip(goal)}")
    if now:
        lines.append(f"Now: {_clip(now)}")
    lines.append(_health_line(pct, stale, bloat))
    if fl.get("state_reminder"):
        lines.append(
            "STATE.md is stale - update .claude/tend/STATE.md "
            "(Now/Decisions/Dead-ends) before continuing."
        )
    adv = advisor.advice(pct, cfg, sp, fl)
    if adv:
        lines.append(adv)
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": _fit(lines, cfg.anchor_max_tokens * 4),
        }
    }


def _clip(s):
    return s if len(s) <= MAX_LINE_CHARS else s[: MAX_LINE_CHARS - 1] + "…"


def _render(lines):
    return "[tend anchor]\n" + "\n".join(lines)


def _fit(lines, budget):
    """Later lines (health, staleness, compaction urge) outrank Goal/Now: when over
    budget, drop whole lines from the front, never truncate the tail."""
    out = list(lines)
    while len(out) > 1 and len(_render(out)) > budget:
        out.pop(0)
    return _render(out)[:budget]


def _health_line(pct, stale, bloat):
    parts = [f"context {pct:.0f}% used" if pct is not None else "context usage unknown"]
    if stale:
        parts.append(f"~{stale:,} tok of stale tool results")
    if bloat:
        parts.append(f"~{bloat:,} tok in oversized results")
    return "Health: " + ", ".join(parts)
```

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass (`test_anchor_truncated_to_budget` still holds — the 10,000-char goal is clipped to 200).

- [ ] **Step 5: Commit**

```bash
git add tend/anchor.py tests/test_anchor.py
git commit -m "fix: anchor keeps urgent tail when over budget and fires for bloat-only states (M9, L6)"
```

---

### Task 7: PreCompact never blocks in $HOME — M5

`~/.claude/tend/STATE.md` can never exist (`sessionstart` refuses to seed `$HOME`), so the first auto-compact of any home-dir session is always blocked, then the anchor nags every prompt.

**Files:**
- Modify: `tend/precompact.py:26-29` (`_is_stale`)
- Test: `tests/test_precompact.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_precompact.py`:

```python
def test_auto_compact_never_blocked_in_home(tend_home):
    """M5: sessionstart never seeds $HOME, so STATE.md can't exist there - don't block."""
    from pathlib import Path

    out = precompact.handle(make_event(
        hook_event_name="PreCompact", trigger="auto", cwd=str(Path.home())))
    assert out is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_precompact.py -q`
Expected: FAIL (block fires). Caution: if YOUR real `~/.claude/tend/STATE.md` exists the test could pass vacuously — it must fail before the fix because `_is_stale` returns True for a missing file; if it passes immediately, delete nothing, just verify by reading the code path (the real home STATE.md is outside `TEND_HOME` isolation; `state.path_for` is cwd-relative so it resolves to the real `~/.claude/tend/STATE.md` — on this machine that file does not exist, so the test fails correctly).

- [ ] **Step 3: Implement**

In `tend/precompact.py`, add `from pathlib import Path` to the imports and change `_is_stale`:

```python
def _is_stale(event, cfg) -> bool:
    cwd = event.get("cwd") or "."
    if Path(cwd).resolve() == Path.home().resolve():
        return False  # $HOME is never seeded (see sessionstart); never block there
    sp = state.path_for(cwd)
    if not sp.exists():
        return True
    summary = ledger.load_summary(event.get("session_id"))
    mark = summary.get("state_mark")
    if mark and mark.get("mtime") != sp.stat().st_mtime:
        return False  # updated since our last mark: fresh
    # No mark ever set (no Stop yet): tokens_since returns None -> treat as not stale.
    since = ledger.tokens_since_state_mark(summary)
    return since is not None and since > cfg.state_stale_tokens
```

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tend/precompact.py tests/test_precompact.py
git commit -m "fix: never block auto-compact in the home directory (M5)"
```

---

### Task 8: Install/uninstall robustness — M10, M11, L13, L14, L17

- **M10**: uninstall drops a WHOLE hooks entry if any inner hook matches — a user hook merged into the same entry is destroyed. Fix: prune inner commands; drop the entry only when its `hooks` list empties (mirrors swarm commit a51df19).
- **M11**: marker-substring idempotency means a dead interpreter path persists across reinstall while the CLI prints success. Fix: install rewrites every marked command (and a tend statusLine) to the CURRENT interpreter.
- **L13**: reinstall after the statusLine was externally removed unlinks `statusline-original.json` — the only copy of the user's statusline. Fix: install never deletes the saved original.
- **L14**: `"hooks": null` or a string statusLine raise raw AttributeError past the CLI's `except SettingsError`. Fix: tolerate/repair malformed shapes; non-object top level raises SettingsError.
- **L17**: the backup is created by `write_text` under default umask, then chmod'd — 0600 settings are world-readable in the window (or forever, on a crash between the calls). Fix: create the backup `os.open(..., mode)` + `fchmod` before content is written; pass the mode into `write_json_atomic` so the settings tmp file is born restrictive too.

**Files:**
- Modify: `tend/install.py` (most of the file)
- Modify: `tend/paths.py:32-37` (`write_json_atomic` gains `mode=`)
- Test: `tests/test_install.py`

- [ ] **Step 1: Update the one existing test that encodes the L13 bug as a feature**

In `tests/test_install.py`, replace `test_install_without_statusline_leaves_no_original` with:

```python
def test_reinstall_preserves_saved_original_when_statusline_removed(tmp_path, tend_home):
    """L13: the saved original may be the only copy of the user's statusline - keep it."""
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps(EXISTING))
    install.install(sp)                     # saves the user's statusline.sh original
    s = json.loads(sp.read_text())
    del s["statusLine"]                     # user (or another tool) removed the wrapper
    sp.write_text(json.dumps(s))
    install.install(sp)                     # reinstall must NOT destroy the original
    orig = paths.read_json(tend_home / "statusline-original.json")
    assert orig and "statusline.sh" in orig["command"]
    install.uninstall(sp)                   # and uninstall can still restore it
    assert "statusline.sh" in json.loads(sp.read_text())["statusLine"]["command"]
```

- [ ] **Step 2: Write the remaining failing tests**

Append to `tests/test_install.py` (add `import os`, `import stat` to its imports):

```python
def test_uninstall_preserves_user_hook_in_shared_entry(tmp_path):
    """M10: prune tend's inner command, keep the user's, keep entry metadata."""
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({"hooks": {"PostToolUse": [{"matcher": "*", "hooks": [
        {"type": "command", "command": "python3 -m other.hook"},
        {"type": "command", "command": '"/usr/bin/python3" -m tend.hook'},
    ]}]}}))
    install.uninstall(sp)
    s = json.loads(sp.read_text())
    entry = s["hooks"]["PostToolUse"][0]
    assert [h["command"] for h in entry["hooks"]] == ["python3 -m other.hook"]
    assert entry["matcher"] == "*"


def test_reinstall_repairs_dead_interpreter(tmp_path, tend_home):
    """M11: a stale '/old/dead/python' must be rewritten to the current interpreter."""
    dead_hook = '"/old/dead/python" -m tend.hook'
    settings = {"hooks": {ev: [{"hooks": [{"type": "command", "command": dead_hook}]}]
                          for ev in install.HOOK_EVENTS},
                "statusLine": {"type": "command",
                               "command": '"/old/dead/python" -m tend.statusline'}}
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps(settings))
    install.install(sp)
    s = json.loads(sp.read_text())
    for ev in install.HOOK_EVENTS:
        cmds = [h["command"] for e in s["hooks"][ev] for h in e["hooks"]]
        assert cmds == [install.hook_command()], ev   # repaired, not duplicated
    assert s["statusLine"]["command"] == install.statusline_command()
    # repairing our own statusline must not overwrite the saved original
    assert not (tend_home / "statusline-original.json").exists()


def test_null_hooks_and_string_statusline_handled(tmp_path, tend_home):
    """L14: malformed-but-parseable settings must round-trip, not AttributeError."""
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({"hooks": None, "statusLine": "echo hi"}))
    install.install(sp)
    s = json.loads(sp.read_text())
    assert "-m tend.statusline" in s["statusLine"]["command"]
    assert paths.read_json(tend_home / "statusline-original.json") == "echo hi"
    install.uninstall(sp)
    assert json.loads(sp.read_text())["statusLine"] == "echo hi"


def test_top_level_array_raises_settings_error(tmp_path):
    sp = tmp_path / "settings.json"
    sp.write_text("[1, 2]")
    with pytest.raises(install.SettingsError):
        install.install(sp)
    with pytest.raises(install.SettingsError):
        install.uninstall(sp)
    assert sp.read_text() == "[1, 2]"


def test_backup_and_settings_keep_restrictive_mode(tmp_path):
    """L17: a 0600 settings file must yield a 0600 backup and stay 0600 itself."""
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps(EXISTING))
    os.chmod(sp, 0o600)
    install.install(sp)
    assert stat.S_IMODE(os.stat(tmp_path / "settings.json.bak-tend").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(sp).st_mode) == 0o600
```

- [ ] **Step 3: Run to verify they fail**

Run: `python3 -m pytest tests/test_install.py -q`
Expected: the 6 new/updated tests FAIL (AttributeError for L14, user hook destroyed for M10, dead path kept for M11, 0o644 backup for L17).

- [ ] **Step 4: Implement**

`tend/paths.py` — extend `write_json_atomic`:

```python
def write_json_atomic(path, obj, indent=None, mode=None) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, indent=indent), encoding="utf-8")
    if mode is not None:
        os.chmod(tmp, mode)
    tmp.replace(p)
```

`tend/install.py` — add `import stat` to the imports; replace `_load_settings`, `install`, `uninstall`, `_has_marker` (delete it), `_write_settings`:

```python
def _load_settings(sp: Path) -> dict:
    if not sp.exists():
        return {}
    try:
        loaded = json.loads(sp.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SettingsError(
            f"{sp} exists but is not valid JSON ({e}). Fix it manually or restore "
            f"{sp.name}.bak-tend before running tend install-hook/uninstall-hook."
        ) from e
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise SettingsError(
            f"{sp} must contain a JSON object at the top level, "
            f"not {type(loaded).__name__}."
        )
    return loaded


def install(settings_path) -> None:
    sp = Path(settings_path).resolve()
    settings = _load_settings(sp)
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = settings["hooks"] = {}
    for ev in HOOK_EVENTS:
        entries = hooks.get(ev)
        if not isinstance(entries, list):
            entries = hooks[ev] = []
        if not _refresh_marked(entries, HOOK_MARKER, hook_command()):
            entries.append({"hooks": [{"type": "command", "command": hook_command()}]})
    sl = settings.get("statusLine")
    if sl and not _is_tend_statusline(sl):
        paths.write_json_atomic(paths.home() / "statusline-original.json", sl)
    # Never delete a saved original here: after an external removal of our
    # wrapper it can be the only copy of the user's statusline.
    settings["statusLine"] = {"type": "command", "command": statusline_command()}
    _write_settings(sp, settings)


def uninstall(settings_path) -> None:
    sp = Path(settings_path).resolve()
    settings = _load_settings(sp)
    changed = False
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    for ev in list(hooks):
        if not isinstance(hooks[ev], list):
            continue
        pruned, ev_changed = _prune_entries(hooks[ev])
        if ev_changed:
            changed = True
            if pruned:
                hooks[ev] = pruned
            else:
                del hooks[ev]
    sl = settings.get("statusLine")
    if _is_tend_statusline(sl):
        changed = True
        orig = paths.read_json(paths.home() / "statusline-original.json")
        if orig:
            settings["statusLine"] = orig
        else:
            settings.pop("statusLine", None)
        (paths.home() / "statusline-original.json").unlink(missing_ok=True)
    if not changed:
        return
    _write_settings(sp, settings)


def _prune_entries(entries):
    """Remove tend's inner hook commands; drop an entry only when emptied (M10)."""
    pruned, changed = [], False
    for e in entries:
        inner = e.get("hooks") if isinstance(e, dict) else None
        if not isinstance(inner, list):
            pruned.append(e)
            continue
        kept = [h for h in inner
                if not (isinstance(h, dict) and HOOK_MARKER in (h.get("command") or ""))]
        if len(kept) == len(inner):
            pruned.append(e)
            continue
        changed = True
        if kept:
            pruned.append({**e, "hooks": kept})
    return pruned, changed


def _refresh_marked(entries, marker, command) -> bool:
    """Repoint existing tend hooks at the current interpreter; True if any found (M11)."""
    found = False
    for e in entries:
        if not isinstance(e, dict):
            continue
        for h in e.get("hooks") or []:
            if isinstance(h, dict) and marker in (h.get("command") or ""):
                h["command"] = command
                found = True
    return found


def _is_tend_statusline(sl) -> bool:
    return isinstance(sl, dict) and STATUSLINE_MARKER in (sl.get("command") or "")


def _write_settings(sp, settings) -> None:
    backup = sp.with_name(sp.name + ".bak-tend")
    mode = None
    if sp.exists():
        mode = stat.S_IMODE(sp.stat().st_mode)
        current_text = sp.read_text(encoding="utf-8")
        # Born with the source's mode: no window where 0600 content sits at 0644 (L17)
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            os.fchmod(fd, mode)  # O_CREAT mode is masked by umask; pin it exactly
            f.write(current_text)
    paths.write_json_atomic(sp, settings, indent=2, mode=mode)
```

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass. `test_install_idempotent` still holds (refresh writes identical content); `test_uninstall_restores` still holds (tend-only entries empty out and are dropped).

- [ ] **Step 6: Commit**

```bash
git add tend/install.py tend/paths.py tests/test_install.py
git commit -m "fix: uninstall prunes inner hooks, reinstall repairs interpreter paths, settings shapes validated, backups keep mode (M10, M11, L13, L14, L17)"
```

---

### Task 9: hookio — Ctrl-C handling and log rotation — L8, L9

- **L8**: `run_fail_open` catches BaseException but `log_error` guards only Exception: a KeyboardInterrupt during logging escapes the wrapper, and a routine Ctrl-C gets logged as an error traceback.
- **L9**: `tend.log` grows forever. Rotate to `tend.log.1` past 1 MB. Statusline's inline log write moves to the same helper.

**Files:**
- Modify: `tend/hookio.py`
- Modify: `tend/statusline.py:31-37` (use `hookio.append_log`)
- Test: `tests/test_hookio.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hookio.py` (ensure `import io`, `from tend import hookio, paths` are present):

```python
def test_keyboard_interrupt_neither_raises_nor_logs(tend_home, monkeypatch):
    """L8: routine Ctrl-C is not a tend error - swallow it, log nothing."""
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))

    def handler(event):
        raise KeyboardInterrupt

    assert hookio.run_fail_open(handler) == 0
    assert not paths.log_path().exists()


def test_log_rotates_at_cap(tend_home):
    """L9: a persistent fault must not grow tend.log without bound."""
    paths.home().mkdir(parents=True, exist_ok=True)
    paths.log_path().write_text("x" * (hookio.MAX_LOG_BYTES + 1))
    hookio.append_log("new entry\n")
    assert (tend_home / "tend.log.1").exists()
    assert paths.log_path().read_text() == "new entry\n"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_hookio.py -q`
Expected: FAIL (KeyboardInterrupt traceback logged / AttributeError on missing `MAX_LOG_BYTES`).

- [ ] **Step 3: Implement**

`tend/hookio.py` — replace `log_error` and `run_fail_open`, add `append_log`:

```python
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
        pass  # routine Ctrl-C: not a tend error, nothing to log
    except BaseException:
        log_error()
    return 0
```

`tend/statusline.py` — replace the stderr-logging block inside `main` (lines 31-37) with:

```python
            if res.stderr:
                from . import hookio

                hookio.append_log(f"statusline-original stderr: {res.stderr}\n")
```

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tend/hookio.py tend/statusline.py tests/test_hookio.py
git commit -m "fix: swallow Ctrl-C without logging, rotate tend.log at 1MB (L8, L9)"
```

---

### Task 10: STATE.md I/O — truncation marker, atomic seed, explicit UTF-8 — L10, L11, L12

- **L10**: `read_text()[:16000]` silently tail-truncates the restored state (Dead-ends vanish while the PREAMBLE claims full state). Cut at a line boundary and append a visible marker pointing at the file.
- **L11**: `seed()` is check-then-write with plain `write_text`. Use `O_CREAT|O_EXCL`.
- **L12**: STATE.md reads/writes omit `encoding="utf-8"` (ASCII-locale crash → fail-open skips restore; latin-1 mojibake). Pin utf-8 in `state.py`, `sessionstart.py`, and `cli.cmd_handoff`.

**Files:**
- Modify: `tend/state.py:28-46`, `tend/sessionstart.py:33-34`, `tend/cli.py:109`
- Test: `tests/test_sessionstart.py`, `tests/test_state.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sessionstart.py`:

```python
def test_oversized_state_truncated_with_visible_marker(tmp_path):
    """L10: a >16k STATE.md must say it was cut and where to read the rest."""
    sp = state.path_for(str(tmp_path))
    sp.parent.mkdir(parents=True)
    sp.write_text("## Goal\nShip it\n" + ("filler line\n" * 2000), encoding="utf-8")
    ctx = sessionstart.handle(ev(tmp_path))["hookSpecificOutput"]["additionalContext"]
    assert "truncated" in ctx
    assert str(sp) in ctx
    assert len(ctx) < 17000
    # cut lands on a line boundary: no half line right before the marker
    body = ctx.split("\n[tend] STATE.md truncated")[0]
    assert body.endswith("filler line")
```

Append to `tests/test_state.py`:

```python
def test_seed_is_atomic_o_excl(tmp_path, monkeypatch):
    """L11: two concurrent seeds must not clobber - second open(O_EXCL) loses quietly."""
    import os as os_mod

    p = state.path_for(str(tmp_path))
    real_open = os_mod.open
    calls = {}

    def racing_open(path, flags, *a, **kw):
        if str(path) == str(p) and not calls:
            calls["raced"] = True
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("winner", encoding="utf-8")  # the rival session wins the race
        return real_open(path, flags, *a, **kw)

    monkeypatch.setattr(state.os, "open", racing_open)
    state.seed(p)  # must not raise, must not overwrite
    assert p.read_text(encoding="utf-8") == "winner"


def test_unicode_state_roundtrip(tmp_path):
    """L12: explicit utf-8 - non-ASCII goals survive regardless of locale."""
    p = state.path_for(str(tmp_path))
    p.parent.mkdir(parents=True)
    p.write_bytes("## Goal\nnaïve café ✓\n".encode("utf-8"))
    goal, _ = state.goal_now(p)
    assert goal == "naïve café ✓"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_sessionstart.py tests/test_state.py -q`
Expected: L10 and L11 tests FAIL (no marker; FileExistsError raised). The unicode test may already pass under a UTF-8 locale — it pins the behavior.

- [ ] **Step 3: Implement**

`tend/state.py` — add `import os` to imports; replace `seed` and the two `read_text()` calls:

```python
def seed(path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        return  # another session seeded first; theirs wins
    except OSError:
        return
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(TEMPLATE)
```

In `read_sections`, change `path.read_text()` to `path.read_text(encoding="utf-8")`.

`tend/sessionstart.py` — replace the fresh-state branch of `handle`:

```python
    if state.is_fresh(sp, cfg.state_fresh_hours):
        text = sp.read_text(encoding="utf-8")
        if len(text) > MAX_INJECT_CHARS:
            cut = text.rfind("\n", 0, MAX_INJECT_CHARS)
            text = text[: cut if cut > 0 else MAX_INJECT_CHARS]
            text += f"\n[tend] STATE.md truncated for injection - read the rest at {sp}"
        return _ctx(PREAMBLE + text)
```

`tend/cli.py` — in `cmd_handoff`, change `print(sp.read_text())` to `print(sp.read_text(encoding="utf-8"))`.

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tend/state.py tend/sessionstart.py tend/cli.py tests/test_sessionstart.py tests/test_state.py
git commit -m "fix: visible STATE.md truncation marker, O_EXCL seed, explicit utf-8 (L10, L11, L12)"
```

---

### Task 11: Readguard skips binary files — L5

A 1 MB PNG gets "~262,144 tokens" advice and an inapplicable offset/limit suggestion. Sniff the first 4 KB for NUL bytes; binary files get no nudge (Claude Code handles images natively).

**Files:**
- Modify: `tend/readguard.py:16-22`
- Test: `tests/test_readguard.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_readguard.py` (match its existing event-building style; use `make_event` from conftest with `tool_input`):

```python
def test_binary_file_not_nudged(tmp_path):
    """L5: bytes//4 'tokens' and offset/limit advice are meaningless for a PNG."""
    big = tmp_path / "img.png"
    big.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 70000)
    out = readguard.handle(make_event(
        tool_name="Read", tool_input={"file_path": str(big)}))
    assert out is None


def test_large_text_file_still_nudged(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("line\n" * 20000)  # 100k chars
    out = readguard.handle(make_event(
        tool_name="Read", tool_input={"file_path": str(f)}))
    assert "offset/limit" in out["hookSpecificOutput"]["additionalContext"]
```

- [ ] **Step 2: Run to verify the binary test fails**

Run: `python3 -m pytest tests/test_readguard.py -q`
Expected: `test_binary_file_not_nudged` FAILS (nudge fires with a bogus token count).

- [ ] **Step 3: Implement**

In `tend/readguard.py`, after the `size <= cfg.read_guard_bytes` check and before the return, insert:

```python
    try:
        with open(fp, "rb") as fh:
            if b"\0" in fh.read(4096):
                return None  # binary: token math and offset/limit advice don't apply
    except OSError:
        return None
```

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tend/readguard.py tests/test_readguard.py
git commit -m "fix: readguard skips binary files (L5)"
```

---

### Task 12: Statusline — fail-open main, pct coercion, honor the kill switch — L15, L18

- **L15**: `f"{pct:.0f}"` on a non-numeric `used_percentage` crashes the whole statusline (blank bar); `main()` has no outer fail-open.
- **L18**: with `$TEND_HOME/disabled` present the wrapper still writes `ctx.json`. The kill switch must stop tend's writes; the passthrough to the original statusline stays (removing the user's statusbar is not what `tend off` means).

**Files:**
- Modify: `tend/statusline.py`
- Test: `tests/test_statusline.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_statusline.py`:

```python
def test_non_numeric_pct_never_blanks_the_bar(monkeypatch, capsys, tend_home):
    """L15: a weird used_percentage must degrade to a line without ctx, not crash."""
    bad = json.dumps({"session_id": "s9", "model": {"display_name": "Fable"},
                      "context_window": {"used_percentage": "??"}})
    monkeypatch.setattr("sys.stdin", io.StringIO(bad))
    assert statusline.main() == 0
    out = capsys.readouterr().out
    assert "Fable" in out


def test_disabled_skips_tee_but_keeps_passthrough(monkeypatch, capsys, tend_home):
    """L18: tend off = no tend writes; the user's statusline still renders."""
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "disabled").touch()
    paths.write_json_atomic(
        tend_home / "statusline-original.json",
        {"type": "command", "command": "echo ORIGINAL-LINE"},
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(STATUS_JSON))
    statusline.main()
    assert "ORIGINAL-LINE" in capsys.readouterr().out
    assert not (tend_home / "sessions" / "s9" / "ctx.json").exists()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_statusline.py -q`
Expected: both FAIL (ValueError on `'??'`; ctx.json written while disabled).

- [ ] **Step 3: Implement**

Replace `tend/statusline.py` `main` with a fail-open wrapper plus `_main`:

```python
def main() -> int:
    try:
        return _main()
    except Exception:
        sys.stdout.write("tend\n")  # a broken wrapper must never blank the statusbar
        return 0


def _main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    sid = data.get("session_id")
    if sid and not paths.disabled():  # kill switch: no tend writes while off
        try:
            paths.write_json_atomic(paths.session_dir(sid) / "ctx.json", data)
        except Exception:
            pass
    orig = paths.read_json(paths.home() / "statusline-original.json")
    if isinstance(orig, dict) and orig.get("command"):
        try:
            res = subprocess.run(
                orig["command"], shell=True, input=raw, capture_output=True, text=True, timeout=10
            )
            if res.returncode == 0 and res.stdout:
                sys.stdout.write(res.stdout)
                return 0
            if res.stderr:
                from . import hookio

                hookio.append_log(f"statusline-original stderr: {res.stderr}\n")
        except Exception:
            pass
    model = (data.get("model") or {}).get("display_name", "")
    pct = (data.get("context_window") or {}).get("used_percentage")
    line = model or "tend"
    if pct is not None:
        try:
            line += f" | ctx {float(pct):.0f}%"
        except (TypeError, ValueError):
            pass
    sys.stdout.write(line + "\n")
    return 0
```

(If Task 9 already moved the stderr logging to `hookio.append_log`, keep that form — this listing already includes it.)

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tend/statusline.py tests/test_statusline.py
git commit -m "fix: statusline fails open, coerces pct, honors tend off for its own writes (L15, L18)"
```

---

### Task 13: CLI survives vanishing tmp files — L16

`is_file()`-then-`stat()` races against the pid-named `.tmp` files `write_json_atomic` creates in the same dirs; `tend status` crashes with FileNotFoundError. One tolerant `_session_mtime` used by both call sites.

**Files:**
- Modify: `tend/cli.py:9-11,35-40`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_session_mtime_tolerates_vanishing_files(tmp_path, monkeypatch):
    """L16: a .tmp file deleted between listing and stat must not crash status."""
    import contextlib

    d = tmp_path / "sess"
    d.mkdir()

    class Vanished:
        name = "summary.json.123.tmp"

        def is_file(self):
            return True

        def stat(self):
            raise FileNotFoundError("vanished between listing and stat")

    @contextlib.contextmanager
    def fake_scandir(path):
        yield iter([Vanished()])

    monkeypatch.setattr(cli.os, "scandir", fake_scandir)
    assert cli._session_mtime(d) == d.stat().st_mtime
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_cli.py -q`
Expected: FAIL — `cli` has no `os` import yet / `_session_mtime` uses `iterdir` and raises.

- [ ] **Step 3: Implement**

In `tend/cli.py`: add `import os` to the imports, replace `_session_mtime`, and use it in `cmd_status`:

```python
def _session_mtime(d):
    """Newest mtime in d, tolerating files that vanish mid-scan (atomic-write tmps)."""
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
        return d.stat().st_mtime
    except OSError:
        return 0.0
```

In `cmd_status`, replace the `newest = max((f.stat().st_mtime ...), default=None)` block with:

```python
    newest = _session_mtime(paths.home() / "sessions" / sid)
    if newest:
        print(f"last hook activity {(time.time() - newest) / 60:.1f}m ago")
```

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: all pass (`test_status_contains_last_hook_activity` still holds).

- [ ] **Step 5: Commit**

```bash
git add tend/cli.py tests/test_cli.py
git commit -m "fix: tend status tolerates files vanishing mid-scan (L16)"
```

---

### Task 14: Documentation + STATE.md close-out — M8 caveat, changed semantics

**Files:**
- Modify: `README.md` (add a Limitations note + config-semantics note)
- Modify: `.claude/tend/STATE.md` (record completion)

- [ ] **Step 1: Add a Limitations section to README.md**

Read the README first to find the right place (after the config section if one exists). Add:

```markdown
## Limitations

- **MCP tools with an `outputSchema`** (M8): Claude Code validates replacement
  outputs against the tool's schema and silently keeps the original when a plain
  text excerpt doesn't match. tend therefore skips offloading for `mcp__*` tools
  whose responses aren't plain strings. Built-in tools (Bash, Grep, Glob,
  WebFetch) are unaffected.
- `state_stale_tokens` counts **output tokens** generated since STATE.md was
  last marked (monotonic across compaction), not context-window growth.
  Default: 3000.
```

- [ ] **Step 2: Update `.claude/tend/STATE.md`**

Set `## Now` to: `Bug-fix round complete: all 31 confirmed findings fixed with regression tests; full suite green. Next: professional README + push to GitHub (varmabudharaju/tend).` Append to `## Files touched` the modules changed in this round.

- [ ] **Step 3: Full suite + commit**

Run: `python3 -m pytest tests/ -q`
Expected: all pass.

```bash
git add README.md .claude/tend/STATE.md
git commit -m "docs: M8 schema-rejection limitation, output-token staleness semantics"
```

---

### Task 15: Live verification of the installed harness

tend is installed live on this machine — the fixed code should be what runs. Verify the editable install picks up the changes and the hooks still answer.

- [ ] **Step 1: Confirm the live install resolves to this repo**

Run: `python3 -c "import tend; print(tend.__file__)"`
Expected: a path under `/Users/varma/tend/` (editable install). If it prints a site-packages copy instead, run `python3 -m pip install -e /Users/varma/tend` and re-check.

- [ ] **Step 2: Smoke-test the hook entry point end-to-end**

Run: `echo '{"hook_event_name":"UserPromptSubmit","session_id":"smoke","cwd":"/Users/varma/tend"}' | python3 -m tend.hook`
Expected: JSON with `[tend anchor]` and a `Goal:` line from this repo's STATE.md, exit 0.

Run: `echo 'not json' | python3 -m tend.hook; echo "exit=$?"`
Expected: `exit=0`, no traceback (fail-open intact).

- [ ] **Step 3: CLI smoke**

Run: `python3 -m tend.cli status --cwd /Users/varma/tend` (or `tend status` if on PATH)
Expected: a status block, no traceback.

- [ ] **Step 4: Final full suite, then stop**

Run: `python3 -m pytest tests/ -q`
Expected: all green. Report the final test count vs the original 110.

No commit for this task unless verification uncovered a fix.
