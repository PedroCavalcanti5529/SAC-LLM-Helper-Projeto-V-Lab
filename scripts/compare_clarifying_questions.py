"""Compare prompt versions for `clarifying_questions`.

Metrics come from the `metrics` field of each run JSON (computed by the CLI with
`support_assistant.metrics.clarifying_questions_metrics`): questions, already_known,
double questions, over the 5-question limit, sequential priorities, cited KB ids.
Old runs without the field are recomputed by `compare_common.run_metrics`.

Usage (from the repo root):
    python scripts/compare_clarifying_questions.py
    python scripts/compare_clarifying_questions.py --scenarios c04:t01 --versions v1,v3
    python scripts/compare_clarifying_questions.py --repeats 3 --extra "--no-cache"
"""
import sys

from compare_common import main

if __name__ == "__main__":
    sys.exit(main("clarifying_questions"))
