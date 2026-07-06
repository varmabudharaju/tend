"""Phase 2b — faithful interactive A/B for tend's lossless-handoff claim.

tend's marquee behavioral feature (restore STATE.md into a fresh context on
/clear, so a long task survives a context reset) is an *interactive* property:
it fires when a human runs /clear, which headless `claude -p` cannot reproduce.

So this is a human-in-the-loop protocol. `setup` creates two isolated sandboxes
and prints the exact prompts to paste; you run the same short script in each arm
(tend ON, tend OFF), ending in /clear then a memory-only probe. `score` then reads
the two transcripts and grades recall of the planted facts.

Isolation: each arm launches claude with its own TEND_HOME (the OFF arm's has a
`disabled` file → tend's hooks no-op). Your global tend and this session are
untouched. STATE.md lives in the sandbox cwd, transcripts under ~/.claude/projects.
"""
import json
from pathlib import Path

from .behavioral import FACTS, PLANT, PROBE, score_recall

RESTORE_MARKER = "State restored from previous session"


def _home_base():
    return Path.home() / "tend" / ".benchmarks" / "interactive"


def setup(log=print):
    base = _home_base()
    arms = {}
    for arm in ("on", "off"):
        sb = base / arm / "project"
        sb.mkdir(parents=True, exist_ok=True)
        home = base / arm / "tend_home"
        home.mkdir(parents=True, exist_ok=True)
        # OFF arm: kill switch so tend hooks no-op even though they are installed.
        disabled = home / "disabled"
        if arm == "off":
            disabled.write_text("", encoding="utf-8")
        elif disabled.exists():
            disabled.unlink()
        arms[arm] = (sb, home)

    launch = {arm: f'TEND_HOME="{home}" claude' for arm, (sb, home) in arms.items()}
    L = ["", "=" * 72, "tend interactive A/B — lossless /clear handoff", "=" * 72,
         "",
         "Run the SAME 3 steps in each arm. Only difference: tend on vs off.",
         "The probe is memory-only — do NOT let the model read files at the probe.",
         ""]
    for arm in ("on", "off"):
        sb, home = arms[arm]
        L += [f"--- ARM: tend {arm.upper()} " + "-" * 50,
              f"1. cd {sb}",
              f"2. launch:   {launch[arm]}",
              "3. paste PROMPT 1 (plant), wait for it to finish writing STATE.md:",
              "", "   " + PLANT.replace("\n", "\n   "), "",
              "4. type:  /clear",
              "5. paste PROMPT 2 (probe) — answer must be from memory only:",
              "", "   " + PROBE.replace("\n", "\n   "), "",
              "6. exit claude (Ctrl-D).", ""]
    L += ["When both arms are done, score it:",
          "   python3 -m bench interactive --score", "",
          f"(facts planted: {', '.join(FACTS.values())})", "=" * 72]
    msg = "\n".join(L)
    log(msg)
    return {arm: str(sb) for arm, (sb, home) in arms.items()}


def _proj_dir(cwd):
    esc = str(Path(cwd).resolve()).replace("/", "-").replace(".", "-")
    return Path.home() / ".claude" / "projects" / esc


def _scan_transcript(cwd):
    d = _proj_dir(cwd)
    files = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime) if d.exists() else []
    if not files:
        return None
    tr = files[-1]
    restored = False
    assistant_texts = []
    for line in tr.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if RESTORE_MARKER in json.dumps(rec):
            restored = True
        if rec.get("type") == "assistant":
            msg = rec.get("message", {}) or {}
            for block in (msg.get("content") or []):
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                    assistant_texts.append(block["text"])
                elif isinstance(block, str) and block.strip():
                    assistant_texts.append(block)
    return {"transcript": str(tr), "restored": restored,
            "probe_answer": assistant_texts[-1] if assistant_texts else ""}


def score(log=print):
    base = _home_base()
    rows = []
    for arm in ("on", "off"):
        cwd = base / arm / "project"
        info = _scan_transcript(cwd)
        if not info:
            rows.append({"arm": arm, "found": False})
            log(f"[{arm}] no transcript found under {_proj_dir(cwd)} — run the protocol first.")
            continue
        hits, recall = score_recall(info["probe_answer"])
        rows.append({"arm": arm, "found": True, "recall": recall, "hits": hits,
                     "tend_restored": info["restored"],
                     "probe_answer": info["probe_answer"][:300],
                     "transcript": info["transcript"]})
    md = _render(rows)
    log("\n" + md)
    return rows, md


def _render(rows):
    L = ["# tend interactive A/B — lossless /clear handoff", "",
         "| arm | recall | tend restored STATE on /clear | probe answer (excerpt) |",
         "|---|--:|:--:|---|"]
    for r in rows:
        if not r.get("found"):
            L.append(f"| {r['arm']} | — | — | (no transcript — run protocol) |")
            continue
        ans = r["probe_answer"].replace("\n", " ").strip()[:90]
        L.append(f"| {r['arm']} | {r['recall']}/4 | "
                 f"{'yes' if r['tend_restored'] else 'no'} | {ans} |")
    on = next((r for r in rows if r["arm"] == "on" and r.get("found")), None)
    off = next((r for r in rows if r["arm"] == "off" and r.get("found")), None)
    if on and off:
        L += ["", f"**Verdict:** tend ON recalled {on['recall']}/4 after /clear, "
              f"tend OFF recalled {off['recall']}/4. "
              + ("tend's STATE restore preserved the facts across the context reset."
                 if on["recall"] > off["recall"] else
                 "No handoff advantage observed in this run.")]
    return "\n".join(L) + "\n"
