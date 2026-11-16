from scripts.usaspending import (
    LookupResult, award_evidence_items, lookup_award_history,
    normalize_legal_name, normalize_uei,
)


class FakeResponse:
    def __init__(self, results):
        self._results = results

    def raise_for_status(self):
        return None

    def json(self):
        return {"results": self._results}


class FakeSession:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def post(self, url, json, timeout):
        self.calls.append((url, json, timeout))
        return FakeResponse(self.results)


def award(name="Acme Systems LLC", uei="ABC123456789", city="Austin", state="TX"):
    return {
        "Award ID": "CONT_AWD_123_0001",
        "Recipient Name": name,
        "Recipient UEI": uei,
        "Recipient Location": {"city_name": city, "state_code": state},
        "Award Amount": 250000,
        "Awarding Agency": "Department of Example",
        "Description": "IT support services",
        "Start Date": "2024-01-01",
        "End Date": "2025-01-01",
    }


def test_normalizers_are_conservative_and_stable():
    assert normalize_uei("abc-123 456 789") == "ABC123456789"
    assert normalize_legal_name("ACME Systems, LLC") == normalize_legal_name("Acme Systems Inc.")


def test_exact_uei_match_returns_awards_and_traceable_evidence():
    session = FakeSession([award()])
    lead = {"company_name": "Different Trading Name", "source_row": {"UEI": "ABC-123456789"}}
    result = lookup_award_history(lead, session=session)
    assert result.status == "matched"
    assert result.match_method == "exact_uei"
    assert len(result.awards) == 1
    evidence = award_evidence_items(result)[0]
    assert evidence["metadata"]["award_id"] == "CONT_AWD_123_0001"
    assert evidence["metadata"]["identity_match_confidence"] == 1.0
    assert "USAspending" in evidence["title"]
    assert session.calls[0][1]["filters"]["recipient_search_text"] == ["ABC123456789"]


def test_name_only_requires_location_corroboration():
    session = FakeSession([award()])
    result = lookup_award_history(
        {"company_name": "Acme Systems LLC", "city": "Austin", "state": "TX"},
        session=session,
    )
    assert result.status == "matched"
    assert result.match_method == "exact_legal_name_and_location"


def test_name_only_without_location_does_not_attach_awards():
    session = FakeSession([award()])
    result = lookup_award_history({"company_name": "Acme Systems LLC"}, session=session)
    assert result.status == "identity_unconfirmed"
    assert result.awards == []
    assert award_evidence_items(result) == []


def test_wrong_uei_never_falls_back_to_name():
    result = lookup_award_history(
        {"company_name": "Acme Systems LLC", "source_row": {"UEI": "ZZZ999999999"}},
        session=FakeSession([award()]),
    )
    assert result.status == "identity_unconfirmed"
    assert result.awards == []


def test_name_and_location_mismatch_is_rejected():
    result = lookup_award_history(
        {"company_name": "Acme Systems LLC", "city": "Dallas", "state": "TX"},
        session=FakeSession([award()]),
    )
    assert result.status == "identity_unconfirmed"



def test_multiple_awards_for_same_recipient_are_not_misclassified_as_ambiguous():
    first = award()
    second = award()
    second["Award ID"] = "CONT_AWD_456_0002"
    second["Award Amount"] = 100000
    result = lookup_award_history(
        {"company_name": "Acme Systems LLC", "city": "Austin", "state": "TX"},
        session=FakeSession([first, second]),
    )
    assert result.status == "matched"
    assert len(result.awards) == 2


def test_distinct_recipient_identities_with_same_name_and_location_are_ambiguous():
    first = award(uei="ABC123456789")
    second = award(uei="XYZ987654321")
    result = lookup_award_history(
        {"company_name": "Acme Systems LLC", "city": "Austin", "state": "TX"},
        session=FakeSession([first, second]),
    )
    assert result.status == "ambiguous"
    assert result.awards == []

def test_lookup_audit_records_no_match_status():
    from scripts.usaspending import lookup_evidence_item
    result = LookupResult("identity_unconfirmed", "legal_name_only", 0, None, [],
                          "Acme Systems LLC", "Need UEI.")
    item = lookup_evidence_item(result)
    assert item["metadata"]["lookup_status"] == "identity_unconfirmed"
    assert item["metadata"]["awards_attached"] == 0
