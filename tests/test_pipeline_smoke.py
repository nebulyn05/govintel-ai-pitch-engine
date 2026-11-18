"""Offline smoke test for the worker's integrated lead-to-draft path."""
from unittest.mock import patch

from scripts import worker


def test_worker_persists_reviewable_pitch_without_outreach(monkeypatch):
    lead = {
        "id": 7, "company_name": "Example Federal Services", "website": "https://example.com",
        "naics_code": "541512", "city": "Austin", "state": "TX",
    }
    browser = {
        "status": "ok", "reason": "", "signals": {},
        "evidence": [{
            "url": "https://example.com/capabilities", "title": "Capabilities",
            "excerpt": "Publicly listed services", "evidence_type": "source_metadata",
        }],
    }
    payload = {
        "outcome": "pitch_ready", "channel": "email", "selected_solution_key": "doc_assistant",
        "claims": [{"claim": "The company lists services.", "evidence_type": "verified_fact",
                    "source_urls": ["https://example.com/capabilities"], "confidence": 0.9}],
        "opportunity_summary": "A possible document workflow opportunity.",
        "proposed_solution": "Registry description", "delivery_status": "buildable",
        "pitch_text": "Would a short discussion be useful?", "assumptions": [],
        "opportunities": [], "quality_checks": {"human_review_required": True},
    }
    registry = [{"solution_key": "doc_assistant", "description": "Approved registry description",
                 "delivery_status": "buildable"}]
    scored = [{
        "priority_score": 72, "scoring_version": "2.0", "evidence_quality": {"score": 80},
        "solution_matches": [{"solution_key": "doc_assistant"}],
    }]
    saved = {}

    monkeypatch.setenv("USASPENDING_ENABLED", "false")
    with patch.object(worker, "claim_next_job", return_value={"job_id": 11, "lead_id": 7, "attempts": 1, "max_attempts": 3}), \
         patch.object(worker, "get_lead", return_value=lead), \
         patch("scripts.orchestrator.load_blueprints", return_value={"default": {"sector": "Services"}}), \
         patch.object(worker, "research_website", return_value=browser), \
         patch.object(worker, "save_evidence"), \
         patch.object(worker, "get_approved_solutions", return_value=registry), \
         patch.object(worker, "call_claude", return_value=payload), \
         patch("scripts.opportunity_engine.score_opportunities", return_value=scored), \
         patch.object(worker, "save_opportunity_analysis", return_value=1), \
         patch.object(worker, "save_pitch", side_effect=lambda l, j, p: saved.update(payload=p)), \
         patch.object(worker, "fail_job") as fail_job:
        assert worker.process_one() is True

    assert saved["payload"]["outcome"] == "pitch_ready"
    assert saved["payload"]["proposed_solution"] == "Approved registry description"
    assert saved["payload"]["quality_checks"]["human_review_required"] is True
    assert saved["payload"]["quality_checks"]["opportunities_saved"] == 1
    fail_job.assert_not_called()
