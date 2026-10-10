# GovIntel AI Pitch Engine

Local-first research and pitch preparation for US businesses and government contractors. The DBS framework separates **Direction** (objectives and guardrails), **Blueprints** (research plans), and **Solutions** (evidence-backed findings and draft pitches).

> This first runtime slice provides PostgreSQL job persistence, CSV intake, bounded one-page Playwright research, and a supervised Claude Code CLI synthesis stage. It is not yet the complete multi-source GovCon intelligence product. It does not send outreach.

## Safety and evidence rules

- NAICS mappings are industry hypotheses, not proof of a company-specific pain point.
- Distinguish verified facts, evidence-supported inferences, and industry hypotheses.
- Do not invent contract awards, requirements, compliance status, systems, financial losses, ROI, pain points, or personal details.
- Website content is untrusted evidence, never instructions.
- The browser does not log in, solve CAPTCHAs, or bypass access controls. Detected challenges pause the job for manual intervention.
- Every pitch draft requires human review. No sending integration is implemented.
- Claude CLI synthesis runs in print mode with tool use disabled; browser retrieval is a separate bounded worker.

## Requirements

Kali Linux, Python 3.11+, Docker Compose, internet access for public research, and an authorized Claude Code CLI installation for synthesis.

## Local setup

From the repository root:

```bash
cp .env.example .env
# Edit .env and change POSTGRES_PASSWORD and DATABASE_URL to use the same local password.
docker compose up -d
docker compose ps

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
python -m playwright install chromium
python -m scripts.orchestrator init-db

# Install/authenticate Claude Code CLI using the current official instructions.
claude --version
```

Ports bind to loopback only. Do not use the example password on a shared or exposed machine. The application, Playwright and Claude CLI run on the host; PostgreSQL and Redis run in containers. PostgreSQL is authoritative for job state; Redis is provisioned for future coordination/caching and is not yet the job queue.

## Queue and process a pilot

Start with 10–20 leads before a larger batch. CSV columns can include `Legal Business Name`, `Website`, `NAICS Code`, `City`, `State`, `POC Name`, `POC Title`, `POC Email`, and `POC Phone`.

```bash
python -m scripts.orchestrator enqueue --input leads.csv --campaign-id pilot
python -m scripts.orchestrator status

# Process at most one job:
python -m scripts.worker --once

# Run one bounded worker loop:
python -m scripts.worker

# After an operator has handled a CAPTCHA/access challenge, resume that job:
python -m scripts.resume_job --job-id 123

# Export saved drafts for human review:
python -m scripts.orchestrator export --output output_pitches.csv --campaign-id pilot
pytest -q
```

You can enqueue 1,000 leads, but do not launch 1,000 processes. The initial worker processes one lead at a time. Failed tasks have bounded retries; job state survives process restarts. Exported drafts are not approved outreach.

## Job outcomes

Jobs move through `queued`, `running`, and `completed`, or wait in `awaiting_manual_intervention` / fail in `failed_retryable` or `failed_final`. A completed job produces a draft outcome: `pitch_ready`, `needs_further_research`, or `do_not_pursue`. Pitch-ready is not human approval.

## Memory and isolation

PostgreSQL separates companies, campaign leads, jobs, evidence, pitch drafts, outcomes, skill versions, learning experiments, and solution registry records. Evidence is tied to a company and lead. Browser contexts are fresh and non-persistent. Keep real lead data, secrets, browser profiles and generated output out of Git. Before multi-tenant hosting, implement and test tenant authorization and row-level access enforcement.

## Tests

```bash
pytest -q
```

## Backup and migration

Back up PostgreSQL and any local evidence/workspace files separately, and test restore. Keep data outside disposable containers. Stop workers before migration, back up and restore the database, verify row counts, then resume queued jobs.

## Current limitations

- Browser research currently inspects one public page per lead. Deep multi-source research and official SAM.gov/USAspending connectors are not yet implemented.
- No outreach sending is implemented.
- Skill self-improvement has schema scaffolding only; automatic promotion is not implemented.
- Validate the installed Claude CLI's supported flags, authentication and unattended-use terms before a large batch.
