"""Compare prompt versions for `resolution_steps`.

Metrics come from the `metrics` field of each run JSON (computed by the CLI with
`support_assistant.metrics.resolution_steps_metrics`). Violations already depend on the
customer profile: jargon only counts for `leigo`, URLs/IPs/commands only on the
`telefone` channel (POL-05), steps that are questions always count. Old runs without
the field are recomputed by `compare_common.run_metrics`.

Usage (from the repo root):
    python scripts/compare_resolution_steps.py
    python scripts/compare_resolution_steps.py --scenarios c04:t01 --versions v1,v3
    python scripts/compare_resolution_steps.py --repeats 3 --extra "--no-cache"
"""
import sys

from compare_common import main

if __name__ == "__main__":
    sys.exit(main("resolution_steps"))
