"""Rubric parsing and deterministic checks. A rubric is YAML/JSON: {"checks": [{"name", "type", ...}]}."""

import json
import re

import yaml

DETERMINISTIC = {"contains", "not_contains", "regex", "max_length", "min_length", "json_valid", "exact_match"}
TYPES = DETERMINISTIC | {"llm_judge"}


class RubricError(ValueError):
    pass


def parse_rubric(text: str) -> dict:
    try:
        rubric = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise RubricError(f"invalid YAML/JSON: {e}") from e
    checks = rubric.get("checks") if isinstance(rubric, dict) else None
    if not checks or not isinstance(checks, list):
        raise RubricError("rubric needs a non-empty 'checks' list")
    names = set()
    for c in checks:
        if not isinstance(c, dict) or c.get("type") not in TYPES or not c.get("name"):
            raise RubricError(f"each check needs a name and a type in {sorted(TYPES)}: {c!r}")
        if c["name"] in names:
            raise RubricError(f"duplicate check name {c['name']!r}")
        names.add(c["name"])
        if c["type"] in {"contains", "not_contains", "regex", "max_length", "min_length"} and "value" not in c:
            raise RubricError(f"check {c['name']!r} needs a 'value'")
        if c["type"] == "regex":
            try:
                re.compile(c["value"])
            except re.error as e:
                raise RubricError(f"check {c['name']!r}: bad regex: {e}") from e
        if c["type"] == "llm_judge" and not c.get("criteria"):
            raise RubricError(f"check {c['name']!r} needs 'criteria'")
        c.setdefault("weight", 1.0)
    return {"checks": checks}


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def run_deterministic(check: dict, item: dict) -> bool:
    out = item.get("output", "") or ""
    t, v = check["type"], check.get("value")
    if t == "contains":
        return _norm(str(v)) in _norm(out)
    if t == "not_contains":
        return _norm(str(v)) not in _norm(out)
    if t == "regex":
        return re.search(v, out) is not None
    if t == "max_length":
        return len(out) <= int(v)
    if t == "min_length":
        return len(out) >= int(v)
    if t == "json_valid":
        try:
            json.loads(out)
            return True
        except ValueError:
            return False
    if t == "exact_match":
        return _norm(out) == _norm(item.get("reference", "") or "")
    raise RubricError(f"not a deterministic check: {t}")
