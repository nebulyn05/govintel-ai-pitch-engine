"""PostgreSQL persistence and durable job queue helpers."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "db" / "schema.sql"
STALE_JOB_MINUTES = 20


def database_url() -> str:
    import os
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is missing. Copy .env.example to .env and configure it.")
    return value


def connect():
    return psycopg.connect(database_url(), row_factory=dict_row, connect_timeout=5)


def init_db() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with connect() as conn:
        for statement in re.split(r";\s*(?=\n|$)", schema):
            if statement.strip():
                conn.execute(statement)


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().casefold())


def normalized_domain(website: str) -> str:
    value = (website or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def identity_key(company_name: str, website: str) -> tuple[str, str, str]:
    name, domain = normalize_name(company_name), normalized_domain(website)
    if not name and not domain:
        raise ValueError("A lead must include at least a company name or website.")
    return hashlib.sha256(f"{name}|{domain}".encode()).hexdigest(), name or domain, domain


def enqueue_lead(row: dict[str, str], campaign_id: str = "local", max_attempts: int = 3) -> tuple[int, bool]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    company_name = (row.get("Legal Business Name") or row.get("Company Name") or row.get("company_name") or "").strip()
    website = (row.get("Website") or row.get("website") or "").strip()
    if not company_name and not website:
        raise ValueError("Missing both Legal Business Name and Website.")
    key, normalized, domain = identity_key(company_name, website)
    campaign = (campaign_id or "local").strip() or "local"
    with connect() as conn:
        company = conn.execute(
            """INSERT INTO companies(identity_key,normalized_name,website_domain) VALUES (%s,%s,%s)
               ON CONFLICT(identity_key) DO UPDATE SET updated_at=NOW() RETURNING id""",
            (key, normalized, domain),
        ).fetchone()
        lead = conn.execute(
            """INSERT INTO leads(company_id,campaign_id,company_name,website,naics_code,city,state,
                contact_name,contact_title,contact_email,contact_phone,source_row)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT(company_id,campaign_id) DO UPDATE SET
                company_name=COALESCE(NULLIF(EXCLUDED.company_name,''),leads.company_name),
                website=COALESCE(NULLIF(EXCLUDED.website,''),leads.website),
                naics_code=COALESCE(NULLIF(EXCLUDED.naics_code,''),leads.naics_code),
                city=COALESCE(NULLIF(EXCLUDED.city,''),leads.city),
                state=COALESCE(NULLIF(EXCLUDED.state,''),leads.state),
                contact_name=COALESCE(NULLIF(EXCLUDED.contact_name,''),leads.contact_name),
                contact_title=COALESCE(NULLIF(EXCLUDED.contact_title,''),leads.contact_title),
                contact_email=COALESCE(NULLIF(EXCLUDED.contact_email,''),leads.contact_email),
                contact_phone=COALESCE(NULLIF(EXCLUDED.contact_phone,''),leads.contact_phone),
                source_row=leads.source_row || EXCLUDED.source_row, updated_at=NOW()
               RETURNING id""",
            (company["id"], campaign, company_name, website,
             (row.get("NAICS Code") or row.get("NAICS") or row.get("naics_code") or "").strip(),
             (row.get("City") or row.get("city") or "").strip(),
             (row.get("State") or row.get("state") or "").strip(),
             (row.get("POC Name") or row.get("Contact Name") or row.get("contact_name") or "").strip(),
             (row.get("POC Title") or row.get("Title") or row.get("contact_title") or "").strip(),
             (row.get("POC Email") or row.get("Email") or row.get("email") or "").strip(),
             (row.get("POC Phone") or row.get("Phone") or row.get("phone") or "").strip(),
             Jsonb(row)),
        ).fetchone()
        job = conn.execute(
            """INSERT INTO research_jobs(lead_id,max_attempts) VALUES (%s,%s)
               ON CONFLICT(lead_id) DO NOTHING RETURNING id""",
            (lead["id"], max_attempts),
        ).fetchone()
        return lead["id"], job is not None


def claim_next_job():
    with connect() as conn:
        # A worker that dies on its final attempt must not strand a job in "running".
        conn.execute(
            """UPDATE research_jobs SET status='failed_final',locked_at=NULL,
                 finished_at=NOW(),updated_at=NOW(),
                 last_error=CASE WHEN last_error='' THEN 'Worker lease expired after final attempt'
                                 ELSE last_error || E'\\nWorker lease expired after final attempt' END
               WHERE status='running' AND attempts>=max_attempts
                 AND (locked_at IS NULL OR locked_at<NOW()-(%s * INTERVAL '1 minute'))""",
            (STALE_JOB_MINUTES,),
        )
        return conn.execute(
            """WITH candidate AS (
                 SELECT id FROM research_jobs
                 WHERE (status IN ('queued','failed_retryable') AND available_at<=NOW())
                    OR (status='running' AND attempts<max_attempts
                        AND (locked_at IS NULL OR locked_at<NOW()-(%s * INTERVAL '1 minute')))
                 ORDER BY available_at,id FOR UPDATE SKIP LOCKED LIMIT 1
               )
               UPDATE research_jobs j SET status='running',attempts=j.attempts+1,locked_at=NOW(),
                 started_at=COALESCE(j.started_at,NOW()),updated_at=NOW(),last_error=''
               FROM candidate WHERE j.id=candidate.id
               RETURNING j.id AS job_id,j.lead_id,j.attempts,j.max_attempts""",
            (STALE_JOB_MINUTES,),
        ).fetchone()


def get_lead(lead_id: int):
    with connect() as conn:
        return conn.execute(
            "SELECT l.*,c.id AS scoped_company_id FROM leads l JOIN companies c ON c.id=l.company_id WHERE l.id=%s",
            (lead_id,),
        ).fetchone()


def save_evidence(lead: dict, job_id: int, item: dict) -> None:
    url = str(item.get("url") or "").strip()
    if not url:
        return
    excerpt = str(item.get("excerpt") or "")[:12000]
    digest = hashlib.sha256(excerpt.encode()).hexdigest()
    with connect() as conn:
        conn.execute(
            """INSERT INTO evidence_items(company_id,lead_id,research_job_id,source_url,source_title,
               excerpt,evidence_type,content_hash,metadata)
               VALUES (%s,%s,%s,%s,%s,%s,'source_metadata',%s,%s)
               ON CONFLICT(lead_id,source_url,content_hash) DO NOTHING""",
            (lead["company_id"],lead["id"],job_id,url,str(item.get("title") or "")[:500],
             excerpt,digest,Jsonb(item.get("metadata") or {})),
        )


def save_pitch(lead: dict, job_id: int, payload: dict) -> None:
    outcome = payload["outcome"]
    claims = payload["claims"]
    assumptions = payload["assumptions"]
    checks = payload["quality_checks"]
    with connect() as conn:
        version = conn.execute("SELECT COALESCE(MAX(version),0)+1 AS v FROM pitch_drafts WHERE lead_id=%s",
                               (lead["id"],)).fetchone()["v"]
        conn.execute(
            """INSERT INTO pitch_drafts(company_id,lead_id,research_job_id,version,outcome,channel,claims,
               opportunity_summary,proposed_solution,pitch_text,assumptions,quality_checks)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (lead["company_id"],lead["id"],job_id,version,outcome,payload["channel"],Jsonb(claims),
             payload["opportunity_summary"],payload["proposed_solution"],payload["pitch_text"],
             Jsonb(assumptions),Jsonb(checks)),
        )
        conn.execute("UPDATE research_jobs SET status='completed',finished_at=NOW(),locked_at=NULL,updated_at=NOW() WHERE id=%s AND status='running'",
                     (job_id,))


