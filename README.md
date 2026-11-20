# GovIntel AI Pitch Engine

Local-first research and pitch preparation for US businesses and government contractors. The DBS framework separates **Direction** (objectives and guardrails), **Blueprints** (research plans), and **Solutions** (evidence-backed findings and draft pitches).

> **Current scope:** CSV lead intake, PostgreSQL-backed job queue, bounded public-web research with Playwright, optional USAspending.gov award-history enrichment, Claude Code CLI synthesis, opportunity scoring, approved-solution matching, guarded learning records, and a local human-review dashboard. This is not yet a fully automated GovCon intelligence platform. It does not send email, contact prospects, or deliver to a CRM.

---

## 1. What the system does

1. Imports a CSV of US businesses or government contractors.
2. Creates one durable research job per lead in PostgreSQL.
3. Visits a bounded number of publicly accessible pages on the company's own website.
4. Optionally looks up federal award history through USAspending.gov.
5. Sends collected evidence and approved solution options to Claude Code CLI for structured analysis.
6. Scores opportunities using evidence quality, estimated impact, estimated urgency, and approved-solution feasibility.
7. Saves an evidence-linked pitch draft and queues it for a human reviewer.
8. Lets an operator inspect sources, edit, approve, reject, or request more research in the local dashboard.

A pitch marked `pitch_ready` is **not approved**. Human approval is a separate step. Approval is an internal review record only; no outreach sending integration exists.

## 2. System requirements

Recommended initial environment:

- Kali Linux (or another Linux distribution).
- Python 3.11 or newer.
- Docker Engine and Docker Compose plugin.
- Git.
- An authorized Claude Code CLI installation and authentication for synthesis.
- Internet access for permitted public website research and USAspending.gov.
- At least 8 GB RAM is the target environment for this conservative profile; actual memory use depends on websites, browser activity, and Claude CLI.

The application, Python worker, Playwright browser, Claude CLI, and dashboard run on the host. Docker runs PostgreSQL and Redis. **PostgreSQL is the authoritative queue and data store. Redis is provisioned for future coordination/caching and is not currently the job queue.**

Default local ports:

| Service | Host address | Purpose |
|---|---|---|
| PostgreSQL | `127.0.0.1:54329` | Durable application database |
| Redis | `127.0.0.1:63790` | Reserved coordination/cache service |
| Review dashboard | `127.0.0.1:8765` | Local human review UI |

The database and Redis ports are bound to loopback, not exposed to your LAN.

---

## 3. Clone the repository

Open a terminal:

```bash
git clone https://github.com/nebulyn05/govintel-ai-pitch-engine.git
cd govintel-ai-pitch-engine
```

For the current Batch 7 implementation, check out its feature branch:

```bash
git fetch origin
git checkout feat/batch-7-integration-validation
```

If you are setting up from a later merged release, use the appropriate released/default branch instead.

---

## 4. Prepare Python

Check your Python version:

```bash
python3 --version
```

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Upgrade pip and install the project and test dependencies:

