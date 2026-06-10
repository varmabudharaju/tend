# tend — Context-Hygiene Harness for Claude Code

**Date:** 2026-06-09
**Status:** Approved design (user-approved in brainstorming session)
**Repo:** `/Users/varma/tend` · Package `tend` · CLI `tend` (PyPI fallback name: `ctx-tend`)
**Language:** Python 3.11 (`python3`), same toolchain conventions as agent-pd

## Problem

Long Claude Code sessions degrade well before the context window is full. In
practice the user abandons sessions at ~40% usage and does a manual handoff,
because past that point the model starts retrieving from stale parts of context
(old file contents, superseded assumptions, failed attempts) and goes down
"weird paths." Auto-compaction does not help: it fires reactively near the
limit with a generic summary, losing detail at the worst possible moment.

The goal is NOT to automate early bail-out. It is to make deep context usable
in the same session: prevent rot, keep the model anchored to current state, and
make compaction/continuation lossless when they do happen.

## Research basis (what causes the 40% cliff)

- **Context rot is content-driven, not percentage-driven.** Stale tool dumps
  and superseded assumptions are competing memories; the model confabulates by
  retrieving outdated context. (Chroma "Context Rot" 2025; Anthropic context-
  engineering guidance.)
- **Attention is U-shaped** — strong at the start and end of context, weak in
  the middle ("lost in the middle", Liu et al.). Late-context injection is the
  most reliable place to keep current state.
- **Consensus mitigations** (Anthropic, MemGPT/Letta, Manus, Cognition):
  minimize the in-context working set; externalize state to files
  continuously; re-anchor the current goal near the end of context; compact
  proactively at semantic boundaries with explicit instructions.

## Verified platform capabilities (ground-truthed 2026-06-09)

These facts were verified against official docs and this machine; the design
depends on them.

| Capability | Status |
|---|---|
| Transcript JSONL carries exact per-message usage (`input_tokens` + `cache_read_input_tokens` + `cache_creation_input_tokens`) | Verified on disk |
| Statusline stdin JSON carries `context_window.used_percentage`, `remaining_percentage`, `context_window_size`, exact token counts | Verified in `~/.claude/statusline.sh` |
| `PostToolUse` hook can replace a tool result (`updatedToolOutput`) and inject `additionalContext` | Documented |
| `UserPromptSubmit` hook can inject `additionalContext` | Documented |
| `SessionStart` hook can inject `additionalContext` | Documented (implementation will re-verify in CLI settings.json context) |
| `PreToolUse` hook can deny/ask/allow and inject `additionalContext` | Documented |
| `PreCompact` hook can block compaction (`decision: "block"`); cannot customize the compaction prompt | Documented |
| `/compact [instructions]` accepts custom focus instructions | Documented |
| Auto-compaction clears older tool outputs first, then summarizes; threshold not configurable | Documented |
| No built-in `/handoff`; no context metrics in hook payloads; hooks cannot retroactively edit context | Verified absent |
| Hook events used: PostToolUse, PreToolUse, UserPromptSubmit, Stop, SessionStart, PreCompact (+ SubagentStart/Stop for the ledger) | Documented |

## Architecture

Daemon-less, same shape as agent-pd: a single fast hook entry point plus a CLI.

```
claude session
  │  hook events (stdin JSON)
  ▼
python3 -m tend.hook          ← registered in ~/.claude/settings.json
  │  dispatch on hook_event_name; fail-open (always exit 0 on error)
  ├─ ledger update            ← incremental transcript parse, per-result sizes
  ├─ pillar logic             ← offload / guard / anchor / advise / snapshot
  └─ JSON output on stdout    ← updatedToolOutput / additionalContext / decision

tend CLI: report · status · handoff · install-hook · uninstall-hook · on/off

state:
  ~/.claude/tend/config.yaml                  global config
  ~/.claude/tend/sessions/<sid>/ctx.json      statusline tee (exact metrics)
  ~/.claude/tend/sessions/<sid>/ledger.jsonl  per-message/per-result accounting
  ~/.claude/tend/sessions/<sid>/outputs/N.txt offloaded tool outputs
  <project>/.claude/tend/STATE.md             externalized session state
```

