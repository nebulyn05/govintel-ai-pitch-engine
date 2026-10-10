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
    # Execute one DDL statement at a time for compatibility with PostgreSQL drivers.
    with connect() as conn:
        # Split only on statement-terminating semicolons, not punctuation in SQL comments or literals.
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
    from psycopg.types.json import Jsonb
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
        return conn.execute(
            """WITH candidate AS (
                 SELECT id FROM research_jobs
                 WHERE (status IN ('queued','failed_retryable') AND available_at<=NOW())
                    OR (status='running' AND locked_at<NOW()-INTERVAL '20 minutes' AND attempts<max_attempts)
                 ORDER BY available_at,id FOR UPDATE SKIP LOCKED LIMIT 1
               )
               UPDATE research_jobs j SET status='running',attempts=j.attempts+1,locked_at=NOW(),
                 started_at=COALESCE(j.started_at,NOW()),updated_at=NOW(),last_error=''
               FROM candidate WHERE j.id=candidate.id
               RETURNING j.id AS job_id,j.lead_id,j.attempts,j.max_attempts"""
        ).fetchone()


def get_lead(lead_id: int):
    with connect() as conn:
        return conn.execute(
            "SELECT l.*,c.id AS scoped_company_id FROM leads l JOIN companies c ON c.id=l.company_id WHERE l.id=%s",
            (lead_id,),
        ).fetchone()


def save_evidence(lead: dict, job_id: int, item: dict) -> None:
    import json
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
    outcome = payload.get("outcome")
    if outcome not in {"pitch_ready","needs_further_research","do_not_pursue"}:
        outcome = "needs_further_research"
    claims = payload.get("claims") if isinstance(payload.get("claims"), list) else []
    assumptions = payload.get("assumptions") if isinstance(payload.get("assumptions"), list) else []
    checks = payload.get("quality_checks") if isinstance(payload.get("quality_checks"), dict) else {}
    with connect() as conn:
        version = conn.execute("SELECT COALESCE(MAX(version),0)+1 AS v FROM pitch_drafts WHERE lead_id=%s",
                               (lead["id"],)).fetchone()["v"]
        conn.execute(
            """INSERT INTO pitch_drafts(company_id,lead_id,research_job_id,version,outcome,channel,claims,
               opportunity_summary,proposed_solution,pitch_text,assumptions,quality_checks)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (lead["company_id"],lead["id"],job_id,version,outcome,
             str(payload.get("channel") or "review_required")[:80],Jsonb(claims),
             str(payload.get("opportunity_summary") or "")[:5000],
             str(payload.get("proposed_solution") or "")[:5000],
             str(payload.get("pitch_text") or "")[:10000],Jsonb(assumptions),Jsonb(checks)),
        )
        conn.execute("UPDATE research_jobs SET status='completed',finished_at=NOW(),locked_at=NULL,updated_at=NOW() WHERE id=%s",
                     (job_id,))


def fail_job(job_id: int, attempts: int, max_attempts: int, error: str) -> None:
    status = "failed_final" if attempts >= max_attempts else "failed_retryable"
    with connect() as conn:
        conn.execute(
            """UPDATE research_jobs SET status=%s,last_error=%s,
               available_at=NOW()+(INTERVAL '30 seconds' * %s),locked_at=NULL,
               finished_at=CASE WHEN %s='failed_final' THEN NOW() ELSE NULL END,updated_at=NOW()
               WHERE id=%s""",
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
