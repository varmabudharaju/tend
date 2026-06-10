# tend Context-Hygiene Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `tend`, a daemon-less context-hygiene harness for Claude Code: exact context measurement, oversized-tool-output offloading, STATE.md externalization, per-prompt anchoring, curated compaction, and lossless session continuation.

**Architecture:** A single fail-open hook entry point (`python3 -m tend.hook`) dispatches on `hook_event_name` to small handler modules; a statusline wrapper tees exact context metrics to disk; a `tend` CLI provides status/report/handoff/install. All session state lives under `~/.claude/tend/` (overridable via `TEND_HOME` for tests); project state lives at `<project>/.claude/tend/STATE.md`.

**Tech Stack:** Python 3.11 (`python3`), stdlib + PyYAML, pytest, setuptools, editable install. Run tests with `python3 -m pytest`.

**Conventions for every task:**
- Run tests from the repo root `/Users/varma/tend`.
- Commit messages are plain, imperative, no Co-Authored-By lines ever.
- Hooks must never crash a session: any exception → log + exit 0. Tests enforce this where relevant.

**Spec:** `docs/superpowers/specs/2026-06-09-context-harness-design.md` (approved).

---

## File structure (locked in)

```
tend/
  pyproject.toml
  .gitignore
  README.md
  tend/
    __init__.py        # empty
    paths.py           # TEND_HOME resolution, session dirs, kill switch, atomic JSON I/O
    tokens.py          # token estimation (chars//4), value→text
    config.py          # Config dataclass, defaults, YAML global + per-project override
    hookio.py          # stdin/stdout JSON, error log, fail-open runner
    hook.py            # __main__: dispatch hook_event_name → handler
    ledger.py          # incremental transcript parse: usage, tool-result sizes, staleness
    ctxmetrics.py      # read statusline tee (ctx.json) → used %
    statusline.py      # __main__: tee statusline JSON, exec original statusline
    flags.py           # per-session flags.json (reminders, boundary, blocked_once)
    state.py           # STATE.md template, sections parser, freshness
    offload.py         # Pillar 1: PostToolUse big-output offloading
    readguard.py       # Pillar 1b: PreToolUse large-Read nudge
    boundary.py        # Stop handler: STATE.md freshness → flags
    advisor.py         # Pillar 4: escalation level + /compact instruction text
    anchor.py          # Pillar 3: UserPromptSubmit anchor injection
    precompact.py      # Pillar 4: snapshot + one-shot auto-compact block
    sessionstart.py    # Pillar 4: continuation injection + template seeding
    install.py         # settings.json merge/unmerge + statusline wrap
    cli.py             # tend status|report|handoff|on|off|install-hook|uninstall-hook|statusline-wrap
  tests/
    conftest.py        # TEND_HOME→tmp autouse fixture, event/transcript helpers
    test_paths.py  test_tokens.py  test_config.py  test_hookio.py
    test_ledger.py test_ctxmetrics.py test_statusline.py test_flags.py
    test_state.py  test_offload.py  test_readguard.py  test_boundary.py
    test_advisor.py test_anchor.py  test_precompact.py test_sessionstart.py
    test_install.py test_cli.py     test_hook_dispatch.py test_integration.py
```

Module dependency order (build in this order): paths → tokens → config → hookio → ledger → statusline → ctxmetrics → flags → state → offload → readguard → boundary → advisor → anchor → precompact → sessionstart → hook (dispatch) → install → cli → integration.

---

### Task 1: Project skeleton + paths module

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `README.md`, `tend/__init__.py`, `tend/paths.py`
- Test: `tests/conftest.py`, `tests/test_paths.py`

- [ ] **Step 1: Create packaging files**

`pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "ctx-tend"
version = "0.1.0"
description = "Context-hygiene harness for Claude Code"
requires-python = ">=3.11"
dependencies = ["pyyaml>=6"]

[project.scripts]
tend = "tend.cli:main"

[tool.setuptools.packages.find]
include = ["tend*"]
```

`.gitignore`:
```
__pycache__/
*.egg-info/
.pytest_cache/
build/
dist/
```

`README.md`:
```markdown
# tend

Context-hygiene harness for Claude Code. See
`docs/superpowers/specs/2026-06-09-context-harness-design.md`.
```

`tend/__init__.py`: empty file.

- [ ] **Step 2: Editable install so `tests/` can import `tend`**

Run: `python3 -m pip install --user -e /Users/varma/tend`
Expected: `Successfully installed ctx-tend-0.1.0`

- [ ] **Step 3: Write conftest and failing paths test**

`tests/conftest.py`:
```python
import json
import pytest


@pytest.fixture(autouse=True)
def tend_home(tmp_path, monkeypatch):
    """Every test gets an isolated TEND_HOME."""
    home = tmp_path / "tend-home"
    monkeypatch.setenv("TEND_HOME", str(home))
    return home


def make_event(**kw):
    base = {
        "session_id": "s1",
        "cwd": "/tmp",
        "hook_event_name": "PostToolUse",
        "transcript_path": "",
    }
    base.update(kw)
    return base


def write_transcript(path, lines):
    path.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
```

`tests/test_paths.py`:
```python
from tend import paths


def test_home_respects_env(tend_home):
    assert paths.home() == tend_home


def test_session_dir_created(tend_home):
    d = paths.session_dir("abc")
    assert d.is_dir()
    assert d == tend_home / "sessions" / "abc"


def test_disabled_flag(tend_home):
    assert not paths.disabled()
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "disabled").touch()
    assert paths.disabled()


def test_json_roundtrip_atomic(tend_home):
    p = tend_home / "x" / "y.json"
    paths.write_json_atomic(p, {"a": 1})
    assert paths.read_json(p) == {"a": 1}
    assert paths.read_json(tend_home / "missing.json", {"d": 1}) == {"d": 1}
    assert not p.with_name(p.name + ".tmp").exists()
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_paths.py -v`
Expected: FAIL — `ModuleNotFoundError`/`AttributeError` (paths module missing).

- [ ] **Step 5: Implement `tend/paths.py`**

```python
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


def disabled() -> bool:
    return (home() / "disabled").exists()


def log_path() -> Path:
    return home() / "tend.log"


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def write_json_atomic(path, obj, indent=None) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=indent))
    tmp.replace(p)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_paths.py -v`
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: project skeleton and paths module"
```

---

### Task 2: tokens module

**Files:**
- Create: `tend/tokens.py`
- Test: `tests/test_tokens.py`

- [ ] **Step 1: Write the failing test**

`tests/test_tokens.py`:
```python
from tend import tokens


def test_estimate_chars_over_four():
    assert tokens.estimate("x" * 400) == 100


def test_estimate_empty_is_zero():
    assert tokens.estimate("") == 0


def test_estimate_short_text_is_at_least_one():
    assert tokens.estimate("ab") == 1


def test_to_text_passthrough_and_json():
    assert tokens.to_text("hi") == "hi"
    assert tokens.to_text({"a": 1}) == '{"a": 1}'
    assert tokens.to_text(None) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_tokens.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `tend/tokens.py`**

```python
"""Cheap token estimation: ~4 chars per token. Exact counts come from transcripts."""
import json


def to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value)
    except Exception:
        return str(value)


def estimate(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_tokens.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: token estimation helpers"
```

---

### Task 3: config module

**Files:**
- Create: `tend/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
from tend import config


def test_defaults_when_no_files():
    cfg = config.load()
    assert cfg.offload_threshold_tokens == 2500
    assert cfg.offload_tools == ("Bash", "Grep", "Glob", "WebFetch")
    assert cfg.advise_pct == 55
    assert cfg.urge_pct == 70


def test_global_override(tend_home):
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text("offload_threshold_tokens: 1000\n")
    assert config.load().offload_threshold_tokens == 1000


def test_project_override_wins(tend_home, tmp_path):
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text("advise_pct: 50\n")
    proj = tmp_path / "proj" / ".claude" / "tend"
    proj.mkdir(parents=True)
    (proj / "config.yaml").write_text("advise_pct: 60\n")
    assert config.load(str(tmp_path / "proj")).advise_pct == 60


def test_unknown_keys_ignored(tend_home):
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "config.yaml").write_text("bogus_key: 1\n")
    cfg = config.load()
    assert not hasattr(cfg, "bogus_key")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `tend/config.py`**

```python
"""Config: baked defaults < ~/.claude/tend/config.yaml < <project>/.claude/tend/config.yaml."""
from dataclasses import dataclass
from pathlib import Path

