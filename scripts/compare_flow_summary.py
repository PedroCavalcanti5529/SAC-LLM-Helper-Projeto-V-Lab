"""Compare prompt versions for `flow_summary`.

Metrics come from the decision-tree schema and reuse the project validation
(`support_assistant.models.analyze_flow`), so the script and the CLI agree on
what a broken tree is.

Usage (from the repo root):
    python scripts/compare_flow_summary.py
    python scripts/compare_flow_summary.py --scenarios c02:t04 --versions v2,v3
    python scripts/compare_flow_summary.py --repeats 3 --extra "--no-cache"
"""
import sys
from pathlib import Path

from compare_common import REPO_ROOT, main

sys.path.insert(0, str(REPO_ROOT / "src"))
from support_assistant.models import analyze_flow, load_kb_ids  # noqa: E402

KB_IDS = load_kb_ids(Path(REPO_ROOT) / "data" / "domains" / "wifi_isp.json")


def metrics(output: dict) -> dict:
    report = analyze_flow(output, KB_IDS)
    return {
        "decisions": report.decisions,
        "depth": report.depth,
        "leaves": report.leaves,
        "leaves_with_ref": report.leaves_with_ref,
        "invalid_questions": len(report.invalid_questions),
        "unreachable": len(report.unreachable),
        "broken_exits": len(report.broken_exits),
        "unknown_refs": len(report.unknown_refs),
        "procedure_leaves": len(report.procedure_refs),
        "cycle": bool(report.cycle),
        "valid": not report.problems(),
    }


if __name__ == "__main__":
    sys.exit(main("flow_summary", metrics))