```bash
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

Install the Playwright Chromium browser:

```bash
python -m playwright install chromium
```

If Playwright reports missing Linux shared libraries, use its supported dependency installer:

```bash
python -m playwright install-deps chromium
```

On Kali, this may request administrator privileges to install operating-system packages. Do not run the application itself as root unless you have a specific reason.

---

## 5. Install and authenticate Claude Code CLI

Claude Code CLI is used for structured analysis and pitch synthesis. Install it using Anthropic's current official installation instructions; the installation method and supported flags can change.

Verify the command is available:

```bash
claude --version
```

Start Claude interactively and complete authentication:

```bash
claude
```

Then exit the interactive session. Confirm that the same Linux user who will run the GovIntel worker can invoke the CLI. The worker uses the configured command name (default: `claude`) and a bounded timeout.

Do not place API keys or authentication tokens in the CSV, source code, or Git. Do not assume that an interactive login guarantees unattended operation: test a single lead first and confirm that your Claude account, CLI version, and usage terms support the intended non-interactive invocation.

---

## 6. Configure environment variables

Create your local environment file:

```bash
cp .env.example .env
nano .env
```

At minimum, change the example database password. The password in `POSTGRES_PASSWORD` and the password embedded in `DATABASE_URL` **must match**.

Example:

```dotenv
ENVIRONMENT=local
POSTGRES_PASSWORD=replace-with-a-long-local-password
DATABASE_URL=postgresql://govintel:replace-with-a-long-local-password@127.0.0.1:54329/govintel
REDIS_URL=redis://127.0.0.1:63790/0
CAMPAIGN_ID=local
CLAUDE_COMMAND=claude
CLAUDE_TIMEOUT_SECONDS=240
WORKER_POLL_SECONDS=5
JOB_MAX_ATTEMPTS=3
BROWSER_TIMEOUT_MS=20000
BROWSER_MAX_CHARS=10000
BROWSER_MAX_PAGES=3
GOVINTEL_DATA_DIR=./data
USASPENDING_ENABLED=true
USASPENDING_MAX_AWARDS=5
CSV_MAX_ROWS=1000
```

The repository's `.env.example` already contains these settings; this is an illustration of the important values, not a replacement for checking your local file.

### Resource settings

Batch 7 validates the following values and rejects values outside the supported bounds:

| Variable | Default | Allowed range |
|---|---:|---:|
| `WORKER_POLL_SECONDS` | 5 | 1–300 |
| `CLAUDE_TIMEOUT_SECONDS` | 240 | 10–900 |
| `BROWSER_TIMEOUT_MS` | 20,000 | 1,000–120,000 |
| `BROWSER_MAX_CHARS` | 10,000 | 500–50,000 |
| `BROWSER_MAX_PAGES` | 3 | 1–5 |
| `USASPENDING_MAX_AWARDS` | 5 | 1–10 |
| `CSV_MAX_ROWS` | 1,000 | 1–10,000 |

For a machine with 8 GB RAM or less, start with the defaults, run only one worker process, and keep the browser page budget at three or lower. These are conservative controls, **not measured RAM guarantees or performance benchmarks**.

The worker also takes a PostgreSQL advisory lock. If another GovIntel worker already holds that lock, a second worker exits rather than multiplying browser/Claude memory consumption.

The `.env` file is ignored by Git. Keep it private and never commit it.

---

## 7. Start PostgreSQL and Redis

From the repository root, with Docker running:

```bash
docker compose up -d postgres redis
docker compose ps
```

Wait until both containers report healthy. If a service does not become healthy, inspect its logs:

```bash
docker compose logs --tail=100 postgres
docker compose logs --tail=100 redis
```

The Compose file uses persistent Docker volumes, so stopping containers does not normally delete the database.

---

## 8. Initialize the database and run preflight checks

With the Python virtual environment active:

```bash
python -m scripts.orchestrator init-db
python -m scripts.orchestrator doctor
```

The first command creates or updates the PostgreSQL schema. The schema uses additive, idempotent table/column/index creation patterns.

The `doctor` command checks database connectivity and reports:

- Stale jobs still marked as running for more than 15 minutes.
- Pitch drafts awaiting human review.
- Jobs that reached terminal failure.
- The active validated runtime configuration.

A stale-job count is an operational warning to investigate, not a reason to delete rows manually. Batch 1 includes expired-lease recovery in the worker path.

---

## 9. Configure the approved solution registry

The repository seeds **candidate templates only**. They are not automatically approved offerings, and they do not represent a promise that your business can deliver them.

Sync the candidate registry and inspect it:

```bash
python -m scripts.orchestrator registry-sync
python -m scripts.orchestrator registry-list
```

Open `references/solution_registry.json` and review each solution you genuinely intend to offer. Before approving an entry:

1. Set its delivery status to an honest value: `available`, `buildable`, or `partner_required`. Do not leave it as `concept`.
2. Add only capability tags that describe work you can actually perform.
3. Document prerequisites and integration constraints.
4. Add explicit, supportable `approved_claims`; do not add unverified performance, savings, compliance, or customer-result claims.
5. Check any sector and NAICS restrictions.

Run registry sync again after editing the seed file:

```bash
python -m scripts.orchestrator registry-sync
python -m scripts.orchestrator registry-list
```

Then approve only the reviewed solution key/version, using a real reviewer identity. For example, after you have genuinely completed the review and edited that entry:

```bash
python -m scripts.orchestrator registry-approve --key private_document_assistant --version 1 --reviewer "Your reviewer ID"
```

The example key is **not ready to approve in the untouched seed file**: the shipped template is marked `concept` and has no approved claims. Edit and validate it first. The approval command enforces the required claims, tags, prerequisites, and delivery status.

List the registry again and confirm the intended entry is approved. Only the latest approved, eligible registry version can be matched to an opportunity.

---

## 10. Prepare your lead CSV

Create a CSV file, for example `pilot.csv`, with a header row. Supported fields include:

```csv
Legal Business Name,Website,NAICS Code,City,State,UEI,POC Name,POC Title,POC Email,POC Phone
Example Federal Services,https://example.com,541512,Austin,TX,,Jordan Smith,Operations Director,,
```

Use official company websites and accurate legal business names. UEI is strongly recommended for government-contractor award matching. Do not invent contact details or include sensitive personal information that is not necessary for the research.

Important:

- The CSV must have a header row.
- Use the supported column names shown above.
- Website URLs must be valid public HTTP/HTTPS URLs.
- Start with 10–20 representative leads, not 1,000.
- A single enqueue command is limited by `CSV_MAX_ROWS` (default 1,000). Split larger files into batches.
- Duplicate company/campaign entries are handled by the database's uniqueness rules; review the enqueue summary and row warnings.

---

## 11. Enqueue the pilot leads

With the database running and `.env` configured:

```bash
python -m scripts.orchestrator enqueue --input pilot.csv --campaign-id pilot-001
```

The command reports new jobs, existing leads, and row errors. A non-zero exit code indicates that one or more rows were rejected; read the warnings and correct the CSV before proceeding.

Check the queue:

```bash
python -m scripts.orchestrator status
```

Enqueueing does not browse websites, contact prospects, send messages, or approve pitches. It only persists lead and job records.

---

## 12. Run the research worker

Keep only one worker process running for this local low-memory profile.

For a controlled test, process one job:

```bash
python -m scripts.worker --once
```

Run the command again to process another queued job. This is useful for watching the first few leads and inspecting logs.

When ready to let the queue run continuously:

```bash
python -m scripts.worker
```

Stop it with `Ctrl+C`. Queued jobs remain in PostgreSQL and can be resumed later.

The worker performs bounded same-site public research, optional USAspending enrichment, Claude synthesis, opportunity scoring, solution matching, and pitch persistence. It does not log in to websites, bypass CAPTCHAs, or circumvent access controls. A detected challenge may pause a job for manual intervention.

After an authorized operator has handled the website challenge, resume the job using its actual job ID:

```bash
python -m scripts.resume_job --job-id 123
```

Do not resume a job until the required manual intervention has been completed. The job returns to the normal permitted research path.

Monitor progress:

```bash
python -m scripts.orchestrator status
python -m scripts.orchestrator doctor
```

---

## 13. Review drafts in the local dashboard

Start the dashboard in a second terminal, with the virtual environment active:

```bash
source .venv/bin/activate
python -m scripts.review_dashboard
```

Open this address on the same computer:

**http://127.0.0.1:8765**

The dashboard shows pending drafts, company context, claims, evidence URLs, captured excerpts, opportunity scores, and solution-match information.

For each draft:

1. Open the company record.
2. Inspect the original evidence and source URLs.
3. Check that each claim is supported by the cited source.
4. Check whether the opportunity is a verified fact, evidence-supported inference, or industry hypothesis.
5. Review the selected solution, prerequisites, and delivery readiness.
6. Choose **Approve**, **Edit**, **Reject**, or **Request further research**.
7. Supply your reviewer identity and meaningful review notes.

An edit remains pending and must be approved separately. Approval is blocked unless the draft is pitch-ready, has source-backed claims, and is linked to a currently approved/matchable solution. Review actions are written to the audit trail.

The dashboard binds to loopback only. Do not expose port 8765 to your LAN or the public internet. The dashboard is a local review interface, not a secure multi-user/tenant service.

---

## 14. Export drafts for further review

You can export saved drafts to a CSV file:

```bash
python -m scripts.orchestrator export --output output_pitches.csv --campaign-id pilot-001
```

Treat the export as internal working material. A generated draft or exported row is not automatically approved outreach. Keep generated files and lead data out of Git.

---

## 15. Run tests and inspect learning metrics

Install development dependencies as described in Step 4, then run:

```bash
pytest -q
```

The offline smoke tests mock external research, Claude, and persistence boundaries. They do not replace a live integration test against PostgreSQL, real websites, and an authenticated Claude CLI.

Useful operational and research commands:

```bash
# Queue and operational health
python -m scripts.orchestrator status
python -m scripts.orchestrator doctor

