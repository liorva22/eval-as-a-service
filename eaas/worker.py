"""Scoring worker: claims queued runs from Postgres and scores them. Run several for parallelism."""

import logging
import time

from . import db
from .judge import make_judge
from .scoring import score_item, summarize

log = logging.getLogger("eaas.worker")


def process_one(conn, judge) -> bool:
    run = db.claim_run(conn)
    if not run:
        return False
    log.info("scoring run %s", run["id"])
    try:
        results = []
        for item in db.run_items(conn, run["id"]):
            r = score_item(run["rubric"], item["data"], judge)
            db.save_item_result(conn, item["id"], r)
            results.append(r)
        db.finish_run(conn, run["id"], summary=summarize(run["rubric"], results))
    except Exception as e:  # a bad run must not kill the worker
        log.exception("run %s failed", run["id"])
        db.finish_run(conn, run["id"], error=f"{type(e).__name__}: {e}")
    return True


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    conn, judge = db.connect(), make_judge()
    log.info("worker started (judge=%s)", judge.name)
    while True:
        if not process_one(conn, judge):
            time.sleep(1)


if __name__ == "__main__":
    main()
