"""Compare prompt versions for `diagnosis`.

Expected output fields (CLAUDE.md, RN03): hypotheses, evidence, missing_info,
probable_conclusion. Missing fields are reported, not treated as a crash.

Usage (from the repo root):
    python scripts/compare_diagnosis.py
    python scripts/compare_diagnosis.py --scenarios c04:t01 --versions v1,v3
    python scripts/compare_diagnosis.py --repeats 3 --extra "--no-cache"
"""
import sys

from compare_common import kb_ids, main

REQUIRED = ("hypotheses", "evidence", "missing_info", "probable_conclusion")


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def metrics(output: dict) -> dict:
    hypotheses = _as_list(output.get("hypotheses"))
    conclusion = output.get("probable_conclusion")

    return {
        "n_hyp": len(hypotheses),
        "n_evidence": len(_as_list(output.get("evidence"))),
        "n_missing": len(_as_list(output.get("missing_info"))),
        # absent fields; hypotheses and conclusion also count when empty
        # (an empty missing_info/evidence list is a valid answer)
        "missing_fields": [f for f in REQUIRED
                           if f not in output
                           or (f in ("hypotheses", "probable_conclusion") and not output[f])],
        "conclusion_chars": len(str(conclusion or "")),
        "kb_ids": kb_ids(output),
        "escalation": any(i.startswith("ESC-") for i in kb_ids(output)),
    }


if __name__ == "__main__":
    sys.exit(main("diagnosis", metrics))
