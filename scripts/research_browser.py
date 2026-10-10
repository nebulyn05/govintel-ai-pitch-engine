"""One-page public website research with SSRF and CAPTCHA safeguards."""
from __future__ import annotations
import ipaddress
import socket
from urllib.parse import urlparse
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


def _public_http_url(url: str) -> bool:
    try:
        parsed=urlparse(url)
        if parsed.scheme not in {"http","https"} or not parsed.hostname or parsed.username or parsed.password:
            return False
        host=parsed.hostname.rstrip(".")
        if host.lower() in {"localhost","localhost.localdomain"}:
            return False
        addresses={entry[4][0] for entry in socket.getaddrinfo(host,parsed.port or (443 if parsed.scheme=="https" else 80),type=socket.SOCK_STREAM)}
        return bool(addresses) and all(ipaddress.ip_address(addr).is_global for addr in addresses)
    except (ValueError,OSError):
        return False


def research_website(url: str, timeout_ms: int=20000, max_chars: int=10000) -> dict:
    """Read one public page only. No login, CAPTCHA solving, or link crawling."""
    if not url:
        return {"status":"skipped","reason":"No website supplied","evidence":[]}
    target=url.strip()
    if "://" not in target: target="https://"+target
    if not _public_http_url(target):
        return {"status":"blocked","reason":"Invalid URL or non-public address","evidence":[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(accept_downloads=False,service_workers="block",java_script_enabled=True,locale="en-US")
        def guard(route):
            if _public_http_url(route.request.url): route.continue_()
            else: route.abort("blockedbyclient")
        context.route("**/*",guard)
        page=context.new_page()
        try:
            response=page.goto(target,wait_until="domcontentloaded",timeout=timeout_ms)
            final_url=page.url
            if not _public_http_url(final_url):
                return {"status":"blocked","reason":"Redirect to non-public address blocked","evidence":[]}
            title=page.title()[:500]
            body=" ".join(page.locator("body").inner_text(timeout=5000).split())[:max_chars]
            lower=body.casefold()
            markers=("verify you are human","checking your browser","captcha","security challenge","unusual traffic","access denied")
            if any(marker in lower for marker in markers):
                return {"status":"awaiting_manual_intervention","reason":"Challenge or denial detected; no bypass attempted","evidence":[]}
            if not body:
                return {"status":"partial","reason":"No readable body text","evidence":[]}
            status_code=response.status if response is not None else None
            return {"status":"ok" if status_code is None or status_code<400 else "partial",
                "reason":"" if status_code is None or status_code<400 else f"HTTP status {status_code}",
                "evidence":[{"url":final_url,"title":title,"excerpt":body,
                    "metadata":{"http_status":status_code,"retrieval_method":"playwright_single_page"}}]}
        except PlaywrightTimeoutError:
            return {"status":"partial","reason":"Navigation timed out","evidence":[]}
        finally:
            context.close(); browser.close()
