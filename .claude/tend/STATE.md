# Session state

## Goal
tend v0.2: fix the 31 confirmed findings from the swarm review
(docs/swarm-review-2026-06-10.md), then professional README + push to GitHub
(varmabudharaju/tend, public — match agent-pd/capture repo style).

## Now
Bug-fix round NOT started (a fixer agent was stopped before editing; master is
green at 110 tests). Next: fix all confirmed HIGH+MEDIUM findings, TDD with
regression tests from each finding's repro.

## Decisions
- Staleness metric fix: switch state_mark to monotonic output_total (not
  context_total) — kills the negative-since bug cluster (2 HIGH-adjacent).
- Ledger partial-line fix: only advance cursor past data ending in \n.
- to_text for Bash dicts: render stdout + "--- stderr ---" sections; other
  dicts json.dumps(indent=2) so offloaded files are line-addressable.
- uninstall must prune inner hook commands, not whole entries (swarm repo
  already fixed this pattern: swarm commit a51df19 — mirror it).
- precompact: never block auto-compact when cwd == $HOME.

## Dead-ends
- max(0, since) does NOT fix the negative-since bug — it disables staleness the
  same way. The metric itself must be monotonic (output_total).

## Files touched
- docs/swarm-review-2026-06-10.md — committed; the authoritative bug list.