**Measurement channels (both exact, no estimation):**
1. *Statusline tee:* `tend statusline-wrap` is installed as the statusLine
   command; it tees stdin JSON to `sessions/<sid>/ctx.json` and execs the
   user's original `statusline.sh` unchanged.
2. *Transcript ledger:* hooks incrementally parse `transcript_path` (offset
   cursor stored per session), recording per-message usage and per-tool-result
   token sizes, with staleness marks (e.g. a `Read` result for a file that a
   later `Edit`/`Write` touched is stale).

**Coexistence:** agent-pd already registers PostToolUse/SubagentStart/Stop
hooks. Multiple hooks per event are supported; agent-pd emits no JSON output,
so there is no output-merge conflict. `tend install-hook` merges
non-destructively and never touches other entries.

## Pillar 1 — Bloat prevention

**PostToolUse offloading.** When a tool result exceeds `offload_threshold`
(default 2,500 tokens, est. chars/4) for tools in `offload_tools` (default:
Bash, Grep, Glob, WebFetch):

1. Save full output to `~/.claude/tend/sessions/<sid>/outputs/<n>.txt`.
2. Emit `updatedToolOutput` = head (default 600 tokens) + `…[tend: N tokens
   offloaded]…` + tail (default 600 tokens) + footer: `Full output:
   <path> (Read with offset/limit if needed).`

Head+tail because build/test failures concentrate at the tail while command
echo/config is at the head. Error results follow the same head+tail rule (the
error text survives in the tail). Never offload: `Read` results (the model
asked for that content *now*) and `Edit`/`Write` confirmations (tiny).

**PreToolUse read guard.** A `Read` with no `limit` on a file larger than
`read_guard_bytes` (default 64 KB) gets `additionalContext` guidance (never a
deny): file size, advice to read a range, or to delegate scanning to an
Explore agent. Nudges, not walls.

## Pillar 2 — State externalization (STATE.md)

`<project>/.claude/tend/STATE.md`, maintained by Claude (not the harness),
fixed sections:

```markdown
# Session state
## Goal          — one paragraph, stable
## Now           — current step, updated often
## Decisions     — settled choices, append-only
## Dead-ends     — approaches tried and abandoned, with why (do not retry)
## Files touched — paths + one-line what/why
```

Enforcement is freshness-based: the Stop hook compares STATE.md mtime against
ledger activity; if more than `state_stale_tokens` (default 25k) of new
session tokens accumulated since the last update, the next anchor injection
(Pillar 3) includes a one-line reminder to update STATE.md. SessionStart in a
project without STATE.md seeds the template and tells Claude the convention.

The **Dead-ends** section is the anti-hallucination workhorse: failed paths
are recorded outside context so they survive compaction and handoffs and do
not get retried.

## Pillar 3 — Late anchoring

On every UserPromptSubmit, inject `additionalContext` ≤ `anchor_max_tokens`
(default 400):

- `Goal` and `Now` lines from STATE.md (verbatim, truncated).
- One context-health line from the latest metrics: used %, offloadable bloat
  total, stale-result total.
- When applicable, one escalation line (Pillar 4 advice or STATE.md staleness
  reminder).

Rationale: end-of-context is the strongest attention region; a small anchor
there keeps the model on the current path deep into the session. The anchor is
plain text prefixed `[tend]` so it is auditable in the transcript.

## Pillar 4 — Curated compaction + lossless continuation

**Advisor.** At `advise_pct` (default 55%) and `urge_pct` (default 70%) — or
earlier when a task boundary is detected (Stop event with fresh STATE.md) —
the anchor escalates to a ready-to-run command:
`/compact <generated instructions>` where the instructions are built from
STATE.md: preserve Goal/Now/Decisions and current change intent; drop
exploration detail and dead-end transcripts (they live in the file).