from . import paths

DEFAULTS = {
    "offload_threshold_tokens": 2500,
    "offload_tools": ["Bash", "Grep", "Glob", "WebFetch"],
    "offload_head_tokens": 600,
    "offload_tail_tokens": 600,
    "read_guard_bytes": 65536,
    "anchor_max_tokens": 400,
    "state_stale_tokens": 25000,
    "state_fresh_hours": 48,
    "advise_pct": 55,
    "urge_pct": 70,
}


@dataclass(frozen=True)
class Config:
    offload_threshold_tokens: int
    offload_tools: tuple
    offload_head_tokens: int
    offload_tail_tokens: int
    read_guard_bytes: int
    anchor_max_tokens: int
    state_stale_tokens: int
    state_fresh_hours: int
    advise_pct: float
    urge_pct: float


def load(cwd=None) -> Config:
    data = dict(DEFAULTS)
    candidates = [paths.home() / "config.yaml"]
    if cwd:
        candidates.append(Path(cwd) / ".claude" / "tend" / "config.yaml")
    for p in candidates:
        if p.is_file():
            import yaml  # lazy: keeps hook startup fast when no config exists

            loaded = yaml.safe_load(p.read_text()) or {}
            data.update({k: v for k, v in loaded.items() if k in DEFAULTS})
    data["offload_tools"] = tuple(data["offload_tools"])
    return Config(**data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: layered config loader with baked defaults"
```

---

### Task 4: hookio (fail-open runner)

**Files:**
- Create: `tend/hookio.py`
- Test: `tests/test_hookio.py`

- [ ] **Step 1: Write the failing test**

`tests/test_hookio.py`:
```python
import io
import json

from tend import hookio, paths


def run(handler, stdin_text, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_text))
    code = hookio.run_fail_open(handler)
    return code, capsys.readouterr().out


def test_handler_output_emitted(monkeypatch, capsys):
    code, out = run(lambda e: {"ok": e["session_id"]}, '{"session_id": "s1"}', monkeypatch, capsys)
    assert code == 0
    assert json.loads(out) == {"ok": "s1"}


def test_none_output_emits_nothing(monkeypatch, capsys):
    code, out = run(lambda e: None, "{}", monkeypatch, capsys)
    assert code == 0 and out == ""


def test_exception_is_swallowed_and_logged(monkeypatch, capsys, tend_home):
    def boom(e):
        raise RuntimeError("boom")

    code, out = run(boom, "{}", monkeypatch, capsys)
    assert code == 0 and out == ""
    assert "boom" in paths.log_path().read_text()


def test_garbage_stdin_is_swallowed(monkeypatch, capsys):
    code, out = run(lambda e: {"x": 1}, "not json", monkeypatch, capsys)
    assert code == 0 and out == ""


def test_disabled_short_circuits(monkeypatch, capsys, tend_home):
    tend_home.mkdir(parents=True, exist_ok=True)
    (tend_home / "disabled").touch()
    called = []
    code, out = run(lambda e: called.append(1), "{}", monkeypatch, capsys)
    assert code == 0 and out == "" and not called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_hookio.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `tend/hookio.py`**

```python
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
    sys.stdout.write(json.dumps(obj))


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
        if out:
            emit(out)
    except Exception:
        log_error()
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_hookio.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: fail-open hook IO runner"
```

---

### Task 5: ledger (incremental transcript accounting)

**Files:**
- Create: `tend/ledger.py`
- Test: `tests/test_ledger.py`

Transcript lines are Claude Code JSONL: `{"type": "assistant"|"user", "message": {"content": [...], "usage": {...}}}`. Exact context size = `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` of the latest assistant message (verified on this machine 2026-06-09).

- [ ] **Step 1: Write the failing test**

`tests/test_ledger.py`:
```python
from conftest import make_event, write_transcript

from tend import ledger


def fixture_lines():
    big = "x" * 2000  # ~500 tokens
    return [
        {"type": "assistant", "message": {"usage": {
            "input_tokens": 10, "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 1000, "output_tokens": 50},
            "content": [{"type": "tool_use", "id": "t1", "name": "Read",
                         "input": {"file_path": "/tmp/proj/a.py"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": big}]}},
        {"type": "assistant", "message": {"usage": {
            "input_tokens": 5, "cache_read_input_tokens": 1500,
            "cache_creation_input_tokens": 600, "output_tokens": 80},
            "content": [{"type": "tool_use", "id": "t2", "name": "Edit",
                         "input": {"file_path": "/tmp/proj/a.py"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t2", "content": "ok"}]}},
        {"type": "assistant", "message": {"usage": {
            "input_tokens": 2, "cache_read_input_tokens": 2200,
            "cache_creation_input_tokens": 300, "output_tokens": 40},
            "content": []}},
    ]


def test_ingest_full_transcript(tmp_path):
    tp = tmp_path / "t.jsonl"
    write_transcript(tp, fixture_lines())
    ev = make_event(transcript_path=str(tp))
    ledger.ingest(ev)
    s = ledger.load_summary("s1")
    assert s["context_total"] == 2 + 2200 + 300
    assert s["output_total"] == 50 + 80 + 40
    assert s["results"]["t1"]["tool"] == "Read"
    assert s["results"]["t1"]["tokens"] == 500
    assert s["results"]["t1"]["stale"] is True  # a.py edited after the read
    assert s["results"]["t2"]["stale"] is False
    assert ledger.stale_tokens(s) == 500


def test_ingest_is_incremental(tmp_path):
    tp = tmp_path / "t.jsonl"
    lines = fixture_lines()
    write_transcript(tp, lines[:2])
    ev = make_event(transcript_path=str(tp))
    ledger.ingest(ev)
    write_transcript(tp, lines)  # rewrite longer file; cursor continues from old offset
    ledger.ingest(ev)
    s = ledger.load_summary("s1")
    assert s["context_total"] == 2502
    assert len(s["results"]) == 2


def test_bad_lines_set_degraded(tmp_path):
    tp = tmp_path / "t.jsonl"
    tp.write_text('{"type": "assistant", "message": {"usage": {"input_tokens": 1}}}\nNOT JSON\n')
    ledger.ingest(make_event(transcript_path=str(tp)))
    assert ledger.load_summary("s1")["degraded"] is True


def test_top_results_sorted(tmp_path):
    tp = tmp_path / "t.jsonl"
    write_transcript(tp, fixture_lines())
    ledger.ingest(make_event(transcript_path=str(tp)))
    top = ledger.top_results(ledger.load_summary("s1"), 1)
    assert top[0]["id"] == "t1" and top[0]["tokens"] == 500


def test_state_mark_roundtrip(tmp_path):
    tp = tmp_path / "t.jsonl"
    write_transcript(tp, fixture_lines())
    ledger.ingest(make_event(transcript_path=str(tp)))
    ledger.set_state_mark("s1", 123.0)
    s = ledger.load_summary("s1")
    assert s["state_mark"] == {"mtime": 123.0, "context_total": 2502}
    assert ledger.tokens_since_state_mark(s) == 0


def test_record_agent():
    ledger.record_agent(make_event(hook_event_name="SubagentStart", agent_id="a1", agent_type="Explore"))
    ledger.record_agent(make_event(hook_event_name="SubagentStop", agent_id="a1"))
    s = ledger.load_summary("s1")
    assert s["agents"]["a1"]["type"] == "Explore"
    assert s["agents"]["a1"]["stopped"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_ledger.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `tend/ledger.py`**

```python
"""Incremental transcript ledger: exact context totals, tool-result sizes, staleness."""
import json
from pathlib import Path

from . import paths, tokens

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def _cursor_path(sid):
    return paths.session_dir(sid) / "cursor.json"


def _summary_path(sid):
    return paths.session_dir(sid) / "summary.json"


def _empty():
    return {
        "context_total": 0,
        "output_total": 0,
        "results": {},
        "reads": {},
        "pending": {},
        "agents": {},
        "state_mark": None,
        "degraded": False,
    }


def load_summary(sid) -> dict:
    return paths.read_json(_summary_path(sid), _empty())


def ingest(event) -> None:
    sid = event.get("session_id")
    tp = event.get("transcript_path")
    if not sid or not tp or not Path(tp).exists():
        return
    cur = paths.read_json(_cursor_path(sid), {"offset": 0})
    summary = load_summary(sid)
    with open(tp, "r", encoding="utf-8") as f:
        f.seek(cur["offset"])
        for line in f:
            _ingest_line(summary, line)
        cur["offset"] = f.tell()
    paths.write_json_atomic(_summary_path(sid), summary)
    paths.write_json_atomic(_cursor_path(sid), cur)


