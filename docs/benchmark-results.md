# carryover benchmark results

How much does carryover actually help — and what does it cost? This is the honest
writeup of a two-phase benchmark run locally on real data and real Claude Code
sessions. Methodology spec: [`docs/superpowers/specs/2026-06-18-tend-benchmark-design.md`](superpowers/specs/2026-06-18-tend-benchmark-design.md) (written pre-rename).

Reproduce:

```bash
python3 -m bench mechanical                      # Phase 1: deterministic, free (frozen corpus)
python3 -m bench behavioral --repeats 2          # Phase 2: live A/B (needs API key)
python3 -m bench behavioral --workload handoff --repeats 5   # Phase 2b: restore A/B
python3 -m bench behavioral --workload discovery --repeats 5 # fair OFF control
python3 -m bench behavioral --workload outcome --repeats 5 \
    --judge claude-sonnet-5 --seed 0             # Phase 3: task-level outcome A/B
python3 -m bench interactive --setup             # human-in-the-loop /clear test
python3 -m bench interactive --score
```

## TL;DR — is carryover better or worse at context management and performance?

| dimension | verdict | evidence |
|---|---|---|
| **Context (within a session)** | **better** | offloading cuts oversized tool outputs **86.6%** on the frozen public corpus (Phase 1) |
| **Context (across a reset)** | **decisively better** | fresh-session recall **4/4 with carryover vs 0/4 without — 5 repeats/arm** (Phase 2b, maintained STATE.md held fixed) |
| **Outcome (one task, one reset)** | **null — and diagnostic** | task-level A/B (Phase 3): the constraints survived **in the artifact itself**, so both arms recovered them by re-reading the code — median 2 vs 3 of 4, blind judge tied, n=5. Maps the boundary: carryover protects reasoning *not yet* embodied in code |
| **Performance overhead** | **small, real — halved in v0.4** | ~10 ms of carryover work per event; a standing anchor cost that netted +14% (Haiku, n=2) / +1–31% (Sonnet, n=2) when there was little to offload — v0.4 **adaptive anchors** cut the Haiku figure to **+6% cost / +1% peak context** (n=3 rerun below); the Sonnet run where offloading fired flipped it to a context *saving* (Phase 2) |
| **When it's redundant** | honest limit | short tasks where the code + CLAUDE.md already hold everything |

carryover's value is conditional: it shines on long, multi-session, decision-heavy
work and is near-neutral on short tasks. The numbers below show exactly where the
line is.

---

## Phase 1 — Mechanical (deterministic, no LLM, free)

Runs carryover's real code paths over 22 **real** tool outputs it offloaded in past
sessions (11–94 KB) plus a synthetic size ladder. The real outputs are the
**frozen, scrubbed corpus committed at [`bench/corpus/`](../bench/corpus/)**
(provenance in its README), so this phase reproduces bit-for-bit for anyone;
`--live-corpus` benchmarks your own history instead.

| metric | result |
|---|---|
| Context reduction (29 outputs) | **86.6%** — 268,716 → 35,939 tok |
| Per real output | 54–95%, scaling with size (a 23K-tok output → fixed ~1,257-tok excerpt) |
| Threshold behavior | 500- and 1,500-tok outputs correctly **left untouched** |
| Anchor token budget | max **263 / 400** tok, even fed a 40,000-char STATE.md |
| Per-event overhead | **~29 ms** (p50); ~18 ms is unavoidable Python startup, **~10 ms is carryover**; the handler algorithm itself is **<0.3 ms** |
| Correctness invariants | **6/6** held (offloads the right things; never inflates) — enforced in CI on every push |
| Footprint replay (22 real outputs, in order) | 174,216 → 27,654 tok — desk stays **84% lighter** |

The overhead is dominated by process startup, not carryover's logic, and is negligible
against LLM turn latency (seconds). A heavy 2,000-tool-call session adds ~54 s of
wall-clock total.

![carryover mechanical benchmark](screenshots/01-bench-mechanical.png)

**Caveat:** token counts are carryover's own `len//4` estimate (the same one it uses to
make decisions). Good for relative comparison; not exact API token counts. (An
earlier private-corpus run measured 88.8%; the committed corpus gives 86.6% —
we cite the reproducible number.)

---

## Phase 2 — Behavioral A/B, headless (live `claude -p`, carryover ON vs OFF)

Identical scripted session in both arms (plant 4 facts → flood context with large
Bash outputs → probe recall). Isolation: per-arm `CARRYOVER_HOME`; the OFF arm drops a
`disabled` kill-switch file so carryover's hooks no-op (true control). Model: Haiku 4.5,
2 repeats/arm.

