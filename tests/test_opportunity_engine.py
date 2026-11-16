from scripts.opportunity_engine import match_approved_solutions, score_opportunities


def approved_solution(**overrides):
    row = {
        "id": 7,
        "solution_key": "doc_assistant",
        "version": 1,
        "title": "Document Assistant",
        "description": "Private document search",
        "delivery_status": "buildable",
        "status": "approved",
        "approved_claims": ["Can be scoped for approved document repositories."],
        "requirements": {
            "capability_tags": ["document_search", "knowledge_retrieval"],
            "supported_sectors": ["construction"],
            "prerequisites": ["Approved document corpus"],
        },
    }
    row.update(overrides)
    return row


def test_only_approved_and_non_restricted_solutions_are_matched():
    opportunity = {"capability_tags": ["document_search"]}
    registry = [
        approved_solution(),
        approved_solution(id=8, solution_key="candidate", status="candidate"),
        approved_solution(id=9, solution_key="restricted", delivery_status="restricted"),
    ]
    matches = match_approved_solutions(opportunity, "236220", "Construction", registry)
    assert [item["solution_key"] for item in matches] == ["doc_assistant"]


def test_company_specific_evidence_scores_higher_than_industry_hypothesis():
    claims = [
        {"evidence_type": "verified_fact", "confidence": 0.9, "source_urls": ["https://example.com/fact"]},
        {"evidence_type": "industry_hypothesis", "confidence": 0.9, "source_urls": []},
    ]
    proposed = [
        {"title": "Evidence-backed opportunity", "description": "Specific issue", "evidence_claim_indices": [0],
         "impact": "medium", "urgency": "medium", "capability_tags": ["document_search"]},
        {"title": "Industry-only hypothesis", "description": "Possible issue", "evidence_claim_indices": [1],
         "impact": "high", "urgency": "high", "capability_tags": ["document_search"]},
    ]
    result = score_opportunities(proposed, claims, [approved_solution()], "236220", "Construction")
    assert result[0]["title"] == "Evidence-backed opportunity"
    assert result[1]["priority_score"] <= 35
    assert result[1]["review_status"] == "needs_more_evidence"


def test_ambiguous_claim_indices_are_rejected():
    try:
        score_opportunities(
            [{"title": "x", "description": "y", "evidence_claim_indices": [4]}],
            [{"evidence_type": "verified_fact", "confidence": 1, "source_urls": ["https://example.com"]}],
            [],
        )
    except ValueError as exc:
        assert "invalid claim index" in str(exc)
    else:
        raise AssertionError("Invalid evidence reference was accepted")


def test_unapproved_solution_never_matches():
    candidate = approved_solution(status="candidate")
    assert not match_approved_solutions({"capability_tags": ["document_search"]}, "", "", [candidate])