def _ingest_line(summary, line) -> None:
    line = line.strip()
    if not line:
        return
    try:
        obj = json.loads(line)
    except Exception:
        summary["degraded"] = True
        return
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
            fp = (block.get("input") or {}).get("file_path")
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


def set_state_mark(sid, mtime) -> None:
    s = load_summary(sid)
    s["state_mark"] = {"mtime": mtime, "context_total": s.get("context_total", 0)}
    paths.write_json_atomic(_summary_path(sid), s)


def tokens_since_state_mark(summary):
    mark = summary.get("state_mark")
    if not mark:
        return None
    return summary.get("context_total", 0) - mark.get("context_total", 0)


def top_results(summary, n=5):
    items = [dict(id=k, **v) for k, v in summary.get("results", {}).items()]
    return sorted(items, key=lambda r: r["tokens"], reverse=True)[:n]


def stale_tokens(summary) -> int:
    return sum(r["tokens"] for r in summary.get("results", {}).values() if r.get("stale"))


def record_agent(event) -> None:
    sid = event.get("session_id")
    aid = event.get("agent_id")
    if not sid or not aid:
        return
    s = load_summary(sid)
    rec = s["agents"].setdefault(aid, {"type": None, "stopped": False})
    if event.get("hook_event_name") == "SubagentStart":
        rec["type"] = event.get("agent_type")
    else:
        rec["stopped"] = True
    paths.write_json_atomic(_summary_path(sid), s)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_ledger.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: incremental transcript ledger with staleness tracking"
```

---

### Task 6: statusline tee

**Files:**
- Create: `tend/statusline.py`
- Test: `tests/test_statusline.py`

- [ ] **Step 1: Write the failing test**

`tests/test_statusline.py`:
```python
import io
import json

from tend import paths, statusline


STATUS_JSON = json.dumps({
    "session_id": "s9",
    "model": {"display_name": "Fable"},
    "context_window": {"used_percentage": 42.5},
})


def test_tee_writes_ctx_json(monkeypatch, capsys, tend_home):
    monkeypatch.setattr("sys.stdin", io.StringIO(STATUS_JSON))
    statusline.main()
    saved = paths.read_json(paths.session_dir("s9") / "ctx.json")
    assert saved["context_window"]["used_percentage"] == 42.5


def test_exec_original_passthrough(monkeypatch, capsys, tend_home):
    paths.write_json_atomic(
        tend_home / "statusline-original.json",
        {"type": "command", "command": "echo ORIGINAL-LINE"},
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(STATUS_JSON))
    statusline.main()
    assert "ORIGINAL-LINE" in capsys.readouterr().out


def test_fallback_line_without_original(monkeypatch, capsys, tend_home):
    monkeypatch.setattr("sys.stdin", io.StringIO(STATUS_JSON))
    statusline.main()
    out = capsys.readouterr().out
    assert "Fable" in out and "42" in out


def test_garbage_input_never_raises(monkeypatch, capsys, tend_home):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    statusline.main()  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_statusline.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `tend/statusline.py`**

```python
"""Statusline wrapper: tee exact context metrics to disk, then run the original statusline."""
import json
import subprocess
import sys

from . import paths


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except Exception:
        data = {}
    sid = data.get("session_id")
    if sid:
        try:
            paths.write_json_atomic(paths.session_dir(sid) / "ctx.json", data)
        except Exception:
            pass
    orig = paths.read_json(paths.home() / "statusline-original.json")
    if orig and orig.get("command"):
        try:
            res = subprocess.run(
                orig["command"], shell=True, input=raw, capture_output=True, text=True, timeout=10
            )
            sys.stdout.write(res.stdout)
            return 0
        except Exception:
            pass
    model = (data.get("model") or {}).get("display_name", "")
    pct = (data.get("context_window") or {}).get("used_percentage")
    line = model or "tend"
    if pct is not None:
        line += f" | ctx {pct:.0f}%"
    sys.stdout.write(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_statusline.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: statusline tee preserving original statusline output"
```

---

### Task 7: ctxmetrics

**Files:**
- Create: `tend/ctxmetrics.py`
- Test: `tests/test_ctxmetrics.py`

- [ ] **Step 1: Write the failing test**

`tests/test_ctxmetrics.py`:
```python
from tend import ctxmetrics, paths


def test_used_pct_from_ctx_json(tend_home):
    paths.write_json_atomic(
        paths.session_dir("s1") / "ctx.json",
        {"context_window": {"used_percentage": 61.2}},
    )
    assert ctxmetrics.used_pct("s1") == 61.2


def test_used_pct_none_when_missing(tend_home):
    assert ctxmetrics.used_pct("nope") is None


def test_used_pct_none_when_field_absent(tend_home):
    paths.write_json_atomic(paths.session_dir("s1") / "ctx.json", {"context_window": {}})
    assert ctxmetrics.used_pct("s1") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_ctxmetrics.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `tend/ctxmetrics.py`**

```python
"""Read the statusline tee for exact context usage."""
from . import paths


def read_ctx(sid):
    return paths.read_json(paths.session_dir(sid) / "ctx.json")


def used_pct(sid):
    ctx = read_ctx(sid)
    if not ctx:
        return None
    pct = (ctx.get("context_window") or {}).get("used_percentage")
    return float(pct) if pct is not None else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_ctxmetrics.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: context metrics reader"
```

---

### Task 8: flags

**Files:**
- Create: `tend/flags.py`
- Test: `tests/test_flags.py`

- [ ] **Step 1: Write the failing test**

`tests/test_flags.py`:
```python
from tend import flags


def test_load_empty_then_roundtrip(tend_home):
    assert flags.load("s1") == {}
    flags.save("s1", {"state_reminder": True})
    assert flags.load("s1") == {"state_reminder": True}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_flags.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `tend/flags.py`**

```python
"""Per-session flags shared between hook invocations."""
from . import paths


def load(sid) -> dict:
    return paths.read_json(paths.session_dir(sid) / "flags.json", {})


def save(sid, fl) -> None:
    paths.write_json_atomic(paths.session_dir(sid) / "flags.json", fl)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_flags.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: per-session flags store"
```

---

### Task 9: state (STATE.md)

**Files:**
- Create: `tend/state.py`
- Test: `tests/test_state.py`

- [ ] **Step 1: Write the failing test**

`tests/test_state.py`:
```python
import os
import time

from tend import state


def test_path_for(tmp_path):
    assert state.path_for(str(tmp_path)) == tmp_path / ".claude" / "tend" / "STATE.md"


def test_seed_creates_template_once(tmp_path):
    p = state.path_for(str(tmp_path))
    state.seed(p)
    assert "## Dead-ends" in p.read_text()
    p.write_text("custom")
    state.seed(p)  # must not overwrite
    assert p.read_text() == "custom"


def test_goal_now_skips_placeholders(tmp_path):
    p = state.path_for(str(tmp_path))
    p.parent.mkdir(parents=True)
    p.write_text(
        "# Session state\n\n## Goal\n(placeholder)\nShip the harness\n\n"
        "## Now\nWriting ledger tests\n\n## Decisions\n- yaml config\n"
    )
    goal, now = state.goal_now(p)
    assert goal == "Ship the harness"
    assert now == "Writing ledger tests"


def test_goal_now_missing_file(tmp_path):
    assert state.goal_now(tmp_path / "nope.md") == ("", "")


def test_is_fresh(tmp_path):
    p = tmp_path / "STATE.md"
    p.write_text("x")
    assert state.is_fresh(p, hours=1)
    old = time.time() - 3 * 3600
    os.utime(p, (old, old))
    assert not state.is_fresh(p, hours=1)
    assert not state.is_fresh(tmp_path / "nope.md", hours=1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_state.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `tend/state.py`**

```python
"""STATE.md: the session's external source of truth, maintained by Claude."""
import time
from pathlib import Path

TEMPLATE = """# Session state

## Goal
(What this session is building - one paragraph. Keep stable.)

## Now
(Current step. Update often.)

## Decisions
(Settled choices. Append-only.)

## Dead-ends
(Approaches tried and abandoned, with why. Do NOT retry these.)

## Files touched
(path - one line on what/why)
"""


