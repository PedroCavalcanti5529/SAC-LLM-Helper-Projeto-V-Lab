"""Compare prompt versions for `flow_summary`.

Metrics come from the `metrics` field of each run JSON (computed by the CLI with
`support_assistant.metrics.flow_summary_metrics`, which reuses `models.analyze_flow`):
decisions, depth, leaves with ref, cited KB ids, escalation, and the quality violations
(yes/no questions, procedure leaves). Structural validity is guaranteed by the CLI
validation, so every run that reaches the script is a valid tree. Old runs without the
field are recomputed by `compare_common.run_metrics`.

Usage (from the repo root):
    python scripts/compare_flow_summary.py
    python scripts/compare_flow_summary.py --scenarios c02:t04 --versions v2,v3
    python scripts/compare_flow_summary.py --repeats 3 --extra "--no-cache"
"""
import sys

from compare_common import main

if __name__ == "__main__":
    sys.exit(main("flow_summary"))
