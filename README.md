# GovIntel AI Pitch Engine

Local-first research and pitch preparation for US businesses and government contractors. The DBS framework separates **Direction** (objectives and guardrails), **Blueprints** (research plans), and **Solutions** (evidence-backed findings and draft pitches).

> This first runtime slice provides PostgreSQL job persistence, CSV intake, bounded adaptive same-site Playwright research, and a supervised Claude Code CLI synthesis stage. It is not yet the complete multi-source GovCon intelligence product. It does not send outreach.

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

Start with 10–20 leads before a larger batch. CSV columns can include `Legal Business Name`, `Website`, `NAICS Code`, `City`, `State`, `UEI`, `POC Name`, `POC Title`, `POC Email`, and `POC Phone`.

```bash
python -m scripts.orchestrator enqueue --input leads.csv --campaign-id pilot
python -m scripts.orchestrator status

# Process at most one job:
python -m scripts.worker --once

# Optional research budget (default 3 pages, maximum 5):
# python -m scripts.worker --once --browser-max-pages 3

# Run one bounded worker loop:
python -m scripts.worker

# After an operator has handled a CAPTCHA/access challenge, resume that job:
python -m scripts.resume_job --job-id 123

# Export saved drafts for human review:
python -m scripts.orchestrator export --output output_pitches.csv --campaign-id pilot
pytest -q
```

You can enqueue 1,000 leads, but do not launch 1,000 processes. The initial worker processes one lead at a time. Failed tasks have bounded retries; job state survives process restarts. Exported drafts are not approved outreach.

## Opportunity discovery and solution registry

The research worker converts Claude's structured opportunity hypotheses into deterministic, explainable priority scores. Each opportunity must reference claim indices from the lead's evidence. Scoring separates evidence strength, estimated impact, urgency and approved-solution feasibility; industry-only hypotheses are capped and routed for more research. These scores support triage and do not automatically authorize outreach.

The solution registry starts with candidate templates in `references/solution_registry.json`. Candidate entries are not offerings and are never recommended as approved solutions. Review and edit their delivery status, prerequisites, capability tags and explicit approved claims before approving one:

```bash
python -m scripts.orchestrator registry-sync
python -m scripts.orchestrator registry-list
# Edit references/solution_registry.json to document actual delivery readiness and approved claims.
python -m scripts.orchestrator registry-sync
python -m scripts.orchestrator registry-approve --key private_document_assistant --version 1 --reviewer "Operator ID"
```

Only registry entries with status `approved` and delivery status `available`, `buildable` or `partner_required` can be matched. The approval command refuses entries without approved claims, capability tags and documented prerequisites. Approved/rejected entries are not overwritten by a later seed sync. Revoke or revise an approved offering by creating and reviewing a new version; do not silently edit approved claims.

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

- Browser research now visits a bounded set of relevant same-site pages (homepage plus selected careers/jobs, contact/intake, capabilities/services or about pages). It does not crawl arbitrary external links.
- CMS, analytics, technology, copyright-year and thin-content observations are weak signals only; they do not prove pain points or justify automatic lead rejection.
- USAspending.gov is a public, unauthenticated source. Enrichment is bounded to at most 10 award results per lead and can be disabled with `USASPENDING_ENABLED=false`. Supply a `UEI` column in the lead CSV for the strongest identity match. Without UEI, exact legal-name and location corroboration are required; otherwise awards remain unattached.
- JavaScript is disabled during retrieval. Some JavaScript-rendered sites may therefore return partial evidence. The page budget defaults to three and can be raised to five; keep it low on machines with limited RAM.
- USAspending.gov public award-history lookup is integrated for a bounded set of recent/high-value federal prime awards. It searches by supplied UEI first; without UEI it requires exact normalized legal-name plus city/state corroboration. Name-only matches are never attached to a lead. Award records are context, not proof of current pain, budget, or buying intent. SAM.gov integration is not implemented.
- No outreach sending is implemented.\n- The solution registry ships with candidate templates only; it contains no human-approved live offerings until an operator completes the review and approval workflow.
- Skill self-improvement has schema scaffolding only; automatic promotion is not implemented.
- Validate the installed Claude CLI's supported flags, authentication and unattended-use terms before a large batch.