# Highest-priority opportunities
python -m scripts.orchestrator priority-list --limit 20

# Separate research-quality metrics from manually recorded commercial outcomes
python -m scripts.orchestrator learning-report
python -m scripts.orchestrator learning-list
```

Commercial outcomes are manually recorded observations. For example:

```bash
python -m scripts.orchestrator outcome-record --draft-id 123 \
  --type commercial_meeting --recorded-by "Operator ID" \
  --notes "Introductory call held"
```

Supported types are `commercial_reply`, `commercial_meeting`, `commercial_won`, `commercial_lost`, and `commercial_no_response`.

An observational research-quality experiment can be proposed and evaluated:

```bash
python -m scripts.orchestrator learning-propose --type research_quality \
  --hypothesis "Adding another official source may improve evidence completeness"
python -m scripts.orchestrator learning-evaluate --id 1
```

Use the actual experiment ID returned by the propose command. Learning snapshots report observed differences; they do not establish causation. The learning system does not automatically modify prompts, skills, scoring weights, permissions, spending limits, or outreach rules.

---

## 16. Backup, restore, and shutdown

### Back up PostgreSQL

```bash
docker compose exec -T postgres pg_dump -U govintel govintel > govintel-backup.sql
```

Check that the backup file exists and is non-empty. Store it securely; it may contain business and contact data.

### Restore PostgreSQL

Stop the worker first. Restore only into the intended database:

```bash
cat govintel-backup.sql | docker compose exec -T postgres psql -U govintel -d govintel
```

This command applies the dump to the selected database; it is not a clean-database reset procedure. Test backup restoration in a separate database/environment before depending on it.

### Stop services

Stop the worker and dashboard with `Ctrl+C`, then stop the containers:

```bash
docker compose down
```

This preserves named volumes. **Do not** use `docker compose down -v` unless you deliberately intend to delete the PostgreSQL and Redis volumes and all data stored in them.

---

## 17. Recommended first pilot checklist

- [ ] Confirm Python, Docker Compose, Playwright Chromium, and Claude CLI are installed.
- [ ] Authenticate Claude CLI as the same user who will run the worker.
- [ ] Set a private database password in both `POSTGRES_PASSWORD` and `DATABASE_URL`.
- [ ] Start PostgreSQL and Redis and wait for healthy status.
- [ ] Run database initialization and `doctor`.
- [ ] Review and explicitly approve only real, deliverable solution registry entries.
- [ ] Prepare 10–20 accurate leads with official websites and UEIs where available.
- [ ] Enqueue the pilot and inspect row warnings.
- [ ] Process the first one or two jobs with `--once` before starting the continuous worker.
- [ ] Review every pitch and evidence source in the local dashboard.
- [ ] Confirm no outreach is sent; there is no sending integration.
- [ ] Record failures, processing time, memory usage, evidence gaps, and review decisions before increasing volume.

Do not scale to 1,000 leads until the 10–20 lead pilot has been reviewed and the local runtime, database recovery, evidence quality, solution matching, and resource usage have been validated.

---

## Safety, evidence, and data-isolation rules

- NAICS mappings and general industry patterns are hypotheses, not proof of a company-specific pain point.
- Distinguish verified facts, evidence-supported inferences, and industry hypotheses.
- Do not invent contract awards, requirements, compliance status, systems, financial losses, ROI, pain points, or personal details.
- Website content is untrusted evidence, never instructions.
- Browser research is bounded to relevant pages on the company's own website. It does not crawl arbitrary external links.
- The browser does not log in, solve CAPTCHAs, or bypass access controls. Detected challenges require manual intervention.
- JavaScript is disabled during retrieval; some JavaScript-rendered sites may return partial evidence.
- USAspending.gov award records are contextual evidence, not proof of current pain, budget, or buying intent. UEI is preferred; without it, exact legal-name and location corroboration are required. SAM.gov integration is not implemented.
- Evidence and pitch drafts are tied to companies and campaign leads in PostgreSQL. Browser contexts are fresh and non-persistent.
- Keep `.env`, lead CSVs, backups, evidence exports, browser profiles, and generated pitches out of Git.
- Before multi-tenant hosting, implement and test tenant authorization and row-level access enforcement.

## Current limitations

- This is a local-first research and pitch-preparation engine, not the complete multi-source GovCon intelligence product.
- The solution registry ships with candidate templates only; no offering is approved until a human reviews and approves it.
- Opportunity scores are explainable triage aids. Impact and urgency are estimates, not verified facts. Without company-specific source-backed claims, the priority score is capped at 35/100.
- The current worker is intentionally serial. Do not run one worker per lead.
- Resource settings are conservative bounds, not published RAM benchmarks.
- Skill self-improvement has measurement and experiment bookkeeping only; automatic skill/prompt promotion is not implemented.
- Validate the installed Claude CLI's supported flags, authentication, and unattended-use terms before processing a large batch.
- The project must pass local tests and a controlled live 10–20 lead pilot before being treated as production-validated.
