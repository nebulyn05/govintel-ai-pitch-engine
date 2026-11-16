"""CSV intake and local GovIntel job management."""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from scripts.db import (
    approve_solution, enqueue_lead, export_pitches, init_db, job_counts,
    list_solution_registry, reject_solution, sync_solution_registry,
)

ROOT = Path(__file__).resolve().parents[1]


def load_blueprints(path: str | None = None) -> dict:
    matrix_path = Path(path) if path else ROOT / "references" / "naics_matrix.json"
    with matrix_path.open(encoding="utf-8") as handle:
        matrix = json.load(handle)
    matrix.setdefault("default", {
        "sector": "Unknown / mixed sector",
        "core_bottleneck": "No NAICS-specific pattern has been validated for this lead.",
        "on_prem_solution": "Research company-specific public evidence first; do not infer a pain point from NAICS alone.",
    })
    return matrix


def construct_local_pitch(row: dict, matrix: dict) -> tuple[str, str, str, str]:
    naics = (row.get("NAICS Code") or "").strip()
    info = matrix.get(naics) or matrix.get("default") or {}
    sector = info.get("sector", "Unknown / mixed sector")
    bottleneck = info.get("core_bottleneck") or info.get("bottleneck") or "No company-specific pain point verified."
    solution = info.get("on_prem_solution") or info.get("solution") or "Research a suitable solution after reviewing public evidence."
    contact = (row.get("POC Name") or "there").strip()
    pitch = (
        f"Hi {contact}, we are researching practical local-first tools for organizations in {sector}. "
        f"We are exploring whether a private workflow could help with {bottleneck.lower()} "
        "This is an industry-level hypothesis, not a verified issue at your organization. Would a short overview be useful?"
    )
    return "review_required", bottleneck, solution, pitch


