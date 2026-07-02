"""The committed corpus must exist, be big enough to exercise offloading,
and contain nothing sensitive (this is the scrub regression gate)."""
import re
from pathlib import Path

CORPUS = Path(__file__).resolve().parent.parent / "bench" / "corpus"

FORBIDDEN = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{8,}"),
    re.compile(r"[A-Za-z0-9._%+-]+@(?!example\.com)[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"/Users/varma|varmabudharaju"),
]


def corpus_files():
    return sorted(CORPUS.glob("*.txt"))


def test_corpus_present_and_offload_sized():
    files = corpus_files()
    assert len(files) >= 5
    # at least one file above the 2500-token (~10k char) offload threshold
    assert any(f.stat().st_size > 2500 * 4 for f in files)


def test_corpus_contains_no_secrets():
    for f in corpus_files():
        text = f.read_text(encoding="utf-8", errors="replace")
        for pat in FORBIDDEN:
            assert not pat.search(text), f"{f.name} matches {pat.pattern}"


def test_load_real_corpus_reads_frozen_dir():
    from bench import mechanical
    items = mechanical.load_real_corpus()
    assert len(items) >= 5
    assert all(name.startswith("real:") for name, _ in items)
