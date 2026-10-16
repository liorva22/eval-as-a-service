# Eval-as-a-Service: pitch

## The pitch
Teams ship LLM prompt and model changes on vibes because evaluating them is manual. EaaS turns an eval into an upload: a CSV of prompts and outputs plus a YAML rubric produces a versioned score and a dashboard comparing the new run against the old one. A CI action blocks the deploy when quality drops. In the demo, the gate passed the good model and blocked both a weaker model and a verbosity regression that a score-only gate would have let through.

## Problem and who it's for
ML and product engineers iterating on prompts, models, or RAG pipelines. They need to answer "is v3 better than v2?" in minutes, and to stop regressions automatically, without building eval infrastructure each time.

## How it works
See the README diagram. The API validates an upload and writes a queued run, with its items, to Postgres. Workers claim runs with `FOR UPDATE SKIP LOCKED` and score each item against the rubric's checks. Deterministic checks (length, regex, banned phrases, JSON validity, exact match) are free. LLM-judge checks score 1-5 against written criteria. Results are stored per item and summarized per run, and runs are numbered per experiment, which gives the trend chart. The `eaas` CLI and the GitHub Action either score locally or record on the server, and exit non-zero below a threshold.

## Stack and design choices
- **Postgres as the queue** instead of Celery/Redis: one less service, atomic claims, state and queue in one row. *Trade-off:* polling, and an upper limit around thousands of runs per minute.
- **Typed rubric mixing cheap deterministic checks with an LLM judge**, instead of a single judge prompt: cheaper, exact where possible, and every failure names the check. *Trade-off:* rubric authors need to know which checks exist.
- **Gate on pass rate by default**, instead of the mean score. Means hide regressions: v3 scored 0.807 but only 57% of its items passed every check.
- **Single-digit judge output** instead of JSON with a rationale: cheap and robust to parse. *Trade-off:* there's no "why" stored for disagreements.
- **Static dashboard** instead of a SPA: zero build, and the API is the product.

## What I'd do differently
- **Measure the real judge.** No API key was available, so the reported agreement (90% accuracy, κ = 0.76 on 60 hand-labeled items) is for the *mock lexical judge*. Notably, it's no better than a "contains the reference" string check (90%, κ = 0.77). That's the point: lexical judges fail on paraphrases ("eight bits" vs "8") and pass near-misses ("Read-only Access Memory"). `python eval/judge_agreement.py` with a key measures Claude on the same 60 items.
- **More, and independent, human labels.** 60 labels from one annotator (me) on short factual QA is a smoke test, not a validation. I'd use 2+ annotators, inter-annotator κ, and longer-form tasks where judges really diverge.
- **Store judge rationales and enable caching.** The rubric prefix is identical across items, so prompt caching would cut judge cost. Rationales make disagreements debuggable.
- **Statistical comparisons.** Bootstrap confidence intervals on the v-new minus v-old delta, so a 1-point change on 30 items isn't treated as signal.
- **Auth and multi-tenancy.** None exist today; anyone who can reach the API can upload.

## Interview talking points
- Why pass rate beats mean score as a gate, shown with the v3 verbosity regression.
- Judge validation: why I compare against trivial baselines (exact match, contains) and why the mock judge's κ = 0.76 isn't a win.
- Postgres `SKIP LOCKED` as a queue: when it's enough and when to move to a broker.
- A real race I hit (concurrent `CREATE TABLE IF NOT EXISTS`) and the advisory-lock fix.
