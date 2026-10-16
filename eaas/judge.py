"""LLM-as-judge. Live: Claude scores 1-5. Mock: reference-token recall mapped to 1-5 (a lexical baseline)."""

import os
import re

JUDGE_MODEL = os.getenv("JUDGE_MODEL", "claude-sonnet-5-5")
# USD per million tokens for JUDGE_MODEL (Sonnet 5.5 list price). Override together with JUDGE_MODEL.
PRICE_IN = float(os.getenv("JUDGE_PRICE_IN", "2.0"))
PRICE_OUT = float(os.getenv("JUDGE_PRICE_OUT", "10.0"))

SYSTEM = (
    "You are a strict evaluation judge. Score the OUTPUT against the CRITERIA on a 1-5 scale: "
    "5 = fully meets the criteria, 4 = meets it with minor issues, 3 = partially, 2 = mostly fails, 1 = fails. "
    "Use the REFERENCE as ground truth when one is given. Reply with the digit only."
)
STOP = set("a an the of in on at to is are was were be it its for and or by with from as that this which".split())


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if t not in STOP}


class MockJudge:
    name = "mock-token-recall"

    def score(self, criteria: str, item: dict) -> tuple[int, float]:
        ref = _tokens(item.get("reference", "") or "")
        if not ref:
            return 3, 0.0
        recall = len(ref & _tokens(item.get("output", "") or "")) / len(ref)
        return 1 + round(4 * recall), 0.0


class ClaudeJudge:
    name = JUDGE_MODEL

    def __init__(self):
        import anthropic

        self.client = anthropic.Anthropic()

    def score(self, criteria: str, item: dict) -> tuple[int, float]:
        user = f"CRITERIA:\n{criteria}\n\nPROMPT:\n{item.get('prompt', '')}\n\n"
        if item.get("reference"):
            user += f"REFERENCE:\n{item['reference']}\n\n"
        user += f"OUTPUT:\n{item.get('output', '')}"
        resp = self.client.beta.messages.create(
            model=JUDGE_MODEL,
            max_tokens=1024,
            system=SYSTEM,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        m = re.search(r"[1-5]", text)
        cost = (resp.usage.input_tokens * PRICE_IN + resp.usage.output_tokens * PRICE_OUT) / 1e6
        return (int(m.group()) if m else 1), cost


def make_judge():
    return MockJudge() if os.getenv("MOCK_MODE", "0") == "1" else ClaudeJudge()
