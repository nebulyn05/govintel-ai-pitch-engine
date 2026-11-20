# Batch 7 — Local integration and 10–20 lead pilot

## Resource profile

The default profile is intentionally serial: run one worker process, use a three-page public-site budget per lead, cap page text at 10,000 characters, and cap USAspending enrichment at five awards. PostgreSQL and Redis have container memory limits in `docker-compose.yml`; Redis is provisioned but PostgreSQL remains the durable queue. Do not launch one process per lead.

The settings are validated by `scripts.runtime_config.RuntimeConfig`:

| Setting | Default | Bound |
|---|---:|---:|
| WORKER_POLL_SECONDS | 5 | 1–300 |
| CLAUDE_TIMEOUT_SECONDS | 240 | 10–900 |
| BROWSER_TIMEOUT_MS | 20,000 | 1,000–120,000 |
| BROWSER_MAX_CHARS | 10,000 | 500–50,000 |
| BROWSER_MAX_PAGES | 3 | 1–5 |
| USASPENDING_MAX_AWARDS | 5 | 0–10 |
| CSV_MAX_ROWS | 1,000 | 1–10,000 |

These are conservative configuration bounds, not measured RAM guarantees. Browser and Claude memory consumption depends on target sites and the installed Claude CLI.

## First-run setup (Kali Linux)

1. Install Docker Engine/Compose, Python 3.11+, and the Claude Code CLI. Authenticate Claude CLI interactively before running unattended jobs.
2. Create a virtual environment and install dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements-dev.txt
   playwright install chromium
   ```

3. Copy `.env.example` to `.env`, change the local database password, and ensure `DATABASE_URL` uses the same password.
4. Start the data services and initialize the schema:

   ```bash
   docker compose up -d postgres redis
   python -m scripts.orchestrator init-db
   python -m scripts.orchestrator registry-sync
   ```

5. Review candidate registry entries and approve only capabilities the business can actually deliver. Do not approve placeholder claims or hypothetical offerings.

## Pilot execution

Use 10–20 leads with valid company names, official websites, NAICS where known, and UEI where available. Keep a copy of the input CSV and note the campaign ID.

```bash
python -m scripts.orchestrator enqueue --input pilot.csv --campaign-id pilot-2026-01
python -m scripts.orchestrator status
python -m scripts.worker --once
# Repeat --once deliberately, or run one continuous worker:
python -m scripts.worker
python -m scripts.review_dashboard
```

Open the dashboard only on the same machine at `http://127.0.0.1:8765`. Review evidence and solution prerequisites before approving. Approval records an internal human decision; no email, CRM delivery, or outreach is sent.

## Validation

```bash
pytest -q
python -m scripts.orchestrator status
python -m scripts.orchestrator learning-report
python -m scripts.orchestrator priority-list --limit 20
```

The pipeline smoke test is offline and mocks the browser, Claude and persistence boundaries. A real pilot still requires a running PostgreSQL instance, an authenticated Claude CLI, and live public websites. Do not use production contacts or send outreach during validation.

## Safe shutdown and backup

Stop the worker with Ctrl+C; queued jobs remain in PostgreSQL. Stop the dashboard with Ctrl+C. Back up the database before schema changes:

```bash
docker compose exec -T postgres pg_dump -U govintel govintel > govintel-backup.sql
```

Restore only into a deliberately selected database after stopping workers:

```bash
cat govintel-backup.sql | docker compose exec -T postgres psql -U govintel -d govintel
```

Keep `.env`, lead CSVs, backups, evidence exports and generated pitches out of Git. Test a restore before relying on a backup.

## Validation limitations

Schema migration idempotence is checked statically in unit tests; actual migration reruns and restore must be verified against a running PostgreSQL instance. Resource limits are conservative defaults, not benchmark claims. GitHub Actions must pass before treating this batch as validated.
