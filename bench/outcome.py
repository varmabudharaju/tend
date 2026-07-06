"""Phase 2c — outcome A/B. The task-level test the other phases could not give.

The pitch is "stays smart ten hours in" — an *outcome* claim. Phases 1/2/2b prove
mechanisms (offloading shrinks context; STATE restore survives a reset) but not the
outcome: that an agent *with* tend finishes a long, decision-heavy task better than
one without. This workload closes that gap.

Shape (a task-level, forced-reset A/B):
  - A scripted multi-step coding task with **4 planted, checkable constraints**
    (a config-key name, an error-output prefix, a required exit code, a named
    function signature) — frozen in CONSTRAINTS below.
  - **Phase A** (plant): the arm is given the task + all 4 constraints and starts
    the file, recording decisions in `.claude/tend/STATE.md` (tend ON maintains it,
    exactly like the handoff arms). Identical prompt in both arms; only tend on/off.
  - **Forced mid-task reset**: phase B runs as a FRESH session (resume_sid=None) —
    the same reset mechanism the handoff workload uses, which fires `SessionStart`.
    tend ON re-injects STATE.md; the OFF (vanilla) arm gets nothing.
  - **Phase B** (finish): "finish the task" — the constraints are NOT restated.
  - **Score** the final artifact on disk: a mechanical per-constraint rubric
    (word-boundary matched, reused from the recall scorer) → /4, plus an optional
    blind judge (a separate model that sees only the task spec + the two artifacts
    under shuffled letters, seed-derived) → 1–5 quality per artifact.

HARD RULE: this module makes **live** `claude -p` calls; unit tests mock the runner
and use canned artifacts — no network in tests, and no run is executed automatically
(it costs real money). Run it yourself with:

    python3 -m bench behavioral --workload outcome --repeats 5 --model <id>
    python3 -m bench behavioral --workload outcome --repeats 5 --model <id> \\
        --judge <judge-model> --seed 0

Results land in `.benchmarks/behavioral-<stamp>.{json,md}` with kind/workload/model
fields, exactly like the other behavioral runs. Docs carry NO numbers until a real
run exists.
"""
import json
import os
import random
import re
import shutil
import tempfile
import time
from pathlib import Path

from .behavioral import (ALLOWED, arm_env, make_sandbox, peak_ctx_in, run_turn,
                         _median)

# The finished artifact the model is asked to produce (a generic name — it leaks
# none of the planted constraint values).
ARTIFACT_NAME = "configlint.py"

# Tools available while the model works the task (must be able to read the partial
# file and write the finished one). Same set the recall/handoff arms allow.
OUTCOME_TOOLS = ALLOWED

# The judge answers from the prompt only — no tools, no files.
JUDGE_BLOCK = "Bash Read Grep Glob Write Edit Task WebFetch"


# --------------------------------------------------------------------------- #
# the 4 planted, checkable constraints (frozen)
# --------------------------------------------------------------------------- #
# Each constraint is matched against the *final* artifact. A "literal" is matched
# with the same word-boundary regex the recall scorer uses (reused via _boundary);
# a "pattern" is an explicit regex for the structural constraints (exit code in an
# exit context; the exact function signature).
CONSTRAINTS = {
    "config_key": {
        "desc": "the config key must be named `max_retry_budget`",
        "literal": "max_retry_budget",
        "value": "max_retry_budget",
    },
    "error_prefix": {
        "desc": "validation errors must be printed with the prefix `CONFIG-ERR:`",
        "pattern": r"(?<![\w-])CONFIG-ERR:",
        "value": "CONFIG-ERR:",
    },
    "exit_code": {
        "desc": "on validation failure the program must exit with code 37",
        "pattern": r"(?i)(?:sys\.exit|systemexit|exit|return|returncode|code)"
                   r"\s*[=(]?\s*37(?![\d.])",
        "value": "37",
    },
    "func_sig": {
        "desc": "the core validator must be `def validate_config(path)`",
        "pattern": r"def\s+validate_config\s*\(\s*path\b",
        "value": "validate_config",
    },
}


def _boundary(literal):
    """The recall scorer's word-boundary match (behavioral.score_recall), reused."""
    return rf"(?<![\w-]){re.escape(literal)}(?![\w-])"


def constraint_regex(name):
    c = CONSTRAINTS[name]
    return c["pattern"] if "pattern" in c else _boundary(c["literal"])


def constraint_values():
    """The concrete strings a phase prompt must (A) state / (B) not restate."""
    return [c["value"] for c in CONSTRAINTS.values()]