| metric (medians) | carryover ON | carryover OFF | delta |
|---|--:|--:|--:|
| recall (/4) | 4.0 | 4.0 | tie |
| peak context tokens | 34,054 | 32,588 | **+4% (worse)** |
| cost / session | $0.121 | $0.106 | **+14% (worse)** |
| outputs offloaded | 1 | 0 | control held ✓ |

**carryover looked slightly worse here — and that result is informative, not a failure.**
Diagnosis from the raw token accounting:

1. **Offloading barely fired** (1 of 3 flood turns). Haiku was *too clever* — it ran
   `grep | sort | uniq` instead of dumping files, so large outputs rarely entered
   context. carryover had almost nothing to offload.
2. **carryover's overhead showed up naked.** ON was already +1,137 tok at the
   *plant* turn, before any flood — that's the SessionStart restore. Each anchor is
   small (≤400 tok; measured max 263), but anchors persist in the transcript, so the
   ON arm carries a **standing ~1–2K of extra context** (restore + every anchor so
   far) that the model re-reads on every turn — the gap grew from ~1.1K to ~2.2K
   across the five turns of run 1. With no offload savings to offset it, that
   standing overhead is the entire cost gap (amplified by a cheap model where it's
   a big fraction of a short turn).

So this measured **carryover's cost without its benefit**. It does not contradict Phase 1
— it just failed to reproduce the large-output condition where offloading pays off.

### Rerun with adaptive anchors (v0.4)

v0.4 made anchors **adaptive**: an unchanged anchor is not re-injected (fingerprint
suppression; full refresh every `anchor_refresh_turns` prompts). Rerunning the exact
workload above (Haiku, now 3 repeats/arm):

| metric (medians) | carryover ON | carryover OFF | delta | was (v0.3) |
|---|--:|--:|--:|--:|
| recall (/4) | 4 | 4 | tie | tie |
| peak context tokens | 32,122 | 31,785 | **+1%** | +4% |
| cost / session | $0.1108 | $0.1044 | **+6%** | +14% |

The standing anchor cost roughly halved, and peak context is now essentially neutral.
Per-run costs overlap between arms (ON $0.101–0.112 vs OFF $0.101–0.107 — small-n
ranges, not points), the control held (1 offload ON, 0 OFF), and recall stayed a
4/4 tie. The remaining +6% is dominated by the SessionStart restore injection plus
the first full anchor — the recurring per-prompt cost is what adaptivity removed.

---

## Why the "drive to real compaction" test is infeasible headless

We tried to push the OFF arm to the ~200K context-window limit so it would compact
and lose the early facts (carryover's recall claim). Two empirical findings stopped this:

- **Tool-output flooding can't grow context.** Three 10K-token `cat`s moved the
  effective context only ~23K → 31K — **Claude Code manages large tool outputs
  itself**. You can't balloon OFF to compaction this way at any sane number of turns.
- **User-prompt flooding *does* accumulate** (~+23K/turn, linear) and would reach
  compaction — but it bypasses carryover's offloading entirely, and carryover can only *block*
  a headless **auto-compaction**, not customize its summary. Customizing a mid-session
  compaction is a genuinely **interactive-only** behavior.

Conclusion: the *mid-session compaction* customization is interactive-only. But carryover's
broader recall claim — restoring STATE.md into a **fresh context** — is testable
headless, because a brand-new session fires `SessionStart` (source `startup`), the same
hook `/clear` uses. That is exactly what Phase 2b measures, automated and repeated ↓.

---

## Phase 2b — Lossless handoff (STATE restore on a fresh context)

carryover's marquee feature: when a context resets (`/clear`, a new session next morning,
a crash), its `SessionStart` hook restores STATE.md into the fresh context. We measured
this two ways — an automated tally and a hands-on interactive run — and they agree.

Two preconditions to read these numbers honestly: **(1)** STATE.md is held fixed on
disk — this isolates the *restore* leg; whether the model *maintains* the file as it
works is a separate, model-dependent step that carryover nudges but this test assumes.
**(2)** The tools-blocked OFF arm is a floor: it *cannot* score by construction. The
fairer control — tools allowed, file unnamed — is the discovery run below.

### Automated A/B (5 repeats/arm, Haiku)

A known-good STATE.md is held fixed on disk in **both** arms (the maintained-notebook
precondition). A **fresh** session then probes with tools blocked, so only carryover's
auto-injection can supply the facts. Only variable: carryover on/off.

