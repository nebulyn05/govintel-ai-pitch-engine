"""Bounded public USAspending.gov award-history lookup with conservative identity matching."""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_BASE = "https://api.usaspending.gov/api/v2"
AWARD_SEARCH_URL = f"{API_BASE}/search/spending_by_award/"
AWARD_TYPES = ["A", "B", "C", "D", "IDV_A", "IDV_B", "IDV_B_A", "IDV_B_B", "IDV_B_C", "IDV_C", "IDV_D", "IDV_E"]
FIELDS = [
    "Award ID", "Recipient Name", "Recipient UEI", "Recipient Location",
    "Award Amount", "Start Date", "End Date", "Period of Performance Start Date",
    "Period of Performance Current End Date", "Awarding Agency", "Awarding Sub Agency",
    "Funding Agency", "Funding Sub Agency", "Description", "Contract Award Type",
    "NAICS", "PSC", "Base Obligation Date", "Last Modified Date",
]
DEFAULT_TIMEOUT = (5, 25)


@dataclass
class LookupResult:
    status: str
    match_method: str
    match_confidence: float
    recipient: dict[str, Any] | None
    awards: list[dict[str, Any]]
    query: str
    message: str = ""


def _session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=2, connect=2, read=2, backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["POST"]),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retries, pool_connections=2, pool_maxsize=2))
    session.headers.update({
        "User-Agent": "GovIntel-AI-Pitch-Engine/0.3 (public-data research)",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    return session


def normalize_uei(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def normalize_legal_name(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", " ", (value or "").casefold())
    tokens = value.split()
    suffixes = {"inc", "incorporated", "llc", "l.l.c", "lp", "llp", "ltd", "limited", "corp", "corporation", "co", "company"}
    while tokens and tokens[-1] in suffixes:
        tokens.pop()
    return " ".join(tokens)


def _location_parts(value: Any) -> tuple[str, str]:
    if isinstance(value, dict):
        city = value.get("city_name") or value.get("city") or value.get("city_name_display") or ""
        state = value.get("state_code") or value.get("state") or value.get("state_name") or ""
        return str(city).strip().casefold(), str(state).strip().casefold()
    return "", ""


def _lead_uei(lead: dict[str, Any]) -> str:
    row = lead.get("source_row") or {}
    for key in ("UEI", "uei", "Unique Entity ID", "Unique Entity Identifier", "Recipient UEI"):
        value = row.get(key) if isinstance(row, dict) else None
        if value:
            return normalize_uei(str(value))
    return ""


def _request_awards(search_term: str, limit: int, session: requests.Session) -> list[dict[str, Any]]:
    payload = {
        "filters": {
            "recipient_search_text": [search_term],
            "award_type_codes": AWARD_TYPES,
        },
        "fields": FIELDS,
        "page": 1,
        "limit": limit,
        "sort": "Award Amount",
        "order": "desc",
        "subawards": False,
    }
    response = session.post(AWARD_SEARCH_URL, json=payload, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("results", []), list):
        raise ValueError("USAspending returned an unexpected award-search response.")
    return data.get("results", [])


def lookup_award_history(
    lead: dict[str, Any],
    limit: int | None = None,
    session: requests.Session | None = None,
) -> LookupResult:
    """Search by UEI first; otherwise require exact legal-name and location corroboration."""
    limit = max(1, min(int(limit or os.getenv("USASPENDING_MAX_AWARDS", "5")), 10))
    company_name = str(lead.get("company_name") or "").strip()
    uei = _lead_uei(lead)
    query = uei or company_name
    if not query:
        return LookupResult("not_searched", "none", 0.0, None, [], "", "No legal name or UEI supplied.")
    if not uei and len(normalize_legal_name(company_name)) < 4:
        return LookupResult("insufficient_identity", "none", 0.0, None, [], query,
                            "Company name is too short for a safe recipient match.")

    client = session or _session()
    results = _request_awards(query, limit, client)
    if not results:
        return LookupResult("no_awards_found", "uei" if uei else "legal_name_location", 0.0,
                            None, [], query, "No matching federal awards were returned.")

    if uei:
        matches = [row for row in results if normalize_uei(str(row.get("Recipient UEI") or "")) == uei]
        if not matches:
            return LookupResult("identity_unconfirmed", "uei", 0.0, None, [], query,
                                "Search results did not contain an exact UEI match.")
        recipient = {
            "name": matches[0].get("Recipient Name"),
            "uei": uei,
            "location": matches[0].get("Recipient Location"),
        }
        return LookupResult("matched", "exact_uei", 1.0, recipient, matches, query,
                            "Recipient UEI matched exactly.")

    target_name = normalize_legal_name(company_name)
    target_city = str(lead.get("city") or "").strip().casefold()
    target_state = str(lead.get("state") or "").strip().casefold()
    exact_name = [row for row in results if normalize_legal_name(str(row.get("Recipient Name") or "")) == target_name]
    corroborated = []
    for row in exact_name:
        city, state = _location_parts(row.get("Recipient Location"))
        city_ok = not target_city or not city or city == target_city
        state_ok = not target_state or not state or state == target_state
        has_location_corroboration = bool(
            (target_city and city and city == target_city) or
            (target_state and state and state == target_state)
        )
        if city_ok and state_ok and has_location_corroboration:
            corroborated.append(row)

    if len(corroborated) == 1:
        row = corroborated[0]
        recipient = {"name": row.get("Recipient Name"), "uei": row.get("Recipient UEI"),
                     "location": row.get("Recipient Location")}
        return LookupResult("matched", "exact_legal_name_and_location", 0.90,
                            recipient, corroborated, query,
                            "Exact normalized legal name plus location corroboration.")
    if len(corroborated) > 1:
        return LookupResult("ambiguous", "exact_legal_name_and_location", 0.0, None, [],
                            query, "Multiple recipient records share the supplied identity.")
    return LookupResult("identity_unconfirmed", "legal_name_only", 0.0, None, [],
                        query, "Name-only results are not attached to this lead; provide UEI or corroborating location.")


def award_evidence_items(result: LookupResult) -> list[dict[str, Any]]:
    """Convert matched award records into compact, traceable evidence rows."""
    items: list[dict[str, Any]] = []
    if result.status != "matched":
        return items
    for award in result.awards:
        award_id = str(award.get("Award ID") or "").strip()
        if not award_id:
            continue
        recipient = result.recipient or {}
        url = f"https://www.usaspending.gov/award/{quote(award_id, safe='')}"
        details = {
            "source": "USAspending.gov",
            "source_url": url,
            "award_id": award_id,
            "recipient_name": award.get("Recipient Name"),
            "recipient_uei": award.get("Recipient UEI"),
            "recipient_location": award.get("Recipient Location"),
            "identity_match_method": result.match_method,
            "identity_match_confidence": result.match_confidence,
            "awarding_agency": award.get("Awarding Agency"),
            "awarding_sub_agency": award.get("Awarding Sub Agency"),
            "funding_agency": award.get("Funding Agency"),
            "funding_sub_agency": award.get("Funding Sub Agency"),
            "award_amount": award.get("Award Amount"),
            "start_date": award.get("Start Date") or award.get("Period of Performance Start Date"),
            "end_date": award.get("End Date") or award.get("Period of Performance Current End Date"),
            "description": award.get("Description"),
            "contract_award_type": award.get("Contract Award Type"),
            "naics": award.get("NAICS"),
            "psc": award.get("PSC"),
            "base_obligation_date": award.get("Base Obligation Date"),
            "last_modified_date": award.get("Last Modified Date"),
        }
        summary = (
            f"Federal award {award_id}; recipient {award.get('Recipient Name')}; "
            f"awarding agency {award.get('Awarding Agency') or 'not stated'}; "
            f"amount {award.get('Award Amount') if award.get('Award Amount') is not None else 'not stated'}; "
            f"period {details['start_date'] or 'unknown'} to {details['end_date'] or 'unknown'}. "
            f"Description: {str(award.get('Description') or '')[:2500]}"
        )
        items.append({
            "url": url,
            "title": f"USAspending award {award_id}",
            "excerpt": summary,
            "metadata": details,
        })
    return items


def lookup_evidence_item(result: LookupResult) -> dict[str, Any]:
    """Persist a search audit even when no award is safely attributable to the lead."""
    return {
        "url": f"https://www.usaspending.gov/search/?hash={quote(result.query, safe='')}",
        "title": "USAspending recipient lookup",
        "excerpt": f"USAspending lookup status: {result.status}. {result.message}",
        "metadata": {
            "source": "USAspending.gov",
            "lookup_status": result.status,
            "match_method": result.match_method,
            "match_confidence": result.match_confidence,
            "query": result.query,
            "recipient": result.recipient,
            "returned_award_count": len(result.awards),
            "awards_attached": len(award_evidence_items(result)),
            "note": "Award history is contextual evidence, not proof of a current pain point or buying intent.",
        },
    }
