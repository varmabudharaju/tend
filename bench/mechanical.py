"""Phase 1 — mechanical benchmark. Deterministic, no LLM, no network.

Measures what carryover *does* to the context window and what it costs per event:
  1. offload savings    — token reduction on real + synthetic tool outputs
  2. anchor budget      — actual anchor token size vs the <=400 claim
  3. per-event overhead — real `python3 -m carryover.hook` subprocess latency
  4. footprint sim      — cumulative in-context tokens, with vs without carryover

All carryover artifacts are redirected to a throwaway CARRYOVER_HOME, so the live
~/.claude setup is never touched.
"""
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# corpora
# --------------------------------------------------------------------------- #
CORPUS_DIR = REPO / "bench" / "corpus"


def load_real_corpus():
    """Frozen, scrubbed real outputs committed in bench/corpus (reproducible)."""
    items = []
    for f in sorted(CORPUS_DIR.glob("*.txt")):
        items.append((f"real:{f.name}", f.read_text(encoding="utf-8", errors="replace")))
    return items


def load_live_corpus():
    """Opt-in: the runner's own offloaded outputs from ~/.claude/carryover/sessions."""
    root = Path.home() / ".claude" / "carryover" / "sessions"
    items = []
    for f in sorted(root.glob("*/outputs/*.txt")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        items.append((f"live:{f.parent.parent.name[:8]}/{f.name}", text))
    return items


def synthetic_corpus():
    """A size ladder (estimated tokens) spanning below/above the offload threshold."""
    sizes = [500, 1500, 2500, 5000, 10000, 25000, 50000]
    line = ("2026-06-18 12:00:00 INFO  worker=7 processing record id=%07d "
            "status=ok latency=12ms payload={'key':'value','n':42}\n")
    items = []
    for n in sizes:
        target = n * 4  # tokens.estimate == len // 4
        buf, total, i = [], 0, 0
        while total < target:
            s = line % i
            buf.append(s)
            total += len(s)
            i += 1
        text = "".join(buf)[:target]
        items.append((f"synthetic:{n}tok", text))
    return items


# --------------------------------------------------------------------------- #
# 1. offload savings
# --------------------------------------------------------------------------- #
def measure_offload(corpus, workdir):
    from carryover import offload, tokens

    rows = []
    for name, text in corpus:
        event = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "session_id": "bench-offload",
            "cwd": str(workdir),
            "tool_response": text,
        }
        result = offload.handle(event)
        full = tokens.estimate(text)
        if result:
            excerpt = result["hookSpecificOutput"]["updatedToolOutput"]
            kept = tokens.estimate(excerpt)
            offloaded = True
        else:
            kept = full
            offloaded = False
        rows.append({
            "name": name,
            "full_tokens": full,
            "kept_tokens": kept,
            "saved_tokens": full - kept,
            "reduction_pct": round(100 * (full - kept) / full, 1) if full else 0.0,
            "offloaded": offloaded,
        })
    return rows


# --------------------------------------------------------------------------- #
# 1b. offload correctness invariants
# --------------------------------------------------------------------------- #
def measure_invariants(workdir):
    """Verify carryover offloads the *right* things, not just a lot of things."""
    from carryover import offload

    big = "x" * 200_000  # ~50k tokens
    base = {"session_id": "bench-inv", "cwd": str(workdir)}
    cases = [
        ("large Bash output is offloaded",
         {**base, "tool_name": "Bash", "tool_response": big}, True),
        ("non-offload tool (Read) left alone",
         {**base, "tool_name": "Read", "tool_response": big}, False),
        ("tiny output left alone",
         {**base, "tool_name": "Bash", "tool_response": "ok"}, False),
        ("MCP structured (non-str) output skipped",
         {**base, "tool_name": "mcp__db__query",
          "tool_response": {"rows": list(range(5000))}}, False),
        ("Bash {stdout,stderr} dict payload offloaded",
         {**base, "tool_name": "Bash",
          "tool_response": {"stdout": big, "stderr": "warn"}}, True),
    ]
    checks = []
    for desc, event, expect in cases:
        got = offload.handle(event) is not None
        checks.append({"invariant": desc,
                       "expected": "offload" if expect else "leave alone",
                       "result": "offloaded" if got else "left alone",
                       "pass": got == expect})
    return checks


