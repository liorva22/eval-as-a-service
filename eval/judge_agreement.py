"""How often does the judge agree with a human? Compares judge pass/fail on the `correct` check with my hand labels.

MOCK_MODE=1 python eval/judge_agreement.py   # lexical mock judge (no keys)
python eval/judge_agreement.py               # Claude judge (~$0.05)
"""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eaas.judge import make_judge  # noqa: E402
from eaas.rubric import parse_rubric  # noqa: E402


def cohen_kappa(a: list[int], b: list[int]) -> float:
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def agreement(pred: list[int], human: list[int]) -> dict:
    tp = sum(p and h for p, h in zip(pred, human))
    fp = sum(p and not h for p, h in zip(pred, human))
    fn = sum(h and not p for p, h in zip(pred, human))
    tn = sum(not p and not h for p, h in zip(pred, human))
    return {
        "accuracy": (tp + tn) / len(human),
        "cohen_kappa": cohen_kappa(pred, human),
        "false_pass_rate": fp / max(1, fp + tn),  # wrong answers the judge let through
        "false_fail_rate": fn / max(1, fn + tp),  # correct answers the judge rejected
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
    }


def norm(s: str) -> str:
    return " ".join(s.lower().replace(".", "").split())


def main():
    ex = ROOT / "examples"
    check = next(c for c in parse_rubric((ex / "rubric.yaml").read_text())["checks"] if c["name"] == "correct")
    items = {}
    for v in ("v1", "v2"):
        for row in csv.DictReader(open(ex / f"qa_{v}.csv", encoding="utf-8")):
            items[(v, row["id"])] = row
    labels = list(csv.DictReader(open(ex / "human_labels.csv", encoding="utf-8")))
    human = [int(r["human_correct"]) for r in labels]
    rows = [items[(r["version"], r["id"])] for r in labels]

    judge, cost, judge_pass, disagreements = make_judge(), 0.0, [], []
    for r, h in zip(rows, human):
        s, c = judge.score(check["criteria"], r)
        cost += c
        p = int(s >= check["pass_at"])
        judge_pass.append(p)
        if p != h:
            disagreements.append({"id": r["id"], "output": r["output"], "reference": r["reference"], "judge": s, "human": h})

    out = {
        "judge": judge.name,
        "n": len(human),
        "human_positive_rate": sum(human) / len(human),
        "judge_cost_usd": cost,
        "llm_judge": agreement(judge_pass, human),
        "baseline_exact_match": agreement([int(norm(r["output"]) == norm(r["reference"])) for r in rows], human),
        "baseline_contains_reference": agreement([int(norm(r["reference"]) in norm(r["output"])) for r in rows], human),
        "disagreements": disagreements,
    }
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / f"agreement_{'mock' if judge.name.startswith('mock') else 'live'}.json").write_text(
        json.dumps(out, indent=2)
    )
    print(f"judge={judge.name} n={out['n']} human-correct={out['human_positive_rate']:.0%} cost=${cost:.4f}")
    print("| method | accuracy | Cohen's kappa | false-pass rate | false-fail rate |\n|---|---|---|---|---|")
    for k in ("llm_judge", "baseline_exact_match", "baseline_contains_reference"):
        a = out[k]
        name = f"judge ({judge.name})" if k == "llm_judge" else k
        print(
            f"| {name} | {a['accuracy']:.1%} | {a['cohen_kappa']:.2f} | {a['false_pass_rate']:.1%} | {a['false_fail_rate']:.1%} |"
        )
    for d in disagreements:
        print(f"  disagree {d['id']}: judge={d['judge']}/5 human={d['human']} :: {d['output'][:70]!r} vs {d['reference']!r}")


if __name__ == "__main__":
    main()