def score_constraints(artifact):
    """Per-constraint pass/fail against the final artifact → (hits, score /4)."""
    text = artifact or ""
    hits = {}
    for name in CONSTRAINTS:
        # literals get the recall scorer's case-insensitive boundary match; the
        # structural patterns carry their own inline flags.
        flags = re.IGNORECASE if "literal" in CONSTRAINTS[name] else 0
        hits[name] = bool(re.search(constraint_regex(name), text, flags))
    return hits, sum(hits.values())


# --------------------------------------------------------------------------- #
# the task + phase prompts
# --------------------------------------------------------------------------- #
TASK = (
    "Build a small Python CLI in a single file, `configlint.py`, that reads a JSON "
    "config file path from argv and validates it.")

# The 4 constraints, written out for the plant phase (and reused verbatim for the
# blind judge's task spec).
_CONSTRAINT_LINES = "\n".join(
    f"  {i}. {c['desc']}." for i, c in enumerate(CONSTRAINTS.values(), 1))

PHASE_A = (
    "We are starting a multi-step coding task. " + TASK + "\n\n"
    "It MUST satisfy these four constraints exactly — they are decisions, honor "
    "them for the whole task:\n"
    f"{_CONSTRAINT_LINES}\n\n"
    "Record the task goal and these four constraints now in .claude/tend/STATE.md "
    "(create it): put 'Build configlint.py' on the Goal line and the four "
    "constraints under a Decisions heading. Then create configlint.py with the "
    "argument parsing and the validate_config(path) skeleton — you will finish the "
    "validation logic next. Reply with just: started.")

PHASE_B = (
    "Pick this task back up and finish it. Complete the implementation in "
    f"{ARTIFACT_NAME} so it fully works end to end, then reply with just: done.\n"
    "Do not ask me to restate anything — use what the project already holds.")

# What the blind judge sees: the task and its constraints, no arm identifiers.
JUDGE_TASK_SPEC = (
    TASK + "\n\nThe finished program must satisfy these constraints:\n"
    f"{_CONSTRAINT_LINES}")


