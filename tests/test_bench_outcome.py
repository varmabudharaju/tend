"""Pure-function tests for the outcome bench harness (no subprocesses, no API).

The outcome workload is a task-level A/B: a multi-step coding task with 4 planted
constraints, a forced mid-task reset, and completion-quality scoring. These tests
use canned artifacts and a mocked runner — they never touch the network.
"""
import json
from pathlib import Path

from bench import outcome


# --------------------------------------------------------------------------- #
# canned artifacts
# --------------------------------------------------------------------------- #
GOOD_ARTIFACT = '''\
import json, sys

def validate_config(path):
    with open(path) as f:
        cfg = json.load(f)
    if "max_retry_budget" not in cfg:
        print("CONFIG-ERR: missing max_retry_budget")
        sys.exit(37)
    return cfg
'''

EMPTY_ARTIFACT = "def main():\n    pass\n"

PARTIAL_ARTIFACT = '''\
def validate_config(path):
    cfg = load(path)
    return "max_retry_budget" in cfg
'''

# plausible-looking near-misses that must NOT satisfy the constraints
SUBSTRING_TRAP = (
    "budgets = max_retry_budgets  # plural key, not the constraint\n"
    "raise SystemExit(137)  # the number is 137, not the required one\n"
    "def validate_configs(p):\n    return p\n"
)


# --------------------------------------------------------------------------- #
# 1. constraint scorer
# --------------------------------------------------------------------------- #
def test_score_constraints_all_pass():
    hits, score = outcome.score_constraints(GOOD_ARTIFACT)
    assert score == 4
    assert all(hits.values())
    # every declared constraint is represented in the hit map
    assert set(hits) == set(outcome.CONSTRAINTS)


def test_score_constraints_all_fail_on_unrelated_code():
    hits, score = outcome.score_constraints(EMPTY_ARTIFACT)
    assert score == 0
    assert not any(hits.values())


def test_score_constraints_empty_input():
    hits, score = outcome.score_constraints("")
    assert score == 0
    assert outcome.score_constraints(None)[1] == 0


def test_score_constraints_partial():
    hits, score = outcome.score_constraints(PARTIAL_ARTIFACT)
    # names the key and the function, but no error prefix / exit code
    assert hits["config_key"] and hits["func_sig"]
    assert not hits["error_prefix"] and not hits["exit_code"]
    assert score == 2


def test_score_constraints_word_boundary_edges():
    # substring look-alikes must not count (this is the boundary regression)
    hits, score = outcome.score_constraints(SUBSTRING_TRAP)
    assert not hits["config_key"], "max_retry_budgets != max_retry_budget"
    assert not hits["exit_code"], "137 != exit code 37"
    assert not hits["func_sig"], "validate_configs(p) != validate_config(path)"
    assert score == 0


def test_score_constraints_exit_code_accepts_common_forms():
    for form in ("sys.exit(37)", "exit(37)", "raise SystemExit(37)", "return 37"):
        hits, _ = outcome.score_constraints(form)
        assert hits["exit_code"], form


def test_score_constraints_exit_code_rejects_embedded_number():
    for form in ("sys.exit(370)", "budget = 1372", "retry 37 times but exit 5"):
        hits, _ = outcome.score_constraints(form)
        assert not hits["exit_code"], form


# --------------------------------------------------------------------------- #
# 2. arm / phase construction
# --------------------------------------------------------------------------- #
def test_phase_a_states_every_constraint():
    a = outcome.PHASE_A
    for token in outcome.constraint_values():
        assert token in a, f"phase A must state constraint value {token!r}"
    # phase A also wires the STATE.md convention (carryover ON maintains it)
    assert "STATE.md" in a


def test_phase_b_restates_no_constraints():
    b = outcome.PHASE_B
    for token in outcome.constraint_values():
        assert token not in b, f"phase B must NOT restate constraint value {token!r}"
    # but it must still tell the model to finish and produce the artifact
    assert outcome.ARTIFACT_NAME in b
    assert "finish" in b.lower()


def test_phases_share_no_constraint_leak_via_artifact_name():
    # the artifact filename is generic and leaks none of the planted values
    assert not any(v in outcome.ARTIFACT_NAME for v in outcome.constraint_values())


# --------------------------------------------------------------------------- #
# 3. blind judge — deterministic label shuffling
# --------------------------------------------------------------------------- #
def test_judge_labels_deterministic_per_seed():
    assert outcome.judge_labels(0) == outcome.judge_labels(0)
    assert outcome.judge_labels(7) == outcome.judge_labels(7)


def test_judge_labels_are_a_bijection():
    m = outcome.judge_labels(0)
    assert set(m) == {"on", "off"}
    assert set(m.values()) == {"A", "B"}


def test_judge_labels_depend_on_seed():
    # across a spread of seeds, both letter-orderings must appear (seed matters)
    seen = {tuple(sorted(outcome.judge_labels(s).items())) for s in range(24)}
    assert len(seen) == 2, "seed must be able to flip which arm is labeled A"


