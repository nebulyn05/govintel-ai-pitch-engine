from scripts.worker import validate_payload


def valid_payload():
    return {
        "outcome": "pitch_ready",
        "channel": "email",
        "claims": [{
            "claim": "The company lists federal contract services.",
            "evidence_type": "verified_fact",
            "source_urls": ["https://example.com/capabilities"],
            "confidence": 0.9,
        }],
        "opportunity_summary": "A potential workflow opportunity.",
        "proposed_solution": "A reviewable automation concept.",
        "delivery_status": "concept",
        "pitch_text": "Would a short discussion be useful?",
        "assumptions": [],
        "quality_checks": {"human_review_required": True},
    }


def test_pitch_ready_requires_source_backed_company_claim():
    payload = validate_payload(valid_payload(), {"https://example.com/capabilities"})
    assert payload["outcome"] == "pitch_ready"
    assert payload["quality_checks"]["source_backed_claims"] is True


def test_unverified_source_downgrades_pitch_ready():
    payload = validate_payload(valid_payload(), {"https://example.com"})
    assert payload["outcome"] == "needs_further_research"
    assert payload["quality_checks"]["unsupported_source_urls"] == ["https://example.com/capabilities"]


def test_industry_hypothesis_cannot_make_pitch_ready():
    payload = valid_payload()
    payload["claims"][0]["evidence_type"] = "industry_hypothesis"
    payload = validate_payload(payload, {"https://example.com/capabilities"})
    assert payload["outcome"] == "needs_further_research"


def test_malformed_claim_is_rejected():
    payload = valid_payload()
    payload["claims"] = ["not a claim"]
    try:
        validate_payload(payload, {"https://example.com/capabilities"})
    except RuntimeError as exc:
        assert "malformed" in str(exc)
    else:
        raise AssertionError("Malformed claim should be rejected")


def test_missing_human_review_guard_is_rejected():
    payload = valid_payload()
    payload["quality_checks"]["human_review_required"] = False
    try:
        validate_payload(payload, {"https://example.com/capabilities"})
    except RuntimeError as exc:
        assert "human-review" in str(exc)
    else:
        raise AssertionError("Missing human-review guard should be rejected")


def test_unknown_delivery_status_is_rejected():
    payload = valid_payload()
    payload["delivery_status"] = "already deployed"
    try:
        validate_payload(payload, {"https://example.com/capabilities"})
    except RuntimeError as exc:
        assert "delivery_status" in str(exc)
    else:
        raise AssertionError("Unknown delivery status should be rejected")
