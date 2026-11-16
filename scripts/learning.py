"""Observational learning reports and experiment bookkeeping.

This module never edits Claude skills, prompts, permissions, or production policy.
Research quality and commercial outcomes are measured independently.
"""
from __future__ import annotations
from typing import Any

from psycopg.types.json import Jsonb

from scripts.db import connect

COMMERCIAL_TYPES = {
    "commercial_reply", "commercial_meeting", "commercial_won",
    "commercial_lost", "commercial_no_response",
}
EXPERIMENT_TYPES = {"research_quality", "commercial_outcome", "skill_change"}


def research_quality_snapshot() -> dict:
    with connect() as conn:
        drafts = conn.execute("""SELECT COUNT(*) AS total,
            COUNT(*) FILTER (WHERE outcome='pitch_ready') AS pitch_ready,
            COUNT(*) FILTER (WHERE outcome='needs_further_research') AS needs_research,
            COUNT(*) FILTER (WHERE outcome='do_not_pursue') AS do_not_pursue,
            COUNT(*) FILTER (WHERE COALESCE(quality_checks->>'source_backed_claims','false')='true') AS source_backed,
            COUNT(*) FILTER (WHERE review_status='approved') AS human_approved,
            COUNT(*) FILTER (WHERE review_status='rejected') AS human_rejected,
            COUNT(*) FILTER (WHERE review_status='needs_further_research') AS human_requested_research,
            COUNT(*) FILTER (WHERE review_status='pending') AS pending_review
            FROM pitch_drafts""").fetchone()
        opportunities = conn.execute("""SELECT COUNT(*) AS total,
            ROUND(COALESCE(AVG(evidence_score),0)::numeric,2) AS mean_evidence_score,
            ROUND(COALESCE(AVG(priority_score),0)::numeric,2) AS mean_priority_score,
            COUNT(*) FILTER (WHERE evidence_type='industry_hypothesis') AS hypotheses,
            COUNT(*) FILTER (WHERE review_status='needs_review') AS source_backed_candidates,
            COUNT(*) FILTER (WHERE review_status='needs_more_evidence') AS evidence_gaps
            FROM opportunities""").fetchone()
        return {"drafts": dict(drafts), "opportunities": dict(opportunities)}


def commercial_outcome_snapshot() -> dict:
    with connect() as conn:
        rows = conn.execute("""SELECT outcome_type,COUNT(*) AS count
            FROM outcomes WHERE outcome_type LIKE 'commercial_%'
            GROUP BY outcome_type ORDER BY outcome_type""").fetchall()
    counts = {row["outcome_type"]: int(row["count"]) for row in rows}
    return {"total": sum(counts.values()), "counts": counts}


def snapshot(experiment_type: str) -> dict:
    if experiment_type == "research_quality":
        return research_quality_snapshot()
    if experiment_type == "commercial_outcome":
        return commercial_outcome_snapshot()
    if experiment_type == "skill_change":
        return {"note": "Skill changes are manually evaluated; no automatic promotion is available."}
    raise ValueError("Unsupported experiment type.")


def create_experiment(experiment_type: str, hypothesis: str, candidate: dict | None = None) -> int:
    if experiment_type not in EXPERIMENT_TYPES:
        raise ValueError("Invalid experiment type.")
    if not hypothesis.strip():
        raise ValueError("Experiment hypothesis is required.")
    baseline = snapshot(experiment_type)
    with connect() as conn:
        row = conn.execute("""INSERT INTO learning_experiments
            (experiment_type,hypothesis,baseline,candidate,status)
            VALUES (%s,%s,%s,%s,'proposed') RETURNING id""",
            (experiment_type, hypothesis.strip(), Jsonb(baseline), Jsonb(candidate or {}))).fetchone()
    return int(row["id"])


