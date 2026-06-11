# Session state

## Goal
tend v0.2: fix the 31 confirmed findings from the swarm review
(docs/swarm-review-2026-06-10.md), then professional README + push to GitHub
(varmabudharaju/tend, public — match agent-pd/capture repo style).

## Now
Model tiering SHIPPED: swarm side (executor effective-model + session cap +
final-retry fallback, validator allow-list, --session-model, skill/docs
guidance, agent frontmatter tiers) merged to swarm master + installed; tend
side (agentguard delegation nudge, session_model_tier, delegation_guard
config, PreToolUse routing) merged to tend master, 164 tests green. Spec:
(spec now only in git history — planning docs removed from public HEAD).
PUBLISHED 2026-06-10: github.com/varmabudharaju/{tend,swarm} (public, full
per-feature history). READMEs now have THREE diagram layers, all mermaid,
render-verified via capture: concept (analogies), engineering (system design,
component layers, advisor/block flowcharts, scheduler loop, run state
machine). v0.2 goal COMPLETE.

## Decisions
- state_stale_tokens now counts OUTPUT tokens (monotonic metric); default
  lowered 25000 -> 3000 to match the ~10x slower growth.
- M8 fix = skip offload for mcp__* tools with non-string responses + README
  Limitations note (hooks can't see outputSchema, so don't pretend).
- Ledger cursor now lives INSIDE summary.json (one atomic write kills the
  L3 torn-write window); legacy cursor.json migrated once then unlinked.
- Truncation reset drops state_mark (re-baselined next Stop) — preserving it
  with rebuilt counters recreates the negative-since bug.
- advisor.clip(goal) at 200 chars: the /compact instruction line was smuggling
  the full Goal past the anchor budget (found while fixing M9).
- Staleness metric fix: switch state_mark to monotonic output_total (not
  context_total) — kills the negative-since bug cluster (2 HIGH-adjacent).
- Ledger partial-line fix: only advance cursor past data ending in \n.
- to_text for Bash dicts: render stdout + "--- stderr ---" sections; other
  dicts json.dumps(indent=2) so offloaded files are line-addressable.
- uninstall must prune inner hook commands, not whole entries (swarm repo
  already fixed this pattern: swarm commit a51df19 — mirror it).
- precompact: never block auto-compact when cwd == $HOME.

## Confirmed in the wild
- U2 (cwd drift) CONFIRMED live 2026-06-10 on CC 2.1.x: a persistent `cd` in
  the session's shell changes hook-event cwd; anchor lost Goal/Now and fired a
  false missing-STATE nag while working from another repo. v0.3 candidate:
  ancestor-walk + project-root pinning for STATE.md resolution.

## Dead-ends
- max(0, since) does NOT fix the negative-since bug — it disables staleness the
  same way. The metric itself must be monotonic (output_total).

## Files touched
- docs/swarm-review-2026-06-10.md — committed; the authoritative bug list.
- tend/{ledger,boundary,config,hook,tokens,offload,anchor,advisor,precompact,
  install,paths,hookio,statusline,state,sessionstart,readguard,cli}.py — all
  31 fixes, one commit per plan task (12 commits on fix/v0.2-swarm-findings).
- tests/* — 43 new regression tests, one per finding repro (plus updates to
  v0.1 tests that encoded overturned behavior).
- README.md — Limitations section (M8, staleness semantics).
- v0.2 plan executed then removed from HEAD with the other planning docs
  (recoverable via git history).
- tend/agentguard.py (new), ctxmetrics.py, config.py, hook.py — delegation guard.
