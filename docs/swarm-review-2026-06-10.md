# tend v0.1 adversarial review — final report

Target: `/Users/varma/tend` (modules in `tend/tend/`, 110 tests green throughout). Six reviewers (r-ledger, r-offload, r-anchor, r-hooks, r-state, r-install) produced 39 findings; two verifiers (v-core, v-shell) independently reproduced every claim using sandboxed `TEND_HOME` probes, live artifacts from real sessions, and the installed Claude Code 2.1.172 binary (embedded zod schemas + construction sites). No project files were modified.

**Final tally: 33 confirmed (31 entries after merging one shared root cause), 2 uncertain, 4 refuted.**

Cross-cutting theme from the confirmed set: the fail-open design (`hookio.run_fail_open`) plus `hook.py:14` running `ledger.ingest` before every handler means each confirmed crash bug degrades into a *silent, total* outage of all tend features — never a visible error.

---

## High severity

### H1. Ledger permanently loses records read during a writer append — `ledger.py:66-70`
`for line in f` yields a partial trailing line mid-append; json fails (degraded set), but `f.tell()` at :70 lands at EOF mid-record, so the cursor skips the fragment forever. Reproduced: tool_use line + first 40 chars of an 8,000-char tool_result → after the writer finished, re-ingest left `results={}`, the tool_use stuck pending, degraded sticky `True`. Record loss is permanent on a routine read/write race.

### H2. Negative `tokens_since_state_mark` kills the entire staleness net — `boundary.py:23` + `precompact.py:35` + `ledger.py:62,:134` (merged; found independently by 3 reviewers)
After `/compact` or a ledger truncation reset, `state_mark.context_total` exceeds the new `context_total`; the plain subtraction at `ledger.py:134` goes negative and neither `boundary.py:23` nor `precompact.py:36` clamps or re-baselines. Both the STATE.md staleness reminder and the stale-auto-compact block are silently disabled until context regrows past the old mark. Reproduced three ways: since = −100,000 → `state_reminder=False`, `_is_stale=False`; mark=140k/ct=30k with a 10-hour-stale STATE.md → auto-compact not blocked (control at ct=170k blocks); truncation reset → since = −57,000. This defeats tend's core promise exactly when it matters (right after compaction).

---

## Medium severity

**M1. UnicodeDecodeError freezes the ledger silently — `ledger.py:68`.** Invalid UTF-8 raises from the file *iterator*, outside the `json.loads` guard at :79. Cursor and summary never advance, `degraded=False`. Permanent for genuinely bad bytes (lines before the bad byte also lost); transient for a partially-flushed multibyte char.

**M2. Valid-JSON non-dict line permanently stalls ingest — `ledger.py:84`.** `'null'` passes `json.loads`, then `obj.get` raises AttributeError outside the try. Cursor never written; identical stall for list/str/number lines; `degraded=False`.

**M3. One ingest exception disables every handler — `hook.py:14`.** `ledger.ingest` runs unconditionally before `fn(event)` inside a single fail-open try. Reproduced: poisoned `cursor.json` `{"offset":"0"}` → TypeError → offload of a 200k output skipped; transcript-unlink FileNotFoundError race also shown. This is the amplifier that turns M1/M2/L2 into full-harness outages.

**M4. Config accepts anything; bad YAML silently kills tend — `config.py:45-48`.** Empty value → `None` poisons Config; `advise_pct: '55'` → str → TypeError on comparison inside fail-open (all hooks dead, silently); `offload_tools: 42` → TypeError at load; top-level list → AttributeError. All four reproduced; `config.load` is called by five handlers plus the CLI.

**M5. Missing STATE.md blocks the first auto-compact — `precompact.py:28`.** No home-dir exemption and `sessionstart` never seeds `$HOME`; `~/.claude/tend/STATE.md` is absent on this very machine where tend is installed with 8 hook events. After the once-per-session block, the anchor nags every prompt.

**M6. `offload_tail_tokens: 0` inflates context while claiming savings — `offload.py:20`.** `text[-0:]` is the whole string: a 20,200-char output became a 22,811-char "excerpt" containing the complete original, banner claiming "~4450 tokens offloaded". The :16 guard misses it.