def path_for(cwd) -> Path:
    return Path(cwd) / ".claude" / "tend" / "STATE.md"


def seed(path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(TEMPLATE)


def read_sections(path) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    sections, current = {}, None
    for line in path.read_text().splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def goal_now(path):
    s = read_sections(path)

    def first_line(text):
        for ln in (text or "").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("("):
                return ln
        return ""

    return first_line(s.get("Goal")), first_line(s.get("Now"))


def is_fresh(path, hours) -> bool:
    path = Path(path)
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < hours * 3600
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_state.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: STATE.md template, parser, freshness"
```

---

### Task 10: offload (Pillar 1)

**Files:**
- Create: `tend/offload.py`
- Test: `tests/test_offload.py`

- [ ] **Step 1: Write the failing test**

`tests/test_offload.py`:
```python
from conftest import make_event

from tend import offload, paths


def big_event(**kw):
    return make_event(
        tool_name="Bash",
        tool_response="HEAD" + ("m" * 20000) + "TAIL",  # ~5k tokens
        **kw,
    )


def test_big_bash_output_offloaded(tend_home):
    out = offload.handle(big_event())
    repl = out["hookSpecificOutput"]["updatedToolOutput"]
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert repl.startswith("HEAD")
    assert "TAIL" in repl
    assert "tokens offloaded" in repl
    files = list((paths.session_dir("s1") / "outputs").glob("*.txt"))
    assert len(files) == 1
    assert files[0].read_text().startswith("HEAD")
    assert str(files[0]) in repl


def test_small_output_untouched():
    assert offload.handle(make_event(tool_name="Bash", tool_response="small")) is None


def test_read_tool_never_offloaded():
    assert offload.handle(make_event(tool_name="Read", tool_response="x" * 20000)) is None


def test_dict_response_serialized(tend_home):
    out = offload.handle(make_event(tool_name="Bash", tool_response={"stdout": "y" * 20000}))
    assert out is not None


def test_sequential_output_numbering(tend_home):
    offload.handle(big_event())
    offload.handle(big_event())
    names = sorted(p.name for p in (paths.session_dir("s1") / "outputs").glob("*.txt"))
    assert names == ["0001.txt", "0002.txt"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_offload.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `tend/offload.py`**

```python
"""Pillar 1: replace oversized tool outputs with head+tail excerpt; full text on disk."""
from . import config, paths, tokens


def handle(event):
    cfg = config.load(event.get("cwd"))
    if event.get("tool_name") not in cfg.offload_tools:
        return None
    raw = event.get("tool_response", event.get("tool_result", ""))
    text = tokens.to_text(raw)
    n = tokens.estimate(text)
    if n < cfg.offload_threshold_tokens:
        return None
    path = _save(event.get("session_id", "unknown"), text)
    head = text[: cfg.offload_head_tokens * 4]
    tail = text[-cfg.offload_tail_tokens * 4 :]
    omitted = max(0, n - cfg.offload_head_tokens - cfg.offload_tail_tokens)
    excerpt = (
        f"{head}\n\n[tend: ~{omitted} tokens offloaded]\n\n{tail}\n\n"
        f"[tend] Full output saved to {path} - Read it (with offset/limit) only if needed."
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "updatedToolOutput": excerpt,
        }
    }


def _save(sid, text):
    d = paths.session_dir(sid) / "outputs"
    d.mkdir(parents=True, exist_ok=True)
    n = len(list(d.glob("*.txt"))) + 1
    p = d / f"{n:04d}.txt"
    p.write_text(text)
    p.chmod(0o600)
    return p
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_offload.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: oversized tool-output offloading (pillar 1)"
```

---

### Task 11: readguard (Pillar 1b)

**Files:**
- Create: `tend/readguard.py`
- Test: `tests/test_readguard.py`

- [ ] **Step 1: Write the failing test**

`tests/test_readguard.py`:
```python
from conftest import make_event

from tend import readguard


def test_large_unbounded_read_gets_nudge(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("x" * 100_000)
    ev = make_event(hook_event_name="PreToolUse", tool_name="Read",
                    tool_input={"file_path": str(f)})
    out = readguard.handle(ev)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "offset/limit" in ctx
    assert "permissionDecision" not in out["hookSpecificOutput"]  # never alter permissions


def test_bounded_read_ignored(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("x" * 100_000)
    ev = make_event(tool_name="Read", tool_input={"file_path": str(f), "limit": 100})
    assert readguard.handle(ev) is None


def test_small_file_ignored(tmp_path):
    f = tmp_path / "small.txt"
    f.write_text("x")
    assert readguard.handle(make_event(tool_name="Read", tool_input={"file_path": str(f)})) is None


def test_other_tools_and_missing_files_ignored(tmp_path):
    assert readguard.handle(make_event(tool_name="Bash", tool_input={})) is None
    assert readguard.handle(
        make_event(tool_name="Read", tool_input={"file_path": str(tmp_path / "nope")})
    ) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_readguard.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `tend/readguard.py`**

```python
"""Pillar 1b: nudge (never block) unbounded Reads of large files."""
import os

from . import config


def handle(event):
    if event.get("tool_name") != "Read":
        return None
    ti = event.get("tool_input") or {}
    if "limit" in ti or "offset" in ti:
        return None
    fp = ti.get("file_path")
    if not fp or not os.path.isfile(fp):
        return None
    cfg = config.load(event.get("cwd"))
    size = os.path.getsize(fp)
    if size <= cfg.read_guard_bytes:
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"[tend] {fp} is ~{size // 4:,} tokens. Prefer Read with offset/limit on the "
                "relevant range, or delegate scanning to an Explore subagent, instead of "
                "loading the whole file into context."
            ),
        }
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_readguard.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: large-read nudge guard (pillar 1b)"
```

---

### Task 12: boundary (Stop handler)

**Files:**
- Create: `tend/boundary.py`
- Test: `tests/test_boundary.py`

Semantics: on every Stop — if STATE.md changed since our recorded mark, re-mark it (records the context total at update time), clear the reminder, and set `boundary=True` (a fresh STATE.md at a stop is a task boundary). If unchanged and more than `state_stale_tokens` of context accumulated since the mark, set `state_reminder=True`. If STATE.md is missing, remind once meaningful context exists.

- [ ] **Step 1: Write the failing test**

`tests/test_boundary.py`:
```python
from conftest import make_event

from tend import boundary, flags, ledger, paths, state


def setup_summary(total):
    paths.write_json_atomic(
        paths.session_dir("s1") / "summary.json",
        {"context_total": total, "output_total": 0, "results": {}, "reads": {},
         "pending": {}, "agents": {}, "state_mark": None, "degraded": False},
    )


def test_fresh_state_marks_and_sets_boundary(tmp_path):
    sp = state.path_for(str(tmp_path))
    state.seed(sp)
    setup_summary(50_000)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))
    fl = flags.load("s1")
    assert fl["boundary"] is True and fl["state_reminder"] is False
    assert ledger.load_summary("s1")["state_mark"]["context_total"] == 50_000


def test_stale_state_sets_reminder(tmp_path):
    sp = state.path_for(str(tmp_path))
    state.seed(sp)
    setup_summary(10_000)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))  # marks at 10k
    setup_summary(40_000)  # 30k tokens later, STATE.md untouched
    # keep the recorded mark when rewriting summary
    s = ledger.load_summary("s1")
    s["state_mark"] = {"mtime": sp.stat().st_mtime, "context_total": 10_000}
    paths.write_json_atomic(paths.session_dir("s1") / "summary.json", s)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))
    fl = flags.load("s1")
    assert fl["state_reminder"] is True and fl["boundary"] is False


def test_missing_state_reminds_after_threshold(tmp_path):
    setup_summary(30_000)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))
    assert flags.load("s1")["state_reminder"] is True


