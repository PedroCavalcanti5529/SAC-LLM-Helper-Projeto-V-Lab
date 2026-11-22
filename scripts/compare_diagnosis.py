"""Compare prompt versions for `diagnosis`.

Metrics come from the `metrics` field of each run JSON (computed by the CLI with
`support_assistant.metrics.diagnosis_metrics`): hypotheses, evidence, missing_info,
likelihood distribution, cited KB ids and escalation. Old runs without the field are
recomputed by `compare_common.run_metrics`.

Usage (from the repo root):
    python scripts/compare_diagnosis.py
    python scripts/compare_diagnosis.py --scenarios c04:t01 --versions v1,v3
    python scripts/compare_diagnosis.py --repeats 3 --extra "--no-cache"
"""
import sys

from compare_common import main

if __name__ == "__main__":
    sys.exit(main("diagnosis"))
