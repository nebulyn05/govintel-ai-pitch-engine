from datetime import datetime

from scripts.research_browser import (
    _link_score,
    _page_type,
    _same_site,
    extract_site_signals,
)


def test_detects_common_technology_signals():
    signals = extract_site_signals(
        '<script src="https://cdn.shopify.com/theme.js"></script>'
        '<script src="https://js.hs-scripts.com/123.js"></script>',
        "A company website with enough text to assess.",
    )
    assert signals["technology_signals"] == ["HubSpot", "Shopify"]
    assert "signal_caveat" in signals


def test_thin_content_is_a_signal_not_a_rejection():
    signals = extract_site_signals("<html></html>", "Only a few words here.")
    assert signals["content_thin_signal"] is True
    assert signals["meaningful_word_count"] < 150
    assert "do_not_pursue" not in signals


def test_old_copyright_is_reported_as_observation():
    old_year = datetime.now().year - 5
    signals = extract_site_signals("<html></html>", f"Copyright © {old_year} Example Inc.")
    assert signals["copyright_years"] == [old_year]
    assert signals["copyright_appears_old"] is True


def test_page_type_uses_path_semantics():
    assert _page_type("https://example.com/careers/openings") == "careers"
    assert _page_type("https://example.com/contact-us") == "contact"
    assert _page_type("https://example.com/") == "homepage"


def test_link_score_prefers_careers_and_contact_pages():
    assert _link_score("https://example.com/careers", "Join our team")[0] > 0
    assert _link_score("https://example.com/contact", "Contact")[0] > 0


def test_same_site_rejects_unrelated_domains():
    assert _same_site("https://careers.example.com/jobs", "https://example.com")
    assert not _same_site("https://example.com.attacker.test", "https://example.com")
    assert not _same_site("https://other.test", "https://example.com")
