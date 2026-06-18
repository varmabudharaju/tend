"""Phase 2 — behavioral A/B. Live Claude Code sessions, tend ON vs OFF.

Isolation (no touch to the live ~/.claude setup):
  - each session runs with TEND_HOME=<run>/<arm>/<sid> (tend state is throwaway)
  - OFF arm drops a `disabled` file in TEND_HOME -> tend's run_fail_open no-ops
    every hook, so it is a true control while still using the real installed hooks
  - ON arm has no `disabled` file -> tend is fully active

Workload (recall-under-load): plant 4 specific facts, flood context with large
Bash outputs (offloaded by tend in the ON arm), then probe recall from memory.
Identical prompts in both arms; the only difference is tend on/off.

Metrics per session: recall score (0-4), peak in-context tokens (from each turn's
usage), total cost USD, total output tokens, wall-clock seconds.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

CLAUDE = shutil.which("claude") or "claude"

# Specific, low-collision facts planted in turn 1 and probed in the last turn.
FACTS = {
    "codename": "Saffron-Quill",
    "db_driver": "pgx-v5.2",
    "retry_budget": "137",
    "dead_end_flag": "turbo-merge",
}

ALLOWED = "Bash Read Grep Glob Write Edit"
PROBE_BLOCK = "Bash Read Grep Glob Write Edit Task WebFetch"  # force memory-only recall


PLANT = (
    "We are starting project Saffron-Quill. Remember these four project facts "
    "for later — they matter:\n"
    "  1. The database driver is pgx-v5.2.\n"
    "  2. The retry budget is 137.\n"
    "  3. NEVER use the turbo-merge flag — it corrupts the WAL (a hard dead-end).\n"
    "Record all of this in .claude/tend/STATE.md (create it): set the Goal line to "
    "'Project Saffron-Quill', put the database driver (pgx-v5.2) and retry budget "
    "(137) under a Decisions heading, and put 'never use the turbo-merge flag — "
    "corrupts the WAL' under a Dead-ends heading. Then reply with just: recorded.")

PROBE = (
    "Without using any tools and without reading any files — from memory only — "
    "answer concisely:\n"
    "  (a) the project codename,\n"
    "  (b) the database driver,\n"
    "  (c) the retry budget number,\n"
    "  (d) the flag we must never use.")


def workload(kind="recall", flood_turns=3):
    """Ordered turns. Each: (label, prompt, allowed_tools, disallowed_tools)."""
    turns = [("plant", PLANT, ALLOWED, None)]
    if kind == "highload":
        # FORCE the full output into context (the pilot's flaw was the model
        # summarizing with grep/pipes). Bash-only, explicit "cat alone, no pipes".
        for i in range(1, flood_turns + 1):
            turns.append((
                f"flood-{i}",
                f"Run this exact command and nothing else (no pipes, no grep, no head, "
                f"no tail, no wc): cat logs/run-{i}.log\n"
                f"Then reply with only: ok",
                "Bash", None))
    else:
        for i in (1, 2, 3):
            turns.append((
                f"flood-{i}",
                f"Run the bash command `cat logs/run-{i}.log` to inspect it, then tell me "
                f"the single most frequent ERROR code in that file. One short sentence.",
                ALLOWED, None))
        turns.append((
            "distractor",
            "Across all three logs you just looked at, roughly what fraction of lines are "
            "ERROR lines? One sentence; you may use bash.",
            ALLOWED, None))
    turns.append(("probe", PROBE, None, PROBE_BLOCK))
    return turns


def make_sandbox(parent, n_logs=3, log_tokens=9000):
    """A throwaway project dir with deterministic large logs for the flood.

    Each log is ~log_tokens (estimated). Distinct content per file so the model
    cannot dedupe/cache it away."""
    sb = Path(tempfile.mkdtemp(prefix="sess-", dir=parent))
    logs = sb / "logs"
    logs.mkdir()
    approx_line = 92  # chars per row below
    for k in range(1, n_logs + 1):
        n_lines = max(1, (log_tokens * 4) // approx_line)
        rows = []
        for i in range(n_lines):
            code = f"E{(i * (k + 1)) % 7:03d}"
            rows.append(f"2026-06-18 12:{i % 60:02d}:{(i * 7) % 60:02d} "
                        f"ERROR worker={i % 8} code={code} shard={k:02d} "
                        f"failed to sync record id={i:06d} reason=timeout retry={i % 5}")
        (logs / f"run-{k}.log").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return sb


def arm_env(run_dir, arm, sid_tag):
    home = Path(run_dir) / arm / sid_tag
    home.mkdir(parents=True, exist_ok=True)
    if arm == "off":
        (home / "disabled").write_text("", encoding="utf-8")  # kill switch -> true control
    env = {**os.environ, "TEND_HOME": str(home)}
    return env, home


def run_turn(prompt, cwd, env, model, resume_sid=None, allowed=None, disallowed=None,
             timeout=300):
    cmd = [CLAUDE, "-p", prompt, "--output-format", "json", "--model", model]
    if resume_sid:
        cmd += ["--resume", resume_sid]
    if allowed is not None:
        cmd += ["--allowedTools", allowed]
    if disallowed is not None:
        cmd += ["--disallowedTools", disallowed]
    proc = subprocess.run(cmd, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=timeout)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"_parse_error": True, "stdout": proc.stdout[:500],
                "stderr": proc.stderr[:500]}


def _iter_ctx(it):
    return (it.get("input_tokens", 0) + it.get("cache_read_input_tokens", 0)
            + it.get("cache_creation_input_tokens", 0))


def peak_ctx_in(usage):
    """True peak context = the largest single inference this turn saw.

    The aggregate usage sums cache-reads across a turn's tool-use iterations
    (double-counting), so we take the max over usage.iterations instead — that
    is the real 'how full was the desk at once'. Falls back to the aggregate."""
    iters = usage.get("iterations") or []
    if iters:
        return max(_iter_ctx(it) for it in iters)
    return (usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0))


def score_recall(answer):
    low = (answer or "").lower()
    hits = {k: (v.lower() in low) for k, v in FACTS.items()}
    return hits, sum(hits.values())


def run_session(arm, run_dir, model, repeat, kind="recall", flood_turns=3,
                log_tokens=9000, log=print):
    sid_tag = f"r{repeat}"
    env, home = arm_env(run_dir, arm, sid_tag)
    turns = workload(kind, flood_turns)
    n_logs = sum(1 for t in turns if t[0].startswith("flood"))
    sb = make_sandbox(home, n_logs=max(1, n_logs), log_tokens=log_tokens)
    sid = None
    peak_ctx = 0
    total_cost = 0.0
    total_out = 0
    probe_answer = ""
    turns_ctx = []
    errored = False
    t0 = time.time()
    for label, prompt, allowed, disallowed in turns:
        data = run_turn(prompt, sb, env, model, resume_sid=sid,
                        allowed=allowed, disallowed=disallowed, timeout=600)
        if data.get("_parse_error"):
            log(f"    [{arm} r{repeat} {label}] PARSE ERROR: {data.get('stderr','')[:120]}")
            errored = True
            continue
        if data.get("is_error"):
            log(f"    [{arm} r{repeat} {label}] API ERROR: {data.get('subtype')} "
                f"{data.get('api_error_status')}")
            errored = True
            if label != "probe":
                continue
        sid = data.get("session_id", sid)
        usage = data.get("usage", {})
        turn_ctx = peak_ctx_in(usage)
        peak_ctx = max(peak_ctx, turn_ctx)
        turns_ctx.append({"turn": label, "ctx": turn_ctx})
        total_cost += data.get("total_cost_usd", 0.0) or 0.0
        total_out += usage.get("output_tokens", 0)
        if label == "probe":
            probe_answer = data.get("result", "")
        log(f"    [{arm} r{repeat} {label}] peak_ctx={turn_ctx:>7,} "
            f"cost=${total_cost:.3f}")
    offload_files = len(list(home.glob("sessions/*/outputs/*.txt")))
    snapshots = len(list(home.glob("sessions/*/snapshots/*"))) \
        + len(list(home.glob("sessions/*/*snapshot*")))
    hits, recall = score_recall(probe_answer)
    # compaction heuristic: context climbed high, then a later turn dropped sharply
    ctxs = [t["ctx"] for t in turns_ctx]
    compacted = any(ctxs[j] < 0.6 * max(ctxs[:j] or [0]) for j in range(1, len(ctxs)))
    return {
        "arm": arm, "repeat": repeat, "model": model, "kind": kind,
        "recall": recall, "recall_hits": hits,
        "peak_ctx_tokens": peak_ctx,
        "total_cost_usd": round(total_cost, 4),
        "total_output_tokens": total_out,
        "offload_files": offload_files,
        "snapshots": snapshots,
        "compacted": compacted,
        "errored": errored,
        "seconds": round(time.time() - t0, 1),
        "turns_ctx": turns_ctx,
        "probe_answer": probe_answer[:400],
    }


HANDOFF_STATE = """# Session state

