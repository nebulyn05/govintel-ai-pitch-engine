"""Adaptive, bounded public-site research with SSRF and challenge safeguards."""
from __future__ import annotations

import ipaddress
import re
import socket
from collections import Counter
from urllib.parse import urljoin, urlparse, urldefrag, urlunparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

PAGE_HINTS = {
    "careers": ("career", "careers", "jobs", "employment", "join-us", "work-with-us"),
    "contact": ("contact", "get-in-touch", "intake", "request-a-quote", "request-info"),
    "capabilities": ("capabilit", "services", "solutions", "products", "what-we-do"),
    "about": ("about", "company", "who-we-are"),
}
FALLBACK_PATHS = (
    ("/careers", "careers"), ("/jobs", "careers"),
    ("/contact", "contact"), ("/contact-us", "contact"),
    ("/capabilities", "capabilities"), ("/services", "capabilities"),
    ("/about", "about"),
)
TECH_PATTERNS = {
    "WordPress": (r"wp-content", r"wp-includes", r"wordpress"),
    "Shopify": (r"cdn\.shopify\.com", r"shopify\.theme", r"myshopify\.com"),
    "HubSpot": (r"js\.hs-scripts\.com", r"js\.hsforms\.net", r"hubspot"),
    "Wix": (r"wixstatic\.com", r"wix\.com"),
    "Squarespace": (r"squarespace\.com", r"squarespace-cdn"),
    "Webflow": (r"webflow\.com", r"website-files\.com"),
    "Drupal": (r"drupalsettings", r"/sites/default/files/"),
    "Google Analytics": (r"google-analytics\.com", r"googletagmanager\.com"),
    "Calendly": (r"calendly\.com"),
}


def _public_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return False
        if parsed.port not in (None, 80, 443):
            return False
        host = parsed.hostname.rstrip(".")
        if host.lower() in {"localhost", "localhost.localdomain"}:
            return False
        addresses = {
            entry[4][0]
            for entry in socket.getaddrinfo(
                host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM
            )
        }
        return bool(addresses) and all(ipaddress.ip_address(address).is_global for address in addresses)
    except (ValueError, OSError):
        return False


def _page_type(url: str) -> str:
    path = urlparse(url).path.casefold()
    for kind, hints in PAGE_HINTS.items():
        if any(hint in path for hint in hints):
            return kind
    return "homepage" if path in {"", "/"} else "other"


def _link_score(url: str, label: str, industry_hint: str = "") -> tuple[int, str]:
    value = (urlparse(url).path + " " + label).casefold()
    scores = []
    for kind, hints in PAGE_HINTS.items():
        score = sum(4 for hint in hints if hint in value)
        if kind == "capabilities" and industry_hint:
            score += sum(1 for word in re.findall(r"[a-z]{4,}", industry_hint.casefold()) if word in value)
        scores.append((score, kind))
    return max(scores, default=(0, "other"))


def extract_site_signals(html: str, text: str) -> dict:
    """Extract weak technical/site-quality signals; none is a business pain-point claim."""
    source = (html or "").casefold()
    technologies = sorted(
        name for name, patterns in TECH_PATTERNS.items()
        if any(re.search(pattern, source) for pattern in patterns)
    )
    years = [int(value) for value in re.findall(r"(?:©|copyright|copyright\s*©?)\s*(20\d{2})", text or "", re.I)]
    current_year = __import__("datetime").datetime.now().year
    words = re.findall(r"\b[\w'-]+\b", text or "")
    meaningful = [word for word in words if len(word.strip("'-")) > 2]
    return {
        "technology_signals": technologies,
        "copyright_years": sorted(set(years)),
        "copyright_appears_old": bool(years and max(years) < current_year - 2),
        "meaningful_word_count": len(meaningful),
        "content_thin_signal": len(meaningful) < 150,
        "signal_caveat": "Technical and content signals are observations only; they do not establish business need, viability, or a reason to reject a lead.",
    }


def _same_site(candidate: str, origin: str) -> bool:
    try:
        host = (urlparse(candidate).hostname or "").lower().rstrip(".")
        root = (urlparse(origin).hostname or "").lower().rstrip(".")
        return bool(host and root and (host == root or host.endswith("." + root)))
    except ValueError:
        return False


def _challenge(body: str) -> bool:
    lower = body.casefold()
    return any(marker in lower for marker in (
        "verify you are human", "checking your browser", "captcha",
        "security challenge", "unusual traffic", "access denied",
    ))


