-- PostgreSQL is authoritative; schema changes are additive and idempotent.
CREATE TABLE IF NOT EXISTS companies (
 id BIGSERIAL PRIMARY KEY, identity_key TEXT NOT NULL UNIQUE,
 normalized_name TEXT NOT NULL, website_domain TEXT NOT NULL DEFAULT '',
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS leads (
 id BIGSERIAL PRIMARY KEY, company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
 campaign_id TEXT NOT NULL DEFAULT 'local', company_name TEXT NOT NULL, website TEXT NOT NULL DEFAULT '',
 naics_code TEXT NOT NULL DEFAULT '', city TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT '',
 contact_name TEXT NOT NULL DEFAULT '', contact_title TEXT NOT NULL DEFAULT '',
 contact_email TEXT NOT NULL DEFAULT '', contact_phone TEXT NOT NULL DEFAULT '',
 source_row JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(company_id,campaign_id)
);
CREATE TABLE IF NOT EXISTS research_jobs (
 id BIGSERIAL PRIMARY KEY, lead_id BIGINT NOT NULL UNIQUE REFERENCES leads(id) ON DELETE RESTRICT,
 status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN
 ('queued','running','completed','awaiting_manual_intervention','failed_retryable','failed_final','cancelled')),
 attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
 available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), locked_at TIMESTAMPTZ,
 started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, last_error TEXT NOT NULL DEFAULT '',
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS research_jobs_dispatch_idx ON research_jobs(status,available_at,id);
CREATE INDEX IF NOT EXISTS leads_campaign_idx ON leads(campaign_id,id);
CREATE TABLE IF NOT EXISTS evidence_items (
 id BIGSERIAL PRIMARY KEY, company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
 lead_id BIGINT NOT NULL REFERENCES leads(id) ON DELETE RESTRICT,
 research_job_id BIGINT REFERENCES research_jobs(id) ON DELETE SET NULL,
 source_url TEXT NOT NULL, source_title TEXT NOT NULL DEFAULT '', excerpt TEXT NOT NULL DEFAULT '',
 evidence_type TEXT NOT NULL DEFAULT 'source_metadata' CHECK (evidence_type IN
 ('verified_fact','evidence_supported_inference','industry_hypothesis','source_metadata')),
 confidence NUMERIC(4,3) CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
 published_at TIMESTAMPTZ, retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 content_hash TEXT NOT NULL DEFAULT '', metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
 UNIQUE(lead_id,source_url,content_hash)
);
CREATE INDEX IF NOT EXISTS evidence_company_idx ON evidence_items(company_id,retrieved_at DESC);
CREATE TABLE IF NOT EXISTS opportunities (
 id BIGSERIAL PRIMARY KEY, company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
 lead_id BIGINT NOT NULL REFERENCES leads(id) ON DELETE RESTRICT,
 research_job_id BIGINT REFERENCES research_jobs(id) ON DELETE SET NULL,
 title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 evidence_type TEXT NOT NULL CHECK (evidence_type IN ('verified_fact','evidence_supported_inference','industry_hypothesis')),
 confidence NUMERIC(4,3) CHECK (confidence IS NULL OR (confidence BETWEEN 0 AND 1)),
 status TEXT NOT NULL DEFAULT 'candidate', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS solution_candidates (
 id BIGSERIAL PRIMARY KEY, company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
 lead_id BIGINT NOT NULL REFERENCES leads(id) ON DELETE RESTRICT,
 opportunity_id BIGINT REFERENCES opportunities(id) ON DELETE SET NULL,
 title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 delivery_status TEXT NOT NULL CHECK (delivery_status IN ('available','buildable','partner_required','concept','restricted')),
 feasibility_notes TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS pitch_drafts (
 id BIGSERIAL PRIMARY KEY, company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
 lead_id BIGINT NOT NULL REFERENCES leads(id) ON DELETE RESTRICT,
 research_job_id BIGINT REFERENCES research_jobs(id) ON DELETE SET NULL,
 version INTEGER NOT NULL DEFAULT 1,
 outcome TEXT NOT NULL CHECK (outcome IN ('pitch_ready','needs_further_research','do_not_pursue')),
 channel TEXT NOT NULL DEFAULT 'review_required', claims JSONB NOT NULL DEFAULT '[]'::jsonb,
 opportunity_summary TEXT NOT NULL DEFAULT '', proposed_solution TEXT NOT NULL DEFAULT '',
 pitch_text TEXT NOT NULL DEFAULT '', assumptions JSONB NOT NULL DEFAULT '[]'::jsonb,
 quality_checks JSONB NOT NULL DEFAULT '{}'::jsonb, approved_by TEXT, approved_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(lead_id,version)
);
CREATE TABLE IF NOT EXISTS outcomes (
 id BIGSERIAL PRIMARY KEY, company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
 lead_id BIGINT NOT NULL REFERENCES leads(id) ON DELETE RESTRICT,
 pitch_draft_id BIGINT REFERENCES pitch_drafts(id) ON DELETE SET NULL,
 outcome_type TEXT NOT NULL, outcome_value JSONB NOT NULL DEFAULT '{}'::jsonb,
 recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS skill_versions (
 id BIGSERIAL PRIMARY KEY, skill_name TEXT NOT NULL, version TEXT NOT NULL,
 content_hash TEXT NOT NULL, risk_class TEXT NOT NULL CHECK (risk_class IN ('low','medium','high')),
 status TEXT NOT NULL CHECK (status IN ('candidate','approved','rejected','rolled_back')),
 evaluation JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(skill_name,version)
);
CREATE TABLE IF NOT EXISTS learning_experiments (
 id BIGSERIAL PRIMARY KEY, experiment_type TEXT NOT NULL CHECK
 (experiment_type IN ('research_quality','commercial_outcome','skill_change')),
 hypothesis TEXT NOT NULL, baseline JSONB NOT NULL DEFAULT '{}'::jsonb,
 candidate JSONB NOT NULL DEFAULT '{}'::jsonb, result JSONB NOT NULL DEFAULT '{}'::jsonb,
 status TEXT NOT NULL DEFAULT 'proposed', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 completed_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS solution_registry (
 id BIGSERIAL PRIMARY KEY, solution_key TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 title TEXT NOT NULL, description TEXT NOT NULL,
 delivery_status TEXT NOT NULL CHECK (delivery_status IN ('available','buildable','partner_required','concept','restricted')),
 approved_claims JSONB NOT NULL DEFAULT '[]'::jsonb, requirements JSONB NOT NULL DEFAULT '{}'::jsonb,
 status TEXT NOT NULL DEFAULT 'candidate', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(solution_key,version)
);