## Goal
Project Saffron-Quill

## Decisions
- Database driver: pgx-v5.2
- Retry budget: 137

## Dead-ends
- never use the turbo-merge flag - corrupts the WAL
"""


def run_handoff_session(arm, run_dir, model, repeat, log=print):
    """Isolates tend's restore claim: a maintained STATE.md is held fixed on disk
    in BOTH arms; a FRESH session (source=startup, the same hook /clear uses) probes
    with tools blocked. tend ON auto-injects STATE.md; tend OFF leaves it on disk
    untouched and the (tool-blocked) model cannot reach it. Only variable: tend on/off.

    (Whether the model *populates* STATE.md as it works is a separate, model-dependent
    step — tend nudges for it; here we assume it and measure the restore.)"""
    env, home = arm_env(run_dir, arm, f"r{repeat}")
    sb = make_sandbox(home, n_logs=1, log_tokens=200)
    st = Path(sb) / ".claude" / "tend" / "STATE.md"
    st.parent.mkdir(parents=True, exist_ok=True)
    st.write_text(HANDOFF_STATE, encoding="utf-8")
    t0 = time.time()
    # FRESH session (resume_sid=None) -> SessionStart fires -> tend (ON) restores STATE.md
    d = run_turn(PROBE, sb, env, model, resume_sid=None, allowed=None,
                 disallowed=PROBE_BLOCK, timeout=200)
    answer = d.get("result", "") if not d.get("_parse_error") else ""
    hits, recall = score_recall(answer)
    cost = d.get("total_cost_usd", 0.0) or 0.0
    log(f"    [{arm} r{repeat} handoff] recall={recall}/4 cost=${cost:.3f}")
    return {
        "arm": arm, "repeat": repeat, "model": model, "kind": "handoff",
        "recall": recall, "recall_hits": hits,
        "state_written": True,
        "peak_ctx_tokens": peak_ctx_in(d.get("usage", {})),
        "total_cost_usd": round(cost, 4),
        "total_output_tokens": d.get("usage", {}).get("output_tokens", 0),
        "offload_files": 0, "snapshots": 0, "compacted": False,
        "errored": bool(d.get("_parse_error")),
        "seconds": round(time.time() - t0, 1),
        "turns_ctx": [],
        "probe_answer": answer[:400],
    }


def run_pilot(out_dir, stamp, model="claude-haiku-4-5-20251001", repeats=2,
              arms=("on", "off"), kind="recall", flood_turns=3, log_tokens=9000,
              log=print):
    run_dir = Path(tempfile.mkdtemp(prefix="tend-bench2-"))
    log(f"[bench2] run dir: {run_dir}  model={model}  repeats={repeats}  arms={arms} "
        f"kind={kind} flood_turns={flood_turns} log_tokens={log_tokens}")
    sessions = []
    for repeat in range(1, repeats + 1):
        for arm in arms:
            log(f"  -> session arm={arm} repeat={repeat}")
            if kind == "handoff":
                s = run_handoff_session(arm, run_dir, model, repeat, log=log)
            else:
                s = run_session(arm, run_dir, model, repeat, kind=kind,
                                flood_turns=flood_turns, log_tokens=log_tokens, log=log)
            sessions.append(s)
            log(f"     done: recall={s['recall']}/4 peak_ctx={s['peak_ctx_tokens']:,} "
                f"offloaded={s['offload_files']} compacted={s['compacted']} "
                f"cost=${s['total_cost_usd']}")
    results = {"stamp": stamp, "model": model, "repeats": repeats, "kind": kind,
               "flood_turns": flood_turns, "log_tokens": log_tokens,
               "sessions": sessions, "summary": _summarize(sessions, arms)}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"behavioral-{stamp}.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8")
    md = render_markdown(results, arms)
    (out_dir / f"behavioral-{stamp}.md").write_text(md, encoding="utf-8")
    shutil.rmtree(run_dir, ignore_errors=True)
    return results, md


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return 0
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _summarize(sessions, arms):
    out = {}
    for arm in arms:
        rows = [s for s in sessions if s["arm"] == arm]
        if not rows:
            continue
        out[arm] = {
            "n": len(rows),
            "median_recall": _median([r["recall"] for r in rows]),
            "median_peak_ctx": _median([r["peak_ctx_tokens"] for r in rows]),
            "median_cost_usd": round(_median([r["total_cost_usd"] for r in rows]), 4),
            "total_cost_usd": round(sum(r["total_cost_usd"] for r in rows), 4),
        }
    return out


def render_markdown(r, arms):
    s = r["summary"]
    L = ["# tend behavioral A/B (pilot)", "",
         f"_Generated {r['stamp']} · model `{r['model']}` · {r['repeats']} repeats/arm · "
         "recall-under-load workload._", "",
         "Identical scripted session in both arms (plant 4 facts → flood context with "
         "large Bash outputs → probe recall from memory). Only difference: tend on/off.",
         "", "## Summary (medians)", "",
         "| metric | tend ON | tend OFF | delta |", "|---|--:|--:|--:|"]
    if "on" in s and "off" in s:
        on, off = s["on"], s["off"]

        def delta(a, b, pct=True):
            if not b:
                return "—"
            d = 100 * (a - b) / b
            return f"{d:+.0f}%" if pct else f"{a-b:+.1f}"
        L += [
            f"| recall (/4) | {on['median_recall']} | {off['median_recall']} "
            f"| {delta(on['median_recall'], off['median_recall'], pct=False)} |",
            f"| peak context tokens | {on['median_peak_ctx']:,} | {off['median_peak_ctx']:,} "
            f"| {delta(on['median_peak_ctx'], off['median_peak_ctx'])} |",
            f"| cost / session (USD) | ${on['median_cost_usd']} | ${off['median_cost_usd']} "
            f"| {delta(on['median_cost_usd'], off['median_cost_usd'])} |",
        ]
    L += ["", "## Per-session", "",
          "| arm | repeat | recall | peak ctx tok | cost $ | offloaded | compacted | sec |",
          "|---|--:|--:|--:|--:|--:|:--:|--:|"]
    for x in r["sessions"]:
        L.append(f"| {x['arm']} | {x['repeat']} | {x['recall']}/4 "
                 f"| {x['peak_ctx_tokens']:,} | {x['total_cost_usd']} "
                 f"| {x['offload_files']} | {'yes' if x.get('compacted') else 'no'}"
                 f"{' ⚠err' if x.get('errored') else ''} | {x['seconds']} |")
    L += ["", "## Probe answers (recall check)", ""]
    for x in r["sessions"]:
        hits = ", ".join(k for k, v in x["recall_hits"].items() if v) or "none"
        L.append(f"- **{x['arm']} r{x['repeat']}** ({x['recall']}/4, hit: {hits}): "
                 f"{x['probe_answer'][:160].strip()}")
    return "\n".join(L) + "\n"