# --------------------------------------------------------------------------- #
# artifact collection
# --------------------------------------------------------------------------- #
def collect_artifact(sandbox):
    """Read the finished artifact the model wrote into the sandbox.

    Prefer the named file; fall back to concatenating any top-level *.py the model
    created (so a differently-named file is still scored, not silently zeroed)."""
    sb = Path(sandbox)
    named = sb / ARTIFACT_NAME
    if named.exists():
        return named.read_text(encoding="utf-8", errors="replace")
    parts = []
    for f in sorted(sb.glob("*.py")):
        try:
            parts.append(f.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# blind judge
# --------------------------------------------------------------------------- #
def judge_labels(seed=0):
    """Deterministic arm→letter map. Same seed → same map; the seed can flip it."""
    order = ["on", "off"]
    random.Random(seed).shuffle(order)
    return {order[0]: "A", order[1]: "B"}


def build_judge_prompt(task_spec, artifacts_by_letter):
    """A strict-rubric prompt. Blind: artifacts appear only under letters A/B, with
    no arm identifiers ('tend'/'on'/'off'/'arm') anywhere."""
    L = [
        "You are grading two candidate solutions to a coding task. Judge only the "
        "code shown; do not run it. Be strict.",
        "",
        "## Task",
        task_spec,
        "",
        "## Rubric (score each artifact 1-5)",
        "  5 = fully correct: satisfies every constraint and is clean.",
        "  4 = satisfies every constraint with minor issues.",
        "  3 = satisfies most constraints; one clear miss.",
        "  2 = satisfies some constraints; multiple misses.",
        "  1 = satisfies few or none of the constraints.",
        "",
    ]
    for letter in ("A", "B"):
        L += [f"## Artifact {letter}", "```python",
              (artifacts_by_letter.get(letter, "") or "").strip(), "```", ""]
    L += ["## Output",
          'Reply with ONLY a JSON object, no prose, e.g. {"A": 3, "B": 5}.']
    return "\n".join(L)


def parse_judge_scores(text):
    """Robustly extract {'A': int|None, 'B': int|None}; scores clamped to 1-5."""
    text = text or ""
    out = {"A": None, "B": None}
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
        except Exception:
            obj = None
        if isinstance(obj, dict):
            for k in ("A", "B"):
                v = obj.get(k)
                if isinstance(v, bool):
                    continue
                if isinstance(v, (int, float)) and 1 <= v <= 5:
                    out[k] = int(v)
    for k in ("A", "B"):
        if out[k] is None:
            mm = re.search(rf"(?<![\w]){k}\b[^\d\n]{{0,12}}?([1-5])(?!\d)", text)
            if mm:
                out[k] = int(mm.group(1))
    return out


def run_judge(artifact_on, artifact_off, model, seed=0, runner=run_turn,
              task_spec=None, cwd=None, env=None):
    """One blind model call scoring both artifacts. Reuses run_turn plumbing.

    The arm→letter map is seed-derived, so the judge never learns which artifact is
    which arm; we invert the map to attribute scores back to on/off afterward."""
    task_spec = task_spec or JUDGE_TASK_SPEC
    labels = judge_labels(seed)  # {'on': 'A'|'B', 'off': ...}
    by_letter = {labels["on"]: artifact_on, labels["off"]: artifact_off}
    prompt = build_judge_prompt(task_spec, by_letter)
    cwd = cwd or tempfile.mkdtemp(prefix="tend-judge-")
    env = env if env is not None else os.environ
    d = runner(prompt, cwd, env, model, resume_sid=None, allowed=None,
               disallowed=JUDGE_BLOCK, timeout=300)
    raw = d.get("result", "") if not d.get("_parse_error") else ""
    by_letter_scores = parse_judge_scores(raw)
    cost = d.get("total_cost_usd", 0.0) or 0.0
    return {
        "judge_model": model,
        "seed": seed,
        "labels": labels,
        "scores_by_letter": by_letter_scores,
        "score_on": by_letter_scores.get(labels["on"]),
        "score_off": by_letter_scores.get(labels["off"]),
        "total_cost_usd": round(cost, 4),
        "raw": raw[:400],
    }


# --------------------------------------------------------------------------- #
# one arm: plant → forced reset → finish
# --------------------------------------------------------------------------- #
def run_outcome_session(arm, run_dir, model, repeat, seed=0, log=print,
                        runner=run_turn):
    env, home = arm_env(run_dir, arm, f"r{repeat}")
    sb = make_sandbox(home, n_logs=1, log_tokens=200)
    t0 = time.time()
    total_cost = 0.0

    # Phase A — plant the task + constraints; ON arm maintains STATE.md.
    a = runner(PHASE_A, sb, env, model, resume_sid=None, allowed=OUTCOME_TOOLS,
               disallowed=None, timeout=600)
    total_cost += a.get("total_cost_usd", 0.0) or 0.0

    # Forced mid-task reset — a FRESH session (no --resume), the handoff mechanism.
    b = runner(PHASE_B, sb, env, model, resume_sid=None, allowed=OUTCOME_TOOLS,
               disallowed=None, timeout=600)
    total_cost += b.get("total_cost_usd", 0.0) or 0.0

    artifact = collect_artifact(sb)
    hits, score = score_constraints(artifact)
    peak = max(peak_ctx_in(a.get("usage", {})), peak_ctx_in(b.get("usage", {})))
    out_tokens = (a.get("usage", {}).get("output_tokens", 0)
                  + b.get("usage", {}).get("output_tokens", 0))
    errored = bool(a.get("_parse_error") or b.get("_parse_error")
                   or a.get("is_error") or b.get("is_error"))
    log(f"    [{arm} r{repeat} outcome] constraints={score}/4 "
        f"cost=${total_cost:.3f}")
    return {
        "arm": arm, "repeat": repeat, "model": model,
        "kind": "outcome", "workload": "outcome",
        "constraint_score": score, "constraint_hits": hits,
        "artifact": artifact[:6000],
        "peak_ctx_tokens": peak,
        "total_cost_usd": round(total_cost, 4),
        "total_output_tokens": out_tokens,
        "errored": errored,
        "seconds": round(time.time() - t0, 1),
    }


# --------------------------------------------------------------------------- #
# run + report
# --------------------------------------------------------------------------- #
def run(out_dir, stamp, model="claude-haiku-4-5-20251001", repeats=3,
        arms=("on", "off"), judge=None, seed=0, log=print, runner=run_turn):
    run_dir = Path(tempfile.mkdtemp(prefix="tend-outcome-"))
    log(f"[outcome] run dir: {run_dir}  model={model}  repeats={repeats}  "
        f"arms={arms}  judge={judge}  seed={seed}")
    sessions = []
    judgements = []
    for repeat in range(1, repeats + 1):
        per = {}
        for arm in arms:
            log(f"  -> session arm={arm} repeat={repeat}")
            s = run_outcome_session(arm, run_dir, model, repeat, seed=seed,
                                    log=log, runner=runner)
            sessions.append(s)
            per[arm] = s
            log(f"     done: constraints={s['constraint_score']}/4 "
                f"cost=${s['total_cost_usd']}")
        if judge and "on" in per and "off" in per:
            j = run_judge(per["on"]["artifact"], per["off"]["artifact"], judge,
                          seed=seed, runner=runner, cwd=str(run_dir))
            j["repeat"] = repeat
            judgements.append(j)
            log(f"     judge: on={j['score_on']} off={j['score_off']}")
    results = {
        "stamp": stamp, "model": model, "repeats": repeats,
        "kind": "outcome", "workload": "outcome", "seed": seed,
        "judge": judge, "arms": list(arms),
        "sessions": sessions, "judgements": judgements,
        "summary": _summarize(sessions, judgements, arms),
    }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"behavioral-{stamp}.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8")
    md = render_markdown(results, arms)
    (out_dir / f"behavioral-{stamp}.md").write_text(md, encoding="utf-8")
    shutil.rmtree(run_dir, ignore_errors=True)
    return results, md