**PreCompact safety net.** On auto-compact: snapshot the ledger and current
metrics to the session dir; if STATE.md is stale, block **once** with reason
"tend: update STATE.md, then run /compact" (a `blocked_once` flag in the
session dir guarantees the next attempt passes — cannot wedge). Manual
compacts are never blocked.

**Lossless continuation.** SessionStart (source: startup/clear) in a project
whose STATE.md was updated within `state_fresh_hours` (default 48h) injects
the file as `additionalContext` with a preamble ("state restored from previous
session; verify Files-touched against current disk before relying on it").
The handoff ritual becomes `/clear`. `tend handoff` additionally finalizes
STATE.md (prompts via stderr if stale) and prints what the next session will
load — useful for cross-machine moves.

## CLI

| Command | Does |
|---|---|
| `tend status` | Current session: used %, bloat breakdown, STATE.md freshness |
| `tend report [sid]` | Ledger report: top tool results by size, stale items, offloads, compaction history |
| `tend handoff` | Finalize STATE.md, print continuation preview |
| `tend install-hook` / `uninstall-hook` | Merge/remove settings.json entries + statusline wrap, non-destructive, idempotent |
| `tend on` / `tend off` | Global kill switch (touch/remove `~/.claude/tend/disabled`; hooks check it first and exit 0) |

## Error handling

- Every hook main is wrapped in a catch-all: on any exception → log to
  `~/.claude/tend/tend.log` → exit 0 with no stdout. The session is never
  blocked by a tend bug. The single intentional block (PreCompact, once) is
  flag-guarded.
- Atomic writes (tmp + rename) for ctx.json/cursors; fcntl locks for ledger
  appends (agent-pd pattern).
- Offloaded outputs may contain secrets a tool printed — they stay local with
  0600 permissions; nothing leaves the machine; no network calls anywhere.
- Transcript parse errors (format drift): skip bad lines, mark ledger
  `degraded: true`; pillars that depend on exact numbers fall back to
  statusline metrics only.
- Hook latency budget: < 150 ms p95 per invocation (no model calls, no
  network; incremental parsing with cursors).

## Testing

- **Unit (pytest):** ledger math against fixture transcripts with known usage;
  offload excerpting (head/tail boundaries, threshold edges); anchor builder
  (truncation, escalation lines); STATE.md staleness logic; install-hook merge
  (preserves agent-pd entries, idempotent).
- **Integration:** run `python3 -m tend.hook` as a subprocess on captured real
  hook payloads (recorded from this machine) and assert stdout JSON shape;
  statusline-wrap tee + exec passthrough.
- **Evidence:** `capture` CLI screenshots of `tend status` / `tend report` and
  a live-session demo in `docs/test-evidence.md`, per global convention.
- **Canary:** after install, a marker in `tend status` confirms hooks fired in
  the last session (detects silent registration breakage).

## Configuration

`~/.claude/tend/config.yaml` (all keys optional; defaults baked in), with
per-project override at `<project>/.claude/tend/config.yaml`:

```yaml
offload_threshold_tokens: 2500
offload_tools: [Bash, Grep, Glob, WebFetch]
offload_head_tokens: 600
offload_tail_tokens: 600
read_guard_bytes: 65536
anchor_max_tokens: 400
state_stale_tokens: 25000
state_fresh_hours: 48
advise_pct: 55
urge_pct: 70
```

## Out of scope (project 2: the orchestrator)

Subagent parallelism, inter-agent context transfer, and workflow fan-out are a
separate project. This harness deliberately records per-agent token usage in
the ledger (SubagentStart/Stop events) so the orchestrator can later build on
the same accounting without rework.

## Build order (for the implementation plan)

1. Skeleton: package, hook entry + dispatch, fail-open wrapper, config loader,
   install-hook/uninstall-hook, kill switch.
2. Measurement: statusline tee + transcript ledger + `tend status`/`report`.
3. Pillar 1: offloading + read guard.
4. Pillars 2+3: STATE.md conventions + anchor injection.
5. Pillar 4: advisor, PreCompact net, SessionStart continuation, `tend handoff`.
6. Evidence pass: capture screenshots, live-session validation.