**M7. Dict tool responses saved as one line of escaped JSON — `offload.py:11`.** Proven by a live artifact: `sessions/bcc84aed-.../outputs/0001.txt` is 11,473 chars, 0 newlines, starting `{"stdout":`. The advertised `Read` offset/limit recovery is line-based and useless on a 1-line file; `ensure_ascii` inflates non-ASCII to `\uXXXX`.

**M8. Claude Code silently rejects the replacement for schema'd tools — `offload.py:29`.** Upgraded from uncertain: the 2.1.172 binary runs `H.outputSchema?.safeParse(updatedToolOutput)` and on failure logs "...using original output", while tend's offload file is already written and tend gets no signal that zero tokens were saved. Latent: only MCP tools with an outputSchema added to `offload_tools`; defaults (Bash/Grep/Glob/WebFetch) unaffected.

**M9. Anchor truncation evicts the most urgent content — `anchor.py:38`.** Head-keeping `text[:max_tokens*4]` after Goal-first assembly: a 1,700-char Goal at 85% context produced a 1,600-char anchor containing neither `Health:` nor the "run now: /compact" urge.

**M10. Uninstall can destroy a user's own hook — `install.py:72`.** Entry-granular filter drops a whole hooks entry if any inner hook matches `-m tend.hook`. Reproduced: shared entry → `{'hooks': {}}`, user hook gone. Conditional: requires user/another tool to have merged commands into one entry.

**M11. Reinstall never repairs a dead interpreter path — `install.py:54,:57`.** Marker-substring idempotency only: `/old/dead/python` persisted in all 8 hooks and the statusLine across `install()`, while the CLI printed success.

---

## Low severity

| # | Site | Finding |
|---|------|---------|
| L1 | `ledger.py:103` | NotebookEdit staleness is dead code: live schema requires `notebook_path`; code reads only `file_path`. |
| L2 | `ledger.py:57,:61` | `cursor.json` of `null`/`{}` → TypeError/KeyError on every ingest, never repaired (crash precedes the rewrite). Exotic precondition. |
| L3 | `ledger.py:71-72` | Crash between summary and cursor writes double-counts `output_total` (100→200) and duplicates read ids. Narrow window; advisory counter. |
| L4 | `offload.py:16` | Guard ignores the ~170-char banner: custom config turned 2,450 chars into a 2,610-char replacement. Defaults unaffected. |
| L5 | `readguard.py:27` | Binary files >64KB get bytes//4 "tokens" (1MB PNG ≈ "262,144 tokens") and inapplicable offset/limit advice. Advisory only. |
| L6 | `anchor.py:17` | Gate omits `bloat_tokens`: a bloat-only state (9,000 tok oversized results) suppresses the anchor that would have reported exactly that. |
| L7 | `boundary.py:16` | First Stop of every session: `state_mark is None` → `boundary=True` even with a 30-day-old STATE.md → false "good moment for /compact" advisory; staleness re-baselined. |
| L8 | `hookio.py:36` vs `:24` | `run_fail_open` catches BaseException but `log_error` guards only Exception: KeyboardInterrupt inside `log_error` escapes the wrapper; routine Ctrl-C logged as an error traceback. |
| L9 | `hookio.py:22` | `tend.log` append-only, never rotated/capped/read; a persistent fault writes a traceback per event across 8 events indefinitely. |
| L10 | `sessionstart.py:34` | `read_text()[:16000]` silently tail-truncates restored state, no marker; Dead-ends section lost while PREAMBLE claims full state. Reproduced with a 20k STATE.md. |
| L11 | `state.py:31-32` | `seed()` check-then-write race with plain `write_text` (no O_EXCL/tmp+rename). Verifier: realistic outcome is template-over-template; clobbering real content needs an implausible window — overstated as written. |
| L12 | `state.py:32,:40` / `sessionstart.py:34` | STATE.md I/O omits `encoding='utf-8'` (paths.py passes it everywhere). Raises only under an ASCII-codec locale with PYTHONCOERCECLOCALE=0 (then fail-open silently skips restore); latin-1 silently mojibakes. Real defect, very narrow trigger. |
| L13 | `install.py:60-61` | Reinstall after statusLine was externally removed unlinks `statusline-original.json`; the user's original statusline is permanently lost. |
| L14 | `install.py:53,:57,:79` | `"hooks": null` or a string statusLine → raw AttributeError; CLI catches only SettingsError → user-facing tracebacks. |
| L15 | `statusline.py:44` | `':.0f'` on `used_percentage` without coercion, no fail-open in `main()`: a string pct crashes the whole statusline (blank). No evidence the current binary emits a string — trigger speculative. |
| L16 | `cli.py:10,:36` | TOCTOU between `is_file()` and `stat()` on the pid-named `.tmp` files `write_json_atomic` creates in the same dirs; FileNotFoundError crashes `tend status`. Narrow but genuine. |
| L17 | `install.py:107-110` | Backup written under default umask before `chmod`: 0600 settings exposed at 0644 in the window, or permanently on a crash between the calls. |
| L18 | `statusline.py:18` | Statusline ignores `tend off`: with `$TEND_HOME/disabled` present it still writes `ctx.json` and execs the original command. Partially by-design. |