def _summarize(sessions, judgements, arms):
    out = {}
    for arm in arms:
        rows = [s for s in sessions if s["arm"] == arm]
        if not rows:
            continue
        entry = {
            "n": len(rows),
            "median_constraint_score": _median([r["constraint_score"] for r in rows]),
            "median_peak_ctx": _median([r["peak_ctx_tokens"] for r in rows]),
            "median_cost_usd": round(_median([r["total_cost_usd"] for r in rows]), 4),
            "total_cost_usd": round(sum(r["total_cost_usd"] for r in rows), 4),
        }
        js = [j[f"score_{arm}"] for j in judgements if j.get(f"score_{arm}") is not None]
        if js:
            entry["median_judge_score"] = _median(js)
        out[arm] = entry
    return out


def render_markdown(r, arms):
    s = r["summary"]
    L = ["# tend behavioral A/B — outcome", "",
         f"_Generated {r['stamp']} · model `{r['model']}` · {r['repeats']} repeats/arm · "
         f"outcome workload"
         + (f" · judge `{r['judge']}` (seed {r['seed']})_" if r.get("judge") else "_"),
         "",
         "A multi-step coding task with 4 planted constraints, a **forced mid-task "
         "reset** (fresh session — the handoff mechanism), then 'finish the task' "
         "with the constraints NOT restated. Identical in both arms; only tend "
         "on/off. Scored on the final artifact: a mechanical per-constraint rubric "
         "(/4)" + (", plus a blind judge (1-5, shuffled letters)." if r.get("judge")
                   else "."),
         "", "## Planted constraints", ""]
    for name, c in CONSTRAINTS.items():
        L.append(f"- **{name}** — {c['desc']}.")
    L += ["", "## Summary (medians)", "",
          "| metric | tend ON | tend OFF | delta |", "|---|--:|--:|--:|"]
    if "on" in s and "off" in s:
        on, off = s["on"], s["off"]

        def delta(a, b, pct=True):
            if not b:
                return "—"
            return f"{100 * (a - b) / b:+.0f}%" if pct else f"{a - b:+.1f}"
        L.append(f"| constraints kept (/4) | {on['median_constraint_score']} "
                 f"| {off['median_constraint_score']} "
                 f"| {delta(on['median_constraint_score'], off['median_constraint_score'], pct=False)} |")
        if "median_judge_score" in on and "median_judge_score" in off:
            L.append(f"| judge quality (1-5) | {on['median_judge_score']} "
                     f"| {off['median_judge_score']} "
                     f"| {delta(on['median_judge_score'], off['median_judge_score'], pct=False)} |")
        L.append(f"| cost / arm (USD) | ${on['median_cost_usd']} "
                 f"| ${off['median_cost_usd']} "
                 f"| {delta(on['median_cost_usd'], off['median_cost_usd'])} |")
    L += ["", "## Per-session", "",
          "| arm | repeat | constraints | cost $ | sec |",
          "|---|--:|--:|--:|--:|"]
    for x in r["sessions"]:
        L.append(f"| {x['arm']} | {x['repeat']} | {x['constraint_score']}/4 "
                 f"| {x['total_cost_usd']} "
                 f"| {x['seconds']}{' ⚠err' if x.get('errored') else ''} |")
    L += ["", "## Constraints kept (per session)", ""]
    for x in r["sessions"]:
        kept = ", ".join(k for k, v in x["constraint_hits"].items() if v) or "none"
        L.append(f"- **{x['arm']} r{x['repeat']}** ({x['constraint_score']}/4): {kept}")
    if r.get("judgements"):
        L += ["", "## Blind judge (shuffled letters)", "",
              "| repeat | tend ON | tend OFF |", "|---|--:|--:|"]
        for j in r["judgements"]:
            L.append(f"| {j.get('repeat', '')} | {j['score_on']} | {j['score_off']} |")
    return "\n".join(L) + "\n"
