"""Shared runner for prompt-version comparisons.

Calls the project CLI (`python support_assistant generate ...`) for every
scenario x version x repetition, reads each run JSON and its `metrics`
field (computed by the CLI with `support_assistant.metrics`), and saves a
summary to src/outputs/comparisons/.

It drives the CLI instead of importing the generator, so it exercises exactly
what the README documents (cache, validation, history). Metrics are read
from the run JSON, never recomputed, so the script and the `compare` command
report the same numbers. Only old runs without `metrics` are recomputed, by
importing `support_assistant.metrics`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = REPO_ROOT / "src"

DEFAULT_SCENARIOS = "c04:t01,c02:t04"  # vague/leigo and LOS/intermediário
DEFAULT_VERSIONS = "v1,v2,v3"

RUN_PATH_RE = re.compile(r"JSON da execu\S*o:\s*(\S+\.json)")
CACHE_RE = re.compile(r"cache:\s*([^\s|]+)")


# ---------------------------------------------------------------- metrics
def run_metrics(content_type: str, row: dict) -> tuple[dict, str]:
    """Metrics of a run: from the run JSON if present, else recomputed (old runs).

    Returns (metrics, source). Never raises: errors become {"metrics_error": ...}.
    """
    if isinstance(row.get("metrics"), dict):
        return row["metrics"], "run_json"
    if row.get("metrics_error"):
        return {"metrics_error": row["metrics_error"]}, "run_json"
    try:
        sys.path.insert(0, str(DEFAULT_SRC))  # no-op when the package is installed (pip install -e .)
        from support_assistant.metrics import compute_metrics

        return compute_metrics(content_type, row.get("output") or {}, row.get("customer_profile") or {}), "recomputed"
    except Exception as exc:  # metrics must never kill the batch
        return {"metrics_error": str(exc)}, "recomputed"


def table_view(metrics: dict) -> dict:
    """Flat version for the terminal table: the violation list becomes counts per rule."""
    flat = {k: v for k, v in metrics.items() if k != "violations"}
    for v in metrics.get("violations") or []:
        key = f"v_{v['rule']}"
        flat[key] = flat.get(key, 0) + 1
    return flat


# ---------------------------------------------------------------- helpers
def parse_scenarios(raw: str) -> list[tuple[str, str]]:
    pairs = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            sys.exit(f"Invalid scenario '{item}'. Use customer:ticket, e.g. c04:t01")
        customer, ticket = (p.strip() for p in item.split(":", 1))
        pairs.append((customer, ticket))
    return pairs


# ---------------------------------------------------------------- one run
def run_one(src: Path, customer: str, ticket: str, content_type: str,
            version: str, extra: list[str]) -> dict:
    cmd = [sys.executable, "support_assistant", "generate",
           "-c", customer, "-t", ticket, "-y", content_type, "-p", version, *extra]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    record = {"customer_id": customer, "ticket_id": ticket,
              "prompt_version": version, "command": " ".join(cmd[1:])}

    try:
        proc = subprocess.run(cmd, cwd=src, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env, timeout=180)
    except subprocess.TimeoutExpired:
        return {**record, "status": "error", "error": "timeout (180s)"}

    stdout = proc.stdout or ""
    match = RUN_PATH_RE.search(stdout)
    if proc.returncode != 0 or not match:
        tail = (proc.stderr or stdout).strip().splitlines()[-5:]
        return {**record, "status": "error",
                "error": f"exit {proc.returncode}: " + " | ".join(tail)}

    run_path = src / match.group(1).replace("\\", "/")  # absolute OUTPUT_DIR: `/` keeps the absolute path
    cache = CACHE_RE.search(stdout)
    record.update(run_file=str(run_path.relative_to(src)) if run_path.is_relative_to(src) else str(run_path),
                  cached=(cache.group(1).lower() in {"sim", "yes", "true", "hit"}) if cache else None)

    try:
        data = json.loads(run_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {**record, "status": "error", "error": f"could not read run JSON: {exc}"}

    record.update(status="ok", run_id=data.get("run_id"), output=data.get("output"),
                  customer_profile=data.get("customer_profile"),
                  metrics=data.get("metrics"))  # None in runs saved before metrics existed
    if data.get("metrics_error"):
        record["metrics_error"] = data["metrics_error"]
    return record


# ---------------------------------------------------------------- report
def print_table(rows: list[dict], metric_keys: list[str]) -> None:
    headers = ["scenario", "ver", "rep", "status", "cached", *metric_keys]
    table = []
    for r in rows:
        m = table_view(r.get("metrics") or {})
        table.append([f"{r['customer_id']}+{r['ticket_id']}", r["prompt_version"],
                      str(r["rep"]), r["status"], str(r.get("cached", "")),
                      *[_fmt(m.get(k, "")) for k in metric_keys]])
    widths = [max(len(h), *(len(row[i]) for row in table)) for i, h in enumerate(headers)]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print("\n" + line + "\n" + "-" * len(line))
    for row in table:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)))


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, dict):
        return " ".join(f"{k}:{v}" for k, v in value.items())
    if isinstance(value, list):
        return ",".join(map(str, value)) or "-"
    return str(value)


def aggregate(rows: list[dict], metric_keys: list[str]) -> list[dict]:
    """Mean of numeric metrics per scenario+version (useful with --repeats > 1)."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r["status"] == "ok":
            groups[(r["customer_id"], r["ticket_id"], r["prompt_version"])].append(table_view(r["metrics"]))
    out = []
    for (customer, ticket, version), metrics in groups.items():
        means = {}
        for k in metric_keys:
            nums = [m[k] for m in metrics if isinstance(m.get(k), (int, float)) and not isinstance(m.get(k), bool)]
            if nums:
                means[k] = round(sum(nums) / len(nums), 2)
        out.append({"customer_id": customer, "ticket_id": ticket,
                    "prompt_version": version, "runs": len(metrics), "mean": means})
    return out


