# Session state

## Goal
v0.4 feature wave: five parallel branches off benchmarks - fix/u2-cwd-drift
(project-root pinning + ancestor-walk), feat/adaptive-anchors (fingerprint
suppression, anchor_refresh_turns), feat/compaction-insurance (re-anchor
STATE.md on SessionStart source=compact), feat/offload-index (index.jsonl +
tend find), bench/outcome-workload (task-level A/B, no live runs). Each lands
as its own PR (base benchmarks); plain commits, no AI attribution (owner's
explicit preference). Naming: pick a simple ONE-WORD term for the practice
(candidates: gardening / upkeep / grooming; "context gardening" leading).

## Now
v0.4 WAVE MERGED TO MASTER (2026-07-06): PRs #1-#7 all merged, CI green,
262 tests. Merge order was #1 benchmarks, #5 U2 (+ compact-never-overwrites-pin
guard), #3 adaptive anchors, #2 compaction insurance (+ pin-aware reads via
state.resolve in _reanchor and _snapshot), #4 offload index + tend find,
#6 outcome harness, #7 context-gardening rebrand. Rebases resolved by hand in
sessionstart.py (order in handle: pin -> anchor_fp clear -> compact reanchor ->
startup/clear), precompact.py, README habit rows.
NAMING DECIDED: "context gardening" is the category term (README tagline+intro,
pyproject description, repo description + context-gardening topic).
Worktrees removed; merged local branches deleted; REMOTE feature branches NOT
deleted (permission scope) - owner can prune on GitHub.
Open follow-ups: run the outcome benchmark live (python3 -m bench behavioral
--workload outcome --repeats 5 --model ... [--judge ... --seed 0], ~$10-20);
re-measure short-task overhead with adaptive anchors (expect +14% -> ~0);
plugin marketplace submission still awaiting owner login.
PREVIOUSLY - REVIEW IMPROVEMENTS: Tasks 1-5 COMMITTED on benchmarks (3bce794 corpus+CI gate,
7555f9b scoring+discovery, bfec926 retention), 190 tests green. Frozen-corpus
mechanical headline = 86.6% (was 88.8% on private corpus); footprint replay 84%
lighter; new full run recorded (.benchmarks/mechanical-2026-07-01-210532).
Task 6 was: discovery A/B (Haiku x5/arm) running in background; next
Sonnet handoff x3 + recall x2 (claude-sonnet-5). Then Task 7/8: fill measured
numbers into README results table + benchmark-results.md (discovery + Sonnet
sections), refresh screenshots via capture, commit.
Anchor reconciliation VERIFIED from pilot turns_ctx: ON arm carries a standing
~1-2K extra context (restore + accumulated anchors), NOT 1.5-2K/turn; both docs
now say so.
Previously: PLUGIN SHIPPED (0.3.0, merge c5f4b44 on master, CI green): tend is a valid
Claude Code plugin - .claude-plugin/{plugin,marketplace}.json, hooks/hooks.json
(8 events via PYTHONPATH=$CLAUDE_PLUGIN_ROOT), bin/tend, pyyaml dropped,
wrap-statusline CLI. Self-serve install LIVE: /plugin marketplace add
varmabudharaju/tend. AWAITING VARMA: submit at
platform.claude.com/plugins/submit (form needs his login; ~24h to listing).
swarm pluginization parked (needs workflow-bootstrap hook).
VISIBLE HEARTBEAT SHIPPED (0.2.1): statusline suffix "| tend: N filed, Xk
stale" (or "on"; absent when disabled) + SessionStart systemMessage
("restored/seeded STATE.md") - the two user-visible surfaces; everything else
stays invisible by design. 169 tests. Funny hero GIF (7a62f0f) + real demo in
See-it both live. Parked: quirky movie-reference graphic GIF idea.
DEMO GIF SHIPPED (65ea3ef): 5-frame real-output terminal demo in README hero
(status dashboard, live offload via real hook call, handoff, install card);
103KB, built with capture session mode + PIL. Open question from user: add
real-Claude-session frames (statusline visible; anchor is invisible by
design - inject-into-context, no pixels).
ADOPTION POLISH COMPLETE (2026-06-10): name decision = keep "tend"; both repos
have MIT LICENSE, CI green on first run (badges live), v0.2.0 metadata,
GitHub topics, install teasers; planning docs removed from public HEAD.
Previously: model tiering SHIPPED: swarm side (executor effective-model + session cap +
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
- Frozen corpus: dropped real-14 (settings/permissions dump - over-shares
  projects/endpoints even scrubbed) and the smoke-live x-block (synthetic);
  22 organic outputs committed, scrub gate in tests/test_bench_corpus.py.
- Cite 86.6% (frozen, reproducible) everywhere, never the old 88.8%.
- test_home_directory_never_seeded made hermetic (monkeypatch Path.home) -
  it was asserting against the host's real ~/.claude/tend/STATE.md.
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
