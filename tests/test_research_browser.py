from unittest.mock import patch

from scripts.research_browser import _public_http_url


def test_blocks_localhost_without_dns_lookup():
    with patch("scripts.research_browser.socket.getaddrinfo") as lookup:
        assert _public_http_url("http://localhost") is False
        lookup.assert_not_called()


def test_blocks_non_http_and_credentials():
    assert _public_http_url("file:///etc/passwd") is False
    assert _public_http_url("https://user:pass@example.com") is False


def test_blocks_nonstandard_ports():
    assert _public_http_url("https://example.com:8443") is False


def test_blocks_private_dns_resolution():
    with patch(
        "scripts.research_browser.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("10.0.0.8", 443))],
    ):
        assert _public_http_url("https://internal.example") is False


def test_accepts_public_dns_resolution():
    with patch(
        "scripts.research_browser.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
    ):
        assert _public_http_url("https://example.com") is True


def test_rejects_mixed_public_and_private_dns_answers():
    with patch(
        "scripts.research_browser.socket.getaddrinfo",
        return_value=[
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("192.168.1.10", 443)),
        ],
    ):
        assert _public_http_url("https://example.com") is False
