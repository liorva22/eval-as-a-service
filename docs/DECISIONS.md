# Design decisions

| # | Decision | Alternatives | Why |
|---|----------|--------------|-----|
| 1 | **Postgres is the job queue** (`FOR UPDATE SKIP LOCKED`) | Celery + Redis, RQ, SQS | One fewer service to run. Claims are atomic, and multiple workers scale horizontally. A run's state and its queue entry live in the same row, so they can't disagree. Swap it out once throughput reaches thousands of runs/minute. |
| 2 | **Separate worker process** instead of FastAPI background tasks | `BackgroundTasks` | Judge calls are slow, and a 5,000-row run must survive API restarts and deploys. Background tasks die with the request process. |
| 3 | **Rubric = YAML list of typed checks**, with deterministic and LLM-judge checks mixed freely | One free-form judge prompt per rubric | Deterministic checks are free, instant, and exact for format and policy rules (length, banned phrases, JSON). Reserving the judge for semantics keeps costs down and makes failures attributable to a named check. |
| 4 | **Item passes only if every check passes; score = weighted mean** | Score only | Weighted means hide regressions. In the demo, v3 kept a score of 0.807 (above a 0.80 gate) while its pass rate fell from 90% to 57%. The gate supports both metrics and defaults to `pass_rate`. |
| 5 | **Versions are per-experiment integers** assigned in the insert, guarded by `unique(experiment_id, version)` | Timestamps; client-supplied versions | "v3 vs v2" is how people talk about it. The unique constraint turns the rare concurrent-upload race into a retryable error instead of a duplicate version. |
| 6 | **Judge returns one digit (1-5) and passes at ≥ 4** | JSON with rationale; binary yes/no | A single digit is cheap and easy to parse. A 1-5 scale keeps more signal than binary for trend charts. The rationale isn't stored, which is a known gap (see PITCH). |
| 7 | **Mock judge = reference-token recall** | Random scores; constant 5 | It's a real, deterministic lexical baseline, so mock-mode agreement numbers measure *something*. The README reports them as the mock judge's numbers, not Claude's. |
| 8 | **CLI scores locally by default; `--server` records history** | Server-only | The GitHub Action works with zero infrastructure. Teams that run the server also get trends. |
| 9 | **Static HTML + Chart.js dashboard served by the API** | React/Next.js app | One file, no build step. The dashboard only reads the JSON API. |
| 10 | **Advisory lock around schema creation** | Migrations tool (Alembic) | The API and workers start at the same moment. Concurrent `CREATE TABLE IF NOT EXISTS` raced and crashed the API during development. Three tables don't justify a migration framework yet. |
| 11 | **Upload limits at the boundary**: 5 MB, 5,000 rows, required columns, rubric validated (including regex compilation) before anything is queued | Validate inside the worker | Bad input fails fast with a 422 the user can act on, instead of producing a failed run minutes later. |