def research_website(
    url: str, timeout_ms: int = 20000, max_chars: int = 10000,
    max_pages: int = 3, industry_hint: str = "",
) -> dict:
    """Read a small set of relevant public pages; never log in or bypass access controls."""
    if timeout_ms < 1000 or max_chars < 100 or max_pages < 1 or max_pages > 5:
        raise ValueError("timeout_ms >= 1000, max_chars >= 100, and max_pages 1..5 are required")
    if not url:
        return {"status": "skipped", "reason": "No website supplied", "evidence": [], "signals": {}}
    target = url.strip()
    if "://" not in target:
        target = "https://" + target
    if not _public_http_url(target):
        return {"status": "blocked", "reason": "Invalid URL or non-public address", "evidence": [], "signals": {}}

    evidence: list[dict] = []
    seen: set[str] = set()
    candidates: dict[str, tuple[int, str]] = {}
    aggregate = Counter()
    signal_records = []
    failures = []
    origin_host = urlparse(target).hostname or ""

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                accept_downloads=False, service_workers="block", java_script_enabled=False, locale="en-US"
            )

            def guard(route):
                if _public_http_url(route.request.url) and _same_site(route.request.url, target):
                    route.continue_()
                else:
                    route.abort("blockedbyclient")

            context.route("**/*", guard)
            page = context.new_page()
            queue = [target]
            try:
                while queue and attempted < max_pages:
                    current = queue.pop(0)
                    current = urldefrag(current)[0]
                    if current in seen:
                        continue
                    seen.add(current)
                    if not _same_site(current, target) or not _public_http_url(current):
                        continue
                    attempted += 1
                    try:
                        response = page.goto(current, wait_until="domcontentloaded", timeout=timeout_ms)
                        final_url = urldefrag(page.url)[0]
                        if not _public_http_url(final_url) or not _same_site(final_url, target):
                            failures.append("Redirect outside original site blocked")
                            continue
                        body = " ".join(page.locator("body").inner_text(timeout=5000).split())
                        if _challenge(body):
                            return {
                                "status": "awaiting_manual_intervention",
                                "reason": "Challenge or denial detected; no bypass attempted",
                                "evidence": [], "signals": {},
                            }
                        html = page.content()
                        title = page.title()[:500]
                        signals = extract_site_signals(html, body)
                        page_kind = _page_type(final_url)
                        signals["page_type"] = page_kind
                        signal_records.append({"url": final_url, **signals})
                        for technology in signals["technology_signals"]:
                            aggregate[technology] += 1
                        excerpt = body[:max_chars]
                        if excerpt:
                            evidence.append({
                                "url": final_url, "title": title, "excerpt": excerpt,
                                "metadata": {
                                    "http_status": response.status if response is not None else None,
                                    "retrieval_method": "playwright_adaptive_same_site",
                                    "page_type": page_kind, "site_signals": signals,
                                },
                            })
                        if len(evidence) == 1:
                            for anchor in page.locator("a[href]").evaluate_all(
                                "(els) => els.map(a => ({href:a.href,label:(a.innerText||a.getAttribute('aria-label')||'').trim()}))"
                            ):
                                href = anchor.get("href", "")
                                if not href or not _same_site(href, target):
                                    continue
                                score, kind = _link_score(href, anchor.get("label", ""), industry_hint)
                                if score:
                                    candidates[urldefrag(href)[0]] = (score, kind)
                            for path, kind in FALLBACK_PATHS:
                                parsed_origin = urlparse(target)\n                                site_root = urlunparse((parsed_origin.scheme, parsed_origin.netloc, "/", "", "", ""))\n                                fallback = urljoin(site_root, path.lstrip("/"))
                                candidates.setdefault(fallback, (1, kind))
                            ordered = sorted(candidates.items(), key=lambda item: (-item[1][0], item[0]))
                            queue.extend(candidate for candidate, _ in ordered[:12] if candidate not in seen)
                    except PlaywrightTimeoutError:
                        failures.append(f"Navigation timed out: {current}")
                    except Exception as exc:
                        failures.append(f"Page retrieval failed ({current}): {type(exc).__name__}")
                status = "ok" if evidence and not failures else ("partial" if evidence or failures else "blocked")
                return {
                    "status": status,
                    "reason": "; ".join(failures[:5]),
                    "evidence": evidence,
                    "signals": {
                        "pages_visited": len(evidence),\n                        "page_attempts": attempted,
                        "technology_signals": sorted(aggregate),
                        "page_signals": signal_records,
                        "signals_are_not_pain_points": True,
                        "candidate_pages_discovered": len(candidates),
                    },
                }
            finally:
                context.close()
        finally:
            browser.close()