def _enqueue_csv(path: Path, campaign_id: str, max_attempts: int) -> tuple[int, int, list[str]]:
    created = existing = 0
    errors = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row.")
        for line, row in enumerate(reader, start=2):
            try:
                _, new_job = enqueue_lead(row, campaign_id, max_attempts)
                created += int(new_job)
                existing += int(not new_job)
            except (ValueError, KeyError) as exc:
                errors.append(f"line {line}: {exc}")
    return created, existing, errors


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="GovIntel local-first batch intake and job management")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="Create/update local PostgreSQL schema")
    enqueue = sub.add_parser("enqueue", help="Enqueue CSV leads; does not contact anyone")
    enqueue.add_argument("--input", type=Path, required=True)
    enqueue.add_argument("--campaign-id", default=None)
    enqueue.add_argument("--max-attempts", type=int, default=None)
    sub.add_parser("status", help="Show durable job counts")
    export = sub.add_parser("export", help="Export drafts for human review")
    export.add_argument("--output", type=Path, default=ROOT / "output_pitches.csv")
    export.add_argument("--campaign-id", default=None)

    sub.add_parser("registry-sync", help="Seed/update candidate solution registry entries")
    sub.add_parser("registry-list", help="List registry entries and approval state")
    approve = sub.add_parser("registry-approve", help="Approve a reviewed registry entry")
    approve.add_argument("--key", required=True)
    approve.add_argument("--version", type=int, default=1)
    approve.add_argument("--reviewer", required=True)
    reject = sub.add_parser("registry-reject", help="Reject a candidate registry entry")
    reject.add_argument("--key", required=True)
    reject.add_argument("--version", type=int, default=1)
    reject.add_argument("--reviewer", required=True)

    sub.add_parser("learning-report", help="Show research-quality and commercial-outcome metrics separately")
    propose = sub.add_parser("learning-propose", help="Create an observational learning experiment; does not change production behavior")
    propose.add_argument("--type", choices=["research_quality", "commercial_outcome", "skill_change"], required=True)
    propose.add_argument("--hypothesis", required=True)
    propose.add_argument("--candidate-json", default="{}")
    evaluate = sub.add_parser("learning-evaluate", help="Evaluate a proposed experiment against a fresh snapshot")
    evaluate.add_argument("--id", type=int, required=True)
    sub.add_parser("learning-list", help="List recent learning experiments")
    outcome = sub.add_parser("outcome-record", help="Record a manually observed commercial outcome")
    outcome.add_argument("--draft-id", type=int, required=True)
    outcome.add_argument("--type", choices=["commercial_reply", "commercial_meeting", "commercial_won", "commercial_lost", "commercial_no_response"], required=True)
    outcome.add_argument("--notes", default="")
    outcome.add_argument("--recorded-by", required=True)
    priority = sub.add_parser("priority-list", help="List leads by explainable opportunity priority")
    priority.add_argument("--limit", type=int, default=50)

    args = parser.parse_args(argv)
    try:
        if args.command == "init-db":
            init_db()
            print("Database schema initialized.")
            return 0
        if args.command == "enqueue":
            if not args.input.is_file():
                parser.error(f"Input CSV does not exist: {args.input}")
            campaign = args.campaign_id or os.getenv("CAMPAIGN_ID", "local")
            attempts = args.max_attempts or int(os.getenv("JOB_MAX_ATTEMPTS", "3"))
            if attempts < 1:
                parser.error("--max-attempts must be >= 1")
            init_db()
            created, existing, errors = _enqueue_csv(args.input, campaign, attempts)
            print(f"New jobs: {created}; existing leads updated: {existing}; row errors: {len(errors)}")
            for error in errors[:50]:
                print(f"WARNING: {error}", file=sys.stderr)
            return 1 if errors else 0
        if args.command == "status":
            for name, count in sorted(job_counts().items()):
                print(f"{name}: {count}")
            return 0
        if args.command == "export":
            campaign = args.campaign_id or os.getenv("CAMPAIGN_ID", "local")
            count = export_pitches(str(args.output), campaign)
            print(f"Exported {count} draft(s) to {args.output}. Human approval is required before outreach.")
            return 0
        if args.command == "registry-sync":
            init_db()
            changed, skipped = sync_solution_registry(str(ROOT / "references" / "solution_registry.json"))
            print(f"Registry candidates inserted/updated: {changed}; approved/rejected entries preserved: {skipped}")
            return 0
        if args.command == "registry-list":
            for row in list_solution_registry():
                print(
                    f'{row["solution_key"]} v{row["version"]}: {row["status"]} | '
                    f'{row["delivery_status"]} | approved claims: {row["approved_claim_count"]} | '
                    f'reviewer: {row["reviewed_by"] or "-"}'
                )
            return 0
        if args.command == "registry-approve":
            approve_solution(args.key, args.version, args.reviewer)
            print(f"Approved {args.key} v{args.version}.")
            return 0
        if args.command == "registry-reject":
            reject_solution(args.key, args.version, args.reviewer)
            print(f"Rejected {args.key} v{args.version}.")
            return 0

        if args.command in {"learning-report", "learning-propose", "learning-evaluate", "learning-list", "outcome-record", "priority-list"}:
            from scripts.learning import (
                commercial_outcome_snapshot, create_experiment, evaluate_experiment,
                list_experiments, priority_queue, record_commercial_outcome,
                research_quality_snapshot,
            )
            if args.command == "learning-report":
                print(json.dumps({
                    "research_quality": research_quality_snapshot(),
                    "commercial_outcomes": commercial_outcome_snapshot(),
                }, indent=2, default=str))
                return 0
            if args.command == "learning-propose":
                candidate = json.loads(args.candidate_json)
                if not isinstance(candidate, dict):
                    parser.error("--candidate-json must decode to a JSON object")
                experiment_id = create_experiment(args.type, args.hypothesis, candidate)
                print(f"Created proposed experiment {experiment_id}; no production settings or skills were changed.")
                return 0
            if args.command == "learning-evaluate":
                result = evaluate_experiment(args.id)
                print(json.dumps(result, indent=2, default=str))
                return 0
            if args.command == "learning-list":
                print(json.dumps(list_experiments(), indent=2, default=str))
                return 0
            if args.command == "outcome-record":
                record_commercial_outcome(args.draft_id, args.type, {
                    "notes": args.notes, "recorded_by": args.recorded_by,
                })
                print(f"Recorded {args.type} for draft {args.draft_id}.")
                return 0
            if args.command == "priority-list":
                print(json.dumps(priority_queue(args.limit), indent=2, default=str))
                return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