| arm | recall (every run) | what the model said |
|---|--:|---|
| **carryover ON** | **4/4 — all 5 runs (20/20 facts)** | *"From the restored session state: (a) Saffron-Quill (b) pgx-v5.2 (c) 137 (d) turbo-merge…"* |
| **carryover OFF** | **0/4 — all 5 runs (0/20 facts)** | *"This appears to be the start of a new session… I don't have this information."* |

Zero variance: with carryover, a fresh context recovers **100%** of the decisions; without
carryover, **0%** — and the model doesn't even know anything was lost. Context and cost were
identical between arms (~20.5K tok, ~$0.021/session); the restore injection is ~free.

This isolates the *restore* mechanism by holding STATE.md fixed. Whether the model
*populates* STATE.md as it works is a separate, model-dependent step — carryover nudges for
it, but in a one-shot headless plant the model often just acknowledges without writing
the file (which is why an end-to-end plant→reset→probe run is noisier than this).

### The fair control — tools allowed, file unnamed (discovery)

The tools-blocked OFF arm above is a floor: it *cannot* score by construction. So
we also ran the fairer control — STATE.md on disk in both arms, tools **allowed**,
and a probe that names no file, just "you're picking this project back up after a
break." 5 repeats/arm, Haiku:

| arm | recall | median cost / probe | median peak ctx |
|---|--:|--:|--:|
| **carryover ON** (auto-inject) | **4/4 — all 5 runs** | $0.022 | 27,471 tok |
| **carryover OFF** (must go look) | **4/4 — all 5 runs** | $0.045 (**2.1×**) | 29,704 tok (+2.2K) |

An honest surprise: vanilla Claude **found STATE.md every time** — it searched the
project, read the file, and answered. So in this setup the restore is not the only
path to the facts. Three caveats keep it from generalizing: the sandbox is minimal
(one log file — STATE.md is nearly the only thing *to* find), the probe hints a
resumption, and discovery took tool-call turns that doubled the probe's cost and
added ~2K of context. What carryover actually buys here is **determinism and economy** —
the facts arrive in the first token of context, every time, with zero tool calls —
plus coverage of the resets where no hint tells the model to go digging (a crash
mid-task, a silent auto-compaction). The claim this run supports is *reliability +
tokens*, not *sole access* — and we've updated the README language to match.

### Sonnet check — does any of this depend on the model?

Everything above ran on Haiku. Rerunning the key claims on **Sonnet 5**:

- **Handoff (3 repeats/arm):** identical — **4/4 with carryover, 0/4 without, every
  run** (*"I don't have any actual memory of this project"*). Peak context was
  near-identical between arms (+175 tok median): the restore injection is ~free
  on Sonnet too. The restore claim is model-independent.
- **Recall/overhead stress test (2 repeats/arm — ranges, not points):** recall
  tied 4/4 both arms. Cost: carryover ON ran **+1% to +31%** (median +15%) — so the
  overhead is *not* just a cheap-model artifact; it's real whenever the workload
  gives carryover little to offload. But unlike Haiku, Sonnet actually dumped the logs
  it was asked to dump, offloading fired (1–3 files/session), and in the run
  where it fired repeatedly carryover's peak context finished **below** the OFF arm
  (−3.5%) — the per-turn gap flipped from +1.7K at the first turn to −1.6K by the
  last. That's the mechanism visible in a single session: anchors cost a standing
  1–2K; each offload claws back more than that. (These Sonnet numbers predate the
  v0.4 adaptive anchors that halved the Haiku overhead — the Sonnet arm has not
  been rerun since.)

### Interactive `/clear` run (N=1/arm, corroboration)

Run by hand in two sandboxes, each ending in a real `/clear` then a memory-only probe:
carryover ON restored STATE and recited the facts (all four restored; it enumerated 3 of 4
in its reply — a completeness quirk, not a miss); carryover OFF said *"I was just `/clear`ed,
so I have no prior conversation to recall… I won't fabricate values."* — 0/4. Same
result as the automated tally, via the real `/clear` path.

---

## What carryover actually adds (and where it's redundant)

A frequent and fair question: *doesn't Claude already load context automatically, and
isn't CLAUDE.md enough?* The boundary:

| | CLAUDE.md | STATE.md (carryover) |
|---|---|---|
| holds | standing project rules (build, style, architecture) | this task's live goal / decisions / dead-ends |
| timescale | **static** — changes rarely | **dynamic** — changes every few turns |
| maintained by | you, by hand | carryover nudges the model to update it as it works |
| auto-loaded fresh session | yes (built-in) | yes (carryover injects on `/clear`/new session) |

- Claude **does** auto-load CLAUDE.md, and the **code on disk** survives a reset — so
  for durable facts and code, carryover adds nothing.
