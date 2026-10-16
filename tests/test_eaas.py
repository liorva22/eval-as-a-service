import os
from pathlib import Path

import pytest

from eaas.cli import main as cli
from eaas.judge import MockJudge
from eaas.rubric import RubricError, parse_rubric, run_deterministic
from eaas.scoring import CSVError, parse_csv, score_item, summarize

EX = Path(__file__).resolve().parent.parent / "examples"
os.environ["MOCK_MODE"] = "1"


def test_rubric_validation():
    with pytest.raises(RubricError):
        parse_rubric("checks: []")
    with pytest.raises(RubricError):
        parse_rubric("checks: [{name: x, type: nope}]")
    with pytest.raises(RubricError):
        parse_rubric("checks: [{name: x, type: regex, value: '('}]")
    with pytest.raises(RubricError):
        parse_rubric("checks: [{name: x, type: max_length, value: 3}, {name: x, type: json_valid}]")
    assert parse_rubric('{"checks": [{"name": "j", "type": "json_valid"}]}')["checks"][0]["weight"] == 1.0


@pytest.mark.parametrize(
    "check,output,expected",
    [
        ({"type": "contains", "value": "Paris"}, "it is  paris.", True),
        ({"type": "not_contains", "value": "as an AI"}, "As an AI, I think", False),
        ({"type": "regex", "value": r"^\d+$"}, "42", True),
        ({"type": "max_length", "value": 3}, "abcd", False),
        ({"type": "min_length", "value": 3}, "abcd", True),
        ({"type": "json_valid"}, '{"a": 1}', True),
        ({"type": "json_valid"}, "{a: 1}", False),
        ({"type": "exact_match"}, " Canberra ", True),
    ],
)
def test_deterministic_checks(check, output, expected):
    assert run_deterministic(check, {"output": output, "reference": "canberra"}) is expected


def test_mock_judge_is_reference_recall():
    j = MockJudge()
    assert j.score("", {"reference": "Canberra", "output": "Canberra is the capital."})[0] == 5
    assert j.score("", {"reference": "Canberra", "output": "Sydney."})[0] == 1
    assert j.score("", {"reference": "Random Access Memory", "output": "Random Memory"})[0] == 4


def test_score_item_weights_and_pass():
    rubric = parse_rubric(
        "checks: [{name: c, type: llm_judge, criteria: x, pass_at: 4, weight: 3}, {name: short, type: max_length, value: 5}]"
    )
    r = score_item(rubric, {"reference": "Canberra", "output": "Canberra is the capital"}, MockJudge())
    assert r["checks"]["c"]["passed"] and not r["checks"]["short"]["passed"]
    assert r["score"] == pytest.approx(0.75) and r["passed"] is False
    s = summarize(rubric, [r, r])
    assert s["n"] == 2 and s["checks"]["short"]["pass_rate"] == 0 and s["score"] == pytest.approx(0.75)


def test_csv_validation():
    with pytest.raises(CSVError):
        parse_csv("prompt,answer\nx,y\n")
    with pytest.raises(CSVError):
        parse_csv("prompt,output\n")
    assert parse_csv("prompt,output\nhi,there\n") == [{"prompt": "hi", "output": "there"}]


def test_cli_gate_exit_codes():
    args = ["run", "--rubric", str(EX / "rubric.yaml"), "--threshold", "0.8"]
    assert cli(args + ["--csv", str(EX / "qa_v2.csv")]) == 0
    assert cli(args + ["--csv", str(EX / "qa_v1.csv")]) == 1


def test_judge_agreement_math():
    import sys

    sys.path.insert(0, str(EX.parent / "eval"))
    from judge_agreement import agreement, cohen_kappa

    assert cohen_kappa([1, 0, 1, 0], [1, 0, 1, 0]) == 1.0
    assert cohen_kappa([1, 1, 0, 0], [1, 0, 1, 0]) == 0.0
    a = agreement([1, 1, 0, 0], [1, 0, 0, 1])
    assert a["confusion"] == {"tp": 1, "fp": 1, "fn": 1, "tn": 1} and a["false_pass_rate"] == 0.5


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="needs Postgres")
def test_upload_worker_and_results_roundtrip():
    from fastapi.testclient import TestClient

    from eaas import db
    from eaas.api import create_app
    from eaas.worker import process_one

    client = TestClient(create_app())
    conn = db.connect()
    conn.execute("delete from experiments where name = 'pytest-exp'")
    rubric = (EX / "rubric.yaml").read_text()

    bad = client.post("/api/experiments/pytest-exp/runs", files={"file": ("x.csv", b"a,b\n1,2\n")}, data={"rubric": rubric})
    assert bad.status_code == 422

    ids = []
    for v in ("v1", "v2"):
        r = client.post(
            "/api/experiments/pytest-exp/runs",
            files={"file": (f"{v}.csv", (EX / f"qa_{v}.csv").read_bytes())},
            data={"rubric": rubric, "model_label": v},
        )
        assert r.status_code == 201 and r.json()["status"] == "queued"
        ids.append(r.json()["id"])
    while process_one(conn, MockJudge()):
        pass

    runs = client.get("/api/experiments/pytest-exp/runs").json()
    assert [r["version"] for r in runs] == [1, 2] and all(r["status"] == "done" for r in runs)
    assert runs[1]["summary"]["score"] > runs[0]["summary"]["score"]
    failed = client.get(f"/api/runs/{ids[0]}/items", params={"failed": True}).json()
    assert failed and all(not i["result"]["passed"] for i in failed)
    assert client.get("/api/runs/999999999").status_code == 404
