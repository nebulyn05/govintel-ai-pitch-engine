"""Resume a job only after an operator has handled its manual-intervention requirement."""
from __future__ import annotations
import argparse
from dotenv import load_dotenv
from scripts.db import ROOT, connect, init_db


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Resume a CAPTCHA/access-challenge job after authorized manual intervention")
    parser.add_argument("--job-id", type=int, required=True)
    args = parser.parse_args()
    if args.job_id < 1:
        parser.error("--job-id must be positive")
    try:
        init_db()
        with connect() as conn:
            row = conn.execute(
                """UPDATE research_jobs
                   SET status='queued', available_at=NOW(), locked_at=NULL, last_error='',
                       finished_at=NULL, updated_at=NOW()
                   WHERE id=%s AND status='awaiting_manual_intervention'
                   RETURNING id""",
                (args.job_id,),
            ).fetchone()
        if not row:
            print("No change: job not found or not awaiting manual intervention.")
            return 1
        print(f"Job {args.job_id} returned to the queue. It will use the normal permitted research path.")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
