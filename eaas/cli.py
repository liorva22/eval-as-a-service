"""`eaas run`: score a CSV against a rubric (locally or via the server) and fail when below a threshold."""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

from .judge import make_judge
from .rubric import parse_rubric
from .scoring import parse_csv, score_item, summarize


def run_local(csv_text: str, rubric_text: str) -> dict:
    rubric, judge = parse_rubric(rubric_text), make_judge()
    return summarize(rubric, [score_item(rubric, item, judge) for item in parse_csv(csv_text)])


def run_remote(server: str, experiment: str, label: str, csv_path: Path, rubric_text: str, timeout: float) -> dict:
    with httpx.Client(base_url=server, timeout=30) as http:
        r = http.post(
            f"/api/experiments/{experiment}/runs",
            files={"file": (csv_path.name, csv_path.read_bytes(), "text/csv")},
            data={"rubric": rubric_text, "model_label": label},
        )
        r.raise_for_status()
        run = r.json()
        print(f"queued run {run['id']} ({experiment} v{run['version']})", file=sys.stderr)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            run = http.get(f"/api/runs/{run['id']}").json()
            if run["status"] == "done":
                return run["summary"] | {"run_id": run["id"], "version": run["version"]}
            if run["status"] == "failed":
                raise SystemExit(f"run failed: {run['error']}")
            time.sleep(1)
    raise SystemExit(f"timed out after {timeout}s waiting for run {run['id']}")


def report(summary: dict, metric: str, threshold: float) -> str:
    lines = [
        "| check | pass rate | mean score |",
        "|---|---|---|",
        *[f"| {n} | {c['pass_rate']:.1%} | {c['mean_score']:.3f} |" for n, c in summary["checks"].items()],
        "",
        f"**score {summary['score']:.3f} | pass rate {summary['pass_rate']:.1%} | n={summary['n']}** "
        f"| gate: {metric} {summary[metric]:.3f} {'>=' if summary[metric] >= threshold else '<'} {threshold}",
    ]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="eaas")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="score a CSV and gate on a threshold")
    r.add_argument("--csv", required=True, type=Path)
    r.add_argument("--rubric", required=True, type=Path)
    r.add_argument("--threshold", type=float, default=0.0)
    r.add_argument("--metric", choices=["score", "pass_rate"], default="score")
    r.add_argument("--server", default=os.getenv("EAAS_SERVER"), help="record the run on a server (default: local)")
    r.add_argument("--experiment", default="default")
    r.add_argument("--model-label", default="")
    r.add_argument("--timeout", type=float, default=600)
    r.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = ap.parse_args(argv)

    rubric_text = args.rubric.read_text(encoding="utf-8")
    if args.server:
        summary = run_remote(args.server, args.experiment, args.model_label, args.csv, rubric_text, args.timeout)
    else:
        summary = run_local(args.csv.read_text(encoding="utf-8-sig"), rubric_text)

    text = report(summary, args.metric, args.threshold)
    print(json.dumps(summary, indent=2) if args.json else text)
    if step_summary := os.getenv("GITHUB_STEP_SUMMARY"):
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write(f"### Eval gate: `{args.csv}`\n\n{text}\n")
    if summary[args.metric] < args.threshold:
        print(f"FAIL: {args.metric} {summary[args.metric]:.3f} < threshold {args.threshold}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
