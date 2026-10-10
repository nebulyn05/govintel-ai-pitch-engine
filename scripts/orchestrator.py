"""CSV intake and local GovIntel job management."""
from __future__ import annotations
import argparse
import csv
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from scripts.db import enqueue_lead, export_pitches, init_db, job_counts

ROOT=Path(__file__).resolve().parents[1]


def load_blueprints(path: str | None=None) -> dict:
    matrix_path=Path(path) if path else ROOT/"references"/"naics_matrix.json"
    with matrix_path.open(encoding="utf-8") as handle: matrix=json.load(handle)
    matrix.setdefault("default",{"sector":"Unknown / mixed sector",
        "core_bottleneck":"No NAICS-specific pattern has been validated for this lead.",
        "on_prem_solution":"Research company-specific public evidence first; do not infer a pain point from NAICS alone."})
    return matrix


def construct_local_pitch(row: dict, matrix: dict) -> tuple[str,str,str,str]:
    naics=(row.get("NAICS Code") or "").strip()
    info=matrix.get(naics) or matrix.get("default") or {}
    sector=info.get("sector","Unknown / mixed sector")
    bottleneck=info.get("core_bottleneck") or info.get("bottleneck") or "No company-specific pain point verified."
    solution=info.get("on_prem_solution") or info.get("solution") or "Research a suitable solution after reviewing public evidence."
    contact=(row.get("POC Name") or "there").strip()
    pitch=(f"Hi {contact}, we are researching practical local-first tools for organizations in {sector}. "
        f"We are exploring whether a private workflow could help with {bottleneck.lower()} "
        "This is an industry-level hypothesis, not a verified issue at your organization. Would a short overview be useful?")
    return "review_required",bottleneck,solution,pitch


def _enqueue_csv(path: Path,campaign_id: str,max_attempts: int) -> tuple[int,int,list[str]]:
    created=existing=0; errors=[]
    with path.open(encoding="utf-8-sig",newline="") as handle:
        reader=csv.DictReader(handle)
        if not reader.fieldnames: raise ValueError("CSV has no header row.")
        for line,row in enumerate(reader,start=2):
            try:
                _,new_job=enqueue_lead(row,campaign_id,max_attempts)
                created+=int(new_job); existing+=int(not new_job)
            except (ValueError,KeyError) as exc: errors.append(f"line {line}: {exc}")
    return created,existing,errors


def main(argv: list[str] | None=None) -> int:
    load_dotenv(ROOT/".env")
    parser=argparse.ArgumentParser(description="GovIntel local-first batch intake and job management")
    sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("init-db",help="Create/update local PostgreSQL schema")
    enqueue=sub.add_parser("enqueue",help="Enqueue CSV leads; does not contact anyone")
    enqueue.add_argument("--input",type=Path,required=True)
    enqueue.add_argument("--campaign-id",default=None)
    enqueue.add_argument("--max-attempts",type=int,default=None)
    sub.add_parser("status",help="Show durable job counts")
    export=sub.add_parser("export",help="Export drafts for human review")
    export.add_argument("--output",type=Path,default=ROOT/"output_pitches.csv")
    export.add_argument("--campaign-id",default=None)
    args=parser.parse_args(argv)
    try:
        if args.command=="init-db":
            init_db(); print("Database schema initialized."); return 0
        if args.command=="enqueue":
            if not args.input.is_file(): parser.error(f"Input CSV does not exist: {args.input}")
            campaign=args.campaign_id or os.getenv("CAMPAIGN_ID","local")
            attempts=args.max_attempts or int(os.getenv("JOB_MAX_ATTEMPTS","3"))
            if attempts<1: parser.error("--max-attempts must be >= 1")
            init_db()
            created,existing,errors=_enqueue_csv(args.input,campaign,attempts)
            print(f"New jobs: {created}; existing leads updated: {existing}; row errors: {len(errors)}")
            for error in errors[:50]: print(f"WARNING: {error}",file=sys.stderr)
            return 1 if errors else 0
        if args.command=="status":
            for name,count in sorted(job_counts().items()): print(f"{name}: {count}")
            return 0
        if args.command=="export":
            campaign=args.campaign_id or os.getenv("CAMPAIGN_ID","local")
            count=export_pitches(str(args.output),campaign)
            print(f"Exported {count} draft(s) to {args.output}. Human approval is required before outreach.")
            return 0
    except Exception as exc:
        print(f"ERROR: {exc}",file=sys.stderr); return 2
    return 2


if __name__=="__main__": raise SystemExit(main())
