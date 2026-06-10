# tend — test evidence

Date: 2026-06-10 · branch `build/v1` · 110 unit/integration tests passing (`python3 -m pytest -q`).

## Live install (real `~/.claude/settings.json`)

`tend install-hook` merged non-destructively, verified by inspection after install:

- agent-pd hooks preserved on PostToolUse / PermissionDenied / SubagentStart / SubagentStop
- tend registered on its 8 events (PreToolUse, PostToolUse, UserPromptSubmit, Stop, SessionStart, PreCompact, SubagentStart, SubagentStop)
- Notification sound hook, model, plugins, marketplaces untouched
- statusLine wrapped (`python3 -m tend.statusline`), original saved to `~/.claude/tend/statusline-original.json`
- backup written: `~/.claude/settings.json.bak-tend`

## Smoke tests against installed entry points

PostToolUse with a 15,000-char Bash output:

```
exit: 0 | keys: ['hookEventName', 'updatedToolOutput']
excerpt tail: ...saved to ~/.claude/tend/sessions/smoke-live/outputs/0001.txt - Read it (with offset/limit) only if needed.
-rw-------  0001.txt  (15000 bytes, mode 0600)
```

Statusline tee with `used_percentage: 47.0` — the wrapper teed `ctx.json` AND
the user's original `statusline.sh` rendered through it unchanged (ANSI bar):

```
'\x1b[1mFable\x1b[0m \x1b[2m│\x1b[0m ctx \x1b[32m████▋░░░░░\x1b[0m 47%\n'
```

SessionStart (`source: startup`, cwd = this repo) seeded
`.claude/tend/STATE.md` and injected the maintenance convention.

PreCompact auto-trigger block-once, manual never blocked, garbage stdin → exit 0
silent: covered by the final review's adversarial pass and the integration suite.

## CLI screenshots (real Terminal, via `capture`)

| Feature | Evidence |
|---|---|
| `tend status` — context %, hook-activity canary, stale/bloat, STATE.md freshness | ![status](screenshots/01-tend-status.png) |
| `tend report` — ledger breakdown, offloaded outputs, snapshots | ![report](screenshots/02-tend-report.png) |
| `tend handoff` — what the next session auto-loads | ![handoff](screenshots/03-tend-handoff.png) |

## Live-session canary (run after next session start)

In any new Claude Code session: the statusline should render as before, and
`tend status` should show `last hook activity` under a minute with the new
session id. Rollback layers if anything misbehaves: `tend off` (instant
neutralization), `tend uninstall-hook` (full revert), `settings.json.bak-tend`.