def test_missing_state_quiet_early(tmp_path):
    setup_summary(5_000)
    boundary.handle(make_event(hook_event_name="Stop", cwd=str(tmp_path)))
    assert flags.load("s1")["state_reminder"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_boundary.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `tend/boundary.py`**

```python
"""Stop handler: track STATE.md freshness, detect task boundaries."""
from . import config, flags, ledger, state


def handle(event):
    sid = event.get("session_id")
    if not sid:
        return None
    cwd = event.get("cwd") or "."
    cfg = config.load(cwd)
    summary = ledger.load_summary(sid)
    fl = flags.load(sid)
    sp = state.path_for(cwd)
    if sp.exists():
        mtime = sp.stat().st_mtime
        mark = summary.get("state_mark")
        if not mark or mark.get("mtime") != mtime:
            ledger.set_state_mark(sid, mtime)
            fl["state_reminder"] = False
            fl["boundary"] = True
        else:
            since = ledger.tokens_since_state_mark(summary)
            fl["state_reminder"] = since is not None and since > cfg.state_stale_tokens
            fl["boundary"] = False
    else:
        fl["state_reminder"] = summary.get("context_total", 0) > cfg.state_stale_tokens
        fl["boundary"] = False
    flags.save(sid, fl)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_boundary.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: stop-time STATE.md freshness and boundary detection"
```

---

### Task 13: advisor (Pillar 4 text)

**Files:**
- Create: `tend/advisor.py`
- Test: `tests/test_advisor.py`

- [ ] **Step 1: Write the failing test**

`tests/test_advisor.py`:
```python
from tend import advisor, config, state


def cfg():
    return config.load()


def test_levels():
    c = cfg()
    assert advisor.level(None, c) is None
    assert advisor.level(40, c) is None
    assert advisor.level(60, c) == "advise"
    assert advisor.level(75, c) == "urge"


def test_advice_none_below_threshold(tmp_path):
    assert advisor.advice(40, cfg(), tmp_path / "STATE.md", {}) is None


def test_advise_with_boundary(tmp_path):
    sp = state.path_for(str(tmp_path))
    state.seed(sp)
    text = advisor.advice(60, cfg(), sp, {"boundary": True})
    assert text.startswith("Task boundary")
    assert "/compact" in text


def test_urge_includes_run_now(tmp_path):
    text = advisor.advice(80, cfg(), tmp_path / "STATE.md", {})
    assert "run now" in text and "/compact" in text


def test_instructions_include_goal(tmp_path):
    sp = state.path_for(str(tmp_path))
    sp.parent.mkdir(parents=True)
    sp.write_text("## Goal\nShip tend v1\n## Now\nx\n")
    assert "Ship tend v1" in advisor.compact_instructions(sp)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_advisor.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `tend/advisor.py`**

```python
"""Pillar 4: when and how to recommend a curated /compact."""
from . import state


def level(pct, cfg):
    if pct is None:
        return None
    if pct >= cfg.urge_pct:
        return "urge"
    if pct >= cfg.advise_pct:
        return "advise"
    return None


def compact_instructions(state_path) -> str:
    base = (
        "preserve the Goal, Now and Decisions from .claude/tend/STATE.md and the intent of "
        "the current change; drop exploration detail, raw tool outputs and dead-end attempts "
        "(they are recorded in STATE.md)"
    )
    goal, _ = state.goal_now(state_path)
    return f"{base}. Goal: {goal}" if goal else base


def advice(pct, cfg, state_path, fl):
    lv = level(pct, cfg)
    if lv is None:
        return None
    instr = compact_instructions(state_path)
    if lv == "urge":
        return f"Context at {pct:.0f}% - run now: /compact {instr}"
    if fl.get("boundary"):
        return f"Task boundary and context at {pct:.0f}% - good moment for: /compact {instr}"
    return f"Context at {pct:.0f}% - at the next task boundary, run: /compact {instr}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_advisor.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: curated compaction advisor"
```

---

### Task 14: anchor (Pillar 3)

**Files:**
- Create: `tend/anchor.py`
- Test: `tests/test_anchor.py`

- [ ] **Step 1: Write the failing test**

`tests/test_anchor.py`:
```python
from conftest import make_event

from tend import anchor, flags, paths, state


def seed_state(tmp_path, goal="Ship tend", now="Writing anchor"):
    sp = state.path_for(str(tmp_path))
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(f"## Goal\n{goal}\n\n## Now\n{now}\n")
    return sp


def seed_ctx(pct):
    paths.write_json_atomic(
        paths.session_dir("s1") / "ctx.json",
        {"context_window": {"used_percentage": pct}},
    )


def ev(tmp_path):
    return make_event(hook_event_name="UserPromptSubmit", cwd=str(tmp_path))


def test_anchor_contains_goal_now_health(tmp_path):
    seed_state(tmp_path)
    seed_ctx(30)
    out = anchor.handle(ev(tmp_path))
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "Goal: Ship tend" in ctx
    assert "Now: Writing anchor" in ctx
    assert "context 30%" in ctx
    assert "/compact" not in ctx  # below advise threshold


def test_anchor_includes_reminder_when_flagged(tmp_path):
    seed_state(tmp_path)
    flags.save("s1", {"state_reminder": True})
    ctx = anchor.handle(ev(tmp_path))["hookSpecificOutput"]["additionalContext"]
    assert "STATE.md is stale" in ctx


def test_anchor_escalates_at_advise(tmp_path):
    seed_state(tmp_path)
    seed_ctx(60)
    ctx = anchor.handle(ev(tmp_path))["hookSpecificOutput"]["additionalContext"]
    assert "/compact" in ctx


def test_anchor_truncated_to_budget(tmp_path):
    seed_state(tmp_path, goal="g" * 10000)
    ctx = anchor.handle(ev(tmp_path))["hookSpecificOutput"]["additionalContext"]
    assert len(ctx) <= 400 * 4


def test_anchor_works_without_state_or_metrics(tmp_path):
    ctx = anchor.handle(ev(tmp_path))["hookSpecificOutput"]["additionalContext"]
    assert "context usage unknown" in ctx
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_anchor.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `tend/anchor.py`**

```python
"""Pillar 3: small end-of-context anchor injected on every user prompt."""
from . import advisor, config, ctxmetrics, flags, ledger, state


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

    lines = []
    if goal:
        lines.append(f"Goal: {goal}")
    if now:
        lines.append(f"Now: {now}")
    lines.append(_health_line(pct, summary))
    if fl.get("state_reminder"):
        lines.append(
            "STATE.md is stale - update .claude/tend/STATE.md "
            "(Now/Decisions/Dead-ends) before continuing."
        )
    adv = advisor.advice(pct, cfg, sp, fl)
    if adv:
        lines.append(adv)
    text = "[tend anchor]\n" + "\n".join(lines)
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": text[: cfg.anchor_max_tokens * 4],
        }
    }


def _health_line(pct, summary):
    parts = [f"context {pct:.0f}% used" if pct is not None else "context usage unknown"]
    st = ledger.stale_tokens(summary)
    if st:
        parts.append(f"~{st:,} tok of stale tool results")
    return "Health: " + ", ".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_anchor.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: per-prompt state anchor injection (pillar 3)"
```

---

### Task 15: precompact (Pillar 4 safety net)

**Files:**
- Create: `tend/precompact.py`
- Test: `tests/test_precompact.py`

- [ ] **Step 1: Write the failing test**

`tests/test_precompact.py`:
```python
from conftest import make_event

from tend import flags, paths, precompact


def ev(trigger, tmp_path):
    return make_event(hook_event_name="PreCompact", trigger=trigger, cwd=str(tmp_path))


def test_auto_blocks_once_when_state_missing(tmp_path):
    out = precompact.handle(ev("auto", tmp_path))
    assert out == {"decision": "block", "reason": precompact.BLOCK_REASON}
    assert flags.load("s1")["blocked_once"] is True
    # second auto-compact must pass
    assert precompact.handle(ev("auto", tmp_path)) is None


def test_manual_never_blocked(tmp_path):
    assert precompact.handle(ev("manual", tmp_path)) is None


def test_snapshot_written(tmp_path):
    precompact.handle(ev("manual", tmp_path))
    snaps = list(paths.session_dir("s1").glob("precompact-*.json"))
    assert len(snaps) == 1


def test_fresh_state_not_blocked(tmp_path):
    from tend import ledger, state

    sp = state.path_for(str(tmp_path))
    state.seed(sp)
    ledger.set_state_mark("s1", sp.stat().st_mtime)  # mark matches: fresh, 0 tokens since
    assert precompact.handle(ev("auto", tmp_path)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_precompact.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `tend/precompact.py`**

```python
"""Pillar 4 safety net: snapshot before compaction; block a stale auto-compact once."""
import time

from . import config, ctxmetrics, flags, ledger, paths, state

BLOCK_REASON = (
    "tend: STATE.md is stale. Update .claude/tend/STATE.md (Goal/Now/Decisions/Dead-ends), "
    "then run /compact. This block fires only once."
)


def handle(event):
    sid = event.get("session_id")
    if not sid:
        return None
    cfg = config.load(event.get("cwd"))
    _snapshot(sid)
    if event.get("trigger") == "auto":
        fl = flags.load(sid)
        if not fl.get("blocked_once") and _is_stale(event, cfg):
            fl["blocked_once"] = True
            flags.save(sid, fl)
            return {"decision": "block", "reason": BLOCK_REASON}
    return None


def _is_stale(event, cfg) -> bool:
    sp = state.path_for(event.get("cwd") or ".")
    if not sp.exists():
        return True
    summary = ledger.load_summary(event.get("session_id"))
    mark = summary.get("state_mark")
    if mark and mark.get("mtime") != sp.stat().st_mtime:
        return False  # updated since our last mark: fresh
    since = ledger.tokens_since_state_mark(summary)
    return since is not None and since > cfg.state_stale_tokens


def _snapshot(sid) -> None:
    snap = {
        "summary": ledger.load_summary(sid),
        "ctx": ctxmetrics.read_ctx(sid),
        "ts": time.time(),
    }
    paths.write_json_atomic(paths.session_dir(sid) / f"precompact-{int(time.time())}.json", snap)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_precompact.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: precompact snapshot and one-shot stale block"
```

---

### Task 16: sessionstart (continuation + seeding)

**Files:**
- Create: `tend/sessionstart.py`
- Test: `tests/test_sessionstart.py`

- [ ] **Step 1: Write the failing test**

`tests/test_sessionstart.py`:
```python
import os
import time
from pathlib import Path

from conftest import make_event

from tend import sessionstart, state


def ev(tmp_path, source="startup"):
    return make_event(hook_event_name="SessionStart", source=source, cwd=str(tmp_path))


def test_seeds_template_and_explains_convention(tmp_path):
    out = sessionstart.handle(ev(tmp_path))
    assert state.path_for(str(tmp_path)).exists()
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "STATE.md" in ctx and "Dead-ends" in ctx


def test_fresh_state_injected(tmp_path):
    sp = state.path_for(str(tmp_path))
    sp.parent.mkdir(parents=True)
    sp.write_text("## Goal\nShip it\n")
    ctx = sessionstart.handle(ev(tmp_path, "clear"))["hookSpecificOutput"]["additionalContext"]
    assert "State restored" in ctx and "Ship it" in ctx


def test_old_state_not_injected(tmp_path):
    sp = state.path_for(str(tmp_path))
    sp.parent.mkdir(parents=True)
    sp.write_text("## Goal\nold\n")
    old = time.time() - 100 * 3600
    os.utime(sp, (old, old))
    assert sessionstart.handle(ev(tmp_path)) is None


def test_resume_and_compact_sources_ignored(tmp_path):
    assert sessionstart.handle(ev(tmp_path, "resume")) is None
    assert sessionstart.handle(ev(tmp_path, "compact")) is None


def test_home_directory_never_seeded():
    out = sessionstart.handle(make_event(
        hook_event_name="SessionStart", source="startup", cwd=str(Path.home())
    ))
    assert out is None
    assert not state.path_for(str(Path.home())).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_sessionstart.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `tend/sessionstart.py`**

```python
"""Pillar 4: lossless continuation - restore STATE.md into fresh sessions; seed convention."""
from pathlib import Path

from . import config, state

CONVENTION = (
    "[tend] This project uses .claude/tend/STATE.md as the session's external state file "
    "(template just created). Maintain it as you work: Goal (stable), Now (current step), "
    "Decisions (append-only), Dead-ends (failed approaches - never retry), Files touched. "
    "Update it whenever you finish a step or make a decision; it survives compaction and "
    "new sessions."
)

PREAMBLE = (
    "[tend] State restored from previous session (.claude/tend/STATE.md below). "
    "Verify 'Files touched' against current disk before relying on it.\n\n"
)

MAX_INJECT_CHARS = 16000


def handle(event):
    if event.get("source") not in ("startup", "clear"):
        return None
    cwd = event.get("cwd") or "."
    if Path(cwd).resolve() == Path.home().resolve():
        return None  # never seed the home directory
    cfg = config.load(cwd)
    sp = state.path_for(cwd)
    if not sp.exists():
        state.seed(sp)
        return _ctx(CONVENTION)
    if state.is_fresh(sp, cfg.state_fresh_hours):
        return _ctx(PREAMBLE + sp.read_text()[:MAX_INJECT_CHARS])
    return None


def _ctx(text):
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_sessionstart.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: session-start state restoration and template seeding"
```

---

### Task 17: hook dispatch (compose everything)

**Files:**
- Create: `tend/hook.py`
- Test: `tests/test_hook_dispatch.py`

- [ ] **Step 1: Write the failing test**

`tests/test_hook_dispatch.py`:
```python
from conftest import make_event, write_transcript

from tend import hook, ledger


def test_posttooluse_ingests_and_offloads(tmp_path):
    tp = tmp_path / "t.jsonl"
    write_transcript(tp, [{"type": "assistant", "message": {"usage": {
        "input_tokens": 1, "cache_read_input_tokens": 2,
        "cache_creation_input_tokens": 3, "output_tokens": 4}, "content": []}}])
    ev = make_event(hook_event_name="PostToolUse", transcript_path=str(tp),
                    tool_name="Bash", tool_response="z" * 20000)
    out = hook.dispatch(ev)
    assert "updatedToolOutput" in out["hookSpecificOutput"]
    assert ledger.load_summary("s1")["context_total"] == 6


def test_subagent_events_recorded():
    hook.dispatch(make_event(hook_event_name="SubagentStart", agent_id="a1", agent_type="Explore"))
    hook.dispatch(make_event(hook_event_name="SubagentStop", agent_id="a1"))
    assert ledger.load_summary("s1")["agents"]["a1"]["stopped"] is True


def test_unknown_event_returns_none():
    assert hook.dispatch(make_event(hook_event_name="Notification")) is None


def test_userpromptsubmit_returns_anchor(tmp_path):
    out = hook.dispatch(make_event(hook_event_name="UserPromptSubmit", cwd=str(tmp_path)))
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_hook_dispatch.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `tend/hook.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_hook_dispatch.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: all tests pass (≈54).

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: hook entry point dispatching all tend events"
```

---

### Task 18: install / uninstall

**Files:**
- Create: `tend/install.py`
- Test: `tests/test_install.py`

- [ ] **Step 1: Write the failing test**

`tests/test_install.py`:
```python
import json

from tend import install, paths


EXISTING = {
    "hooks": {
        "PostToolUse": [{"hooks": [{"type": "command", "command": "python3 -m agent_pd.hook"}]}],
    },
    "statusLine": {"type": "command", "command": "bash /Users/varma/.claude/statusline.sh"},
    "model": "claude-fable-5[1m]",
}


def test_install_merges_preserving_existing(tmp_path, tend_home):
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps(EXISTING))
    install.install(sp)
    s = json.loads(sp.read_text())
    cmds = [h["command"] for e in s["hooks"]["PostToolUse"] for h in e["hooks"]]
    assert any("agent_pd" in c for c in cmds)          # preserved
    assert any("-m tend.hook" in c for c in cmds)      # added
    for ev in install.HOOK_EVENTS:
        assert any("-m tend.hook" in h["command"] for e in s["hooks"][ev] for h in e["hooks"])
    assert s["model"] == "claude-fable-5[1m]"          # untouched
    # statusline wrapped, original preserved
    assert "-m tend.statusline" in s["statusLine"]["command"]
    orig = paths.read_json(tend_home / "statusline-original.json")
    assert "statusline.sh" in orig["command"]
    # backup written
    assert (tmp_path / "settings.json.bak-tend").exists()


