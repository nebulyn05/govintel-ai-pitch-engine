from unittest.mock import MagicMock, patch

import pytest

from scripts.review_dashboard import record_review


def _fake_connection(draft, matched=True):
    connection = MagicMock()
    draft_result = MagicMock()
    draft_result.fetchone.return_value = draft
    match_result = MagicMock()
    match_result.fetchone.return_value = {"ok": 1} if matched else None
    connection.execute.side_effect = [draft_result, match_result, MagicMock(), MagicMock()]
    context = MagicMock()
    context.__enter__.return_value = connection
    context.__exit__.return_value = False
    return context, connection


def _reviewable_draft():
    return {
        "id": 12, "company_id": 3, "lead_id": 7, "review_status": "pending",
        "outcome": "pitch_ready", "pitch_text": "A carefully qualified draft.",
        "proposed_solution": "Approved registry description",
        "quality_checks": {"source_backed_claims": True},
        "claims": [{
            "evidence_type": "verified_fact",
            "source_urls": ["https://example.com/source"],
        }],
    }


def test_human_approval_requires_source_backed_claim_and_current_solution_match():
    context, connection = _fake_connection(_reviewable_draft(), matched=True)
    with patch("scripts.review_dashboard.connect", return_value=context):
        record_review(12, "approve", "Pilot reviewer", "Evidence checked", "")
    assert connection.execute.call_count == 4
    update_sql = connection.execute.call_args_list[2].args[0]
    assert "approved_by" in update_sql
    audit_sql = connection.execute.call_args_list[3].args[0]
    assert "INSERT INTO outcomes" in audit_sql


def test_human_approval_is_blocked_without_registry_match():
    context, _ = _fake_connection(_reviewable_draft(), matched=False)
    with patch("scripts.review_dashboard.connect", return_value=context):
        with pytest.raises(ValueError, match="currently approved solution match"):
            record_review(12, "approve", "Pilot reviewer", "Evidence checked", "")


def test_human_approval_is_blocked_without_company_specific_source_claim():
    draft = _reviewable_draft()
    draft["claims"] = [{"evidence_type": "industry_hypothesis", "source_urls": ["https://example.com"]}]
    context, _ = _fake_connection(draft, matched=True)
    with patch("scripts.review_dashboard.connect", return_value=context):
        with pytest.raises(ValueError, match="source-backed claims"):
            record_review(12, "approve", "Pilot reviewer", "Evidence checked", "")
