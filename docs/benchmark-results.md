# tend benchmark results

How much does tend actually help — and what does it cost? This is the honest
writeup of a two-phase benchmark run locally on real data and real Claude Code
sessions. Methodology spec: [`docs/superpowers/specs/2026-06-18-tend-benchmark-design.md`](superpowers/specs/2026-06-18-tend-benchmark-design.md).

Reproduce:

```bash
python3 -m bench mechanical                      # Phase 1: deterministic, free
python3 -m bench behavioral --repeats 2          # Phase 2: live A/B (needs API key)
python3 -m bench interactive --setup             # Phase 2b: human-in-the-loop /clear test
python3 -m bench interactive --score
```

## TL;DR — is tend better or worse at context management and performance?

| dimension | verdict | evidence |
|---|---|---|
| **Context (within a session)** | **better** | offloading cuts oversized tool outputs **88.8%** (Phase 1) |
| **Context (across a reset)** | **decisively better** | fresh-session recall **4/4 with tend vs 0/4 without — 5/5 runs each** (Phase 2b) |
| **Performance overhead** | **small, real** | ~9 ms of tend work per event; a per-turn anchor cost that nets +14% only when there's nothing to offload (Phase 2) |
| **When it's redundant** | honest limit | short tasks where the code + CLAUDE.md already hold everything |

tend's value is conditional: it shines on long, multi-session, decision-heavy
work and is near-neutral on short tasks. The numbers below show exactly where the
line is.

---

## Phase 1 — Mechanical (deterministic, no LLM, free)

Runs tend's real code paths over 15 **real** tool outputs it offloaded in past
sessions (11–94 KB) plus a synthetic size ladder. Fully reproducible.

| metric | result |
|---|---|
| Context reduction (22 outputs) | **88.8%** — 242,757 → 27,140 tok |
| Per real output | 55–95%, scaling with size (a 23K-tok output → fixed ~1,257-tok excerpt) |
| Threshold behavior | 500- and 1,500-tok outputs correctly **left untouched** |
| Anchor token budget | max **263 / 400** tok, even fed a 40,000-char STATE.md |
| Per-event overhead | **~27 ms** (p50); ~18 ms is unavoidable Python startup, **~9 ms is tend**; the handler algorithm itself is **<0.3 ms** |
| Correctness invariants | **6/6** held (offloads the right things; never inflates) |
| Footprint replay (15 real outputs, in order) | 148,257 → 18,855 tok — desk stays **87% lighter** |

The overhead is dominated by process startup, not tend's logic, and is negligible
against LLM turn latency (seconds). A heavy 2,000-tool-call session adds ~54 s of
wall-clock total.

![tend mechanical benchmark](screenshots/01-bench-mechanical.png)

**Caveat:** token counts are tend's own `len//4` estimate (the same one it uses to
make decisions). Good for relative comparison; not exact API token counts.

---

## Phase 2 — Behavioral A/B, headless (live `claude -p`, tend ON vs OFF)

Identical scripted session in both arms (plant 4 facts → flood context with large
Bash outputs → probe recall). Isolation: per-arm `TEND_HOME`; the OFF arm drops a
`disabled` kill-switch file so tend's hooks no-op (true control). Model: Haiku 4.5,
2 repeats/arm.

| metric (medians) | tend ON | tend OFF | delta |
|---|--:|--:|--:|
| recall (/4) | 4.0 | 4.0 | tie |
| peak context tokens | 34,054 | 32,588 | **+4% (worse)** |
| cost / session | $0.121 | $0.106 | **+14% (worse)** |
| outputs offloaded | 1 | 0 | control held ✓ |

**tend looked slightly worse here — and that result is informative, not a failure.**
Diagnosis from the raw token accounting:

1. **Offloading barely fired** (1 of 3 flood turns). Haiku was *too clever* — it ran
   `grep | sort | uniq` instead of dumping files, so large outputs rarely entered
   context. tend had almost nothing to offload.
2. **tend's per-turn overhead showed up naked.** ON was already +1,137 tok at the
   *plant* turn, before any flood — that's the SessionStart restore + the anchor tend
   injects every prompt. With no offload savings to offset it, that ~1.5–2K/turn
   anchor cost is the entire gap (amplified by a cheap model where ~250 anchor tokens
   are a big fraction of a short turn).

So this measured **tend's cost without its benefit**. It does not contradict Phase 1
— it just failed to reproduce the large-output condition where offloading pays off.

---

## Why the "drive to real compaction" test is infeasible headless

