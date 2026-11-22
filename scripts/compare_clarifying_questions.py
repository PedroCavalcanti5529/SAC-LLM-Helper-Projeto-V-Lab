"""Compare prompt versions for `clarifying_questions`.

Usage (from the repo root):
    python scripts/compare_clarifying_questions.py
    python scripts/compare_clarifying_questions.py --scenarios c04:t01 --versions v1,v3
    python scripts/compare_clarifying_questions.py --repeats 3 --extra "--no-cache"
"""
import sys

from compare_common import kb_ids, main

MAX_QUESTIONS = 5  # limit defined in the v3 task


def metrics(output: dict) -> dict:
    questions = output.get("questions") or []
    known = output.get("already_known") or []
    texts = [str(q.get("question", "")) for q in questions]
    priorities = [q.get("priority") for q in questions]

    return {
        "n_questions": len(questions),
        "n_known": len(known),
        # more than one "?" in one item = two questions joined together
        "double_q": sum(t.count("?") > 1 for t in texts),
        "over_limit": len(questions) > MAX_QUESTIONS,
        "prio_ok": priorities == list(range(1, len(questions) + 1)),
        "kb_ids": kb_ids([q.get("purpose", "") for q in questions]),
    }


if __name__ == "__main__":
    sys.exit(main("clarifying_questions", metrics))
