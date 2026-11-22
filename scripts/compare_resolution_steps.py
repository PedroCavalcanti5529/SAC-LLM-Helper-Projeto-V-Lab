"""Compare prompt versions for `resolution_steps`.

The metrics only see the output, not the customer profile, so read them
together with the scenario: jargon hits matter for `leigo`, and URLs, IPs
or commands matter for the `telefone` channel (POL-05).

The step list is found in `steps` if present, otherwise in the first list
field of the output. Each step may be a string or an object.

Usage (from the repo root):
    python scripts/compare_resolution_steps.py
    python scripts/compare_resolution_steps.py --scenarios c04:t01 --versions v1,v3
    python scripts/compare_resolution_steps.py --repeats 3 --extra "--no-cache"
"""
import re
import sys

from compare_common import kb_ids, main

# terms the base layer forbids for `leigo`
JARGON = ("ONT", "PON", "LOS", "DNS", "IP", "LAN", "GHz", "ping", "traceroute", "firmware")
JARGON_RE = re.compile(r"\b(" + "|".join(map(re.escape, JARGON)) + r")\b", re.IGNORECASE)
URL_RE = re.compile(r"https?://\S+|www\.\S+|\b\d{1,3}(?:\.\d{1,3}){3}\b")
COMMAND_RE = re.compile(r"\b(ping|traceroute|tracert|ipconfig|nslookup)\s+\S+", re.IGNORECASE)


def _strings(value):
    """Yield every string inside a nested JSON value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _steps(output: dict) -> list:
    if isinstance(output.get("steps"), list):
        return output["steps"]
    return next((v for v in output.values() if isinstance(v, list)), [])


def metrics(output: dict) -> dict:
    steps = _steps(output)
    step_texts = [" ".join(_strings(s)) for s in steps]
    words = [len(t.split()) for t in step_texts]
    full_text = " ".join(_strings(output))
    ids = kb_ids(output)

    return {
        "n_steps": len(steps),
        "avg_words": round(sum(words) / len(words), 1) if words else 0,
        "max_words": max(words, default=0),
        "jargon": sorted({m.upper() for m in JARGON_RE.findall(full_text)}),
        "urls_ips": len(URL_RE.findall(full_text)),
        "commands": len(COMMAND_RE.findall(full_text)),
        "escalation": any(i.startswith("ESC-") for i in ids),
        "kb_ids": ids,
    }


if __name__ == "__main__":
    sys.exit(main("resolution_steps", metrics))