---

## Uncertain (mechanism proven, real-world trigger not demonstrated)

**U1. `ctxmetrics.py:5-14` — no freshness check on `ctx.json`.** It is only rewritten when Claude Code renders the statusline, so between `/compact` and the next render the anchor/advisor consume the pre-compact percentage (e.g. 85 → "run now: /compact" right after compacting). Code half is fact; the stale window is normally short and a racing prompt was not demonstrated live.

**U2. `state.py:24-25` / `config.py:37-39` — no ancestor walk from event cwd.** With event cwd = `<project>/src`, STATE.md resolution misses the project-root file: `goal_now` returns empty and boundary takes the missing-STATE branch despite valid state one level up. Mechanics reproduced; whether CC 2.1.172 actually reports a drifted cwd after a persistent `cd` could not be established — trigger version-dependent.

---

## Refuted (4) — premises false on installed Claude Code 2.1.172

1. **`ledger.py:93` isSidechain pollution (r-ledger).** Subagent transcripts live in separate `subagents/agent-*.jsonl` files; 0 of 53 main transcripts on this machine contain a sidechain usage line. The missing filter has no trigger in the current layout (only relevant to older inline-sidechain versions).
2. **`hook.py:15` missing `agent_id` no-op (r-hooks).** Embedded zod schemas make `agent_id`/`agent_type` REQUIRED on SubagentStart/Stop; a real 34-subagent session shows agent tracking working.
3. **`hook.py:13` subagent transcript_path cursor thrash (r-hooks).** All hook inputs build `transcript_path` from `session_id` (always the main transcript); the subagent transcript appears only as the separate `agent_transcript_path` on SubagentStop. 34-subagent session: `degraded=False`, stable totals.
4. **`statusline.py:25` indefinite hang past timeout (r-install).** On POSIX/CPython 3.11, `TimeoutExpired` is raised at the deadline regardless of a backgrounded grandchild holding the pipe (the blocking post-kill `communicate()` is the Windows branch). End-to-end fallback at exactly 10s. Residual truth: each render can stall the full configured 10s — bounded by design, not a hang.

---

## Suggested fix priorities

1. **H1 + H2 first** — both silently defeat tend's core value (accurate ledger; staleness protection around compaction). H2 is a small fix: clamp/re-baseline `since` when `mark.context_total > context_total`.
2. **M3 (`hook.py:14`)** — wrapping `ledger.ingest` in its own try (mark degraded, continue to handler) converts every ledger crash bug from "all features silently dead" to "ledger degraded, features still run", defusing M1, M2, L2 simultaneously.
3. **M4 config validation and the M1/M2 guard widening** (move decode + non-dict handling inside the per-line guard) are cheap, high-leverage robustness wins.
4. Install/uninstall mediums (M10, M11) matter for anyone sharing `settings.json` with other tooling.

Full verifier evidence: `/Users/varma/.claude/swarm/runs/-Users-varma-tend/2026-06-10-tend-review/results/v-core.json` and `.../results/v-shell.json`.