def fail_job(job_id: int, attempts: int, max_attempts: int, error: str) -> None:
    status = "failed_final" if attempts >= max_attempts else "failed_retryable"
    with connect() as conn:
        conn.execute(
            """UPDATE research_jobs SET status=%s,last_error=%s,
               available_at=NOW()+(INTERVAL '30 seconds' * %s),locked_at=NULL,
               finished_at=CASE WHEN %s='failed_final' THEN NOW() ELSE NULL END,updated_at=NOW()
               WHERE id=%s AND status='running'""",
            (status,error[:2000],max(1,attempts),status,job_id),
        )


def job_counts() -> dict[str, int]:
    with connect() as conn:
        rows = conn.execute("SELECT status,COUNT(*) AS n FROM research_jobs GROUP BY status").fetchall()
    return {row["status"]: row["n"] for row in rows}


def export_pitches(output_path: str, campaign_id: str = "local") -> int:
    import csv
    with connect() as conn:
        rows = conn.execute(
            """SELECT l.company_name AS "Legal Business Name",l.website AS "Website",
               l.naics_code AS "NAICS Code",l.contact_name AS "POC Name",l.contact_email AS "POC Email",
               l.contact_phone AS "POC Phone",p.channel AS "Target Channel",
               p.opportunity_summary AS "Opportunity Summary",p.proposed_solution AS "Proposed Solution",
               p.pitch_text AS "Pitch Draft",p.outcome AS "Review Status",p.created_at AS "Created At"
               FROM pitch_drafts p JOIN leads l ON l.id=p.lead_id
               WHERE l.campaign_id=%s ORDER BY p.created_at,l.id""", (campaign_id,)
        ).fetchall()
    fields = list(rows[0].keys()) if rows else ["Legal Business Name","Website","NAICS Code","POC Name",
        "POC Email","POC Phone","Target Channel","Opportunity Summary","Proposed Solution","Pitch Draft",
        "Review Status","Created At"]
    with open(output_path,"w",encoding="utf-8",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    return len(rows)


def get_approved_solutions() -> list[dict]:
    """Return only human-approved, non-restricted registry entries."""
    with connect() as conn:
        return conn.execute(
            """SELECT id,solution_key,version,title,description,delivery_status,
                      approved_claims,requirements,status
               FROM solution_registry WHERE status='approved'
               ORDER BY solution_key,version DESC"""
        ).fetchall()


def list_solution_registry() -> list[dict]:
    with connect() as conn:
        return conn.execute(
            """SELECT id,solution_key,version,title,delivery_status,status,
                      jsonb_array_length(approved_claims) AS approved_claim_count,
                      reviewed_by,reviewed_at
               FROM solution_registry ORDER BY solution_key,version"""
        ).fetchall()


def sync_solution_registry(seed_path: str) -> tuple[int, int]:
    """Insert/update seed entries only while they remain unapproved candidates."""
    import json
    from pathlib import Path
    rows = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Solution registry seed must be a JSON array.")
    inserted_or_updated = skipped = 0
    with connect() as conn:
        for row in rows:
            required = ("solution_key", "version", "title", "description", "delivery_status", "requirements")
            if not isinstance(row, dict) or any(not row.get(key) for key in required):
                raise ValueError("Every registry seed entry needs key, version, title, description, delivery_status and requirements.")
            if row["delivery_status"] not in {"available", "buildable", "partner_required", "concept", "restricted"}:
                raise ValueError(f"Invalid delivery status for {row['solution_key']}.")
            result = conn.execute(
                """INSERT INTO solution_registry(solution_key,version,title,description,delivery_status,
                       approved_claims,requirements,status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'candidate')
                   ON CONFLICT(solution_key,version) DO UPDATE SET
                       title=EXCLUDED.title,description=EXCLUDED.description,
                       delivery_status=EXCLUDED.delivery_status,approved_claims=EXCLUDED.approved_claims,
                       requirements=EXCLUDED.requirements
                   WHERE solution_registry.status='candidate'
                   RETURNING id""",
                (row["solution_key"], int(row["version"]), row["title"], row["description"],
                 row["delivery_status"], Jsonb(row.get("approved_claims") or []),
                 Jsonb(row["requirements"])),
            ).fetchone()
            if result:
                inserted_or_updated += 1
            else:
                skipped += 1
    return inserted_or_updated, skipped


def approve_solution(solution_key: str, version: int, reviewer: str) -> None:
    if not reviewer.strip():
        raise ValueError("A reviewer identity is required.")
    with connect() as conn:
        row = conn.execute(
            """SELECT id,delivery_status,approved_claims,requirements,status
               FROM solution_registry WHERE solution_key=%s AND version=%s FOR UPDATE""",
            (solution_key, version),
        ).fetchone()
        if not row:
            raise ValueError("Solution registry entry not found.")
        if row["status"] != "candidate":
            raise ValueError("Only candidate registry entries can be approved.")
        if row["delivery_status"] == "restricted":
            raise ValueError("Restricted solutions cannot be approved for matching.")
        claims = row["approved_claims"] or []
        requirements = row["requirements"] or {}
        if not claims or not all(isinstance(item, str) and item.strip() for item in claims):
            raise ValueError("Add explicit approved_claims before approving this solution.")
        if not isinstance(requirements.get("capability_tags"), list) or not requirements["capability_tags"]:
            raise ValueError("Add capability_tags before approving this solution.")
        if not isinstance(requirements.get("prerequisites"), list) or not requirements["prerequisites"]:
            raise ValueError("Document prerequisites before approving this solution.")
        conn.execute(
            """UPDATE solution_registry SET status='approved',reviewed_by=%s,reviewed_at=NOW()
               WHERE id=%s""",
            (reviewer.strip(), row["id"]),
        )


def reject_solution(solution_key: str, version: int, reviewer: str) -> None:
    if not reviewer.strip():
        raise ValueError("A reviewer identity is required.")
    with connect() as conn:
        result = conn.execute(
            """UPDATE solution_registry SET status='rejected',reviewed_by=%s,reviewed_at=NOW()
               WHERE solution_key=%s AND version=%s AND status='candidate' RETURNING id""",
            (reviewer.strip(), solution_key, version),
        ).fetchone()
        if not result:
            raise ValueError("Candidate solution not found or no longer reviewable.")


def save_opportunity_analysis(lead: dict, job_id: int, opportunities: list[dict]) -> int:
    saved = 0
    with connect() as conn:
        for item in opportunities:
            row = conn.execute(
                """INSERT INTO opportunities(company_id,lead_id,research_job_id,title,description,
                       evidence_type,confidence,status,impact,urgency,evidence_score,impact_score,
                       urgency_score,feasibility_score,priority_score,evidence_claim_indices,
                       capability_tags,buyer_role,review_status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'candidate',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   RETURNING id""",
                (lead["company_id"], lead["id"], job_id, item["title"], item["description"],
                 item["evidence_type"], item["confidence"], item["impact"], item["urgency"],
                 item["evidence_score"], item["impact_score"], item["urgency_score"],
                 item["feasibility_score"], item["priority_score"],
                 Jsonb(item["evidence_claim_indices"]), Jsonb(item["capability_tags"]),
                 item["buyer_role"], item["review_status"]),
            ).fetchone()
            opportunity_id = row["id"]
            for match in item["solution_matches"]:
                conn.execute(
                    """INSERT INTO solution_candidates(company_id,lead_id,opportunity_id,title,
                           description,delivery_status,feasibility_notes,solution_registry_id,
                           match_score,match_metadata,review_status)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'candidate')""",
                    (lead["company_id"], lead["id"], opportunity_id, match["title"],
                     match["description"], match["delivery_status"],
                     "Prerequisites: " + "; ".join(match["prerequisites"]),
                     match["registry_id"], match["match_score"],
                     Jsonb({key: value for key, value in match.items()
                            if key not in {"title", "description"}})),
                )
            saved += 1
    return saved