We tried to push the OFF arm to the ~200K context-window limit so it would compact
and lose the early facts (tend's recall claim). Two empirical findings stopped this:

- **Tool-output flooding can't grow context.** Three 10K-token `cat`s moved the
  effective context only ~23K → 31K — **Claude Code manages large tool outputs
  itself**. You can't balloon OFF to compaction this way at any sane number of turns.
- **User-prompt flooding *does* accumulate** (~+23K/turn, linear) and would reach
  compaction — but it bypasses tend's offloading entirely, and tend can only *block*
  a headless **auto-compaction**, not customize its summary. Customizing a mid-session
  compaction is a genuinely **interactive-only** behavior.

Conclusion: the *mid-session compaction* customization is interactive-only. But tend's
broader recall claim — restoring STATE.md into a **fresh context** — is testable
headless, because a brand-new session fires `SessionStart` (source `startup`), the same
hook `/clear` uses. That is exactly what Phase 2b measures, automated and repeated ↓.

---

## Phase 2b — Lossless handoff (STATE restore on a fresh context)

tend's marquee feature: when a context resets (`/clear`, a new session next morning,
a crash), its `SessionStart` hook restores STATE.md into the fresh context. We measured
this two ways — an automated tally and a hands-on interactive run — and they agree.

### Automated A/B (5 repeats/arm, Haiku)

A known-good STATE.md is held fixed on disk in **both** arms (the maintained-notebook
precondition). A **fresh** session then probes with tools blocked, so only tend's
auto-injection can supply the facts. Only variable: tend on/off.

| arm | recall (every run) | what the model said |
|---|--:|---|
| **tend ON** | **4/4 — all 5 runs (20/20 facts)** | *"From the restored session state: (a) Saffron-Quill (b) pgx-v5.2 (c) 137 (d) turbo-merge…"* |
| **tend OFF** | **0/4 — all 5 runs (0/20 facts)** | *"This appears to be the start of a new session… I don't have this information."* |

Zero variance: with tend, a fresh context recovers **100%** of the decisions; without
tend, **0%** — and the model doesn't even know anything was lost. Context and cost were
identical between arms (~20.5K tok, ~$0.021/session); the restore injection is ~free.

This isolates the *restore* mechanism by holding STATE.md fixed. Whether the model
*populates* STATE.md as it works is a separate, model-dependent step — tend nudges for
it, but in a one-shot headless plant the model often just acknowledges without writing
the file (which is why an end-to-end plant→reset→probe run is noisier than this).

### Interactive `/clear` run (N=1/arm, corroboration)

Run by hand in two sandboxes, each ending in a real `/clear` then a memory-only probe:
tend ON restored STATE and recited the facts (all four restored; it enumerated 3 of 4
in its reply — a completeness quirk, not a miss); tend OFF said *"I was just `/clear`ed,
so I have no prior conversation to recall… I won't fabricate values."* — 0/4. Same
result as the automated tally, via the real `/clear` path.

---

## What tend actually adds (and where it's redundant)

A frequent and fair question: *doesn't Claude already load context automatically, and
isn't CLAUDE.md enough?* The boundary:

| | CLAUDE.md | STATE.md (tend) |
|---|---|---|
| holds | standing project rules (build, style, architecture) | this task's live goal / decisions / dead-ends |
| timescale | **static** — changes rarely | **dynamic** — changes every few turns |
| maintained by | you, by hand | tend nudges the model to update it as it works |
| auto-loaded fresh session | yes (built-in) | yes (tend injects on `/clear`/new session) |

- Claude **does** auto-load CLAUDE.md, and the **code on disk** survives a reset — so
  for durable facts and code, tend adds nothing.
- Claude does **not** keep a running log of *why* (decisions, rejected dead-ends) as
  it works, and that reasoning lives only in the conversation — which `/clear` and
  compaction delete. There is **no automatic home** for transient task reasoning;
  CLAUDE.md is the wrong place (it would bloat and go stale).
- **That gap is the only thing tend fills**, automatically: maintain the running
  decision log while the reasoning is fresh, and restore it on every reset.

You could do this by hand with your own notes file and discipline; tend is the
automation of that discipline, plus it catches resets you can't manually recover
from (a crash, or a silent auto-compaction mid-task).

**Bottom line:** earns its keep on long, multi-session, decision-heavy work; roughly
neutral (small overhead) on short tasks the code + CLAUDE.md already cover.

---

## Artifacts & cost

- `bench/{mechanical,behavioral,interactive}.py` — the harnesses (reusable).
- `.benchmarks/mechanical-*.{json,md}` — Phase 1 results.
- `.benchmarks/behavioral-*.{json,md}` — Phase 2 (recall pilot) and Phase 2b (handoff
  tally) results; the `kind` field in each JSON says which.
- `docs/screenshots/01-bench-mechanical.png` — captured run.
- Live-session API spend ≈ **$1.8** total (Haiku), across the pilot, the handoff tally,
  and the feasibility diagnostics; the interactive `/clear` run was by hand.
- Host: Darwin arm64 (M-series MacBook Air), Python 3.11. Latency numbers are
  machine-dependent.
