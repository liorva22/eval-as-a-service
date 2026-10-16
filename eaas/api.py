from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from . import db
from .rubric import RubricError, parse_rubric
from .scoring import CSVError, parse_csv

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
STATIC = Path(__file__).parent / "static"


def create_app(dsn: str | None = None) -> FastAPI:
    app = FastAPI(title="Eval-as-a-Service", version="1.0.0")
    conn = db.connect(dsn)

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(STATIC / "index.html")

    @app.get("/healthz")
    def healthz():
        conn.execute("select 1")
        return {"ok": True}

    @app.post("/api/experiments/{experiment}/runs", status_code=201)
    async def upload(experiment: str, file: UploadFile = File(...), rubric: str = Form(...), model_label: str = Form("")):
        raw = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(raw) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "CSV larger than 5 MB")
        try:
            rows = parse_csv(raw.decode("utf-8-sig"))
            parsed = parse_rubric(rubric)
        except (CSVError, RubricError, UnicodeDecodeError) as e:
            raise HTTPException(422, str(e)) from e
        return db.create_run(conn, experiment[:200], model_label[:200], parsed, rows)

    @app.get("/api/experiments")
    def experiments():
        return db.list_experiments(conn)

    @app.get("/api/experiments/{experiment}/runs")
    def runs(experiment: str):
        return db.list_runs(conn, experiment)

    @app.get("/api/runs/{run_id}")
    def run(run_id: int):
        r = db.get_run(conn, run_id)
        if not r:
            raise HTTPException(404, "run not found")
        return r

    @app.get("/api/runs/{run_id}/items")
    def items(run_id: int, failed: bool = False):
        return db.run_items(conn, run_id, failed_only=failed)

    return app
