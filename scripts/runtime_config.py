"""Validated resource and timeout settings for small local deployments."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return value


@dataclass(frozen=True)
class RuntimeConfig:
    worker_poll_seconds: int = 5
    claude_timeout_seconds: int = 240
    browser_timeout_ms: int = 20_000
    browser_max_chars: int = 10_000
    browser_max_pages: int = 3
    usaspending_max_awards: int = 5
    csv_max_rows: int = 1_000

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        return cls(
            worker_poll_seconds=_integer("WORKER_POLL_SECONDS", 5, 1, 300),
            claude_timeout_seconds=_integer("CLAUDE_TIMEOUT_SECONDS", 240, 10, 900),
            browser_timeout_ms=_integer("BROWSER_TIMEOUT_MS", 20_000, 1_000, 120_000),
            browser_max_chars=_integer("BROWSER_MAX_CHARS", 10_000, 500, 50_000),
            browser_max_pages=_integer("BROWSER_MAX_PAGES", 3, 1, 5),
            usaspending_max_awards=_integer("USASPENDING_MAX_AWARDS", 5, 1, 10),
            csv_max_rows=_integer("CSV_MAX_ROWS", 1_000, 1, 10_000),
        )
