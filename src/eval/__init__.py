"""External-benchmark evaluation helpers (v5).

Converters that normalize third-party public safety datasets into the corpus
JSONL schema the committee harness already reads, so `src/revote.py` can run the
committee-as-classifier over them (no generation — the dataset's own response is
the fixed `candidate`). See docs/external-benchmarks-plan.md / docs/v5-results.md.
"""
