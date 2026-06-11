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
Invalid values fall back to defaults rather than disabling tend.

## Limitations

- **MCP tools with an `outputSchema`**: Claude Code validates replacement
  outputs against the tool's schema and silently keeps the original when a
  plain-text excerpt doesn't match. tend therefore skips offloading for
  `mcp__*` tools whose responses aren't plain strings. Built-in tools (Bash,
  Grep, Glob, WebFetch) are unaffected.
- `state_stale_tokens` counts **output tokens** generated since STATE.md was
  last marked (monotonic across compaction), not context-window growth.
  Default: 3000.
