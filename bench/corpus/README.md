# Frozen benchmark corpus

22 real tool outputs that tend offloaded in the author's production Claude Code
sessions (June–July 2026), frozen here so `python3 -m bench mechanical`
reproduces the same numbers for everyone. Scrubbed before committing: home paths
and the username normalized to `user`, emails to `redacted@example.com`,
anything key-shaped to `[REDACTED-*]` (enforced by `tests/test_bench_corpus.py`);
one settings-dump output and one synthetic smoke artifact were dropped in review.
Sizes and structure are otherwise untouched — these are the outputs exactly as
tend saw them. To benchmark against your own history instead:
`python3 -m bench mechanical --live-corpus`.