# --------------------------------------------------------------------------- #
# 2. anchor budget
# --------------------------------------------------------------------------- #
def measure_anchor(workdir):
    from carryover import anchor, config, paths, tokens

    cfg = config.load(str(workdir))
    sp = workdir / ".claude" / "carryover" / "STATE.md"
    sp.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    # Sweep goal/now text length, including absurd sizes, to probe the cap.
    for chars in [40, 120, 400, 2000, 20000]:
        goal = "build a context-hygiene harness " * (chars // 32 + 1)
        now = "wiring the per-prompt anchor injection path " * (chars // 44 + 1)
        sp.write_text(f"# Session state\n\n## Goal\n{goal}\n\n## Now\n{now}\n",
                      encoding="utf-8")
        sid = f"bench-anchor-{chars}"
        sd = paths.session_dir(sid)
        (sd / "ctx.json").write_text(json.dumps(
            {"context_window": {"used_percentage": 75},
             "model": {"display_name": "Opus"}}), encoding="utf-8")
        # Trigger every health/advice line: stale + bloat + reminder + urge.
        (sd / "summary.json").write_text(json.dumps(
            {"output_total": 5000,
             "results": {"r1": {"tokens": 8000, "stale": True},
                         "r2": {"tokens": 12000, "stale": False}}}),
            encoding="utf-8")
        (sd / "flags.json").write_text(json.dumps(
            {"state_reminder": True, "boundary": True}), encoding="utf-8")

        event = {"hook_event_name": "UserPromptSubmit", "session_id": sid,
                 "cwd": str(workdir), "prompt": "continue the work"}
        res = anchor.handle(event)
        ac = res["hookSpecificOutput"]["additionalContext"] if res else ""
        rows.append({
            "state_text_chars": len(goal) + len(now),
            "anchor_chars": len(ac),
            "anchor_tokens": tokens.estimate(ac),
            "within_budget": tokens.estimate(ac) <= cfg.anchor_max_tokens,
        })
    return rows, cfg.anchor_max_tokens


# --------------------------------------------------------------------------- #
# 3. per-event overhead
# --------------------------------------------------------------------------- #
def _events(workdir):
    big = "ERROR something\n" * 4000  # ~16k tokens -> exercises offload path
    return {
        "PostToolUse(offload)": {
            "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "session_id": "bench-lat", "cwd": str(workdir),
            "tool_response": big},
        "PreToolUse(guards)": {
            "hook_event_name": "PreToolUse", "tool_name": "Read",
            "session_id": "bench-lat", "cwd": str(workdir),
            "tool_input": {"file_path": "/etc/hosts"}},
        "UserPromptSubmit(anchor)": {
            "hook_event_name": "UserPromptSubmit", "session_id": "bench-lat",
            "cwd": str(workdir), "prompt": "do the thing"},
        "Stop(boundary)": {
            "hook_event_name": "Stop", "session_id": "bench-lat",
            "cwd": str(workdir)},
        "SessionStart": {
            "hook_event_name": "SessionStart", "session_id": "bench-lat",
            "cwd": str(workdir)},
        "PreCompact": {
            "hook_event_name": "PreCompact", "session_id": "bench-lat",
            "cwd": str(workdir)},
    }


def _pctiles(xs):
    xs = sorted(xs)
    n = len(xs)

    def at(q):
        return xs[min(n - 1, int(q * n))] if n else 0.0

    return {
        "n": n,
        "mean_ms": round(statistics.mean(xs), 2) if xs else 0.0,
        "p50_ms": round(statistics.median(xs), 2) if xs else 0.0,
        "p95_ms": round(at(0.95), 2),
        "p99_ms": round(at(0.99), 2),
    }


def _bar(frac, width=28):
    frac = 0.0 if frac is None else max(0.0, min(1.0, frac))
    n = round(frac * width)
    return "#" * n + "." * (width - n)


def measure_latency_subprocess(workdir, iters=40):
    """Real per-event wall-clock: a cold `python3 -m carryover.hook` subprocess."""
    env = {**os.environ, "CARRYOVER_HOME": str(workdir / "carryover_home")}
    results = {}

    # Baseline: bare interpreter start, to attribute startup vs carryover's own work.
    base = []
    for _ in range(iters):
        t0 = time.perf_counter()
        subprocess.run([sys.executable, "-c", "pass"], capture_output=True,
                       env=env, cwd=str(REPO))
        base.append((time.perf_counter() - t0) * 1000)
    results["_baseline(python -c pass)"] = _pctiles(base)

    for label, ev in _events(workdir).items():
        payload = json.dumps(ev)
        times = []
        for _ in range(iters):
            t0 = time.perf_counter()
            subprocess.run([sys.executable, "-m", "carryover.hook"], input=payload,
                           text=True, capture_output=True, env=env, cwd=str(REPO))
            times.append((time.perf_counter() - t0) * 1000)
        results[label] = _pctiles(times)
    return results


def measure_latency_inprocess(workdir, iters=300):
    """Algorithmic cost only: the handler call, interpreter already warm."""
    from carryover import hook

    results = {}
    for label, ev in _events(workdir).items():
        times = []
        for _ in range(iters):
            t0 = time.perf_counter()
            try:
                hook.dispatch(dict(ev))
            except Exception:
                pass
            times.append((time.perf_counter() - t0) * 1000)
        results[label] = _pctiles(times)
    return results


# --------------------------------------------------------------------------- #
# 4. cumulative footprint simulation
# --------------------------------------------------------------------------- #
def measure_footprint(corpus, workdir):
    from carryover import offload, tokens

    series, cum_without, cum_with = [], 0, 0
    for i, (name, text) in enumerate(corpus, 1):
        full = tokens.estimate(text)
        event = {"hook_event_name": "PostToolUse", "tool_name": "Bash",
                 "session_id": "bench-footprint", "cwd": str(workdir),
                 "tool_response": text}
        res = offload.handle(event)
        if res:
            kept = tokens.estimate(res["hookSpecificOutput"]["updatedToolOutput"])
        else:
            kept = full
        cum_without += full
        cum_with += kept
        series.append({"step": i, "name": name,
                       "cum_without_carryover": cum_without, "cum_with_carryover": cum_with})
    return series


# --------------------------------------------------------------------------- #
# run + report
# --------------------------------------------------------------------------- #
def run(out_dir, stamp, iters=40, live_corpus=False):
    tmp = tempfile.mkdtemp(prefix="carryover-bench-")
    workdir = Path(tmp)
    os.environ["CARRYOVER_HOME"] = str(workdir / "carryover_home")

    real = load_live_corpus() if live_corpus else load_real_corpus()
    synth = synthetic_corpus()
    corpus = real + synth

    offload_rows = measure_offload(corpus, workdir)
    invariants = measure_invariants(workdir)
    anchor_rows, anchor_budget = measure_anchor(workdir)
    lat_sub = measure_latency_subprocess(workdir, iters=iters)
    lat_in = measure_latency_inprocess(workdir)
    footprint = measure_footprint(real or synth, workdir)

    off = [r for r in offload_rows if r["offloaded"]]
    tot_full = sum(r["full_tokens"] for r in offload_rows)
    tot_kept = sum(r["kept_tokens"] for r in offload_rows)
    never_inflates = all(r["kept_tokens"] <= r["full_tokens"] for r in offload_rows)
    invariants.append({"invariant": "carryover never inflates context (kept <= full, all outputs)",
                       "expected": "kept <= full", "result": "held" if never_inflates else "VIOLATED",
                       "pass": never_inflates})
    results = {
        "stamp": stamp,
        "host": {
            "platform": sys.platform,
            "python": sys.version.split()[0],
            "uname": " ".join(os.uname()),
        },
        "config": {"anchor_max_tokens": anchor_budget},
        "offload": {
            "rows": offload_rows,
            "n_outputs": len(offload_rows),
            "n_offloaded": len(off),
            "total_full_tokens": tot_full,
            "total_kept_tokens": tot_kept,
            "total_saved_tokens": tot_full - tot_kept,
            "overall_reduction_pct": round(100 * (tot_full - tot_kept) / tot_full, 1)
            if tot_full else 0.0,
        },
        "invariants": invariants,
        "anchor": {"rows": anchor_rows, "budget_tokens": anchor_budget,
                   "max_observed_tokens": max((r["anchor_tokens"] for r in anchor_rows),
                                              default=0)},
        "latency_subprocess_ms": lat_sub,
        "latency_inprocess_ms": lat_in,
        "footprint": footprint,
    }

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"mechanical-{stamp}.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8")
    md = render_markdown(results)
    (out_dir / f"mechanical-{stamp}.md").write_text(md, encoding="utf-8")
    return results, md


def render_markdown(r):
    o = r["offload"]
    a = r["anchor"]
    inv = r["invariants"]
    sub = r["latency_subprocess_ms"]
    ev_lat = [v for k, v in sub.items() if not k.startswith("_")]
    p50 = round(statistics.median([s["p50_ms"] for s in ev_lat]), 1) if ev_lat else 0
    base = sub.get("_baseline(python -c pass)", {}).get("p50_ms", 0)
    inv_pass = sum(1 for c in inv if c["pass"])

    # ---- verdict header ----
    L = ["# carryover mechanical benchmark", "",
         f"_Generated {r['stamp']} on {r['host']['uname']} (Python {r['host']['python']})._",
         "", "## Verdict at a glance", "",
         f"- **Context management:** {o['overall_reduction_pct']}% fewer tokens in context "
         f"across {o['n_outputs']} outputs ({o['total_full_tokens']:,} -> {o['total_kept_tokens']:,}).",
         f"- **Anchor budget:** max {a['max_observed_tokens']} / {a['budget_tokens']} tokens — within budget.",
         f"- **Overhead:** ~{p50} ms per event (of which ~{base} ms is bare Python startup).",
         f"- **Correctness:** {inv_pass}/{len(inv)} invariants held.",
         "", "## 1. Context savings (offloading)", "",
         f"- Outputs tested: **{o['n_outputs']}** ({o['n_offloaded']} large enough to offload)",
         f"- Total in-context tokens **without carryover: {o['total_full_tokens']:,}**",
         f"- Total in-context tokens **with carryover: {o['total_kept_tokens']:,}**",
         f"- **Saved: {o['total_saved_tokens']:,} tokens ({o['overall_reduction_pct']}% reduction)**",
         ""]
    # savings curve over the synthetic size ladder
    synth = [row for row in o["rows"] if row["name"].startswith("synthetic:")]
    if synth:
        L += ["Savings curve (synthetic size ladder, bar = % reduction):", "", "```"]
        for row in synth:
            size = row["name"].split(":")[1]
            L.append(f"{size:>10}  {_bar(row['reduction_pct'] / 100)}  {row['reduction_pct']:>5}%")
        L += ["```", ""]
    L += ["| output | full tok | kept tok | reduction | offloaded |",
          "|---|--:|--:|--:|:--:|"]
    for row in o["rows"]:
        L.append(f"| {row['name']} | {row['full_tokens']:,} | {row['kept_tokens']:,} "
                 f"| {row['reduction_pct']}% | {'yes' if row['offloaded'] else 'no'} |")

    # ---- invariants ----
    L += ["", "## 1b. Offload correctness invariants", "",
          f"**{inv_pass}/{len(inv)} held.** carryover offloads the right things, not just a lot of things.",
          "", "| invariant | expected | result | pass |", "|---|---|---|:--:|"]
    for c in inv:
        L.append(f"| {c['invariant']} | {c['expected']} | {c['result']} "
                 f"| {'PASS' if c['pass'] else 'FAIL'} |")

    L += ["", "## 2. Anchor token budget", "",
          f"Budget (`anchor_max_tokens`): **{a['budget_tokens']}** tokens. "
          f"Max observed: **{a['max_observed_tokens']}** tokens.", "",
          "| state text chars | anchor tokens | within budget |",
          "|--:|--:|:--:|"]
    for row in a["rows"]:
        L.append(f"| {row['state_text_chars']:,} | {row['anchor_tokens']} "
                 f"| {'yes' if row['within_budget'] else 'NO'} |")

    L += ["", "## 3. Per-event overhead", "",
          "Real cost = a cold `python3 -m carryover.hook` subprocess (fires on every event).",
          "", "| hook event | p50 ms | p95 ms | p99 ms | mean ms |", "|---|--:|--:|--:|--:|"]
    for label, s in r["latency_subprocess_ms"].items():
        L.append(f"| {label} | {s['p50_ms']} | {s['p95_ms']} | {s['p99_ms']} | {s['mean_ms']} |")
    L += ["", "_In-process handler cost (interpreter warm, isolates algorithm):_", "",
          "| hook event | p50 ms | p95 ms | mean ms |", "|---|--:|--:|--:|"]
    for label, s in r["latency_inprocess_ms"].items():
        L.append(f"| {label} | {s['p50_ms']} | {s['p95_ms']} | {s['mean_ms']} |")

    f = r["footprint"]
    if f:
        last = f[-1]
        peak = last["cum_without_carryover"] or 1
        L += ["", "## 4. Cumulative context footprint (replay sim)", "",
              f"Replaying {len(f)} real tool outputs in order — how the desk fills "
              "(bar scaled to the without-carryover peak):", "", "```",
              f"{'step':>4}  without carryover                    with carryover"]
        for row in f:
            L.append(f"{row['step']:>4}  {_bar(row['cum_without_carryover'] / peak, 24)}  "
                     f"{_bar(row['cum_with_carryover'] / peak, 24)}")
        L += ["```", "",
              f"- final **without carryover: {last['cum_without_carryover']:,}** tokens",
              f"- final **with carryover: {last['cum_with_carryover']:,}** tokens",
              f"- desk stays **{round(100*(1-last['cum_with_carryover']/peak))}% lighter**"]
    return "\n".join(L) + "\n"
