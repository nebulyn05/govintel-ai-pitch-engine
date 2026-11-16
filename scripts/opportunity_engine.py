"""Explainable opportunity scoring with source corroboration and evidence quality."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

EVIDENCE_TYPES = {"verified_fact", "evidence_supported_inference", "industry_hypothesis"}
LEVELS = {"low": 25.0, "medium": 60.0, "high": 100.0}
MATCHABLE_DELIVERY = {"available", "buildable", "partner_required"}
SCORING_VERSION = "2.0"


def _tags(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {str(value).strip().casefold().replace(" ", "_") for value in values if str(value).strip()}


def _claim_indices(opportunity: dict, claims: list[dict]) -> list[int]:
    raw = opportunity.get("evidence_claim_indices", [])
    if not isinstance(raw, list):
        raise ValueError("evidence_claim_indices must be an array.")
    indices = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value >= len(claims):
            raise ValueError("Opportunity references an invalid claim index.")
        if value not in indices:
            indices.append(value)
    return indices


def _source_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ""
        return parsed.hostname.casefold().removeprefix("www.")
    except (TypeError, ValueError):
        return ""


def score_claim_evidence(claims: list[dict]) -> dict:
    """Score claim grounding separately from model-estimated impact and urgency."""
    if not claims:
        return {"score": 0.0, "company_specific": False, "claim_count": 0,
                "source_count": 0, "distinct_source_domain_count": 0,
                "corroboration_bonus": 0.0, "mean_confidence": 0.0}
    weights = {"verified_fact": 1.0, "evidence_supported_inference": 0.75,
               "industry_hypothesis": 0.20}
    values, domains, urls_seen, confidences = [], set(), set(), []
    has_company_specific = False
    for claim in claims:
        kind = claim.get("evidence_type")
        confidence = min(1.0, max(0.0, float(claim.get("confidence", 0) or 0)))
        confidences.append(confidence)
        urls = claim.get("source_urls") or []
        valid_domains = {_source_domain(url) for url in urls if isinstance(url, str)}
        valid_domains.discard("")
        source_backed = bool(valid_domains) and kind in {
            "verified_fact", "evidence_supported_inference"
        }
        if source_backed:
            has_company_specific = True
            domains.update(valid_domains)
            urls_seen.update(url for url in urls if isinstance(url, str))
        values.append(confidence * weights.get(kind, 0.0) * 100)
    base = sum(values) / len(values)
    bonus = min(15.0, max(0, len(domains) - 1) * 5.0)
    return {
        "score": round(min(100.0, base + bonus), 2),
        "company_specific": has_company_specific,
        "claim_count": len(claims),
        "source_count": len(urls_seen),
        "distinct_source_domain_count": len(domains),
        "corroboration_bonus": round(bonus, 2),
        "mean_confidence": round(sum(confidences) / len(confidences), 3),
    }


def _evidence_score(claims: list[dict]) -> tuple[float, bool]:
    result = score_claim_evidence(claims)
    return result["score"], result["company_specific"]


def match_approved_solutions(
    opportunity: dict, naics_code: str, sector: str, registry: list[dict],
) -> list[dict]:
    wanted = _tags(opportunity.get("capability_tags"))
    matches = []
    for solution in registry:
        if solution.get("status") != "approved" or solution.get("delivery_status") not in MATCHABLE_DELIVERY:
            continue
        requirements = solution.get("requirements") or {}
        supported_naics = _tags(requirements.get("supported_naics"))
        supported_sectors = _tags(requirements.get("supported_sectors"))
        solution_tags = _tags(requirements.get("capability_tags"))
        overlap = wanted & solution_tags
        if not overlap:
            continue
        industry_match = (
            not supported_naics and not supported_sectors
            or naics_code.casefold() in supported_naics
            or bool(_tags([sector]) & supported_sectors)
        )
        if not industry_match:
            continue
        tag_score = len(overlap) / max(1, len(wanted)) * 70
        score = min(100.0, tag_score + (30 if industry_match else 0))
        matches.append({
            "registry_id": solution["id"], "solution_key": solution["solution_key"],
            "version": solution["version"], "title": solution["title"],
            "description": solution["description"], "delivery_status": solution["delivery_status"],
            "match_score": round(score, 2), "matched_capability_tags": sorted(overlap),
            "industry_match": industry_match, "prerequisites": requirements.get("prerequisites", []),
            "approved_claims": solution.get("approved_claims", []),
        })
    return sorted(matches, key=lambda item: (-item["match_score"], item["solution_key"]))[:5]


def score_opportunities(
    proposed: list[dict], claims: list[dict], registry: list[dict],
    naics_code: str = "", sector: str = "",
) -> list[dict]:
    if not isinstance(proposed, list):
        raise ValueError("opportunities must be an array.")
    scored = []
    for item in proposed[:10]:
        if not isinstance(item, dict):
            raise ValueError("Every opportunity must be an object.")
        title, description = str(item.get("title") or "").strip(), str(item.get("description") or "").strip()
        if not title or not description:
            raise ValueError("Every opportunity needs a title and description.")
        indices = _claim_indices(item, claims)
        linked_claims = [claims[index] for index in indices]
        if any(claim.get("evidence_type") not in EVIDENCE_TYPES for claim in linked_claims):
            raise ValueError("Opportunity references a claim with an invalid evidence type.")
        quality = score_claim_evidence(linked_claims)
        evidence_score, company_specific = quality["score"], quality["company_specific"]
        impact, urgency = str(item.get("impact") or "low").casefold(), str(item.get("urgency") or "low").casefold()
        if impact not in LEVELS or urgency not in LEVELS:
            raise ValueError("Opportunity impact and urgency must be low, medium, or high.")
        matches = match_approved_solutions(item, naics_code, sector, registry)
        feasibility = matches[0]["match_score"] if matches else 0.0
        impact_score, urgency_score = LEVELS[impact], LEVELS[urgency]
        score = 0.40 * evidence_score + 0.20 * impact_score + 0.20 * urgency_score + 0.20 * feasibility
        if not company_specific:
            score = min(score, 35.0)
        scored.append({
            "title": title[:300], "description": description[:4000],
            "evidence_type": (
                "verified_fact" if linked_claims and all(c.get("evidence_type") == "verified_fact" for c in linked_claims)
                else "evidence_supported_inference" if company_specific else "industry_hypothesis"
            ),
            "confidence": round(min(1.0, max(0.0, float(item.get("confidence", evidence_score / 100)))), 3),
            "evidence_claim_indices": indices, "impact": impact, "urgency": urgency,
            "evidence_score": evidence_score, "evidence_quality": quality,
            "scoring_version": SCORING_VERSION, "impact_score": impact_score,
            "urgency_score": urgency_score, "feasibility_score": round(feasibility, 2),
            "priority_score": round(score, 2),
            "review_status": "needs_review" if company_specific else "needs_more_evidence",
            "company_specific_evidence": company_specific, "solution_matches": matches,
            "capability_tags": sorted(_tags(item.get("capability_tags"))),
            "buyer_role": str(item.get("buyer_role") or "")[:200],
        })
    return sorted(scored, key=lambda item: item["priority_score"], reverse=True)
