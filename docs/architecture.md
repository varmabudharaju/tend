# tend architecture

How tend plugs into Claude Code: no daemon, one short-lived process per hook
event, everything durable in plain files. (Extracted from the README; this is
the deep-dive companion to [../README.md](../README.md).)

## System design — how tend plugs into Claude Code

No daemon, no background process: Claude Code fires an event, a tiny tend process wakes, reads its state from disk, acts, and exits. Everything durable lives in plain files.

```mermaid
flowchart TB
    subgraph cc ["Claude Code"]
        EV["8 hook events"]
        SL["statusline render"]
        TR["session transcript .jsonl"]
    end
    subgraph tendp ["tend - one short-lived process per event"]
        HK["hook.py dispatcher<br/>fail-open wrapper"]
        LG["ledger.py<br/>incremental token accounting"]
        HD["event handlers<br/>offload, readguard, agentguard,<br/>anchor, boundary, precompact, sessionstart"]
        SLW["statusline.py wrapper"]
    end
    subgraph disk ["state on disk - ~/.claude/tend/"]
        SUM["sessions/ID/summary.json<br/>ledger totals + cursor"]
        CTX["sessions/ID/ctx.json<br/>exact context metrics"]
        OUT["sessions/ID/outputs/NNNN.txt<br/>offloaded tool outputs"]
        FLG["sessions/ID/flags.json"]
    end
    ST["project/.claude/tend/STATE.md<br/>the notebook"]
    EV -->|"stdin JSON"| HK
    HK --> LG
    HK --> HD
    LG -->|"reads incrementally"| TR
    LG <--> SUM
    SL --> SLW
    SLW --> CTX
    HD <--> FLG
    HD --> OUT
    HD <--> ST
    HD -->|"stdout JSON: excerpt, anchor,<br/>restored state, or block"| EV
```

## Component view — module layers

```mermaid
flowchart TB
    subgraph entry ["Entry points"]
        cli["cli.py"]
        hookpy["hook.py"]
        slpy["statusline.py"]
        inst["install.py"]
    end
    subgraph handlers ["Event handlers"]
        off["offload"]
        rg["readguard"]
        ag["agentguard"]
        an["anchor"]
        bd["boundary"]
        pc["precompact"]
        ss["sessionstart"]
    end
    subgraph core ["Core services"]
        led["ledger"]
        stm["state"]
        adv["advisor"]
        cm["ctxmetrics"]
        cfg["config"]
        flg["flags"]
        tk["tokens"]
    end
    subgraph infra ["Infrastructure"]
        io["hookio - fail-open, log rotation"]
        pa["paths - atomic JSON I/O"]
    end
    hookpy --> handlers
    cli --> core
    cli --> inst
    slpy --> infra
    handlers --> core
    core --> infra
```

## Flow chart — when does tend recommend compaction?

The advisor runs on every prompt; this is its whole decision:

```mermaid
flowchart TD
    p["context % from ctx.json"] --> u{"at or above<br/>urge threshold? (70%)"}
    u -->|yes| now["anchor says:<br/>run now: /compact + curated instructions"]
    u -->|no| a{"at or above<br/>advise threshold? (55%)"}
    a -->|no| quiet["say nothing"]
    a -->|yes| b{"is this a task boundary?<br/>(STATE.md was just updated)"}
    b -->|yes| good["good moment for /compact"]
    b -->|no| later["at the next task boundary,<br/>run /compact"]
```

And the one time tend ever blocks anything:

```mermaid
flowchart TD
    ac["auto-compact about to fire"] --> home{"working in the<br/>home directory?"}
    home -->|yes| pass["allow"]
    home -->|no| stale{"is STATE.md stale?<br/>(notebook behind the work)"}
    stale -->|no| pass
    stale -->|yes| once{"already blocked once<br/>this session?"}
    once -->|yes| pass
    once -->|no| block["block ONCE:<br/>update the notebook, then compact"]
```

## Modules

```
tend/
  hook.py          entry point: python3 -m tend.hook (all 8 events)
  hookio.py        stdin/stdout plumbing, fail-open wrapper, log rotation
  ledger.py        incremental transcript ledger: exact context totals,
                   tool-result sizes, staleness, crash-safe single-file cursor
  offload.py       pillar 1: oversized-output offloading
  readguard.py     pillar 1b: nudge unbounded Reads of large text files
  agentguard.py    pillar 1c: model-tier nudge for subagent spawns
  state.py         STATE.md template, parsing, atomic seeding
  sessionstart.py  pillar 4: state restore into fresh sessions
  anchor.py        pillar 3: per-prompt anchor (urgency-first truncation)
  boundary.py      Stop-event task-boundary + staleness detection
  precompact.py    pillar 4 safety net: snapshot + one-shot stale block
  advisor.py       when and how to recommend a curated /compact
  retention.py     age-capped GC of session state (tend clean + daily auto-sweep)
  statusline.py    statusline wrapper: tees exact context metrics to disk
  config.py        defaults < global yaml < project yaml, validated
  install.py       reversible settings.json merge (backup, mode-preserving)
  cli.py           status / report / handoff / clean / on / off / (un)install-hook
```