def test_install_idempotent(tmp_path):
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps(EXISTING))
    install.install(sp)
    once = json.loads(sp.read_text())
    install.install(sp)
    assert json.loads(sp.read_text()) == once


def test_uninstall_restores(tmp_path, tend_home):
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps(EXISTING))
    install.install(sp)
    install.uninstall(sp)
    s = json.loads(sp.read_text())
    cmds = [h["command"] for e in s["hooks"].get("PostToolUse", []) for h in e["hooks"]]
    assert cmds == ["python3 -m agent_pd.hook"]
    assert s["statusLine"]["command"] == "bash /Users/varma/.claude/statusline.sh"
    assert "PreCompact" not in s["hooks"]


def test_install_into_empty_settings(tmp_path):
    sp = tmp_path / "settings.json"
    install.install(sp)
    s = json.loads(sp.read_text())
    assert "-m tend.statusline" in s["statusLine"]["command"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_install.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `tend/install.py`**

```python
"""Merge tend into ~/.claude/settings.json non-destructively; reversible."""
import sys
from pathlib import Path

from . import paths

HOOK_EVENTS = [
    "PreToolUse",
    "PostToolUse",
    "UserPromptSubmit",
    "Stop",
    "SessionStart",
    "PreCompact",
    "SubagentStart",
    "SubagentStop",
]

HOOK_MARKER = "-m tend.hook"
STATUSLINE_MARKER = "-m tend.statusline"


def hook_command() -> str:
    return f"{sys.executable} {HOOK_MARKER}"


def statusline_command() -> str:
    return f"{sys.executable} {STATUSLINE_MARKER}"


def install(settings_path) -> None:
    sp = Path(settings_path)
    settings = paths.read_json(sp, {}) or {}
    hooks = settings.setdefault("hooks", {})
    for ev in HOOK_EVENTS:
        entries = hooks.setdefault(ev, [])
        if not _has_marker(entries, HOOK_MARKER):
            entries.append({"hooks": [{"type": "command", "command": hook_command()}]})
    sl = settings.get("statusLine")
    if sl and STATUSLINE_MARKER not in (sl.get("command") or ""):
        paths.write_json_atomic(paths.home() / "statusline-original.json", sl)
        settings["statusLine"] = {"type": "command", "command": statusline_command()}
    elif not sl:
        settings["statusLine"] = {"type": "command", "command": statusline_command()}
    _write_settings(sp, settings)


def uninstall(settings_path) -> None:
    sp = Path(settings_path)
    settings = paths.read_json(sp, {}) or {}
    hooks = settings.get("hooks", {})
    for ev in list(hooks):
        hooks[ev] = [e for e in hooks[ev] if not _has_marker([e], HOOK_MARKER)]
        if not hooks[ev]:
            del hooks[ev]
    sl = settings.get("statusLine") or {}
    if STATUSLINE_MARKER in (sl.get("command") or ""):
        orig = paths.read_json(paths.home() / "statusline-original.json")
        if orig:
            settings["statusLine"] = orig
        else:
            settings.pop("statusLine", None)
    _write_settings(sp, settings)


def _has_marker(entries, marker) -> bool:
    return any(
        marker in (h.get("command") or "")
        for e in entries
        for h in (e.get("hooks") or [])
    )


def _write_settings(sp, settings) -> None:
    backup = sp.with_name(sp.name + ".bak-tend")
    if sp.exists() and not backup.exists():
        backup.write_text(sp.read_text())
    paths.write_json_atomic(sp, settings, indent=2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_install.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: non-destructive settings.json install/uninstall"
```

---

### Task 19: CLI

**Files:**
- Create: `tend/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
import json

from tend import cli, paths


def seed_session(sid="s1", total=50000, pct=42.0):
    paths.write_json_atomic(paths.session_dir(sid) / "summary.json", {
        "context_total": total, "output_total": 100,
        "results": {"t1": {"tool": "Bash", "tokens": 3000, "file": None, "stale": True}},
        "reads": {}, "pending": {}, "agents": {}, "state_mark": None, "degraded": False,
    })
    paths.write_json_atomic(paths.session_dir(sid) / "ctx.json",
                            {"context_window": {"used_percentage": pct}})


def test_status_prints_summary(capsys, tend_home):
    seed_session()
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "42%" in out and "50,000" in out and "3,000" in out and "STALE" in out


def test_status_no_sessions(capsys, tend_home):
    assert cli.main(["status"]) == 0
    assert "no tend sessions" in capsys.readouterr().out


def test_report_lists_results(capsys, tend_home):
    seed_session()
    assert cli.main(["report"]) == 0
    assert "Bash" in capsys.readouterr().out


def test_on_off(tend_home):
    assert cli.main(["off"]) == 0
    assert paths.disabled()
    assert cli.main(["on"]) == 0
    assert not paths.disabled()


def test_handoff_prints_state(capsys, tmp_path, tend_home):
    sp = tmp_path / ".claude" / "tend" / "STATE.md"
    sp.parent.mkdir(parents=True)
    sp.write_text("## Goal\nShip it\n")
    assert cli.main(["handoff", "--cwd", str(tmp_path)]) == 0
    assert "Ship it" in capsys.readouterr().out


def test_handoff_warns_when_missing(capsys, tmp_path, tend_home):
    assert cli.main(["handoff", "--cwd", str(tmp_path)]) == 1
    assert "No STATE.md" in capsys.readouterr().out


def test_install_hook_via_cli(tmp_path, tend_home):
    sp = tmp_path / "settings.json"
    sp.write_text("{}")
    assert cli.main(["install-hook", "--settings", str(sp)]) == 0
    assert "-m tend.hook" in sp.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `tend/cli.py`**

```python
"""tend CLI: status, report, handoff, on/off, install-hook, uninstall-hook, statusline-wrap."""
import argparse
import time
from pathlib import Path

from . import ctxmetrics, install, ledger, paths, state


def latest_session():
    root = paths.home() / "sessions"
    if not root.exists():
        return None
    dirs = [d for d in root.iterdir() if d.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda d: d.stat().st_mtime).name


def cmd_status(args) -> int:
    sid = args.session or latest_session()
    if not sid:
        print("no tend sessions recorded yet")
        return 0
    summary = ledger.load_summary(sid)
    pct = ctxmetrics.used_pct(sid)
    print(f"session  {sid}")
    pct_s = f"{pct:.0f}%" if pct is not None else "unknown"
    print(f"context  {pct_s} ({summary.get('context_total', 0):,} tok)")
    print(f"stale    {ledger.stale_tokens(summary):,} tok of stale tool results")
    sp = state.path_for(args.cwd)
    if sp.exists():
        age_h = (time.time() - sp.stat().st_mtime) / 3600
        print(f"STATE.md updated {age_h:.1f}h ago ({sp})")
    else:
        print("STATE.md missing for this project")
    top = ledger.top_results(summary, 3)
    if top:
        print("top results:")
        for r in top:
            mark = "  STALE" if r.get("stale") else ""
            print(f"  {r['tokens']:>8,} tok  {r.get('tool') or '?'} {r.get('file') or ''}{mark}")
    return 0


def cmd_report(args) -> int:
    sid = args.session or latest_session()
    if not sid:
        print("no tend sessions recorded yet")
        return 0
    summary = ledger.load_summary(sid)
    print(f"# tend report - session {sid}\n")
    print(f"context total : {summary.get('context_total', 0):,} tok")
    print(f"output total  : {summary.get('output_total', 0):,} tok")
    print(f"stale results : {ledger.stale_tokens(summary):,} tok")
    print(f"degraded      : {summary.get('degraded')}")
    print("\n## tool results by size")
    for r in ledger.top_results(summary, 20):
        mark = "  STALE" if r.get("stale") else ""
        print(f"  {r['tokens']:>8,} tok  {r.get('tool') or '?'} {r.get('file') or ''}{mark}")
    outputs = sorted((paths.session_dir(sid) / "outputs").glob("*.txt"))
    if outputs:
        print(f"\n## offloaded outputs ({len(outputs)})")
        for p in outputs:
            print(f"  {p}")
    agents = summary.get("agents", {})
    if agents:
        print(f"\n## subagents ({len(agents)})")
        for aid, a in agents.items():
            status = "done" if a.get("stopped") else "running"
            print(f"  {aid}  {a.get('type') or '?'}  {status}")
    return 0


def cmd_handoff(args) -> int:
    sp = state.path_for(args.cwd)
    if not sp.exists():
        print(f"No STATE.md at {sp} - nothing to hand off. "
              "Ask Claude to write it, or start a session to seed the template.")
        return 1
    age_h = (time.time() - sp.stat().st_mtime) / 3600
    print(f"STATE.md ({sp}) - updated {age_h:.1f}h ago")
    if age_h > 4:
        print("WARNING: state may be stale; ask Claude to update it before switching sessions.")
    print("\nA new session in this project will auto-load:\n")
    print(sp.read_text())
    return 0


def cmd_on(args) -> int:
    (paths.home() / "disabled").unlink(missing_ok=True)
    print("tend enabled")
    return 0


def cmd_off(args) -> int:
    paths.home().mkdir(parents=True, exist_ok=True)
    (paths.home() / "disabled").touch()
    print("tend disabled (hooks exit immediately)")
    return 0


def cmd_install(args) -> int:
    install.install(args.settings)
    print(f"tend hooks + statusline installed into {args.settings}")
    print("Restart your Claude Code session to activate.")
    return 0


def cmd_uninstall(args) -> int:
    install.uninstall(args.settings)
    print(f"tend removed from {args.settings}")
    return 0


def cmd_statusline_wrap(args) -> int:
    from . import statusline

    return statusline.main()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tend", description="Context-hygiene harness for Claude Code")
    sub = parser.add_subparsers(dest="command", required=True)
    default_settings = str(Path.home() / ".claude" / "settings.json")

    for name, fn, opts in [
        ("status", cmd_status, ["session", "cwd"]),
        ("report", cmd_report, ["session", "cwd"]),
        ("handoff", cmd_handoff, ["cwd"]),
        ("on", cmd_on, []),
        ("off", cmd_off, []),
        ("install-hook", cmd_install, ["settings"]),
        ("uninstall-hook", cmd_uninstall, ["settings"]),
        ("statusline-wrap", cmd_statusline_wrap, []),
    ]:
        p = sub.add_parser(name)
        if "session" in opts:
            p.add_argument("--session", default=None)
        if "cwd" in opts:
            p.add_argument("--cwd", default=".")
        if "settings" in opts:
            p.add_argument("--settings", default=default_settings)
        p.set_defaults(fn=fn)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: tend CLI"
```

---

### Task 20: integration tests + README

**Files:**
- Create: `tests/test_integration.py`
- Modify: `README.md`

- [ ] **Step 1: Write the integration test (subprocess, real entry point)**

`tests/test_integration.py`:
```python
import json
import os
import subprocess
import sys


def run_hook(payload, env_home):
    env = dict(os.environ, TEND_HOME=str(env_home))
    return subprocess.run(
        [sys.executable, "-m", "tend.hook"],
        input=payload, capture_output=True, text=True, env=env, timeout=30,
    )


def test_posttooluse_offload_end_to_end(tmp_path):
    payload = json.dumps({
        "hook_event_name": "PostToolUse",
        "session_id": "int1",
        "cwd": str(tmp_path),
        "transcript_path": "",
        "tool_name": "Bash",
        "tool_response": "B" * 20000,
    })
    res = run_hook(payload, tmp_path / "home")
    assert res.returncode == 0
    out = json.loads(res.stdout)
    assert "tokens offloaded" in out["hookSpecificOutput"]["updatedToolOutput"]


def test_garbage_stdin_exits_zero_silently(tmp_path):
    res = run_hook("NOT JSON AT ALL", tmp_path / "home")
    assert res.returncode == 0
    assert res.stdout == ""


def test_statusline_end_to_end(tmp_path):
    payload = json.dumps({
        "session_id": "int2",
        "model": {"display_name": "Fable"},
        "context_window": {"used_percentage": 33.0},
    })
    env = dict(os.environ, TEND_HOME=str(tmp_path / "home"))
    res = subprocess.run(
        [sys.executable, "-m", "tend.statusline"],
        input=payload, capture_output=True, text=True, env=env, timeout=30,
    )
    assert res.returncode == 0
    assert "Fable" in res.stdout
    ctx = json.loads((tmp_path / "home" / "sessions" / "int2" / "ctx.json").read_text())
    assert ctx["context_window"]["used_percentage"] == 33.0
```

- [ ] **Step 2: Run integration tests**

Run: `python3 -m pytest tests/test_integration.py -v`
Expected: 3 passed.

- [ ] **Step 3: Write the real README**

Replace `README.md` with:
```markdown
# tend

Context-hygiene harness for Claude Code. Makes deep context usable instead of
bailing out early: offloads oversized tool outputs to disk, keeps session
state externalized in `STATE.md`, anchors the current goal at the end of
context on every prompt, and turns compaction into a curated, well-timed
event. New sessions auto-restore state, so `/clear` is a lossless handoff.

## Install

    python3 -m pip install --user -e .
    tend install-hook        # merges hooks + statusline into ~/.claude/settings.json
    # restart your Claude Code session

## Commands

| Command | Does |
|---|---|
| `tend status` | Context %, totals, stale-result tokens, STATE.md freshness |
| `tend report` | Full ledger: tool results by size, offloads, subagents |
| `tend handoff` | Show what the next session will auto-load |
| `tend on` / `tend off` | Global kill switch |
| `tend install-hook` / `tend uninstall-hook` | Reversible settings.json setup |

## How it works

Six hooks + a statusline tee. All fail-open: a tend bug can never break your
session. See `docs/superpowers/specs/2026-06-09-context-harness-design.md`.

Config: `~/.claude/tend/config.yaml`, overridable per project in
`<project>/.claude/tend/config.yaml`. Keys and defaults are in `tend/config.py`.
```

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest -q`
Expected: all tests pass (≈57). Fix anything that fails before committing.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "test: end-to-end integration tests; real README"
```

---

### Task 21: Live install + visual evidence

**Files:**
- Create: `docs/test-evidence.md`, `docs/screenshots/*.png`, `.capture.yaml`

This task touches the real `~/.claude/settings.json`. The backup
(`settings.json.bak-tend`) is written automatically by install.

- [ ] **Step 1: Install for real**

Run:
```bash
python3 -m pip install --user -e /Users/varma/tend
tend install-hook
python3 -c "import json; s=json.load(open('/Users/varma/.claude/settings.json')); print(json.dumps(s['hooks'].keys() if 0 else list(s['hooks']), indent=0)); print(s['statusLine'])"
```
Expected: all 8 tend events present alongside agent-pd entries; statusLine command contains `-m tend.statusline`; `~/.claude/tend/statusline-original.json` holds the original `bash /Users/varma/.claude/statusline.sh`.

- [ ] **Step 2: Smoke-test the hook against a real captured payload**

Run:
```bash
echo '{"hook_event_name":"PostToolUse","session_id":"smoke","cwd":"/tmp","tool_name":"Bash","tool_response":"'$(python3 -c "print('x'*15000)")'"}' | python3 -m tend.hook
```
Expected: JSON on stdout containing `updatedToolOutput`; file under `~/.claude/tend/sessions/smoke/outputs/`.

- [ ] **Step 3: Capture CLI evidence**

Write `.capture.yaml` in the repo root:
```yaml
shots:
  - kind: cli
    command: tend status
    name: tend-status
  - kind: cli
    command: tend report
    name: tend-report
  - kind: cli
    command: tend handoff --cwd /Users/varma/tend
    name: tend-handoff
```
Run: `capture run`
Expected: numbered PNGs under `docs/screenshots/`.

- [ ] **Step 4: Write `docs/test-evidence.md`**

One captioned screenshot per feature (status, report, handoff), plus the
smoke-test transcript from Step 2 in a code block.

- [ ] **Step 5: Live-session canary (user-assisted)**

A fresh Claude Code session must be started to verify end-to-end behavior:
- statusline still renders (wrapped, not broken)
- `~/.claude/tend/sessions/<new-sid>/ctx.json` appears after first prompt
- STATE.md template seeded in the project + convention note visible to Claude
- a deliberately huge `Bash` output (e.g. `seq 1 20000`) gets offloaded

Document results in `docs/test-evidence.md`. If anything misbehaves:
`tend off` instantly neutralizes all hooks (they exit immediately), and
`tend uninstall-hook` fully reverts settings.

- [ ] **Step 6: Final commit**

```bash
git add -A && git commit -m "docs: install evidence and live validation"
```

---

## Self-review checklist (done at plan-writing time)

- **Spec coverage:** skeleton (T1-4), measurement (T5-7), pillar 1 (T10-11), pillar 2 (T9, T12), pillar 3 (T13-14), pillar 4 (T13, T15-16), dispatch (T17), install (T18), CLI (T19), integration+README (T20), evidence/canary (T21). Per-agent ledger for the future orchestrator: T5 (`record_agent`) + T17 wiring.
- **Type consistency:** `config.load(cwd)`, `ledger.load_summary(sid)`, `flags.load/save(sid, fl)`, `state.path_for(cwd)`, `advisor.advice(pct, cfg, state_path, fl)` used identically across tasks; summary dict keys (`context_total`, `results`, `state_mark`, `agents`) consistent between T5, T12, T15, T19.
- **No placeholders:** every code step contains complete, runnable code.
