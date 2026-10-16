"""Postgres storage. Also the job queue: the worker claims queued runs with FOR UPDATE SKIP LOCKED."""

import os

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

SCHEMA = """
create table if not exists experiments (
    id bigserial primary key,
    name text unique not null,
    created_at timestamptz not null default now()
);
create table if not exists runs (
    id bigserial primary key,
    experiment_id bigint not null references experiments(id) on delete cascade,
    version int not null,
    model_label text not null default '',
    status text not null default 'queued' check (status in ('queued', 'running', 'done', 'failed')),
    rubric jsonb not null,
    summary jsonb,
    error text,
    created_at timestamptz not null default now(),
    finished_at timestamptz,
    unique (experiment_id, version)
);
create table if not exists items (
    id bigserial primary key,
    run_id bigint not null references runs(id) on delete cascade,
    idx int not null,
    data jsonb not null,
    result jsonb
);
create index if not exists items_run_idx on items (run_id, idx);
"""


def connect(dsn: str | None = None):
    conn = psycopg.connect(dsn or os.environ["DATABASE_URL"], autocommit=True, row_factory=dict_row)
    with conn.transaction():  # API and workers start together; concurrent CREATE IF NOT EXISTS can still collide
        conn.execute("select pg_advisory_xact_lock(4242)")
        conn.execute(SCHEMA)
    return conn


def create_run(conn, experiment: str, model_label: str, rubric: dict, rows: list[dict]) -> dict:
    with conn.transaction():
        exp = conn.execute(
            "insert into experiments (name) values (%s) on conflict (name) do update set name = excluded.name returning id",
            (experiment,),
        ).fetchone()
        # ponytail: two simultaneous uploads to one experiment can collide on (experiment_id, version);
        # the unique constraint turns that into an error for the client to retry rather than a silent dupe.
        run = conn.execute(
            "insert into runs (experiment_id, version, model_label, rubric)"
            " select %s, coalesce(max(version), 0) + 1, %s, %s from runs where experiment_id = %s"
            " returning id, version, status",
            (exp["id"], model_label, Jsonb(rubric), exp["id"]),
        ).fetchone()
        with conn.cursor() as cur:
            cur.executemany(
                "insert into items (run_id, idx, data) values (%s, %s, %s)",
                [(run["id"], i, Jsonb(r)) for i, r in enumerate(rows)],
            )
    return run


def claim_run(conn) -> dict | None:
    return conn.execute(
        "update runs set status = 'running' where id = ("
        "  select id from runs where status = 'queued' order by id for update skip locked limit 1"
        ") returning id, rubric"
    ).fetchone()


def run_items(conn, run_id: int, failed_only: bool = False) -> list[dict]:
    q = "select id, idx, data, result from items where run_id = %s"
    if failed_only:
        q += " and (result->>'passed')::boolean is false"
    return conn.execute(q + " order by idx", (run_id,)).fetchall()


def save_item_result(conn, item_id: int, result: dict):
    conn.execute("update items set result = %s where id = %s", (Jsonb(result), item_id))


def finish_run(conn, run_id: int, summary: dict | None = None, error: str | None = None):
    conn.execute(
        "update runs set status = %s, summary = %s, error = %s, finished_at = now() where id = %s",
        ("failed" if error else "done", Jsonb(summary) if summary else None, error, run_id),
    )


RUN_COLS = "r.id, e.name as experiment, r.version, r.model_label, r.status, r.summary, r.error, r.created_at, r.finished_at"


def get_run(conn, run_id: int) -> dict | None:
    return conn.execute(
        f"select {RUN_COLS} from runs r join experiments e on e.id = r.experiment_id where r.id = %s", (run_id,)
    ).fetchone()


def list_runs(conn, experiment: str) -> list[dict]:
    return conn.execute(
        f"select {RUN_COLS} from runs r join experiments e on e.id = r.experiment_id where e.name = %s order by r.version",
        (experiment,),
    ).fetchall()


def list_experiments(conn) -> list[dict]:
    return conn.execute(
        "select e.name, count(r.id) as runs, max(r.version) as latest_version from experiments e"
        " left join runs r on r.experiment_id = e.id group by e.id order by e.name"
    ).fetchall()
