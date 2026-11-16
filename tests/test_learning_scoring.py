from scripts.opportunity_engine import score_claim_evidence, score_opportunities


def test_independent_domains_add_bounded_corroboration_bonus():
    one = score_claim_evidence([{
        "evidence_type": "verified_fact", "confidence": 0.8,
        "source_urls": ["https://www.example.com/a", "https://example.com/b"],
    }])
    two = score_claim_evidence([{
        "evidence_type": "verified_fact", "confidence": 0.8,
        "source_urls": ["https://example.com/a", "https://agency.gov/b", "https://data.gov/c"],
    }])
    assert one["independent_source_count"] == 1
    assert two["independent_source_count"] == 3
    assert two["corroboration_bonus"] == 10
    assert two["score"] > one["score"]


def test_industry_hypothesis_does_not_become_company_specific_with_a_url():
    result = score_claim_evidence([{
        "evidence_type": "industry_hypothesis", "confidence": 1,
        "source_urls": ["https://example.com/industry-report"],
    }])
    assert result["company_specific"] is False


def test_opportunity_exposes_explainable_score_components():
    result = score_opportunities([{
        "title": "Document workflow", "description": "Observed document workflow evidence",
        "evidence_claim_indices": [0], "impact": "medium", "urgency": "low",
        "capability_tags": [],
    }], [{
        "evidence_type": "verified_fact", "confidence": 0.9,
        "source_urls": ["https://agency.gov/fact"],
    }], [])
    row = result[0]
    assert row["scoring_version"] == "2.0"
    assert row["evidence_quality"]["source_count"] == 1
    assert row["priority_score"] == round(
        .4 * row["evidence_score"] + .2 * row["impact_score"]
        + .2 * row["urgency_score"] + .2 * row["feasibility_score"], 2
    )