def _numeric_deltas(before: Any, after: Any, prefix: str = "") -> dict:
    result = {}
    if not isinstance(before, dict) or not isinstance(after, dict):
        return result
    for key, old in before.items():
        new = after.get(key)
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(old, dict) and isinstance(new, dict):
            result.update(_numeric_deltas(old, new, name))
        elif isinstance(old, (int, float)) and not isinstance(old, bool) and isinstance(new, (int, float)) and not isinstance(new, bool):
            result[name] = round(float(new) - float(old), 3)
    return result


def evaluate_experiment(experiment_id: int) -> dict:
    with connect() as conn:
        experiment = conn.execute("SELECT * FROM learning_experiments WHERE id=%s FOR UPDATE",
                                  (experiment_id,)).fetchone()
        if not experiment:
            raise ValueError("Experiment not found.")
        if experiment["status"] != "proposed":
            raise ValueError("Only proposed experiments can be evaluated.")
        after = snapshot(experiment["experiment_type"])
        before = experiment["baseline"] or {}
        result = {
            "measurement": "observational_snapshot",
            "baseline": before,
            "observed": after,
            "numeric_deltas": _numeric_deltas(before, after),
            "causal_claim": False,
            "limitations": [
                "This before/after snapshot is observational and does not establish causation.",
                "Review volume and source coverage affect the metrics; inspect sample sizes.",
            ],
        }
        status = "awaiting_human_approval" if experiment["experiment_type"] == "skill_change" else "evaluated"
        conn.execute("""UPDATE learning_experiments SET candidate=candidate || %s,
            result=%s,status=%s,completed_at=NOW() WHERE id=%s""",
            (Jsonb({"observed_snapshot": after}), Jsonb(result), status, experiment_id))
    return {"id": experiment_id, "status": status, "result": result}


def list_experiments() -> list[dict]:
    with connect() as conn:
        return conn.execute("""SELECT id,experiment_type,hypothesis,status,baseline,candidate,result,
            created_at,completed_at FROM learning_experiments ORDER BY id DESC LIMIT 100""").fetchall()


def record_commercial_outcome(draft_id: int, outcome_type: str, value: dict) -> None:
    if outcome_type not in COMMERCIAL_TYPES:
        raise ValueError("Unsupported commercial outcome type.")
    with connect() as conn:
        draft = conn.execute("SELECT company_id,lead_id FROM pitch_drafts WHERE id=%s",
                             (draft_id,)).fetchone()
        if not draft:
            raise ValueError("Pitch draft not found.")
        conn.execute("""INSERT INTO outcomes(company_id,lead_id,pitch_draft_id,outcome_type,outcome_value)
            VALUES (%s,%s,%s,%s,%s)""",
            (draft["company_id"], draft["lead_id"], draft_id, outcome_type, Jsonb(value)))


def priority_queue(limit: int = 50) -> list[dict]:
    limit = max(1, min(int(limit), 200))
    with connect() as conn:
        return conn.execute("""SELECT l.id AS lead_id,l.company_name,l.website,l.naics_code,
            p.id AS pitch_draft_id,p.outcome,p.review_status,
            COALESCE(best.priority_score,0) AS priority_score,
            COALESCE(best.evidence_score,0) AS evidence_score,
            COALESCE(best.title,'No scored opportunity') AS top_opportunity,
            COALESCE(best.evidence_type,'') AS evidence_type
            FROM leads l
            LEFT JOIN LATERAL (SELECT o.priority_score,o.evidence_score,o.title,o.evidence_type
                FROM opportunities o WHERE o.lead_id=l.id
                ORDER BY o.priority_score DESC,o.id DESC LIMIT 1) best ON TRUE
            LEFT JOIN LATERAL (SELECT d.id,d.outcome,d.review_status FROM pitch_drafts d
                WHERE d.lead_id=l.id ORDER BY d.version DESC LIMIT 1) p ON TRUE
            ORDER BY priority_score DESC,evidence_score DESC,l.id LIMIT %s""", (limit,)).fetchall()
