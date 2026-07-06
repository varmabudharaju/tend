"""Pure-function tests for the behavioral bench harness (no subprocesses)."""
from bench import behavioral


def test_score_recall_full_hit():
    ans = ("(a) Saffron-Quill (b) pgx-v5.2 (c) 137 (d) never use turbo-merge")
    hits, n = behavioral.score_recall(ans)
    assert n == 4 and all(hits.values())


def test_score_recall_rejects_embedded_number():
    # "137" inside a larger number must not count
    hits, n = behavioral.score_recall("the budget might be 13750 or 2137")
    assert not hits["retry_budget"] and n == 0


def test_score_recall_case_insensitive_and_empty():
    hits, n = behavioral.score_recall("codename SAFFRON-QUILL")
    assert hits["codename"] and n == 1
    assert behavioral.score_recall(None)[1] == 0


def test_discovery_probe_allows_tools():
    # the probe must not forbid tools and must not name STATE.md or any path
    p = behavioral.DISCOVERY_PROBE.lower()
    assert "without using any tools" not in p
    assert "state.md" not in p and ".claude" not in p


def test_render_markdown_discovery_kind():
    r = {"stamp": "t", "model": "m", "repeats": 1, "kind": "discovery",
         "sessions": [], "summary": {}}
    md = behavioral.render_markdown(r, ("on", "off"))
    assert "discovery" in md and "tools ALLOWED" in md