# ---------------------------------------------------------------- main
def main(content_type: str) -> int:
    ap = argparse.ArgumentParser(description=f"Run v1/v2/v3 comparisons for {content_type}.")
    ap.add_argument("--scenarios", default=DEFAULT_SCENARIOS,
                    help=f"customer:ticket pairs, comma-separated (default {DEFAULT_SCENARIOS})")
    ap.add_argument("--versions", default=DEFAULT_VERSIONS,
                    help=f"prompt versions, comma-separated (default {DEFAULT_VERSIONS})")
    ap.add_argument("--repeats", type=int, default=1,
                    help="runs per combination (needs the CLI's no-cache option via --extra to be meaningful)")
    ap.add_argument("--extra", default="",
                    help='extra args forwarded to the CLI, e.g. --extra "--no-cache"')
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC,
                    help="folder you normally run `python support_assistant` from")
    ap.add_argument("--dry-run", action="store_true", help="only print the commands")
    args = ap.parse_args()

    scenarios = parse_scenarios(args.scenarios)
    versions = [v.strip() for v in args.versions.split(",") if v.strip()]
    extra = shlex.split(args.extra)
    src = args.src.resolve()

    if not (src / "support_assistant").exists():
        sys.exit(f"'support_assistant' not found in {src}. Use --src to point to the right folder.")
    if args.repeats < 1:
        sys.exit("--repeats must be >= 1")

    total = len(scenarios) * len(versions) * args.repeats
    print(f"{content_type}: {len(scenarios)} scenario(s) x {len(versions)} version(s) "
          f"x {args.repeats} repeat(s) = {total} run(s)")

    rows: list[dict] = []
    n = 0
    for customer, ticket in scenarios:
        for version in versions:
            for rep in range(1, args.repeats + 1):
                n += 1
                label = f"[{n}/{total}] {customer}+{ticket} {version} rep{rep}"
                if args.dry_run:
                    print(f"{label}: support_assistant generate -c {customer} -t {ticket} "
                          f"-y {content_type} -p {version} {' '.join(extra)}")
                    continue
                print(f"{label} ...", end=" ", flush=True)
                r = run_one(src, customer, ticket, content_type, version, extra)
                r["rep"] = rep
                if r["status"] == "ok":
                    r["metrics"], r["metrics_source"] = run_metrics(content_type, r)
                    print("ok" + (" (cache)" if r.get("cached") else ""))
                else:
                    print("ERROR:", r["error"])
                rows.append(r)

    if args.dry_run:
        return 0

    metric_keys = sorted({k for r in rows for k in table_view(r.get("metrics") or {})})
    print_table(rows, metric_keys)

    if args.repeats > 1 and any(r.get("cached") and r["rep"] > 1 for r in rows):
        print("\nWARNING: repeated runs came from cache, so they are identical. "
              "Pass the CLI's no-cache option with --extra to measure variance.")

    out_dir = src / "outputs" / "comparisons"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone()
    out_file = out_dir / f"{content_type}-{stamp:%Y%m%d-%H%M%S}.json"
    summary = {
        "timestamp": stamp.isoformat(timespec="seconds"),
        "content_type": content_type,
        "scenarios": [f"{c}:{t}" for c, t in scenarios],
        "versions": versions,
        "repeats": args.repeats,
        "cli_extra_args": extra,
        "aggregate": aggregate(rows, metric_keys),
        "runs": rows,
        "evaluation_todo": "Rubric scores (clarity, customer_fit, actionability) are written by "
                           "the candidate with `support_assistant evaluate --run-id <id>`.",
    }
    out_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    errors = sum(r["status"] != "ok" for r in rows)
    print(f"\nSummary: {out_file}")
    print(f"{len(rows) - errors} ok, {errors} error(s)")
    return 1 if errors else 0