- Claude does **not** keep a running log of *why* (decisions, rejected dead-ends) as
  it works, and that reasoning lives only in the conversation — which `/clear` and
  compaction delete. There is **no automatic home** for transient task reasoning;
  CLAUDE.md is the wrong place (it would bloat and go stale).
- **That gap is the only thing carryover fills**, automatically: maintain the running
  decision log while the reasoning is fresh, and restore it on every reset.

You could do this by hand with your own notes file and discipline; carryover is the
automation of that discipline, plus it catches resets you can't manually recover
from (a crash, or a silent auto-compaction mid-task).

**Bottom line:** earns its keep on long, multi-session, decision-heavy work; roughly
neutral (small overhead) on short tasks the code + CLAUDE.md already cover.

---

## Phase 3 — Outcome (task-level A/B): a null result, and what it maps

The pitch is "stays smart ten hours in" — an *outcome* claim. Phases 1–2 prove
mechanisms; this phase tried to measure the outcome directly: a multi-step coding
task (build `configlint.py`) with 4 planted constraints (a config key name, an
error prefix, an exit code, a function signature), a **forced mid-task reset**,
then "finish the task" with the constraints deliberately not restated. Scored
mechanically per constraint plus a blind judge (Sonnet 5, shuffled labels).
5 repeats/arm, Haiku:

| metric (medians) | carryover ON | carryover OFF |
|---|--:|--:|
| constraints kept (/4) | 2 | 3 |
| blind judge quality (1–5) | 2 | 2 |
| cost / arm | $0.145 (+7%) | $0.135 |

**No measured advantage — and the reason is the finding.** Both arms swing
together (1/4 on runs 1–2, 4/4 on runs 3 and 5): by the reset, phase A had
already written the constraints **into the artifact on disk**, and the artifact
survives the reset in both arms. The OFF model recovers the constraints the same
way the ON model does — by re-reading its own code. That is exactly the boundary
the "[What carryover actually adds](#what-carryover-actually-adds-and-where-its-redundant)"
section predicts: *code on disk survives a reset; carryover adds nothing for facts
already embodied in code.* What carryover protects is the reasoning **not yet** in
code — decisions pending application, rejected dead-ends, the why — which this
task shape doesn't isolate, because its constraints become code almost
immediately.

We report this null result as-is. A follow-up design that would isolate memory:
constraints that must stay *out* of the artifact until the end (e.g. "apply
decision X only in the final step"), or deleting the work-in-progress at reset.
(A first attempt at this run was discarded: a usage-limit window silently killed
sessions mid-run at $0 — artifact `behavioral-2026-07-06-113517` is excluded and
should not be cited.)

---

## What we still have NOT measured

The long-horizon outcome claim itself. Phase 3 covers *one* task with *one*
reset on a cheap model, and its constraints leaked into the artifact; a credible
"ten hours in" test needs decision-heavy work where the reasoning stays outside
the code for long stretches, plus many repeats. Until that exists, "stays smart
ten hours in" remains an argument from mechanism (86.6% offload + 4/4 restore +
now-near-zero anchor overhead), and you should read it that way.

---

## Artifacts & cost

- `bench/{mechanical,behavioral,interactive}.py` — the harnesses (reusable).
- `bench/corpus/` — the frozen, scrubbed real-output corpus Phase 1 runs on.
- `.benchmarks/mechanical-*.{json,md}` — Phase 1 results.
- `.benchmarks/behavioral-*.{json,md}` — Phase 2 (recall pilot + Sonnet rerun +
  the v0.4 adaptive-anchor rerun `2026-07-06-113304`), Phase 2b (handoff tallies,
  Haiku + Sonnet), the discovery control, and Phase 3 outcome (smoke
  `2026-07-06-113231`, full run `2026-07-06-160640`; `2026-07-06-113517` is the
  excluded usage-limit-poisoned run); the `kind`, `workload`, and `model` fields
  in each JSON say which.
- `docs/screenshots/01-bench-mechanical.png` — captured run.
- Live-session API spend ≈ **$7.3** total: ≈$1.8 for the original Haiku pilot,
  handoff tally, and feasibility diagnostics; ≈$2.6 for the discovery control
  ($0.34), Sonnet handoff ($0.43), and Sonnet recall ($1.85); ≈$2.9 for the v0.4
  wave — adaptive-anchor rerun ($0.64), outcome smoke ($0.26), full outcome A/B
  ($1.46 + judge), and ~$0.5 lost to the poisoned run. The interactive
  `/clear` run was by hand.
- Host: Darwin arm64 (M-series MacBook Air), Python 3.11. Latency numbers are
  machine-dependent.
