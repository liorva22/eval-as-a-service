"""Score items against a rubric and summarize a run. Pure functions: used by the worker and by `eaas run --local`."""

import csv
import io

from .rubric import run_deterministic

MAX_ROWS = 5000


class CSVError(ValueError):
    pass


def parse_csv(text: str) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise CSVError("CSV has no rows")
    missing = {"prompt", "output"} - set(rows[0])
    if missing:
        raise CSVError(f"CSV is missing required columns: {sorted(missing)}")
    if len(rows) > MAX_ROWS:
        raise CSVError(f"CSV has {len(rows)} rows; limit is {MAX_ROWS}")
    return rows


def score_item(rubric: dict, item: dict, judge) -> dict:
    """Returns {"checks": {name: {"score", "passed", ...}}, "score": weighted mean, "passed": all checks passed, "cost"}."""
    checks, cost = {}, 0.0
    for c in rubric["checks"]:
        if c["type"] == "llm_judge":
            s, cst = judge.score(c["criteria"], item)
            cost += cst
            checks[c["name"]] = {"score": (s - 1) / 4, "passed": s >= c.get("pass_at", 4), "raw": s}
        else:
            ok = run_deterministic(c, item)
            checks[c["name"]] = {"score": float(ok), "passed": ok}
    total_w = sum(c["weight"] for c in rubric["checks"])
    score = sum(checks[c["name"]]["score"] * c["weight"] for c in rubric["checks"]) / total_w
    return {"checks": checks, "score": score, "passed": all(v["passed"] for v in checks.values()), "cost": cost}


def summarize(rubric: dict, results: list[dict]) -> dict:
    n = len(results)
    return {
        "n": n,
        "score": sum(r["score"] for r in results) / n,
        "pass_rate": sum(r["passed"] for r in results) / n,
        "judge_cost_usd": sum(r["cost"] for r in results),
        "checks": {
            c["name"]: {
                "pass_rate": sum(r["checks"][c["name"]]["passed"] for r in results) / n,
                "mean_score": sum(r["checks"][c["name"]]["score"] for r in results) / n,
            }
            for c in rubric["checks"]
        },
    }
