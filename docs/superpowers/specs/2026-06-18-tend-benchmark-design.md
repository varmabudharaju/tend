# tend benchmark — methodology & design

**Date:** 2026-06-18
**Status:** approved (local-only; Phase 1 first, then decide on Phase 2 and shipping)
**Goal:** Measure whether tend makes Claude Code *better or worse* at (a) **context
management** and (b) **performance** — with real, reproducible numbers, run locally.

## Why this is hard (and how we cut it)

tend's value is claimed in two registers:

1. **Mechanical** — what tend *does* to the context window, deterministically: it
   shrinks oversized tool outputs, keeps the per-prompt anchor under a token budget,
   and adds some per-event overhead. This needs **no LLM**, is **free**, **fast**, and
   **reproducible**. It answers: *does tend shrink context, and what does it cost?*

2. **Behavioral** — whether Claude *actually performs better* with tend: stays on
   goal, remembers decisions across compaction, finishes tasks. This needs **live
   Claude Code sessions**, an **API key**, costs **tokens**, and is **noisy** (LLM
   variance). It answers: *is Claude sharper with tend on?*

The two are built as separate phases so mechanical results land immediately and the
expensive behavioral runs are opt-in.

## Phase 1 — Mechanical benchmark (this deliverable)

Pure-Python harness in `bench/`, no network, exercises tend's real code paths. Results
written to `.benchmarks/` (JSON + a markdown summary). Four measurements:

### 1.1 Context savings (offloading)
- **Corpus:** the real recorded tool outputs in `~/.claude/tend/sessions/*/outputs/*.txt`
  (genuine large outputs tend offloaded in production, ~11–94 KB each) **plus** a
  synthetic ladder of sizes (sub-threshold → very large) to map the savings curve and
  confirm threshold behavior.
- **Method:** replay each output through `offload.handle()` with `TEND_HOME` pointed at
  a throwaway dir (so nothing real is touched). Compare in-context footprint:
  - *without tend* = `tokens.estimate(full_output)`
  - *with tend* = `tokens.estimate(excerpt)` if offloaded, else the full size.
- **Report:** per-output and aggregate token reduction %, count offloaded vs left
  alone, banner overhead, and the savings-vs-size curve. Assert the documented
  invariants hold (small outputs untouched; never inflates).

### 1.2 Anchor token budget
- **Method:** construct `STATE.md` files with goal/now text across a range of sizes,
  wire session `ctx.json`/`summary.json`/`flags.json` to trigger every anchor line
  (health, staleness, bloat, stale-state reminder, compaction urge), call
  `anchor.handle()`, measure `tokens.estimate(additionalContext)`.
- **Report:** the actual token distribution vs the ≤400-token claim (`anchor_max_tokens`),
  including the worst case.

### 1.3 Per-event overhead (performance cost)
- **Method:** the honest per-event cost is the `python3 -m tend.hook` **subprocess**
  (cold interpreter start + imports + handler), since that is what fires on every
  Claude Code event. Pipe representative JSON events for each hook type
  (PostToolUse/offload, PreToolUse/guards, UserPromptSubmit/anchor, Stop/boundary,
  SessionStart, PreCompact) to the real entry point over many iterations.
- **Report:** p50/p95/p99 wall-clock latency per hook type, plus the in-process
  `handle()` time (algorithmic cost, isolating interpreter startup).

### 1.4 Cumulative context-footprint simulation (bridge metric)
- **Method:** replay a realistic sequence of tool outputs (the real corpus, in order)
  and accumulate the in-context footprint *with* vs *without* tend, to visualize how
  the desk fills over a session. Deterministic; no LLM. This is a *bridge* to the
  behavioral phase — it shows the mechanism, not model quality.

### CLI
`python3 -m bench mechanical` → runs 1.1–1.4, prints a table, writes
`.benchmarks/mechanical-<date>.json` and `.benchmarks/mechanical-<date>.md`.

## Phase 2 — Behavioral A/B (designed, run later if Phase 1 warrants)

Live, local, uses the user's API key. Not built until Phase 1 is reviewed.

- **Isolation:** each session runs with `TEND_HOME=<throwaway>` and a per-arm
  `claude --settings <file>`: **ON arm** = settings wired with tend's hooks, **OFF arm**
  = bare settings (true control). The live `~/.claude` setup is never modified.
- **Drive:** `claude -p` headless; multi-turn (to force degradation/compaction) via
  `--resume` looping or `--input-format stream-json`; `--output-format json` for
  per-session cost/tokens/turns.
- **Ground truth (arm-agnostic):** the transcript JSONL carries exact per-message
  usage (input + cache_read + cache_creation = context size per turn) → peak context %,
  context-over-time curve, and compaction-event count, identically for both arms.
- **Workload 1 — recall-under-load:** plant facts/decisions/dead-ends early, flood
  context, probe recall at the end; auto-scored by exact match.
- **Workload 2 — e2e sandbox task:** a multi-step task in a throwaway repo, graded by a
  hidden unit-test suite (objective, no grader-LLM cost).
- **Metrics:** peak context %, compaction count, total tokens + USD, duration, success
  score; (ON only) decisions retained in STATE.md.
- **Rigor:** start as a pilot (few repeats) to validate the harness, then scale to the
  statistical target (paired medians, spread, bootstrap CIs, Mann-Whitney/Wilcoxon).

## Explicitly deferred (decide after seeing local results)
- CI integration / push-triggered runs and regression gates.
- A `workflow_dispatch` gated behavioral workflow.
- User-facing packaging ("run this to evaluate tend on your setup").

## Risks / honest caveats
- Token estimate is `len//4`; mechanical numbers are in *estimated* tokens, consistent
  with what tend itself uses to make decisions. Behavioral phase uses exact transcript
  usage.
- The recorded corpus is small (15 outputs) and all above-threshold; the synthetic
  ladder covers the rest of the curve.
- Behavioral results will be noisy; report spread, never single runs.
- Subprocess latency depends on the machine; report the host and Python version.
