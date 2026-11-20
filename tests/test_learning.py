from scripts.learning import _numeric_deltas


def test_numeric_deltas_are_recursive_and_ignore_non_numeric_values():
    before = {"drafts": {"total": 10, "approved": 2}, "label": "old"}
    after = {"drafts": {"total": 14, "approved": 5}, "label": "new"}
    assert _numeric_deltas(before, after) == {
        "drafts.total": 4.0,
        "drafts.approved": 3.0,
    }


def test_numeric_deltas_do_not_treat_booleans_as_counts():
    assert _numeric_deltas({"flag": True, "count": 1}, {"flag": False, "count": 3}) == {
        "count": 2.0
    }