def test_judge_prompt_is_blind():
    prompt = outcome.build_judge_prompt(
        outcome.JUDGE_TASK_SPEC, {"A": GOOD_ARTIFACT, "B": EMPTY_ARTIFACT})
    low = prompt.lower()
    assert "carryover" not in low
    import re
    assert re.search(r"\barm\b", low) is None
    # artifacts are referred to only by their shuffled letters, and both appear
    assert "Artifact A" in prompt and "Artifact B" in prompt
    assert GOOD_ARTIFACT.strip() in prompt and EMPTY_ARTIFACT.strip() in prompt


def test_parse_judge_scores_json_and_freeform():
    assert outcome.parse_judge_scores('{"A": 4, "B": 2}') == {"A": 4, "B": 2}
    assert outcome.parse_judge_scores("Artifact A: 5\nArtifact B - 1") == {"A": 5, "B": 1}
    # out-of-range / missing -> None, never crashes
    got = outcome.parse_judge_scores("A=9 nonsense")
    assert got["A"] is None and got["B"] is None


def test_run_judge_unshuffles_scores_back_to_arms():
    # a fake judge that scores whichever labeled section holds the GOOD artifact.
    # It inspects ONLY the A code block (between the two artifact headers) so the
    # task spec that precedes them cannot leak the answer.
    def fake_runner(prompt, cwd, env, model, resume_sid=None, allowed=None,
                    disallowed=None, timeout=300):
        a_block = prompt.split("## Artifact A", 1)[1].split("## Artifact B", 1)[0]
        good_in_a = "def validate_config(path)" in a_block
        scores = {"A": 5, "B": 1} if good_in_a else {"A": 1, "B": 5}
        return {"session_id": "j", "result": json.dumps(scores),
                "usage": {"output_tokens": 5}, "total_cost_usd": 0.002}

    # regardless of seed / label assignment, the GOOD (on) arm must score 5
    for seed in range(6):
        res = outcome.run_judge(GOOD_ARTIFACT, EMPTY_ARTIFACT, "judge-model",
                                seed=seed, runner=fake_runner)
        assert res["score_on"] == 5, seed
        assert res["score_off"] == 1, seed
        assert res["judge_model"] == "judge-model"
        assert set(res["labels"]) == {"on", "off"}


# --------------------------------------------------------------------------- #
# 4. results serialization
# --------------------------------------------------------------------------- #
def _artifact_writing_runner(prompt, cwd, env, model, resume_sid=None, allowed=None,
                             disallowed=None, timeout=300):
    """Emulates the model writing the finished artifact into the sandbox cwd."""
    (Path(cwd) / outcome.ARTIFACT_NAME).write_text(GOOD_ARTIFACT, encoding="utf-8")
    return {"session_id": "sid", "result": "done",
            "usage": {"output_tokens": 12, "input_tokens": 200},
            "total_cost_usd": 0.01}


def test_run_serializes_workload_model_kind(tmp_path):
    results, md = outcome.run(str(tmp_path), "stamp-1", model="test-model",
                              repeats=1, arms=("on", "off"),
                              runner=_artifact_writing_runner)
    assert results["kind"] == "outcome"
    assert results["workload"] == "outcome"
    assert results["model"] == "test-model"
    for s in results["sessions"]:
        assert s["kind"] == "outcome" and s["workload"] == "outcome"
        assert s["model"] == "test-model"
        assert s["constraint_score"] == 4
    # results are JSON-serializable and were written to disk like existing runs
    json.dumps(results)
    assert (tmp_path / "behavioral-stamp-1.json").exists()
    assert (tmp_path / "behavioral-stamp-1.md").exists()
    assert "outcome" in md


def test_run_with_judge_records_judgements(tmp_path):
    def runner(prompt, cwd, env, model, resume_sid=None, allowed=None,
               disallowed=None, timeout=300):
        if "Artifact A" in prompt:  # judge call
            return {"session_id": "j", "result": '{"A": 4, "B": 4}',
                    "usage": {"output_tokens": 5}, "total_cost_usd": 0.001}
        (Path(cwd) / outcome.ARTIFACT_NAME).write_text(GOOD_ARTIFACT, encoding="utf-8")
        return {"session_id": "s", "result": "done",
                "usage": {"output_tokens": 10}, "total_cost_usd": 0.01}

    results, _ = outcome.run(str(tmp_path), "stamp-2", model="m", repeats=1,
                             arms=("on", "off"), judge="judge-model", seed=0,
                             runner=runner)
    assert results["judge"] == "judge-model"
    assert len(results["judgements"]) == 1
    j = results["judgements"][0]
    assert j["score_on"] == 4 and j["score_off"] == 4
    assert j["judge_model"] == "judge-model"


# --------------------------------------------------------------------------- #
# 5. CLI wiring
# --------------------------------------------------------------------------- #
def test_cli_accepts_outcome_flags(monkeypatch):
    from bench import behavioral, __main__ as cli

    captured = {}

    def stub(out_dir, stamp, **kw):
        captured.update(kw)
        captured["out_dir"] = out_dir
        return {}, "md"

    monkeypatch.setattr(behavioral, "run_pilot", stub)
    rc = cli.main(["behavioral", "--workload", "outcome", "--judge", "judge-model",
                   "--seed", "3", "--repeats", "1", "--model", "m"])
    assert rc == 0
    assert captured["kind"] == "outcome"
    assert captured["judge"] == "judge-model"
    assert captured["seed"] == 3
