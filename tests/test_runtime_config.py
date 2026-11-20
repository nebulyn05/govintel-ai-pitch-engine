import pytest

from scripts.runtime_config import RuntimeConfig


def test_small_machine_defaults_are_bounded(monkeypatch):
    for key in (
        "WORKER_POLL_SECONDS", "CLAUDE_TIMEOUT_SECONDS", "BROWSER_TIMEOUT_MS",
        "BROWSER_MAX_CHARS", "BROWSER_MAX_PAGES", "USASPENDING_MAX_AWARDS", "CSV_MAX_ROWS",
    ):
        monkeypatch.delenv(key, raising=False)
    config = RuntimeConfig.from_env()
    assert config.browser_max_pages == 3
    assert config.usaspending_max_awards == 5
    assert config.csv_max_rows == 1000


@pytest.mark.parametrize("name,value", [
    ("BROWSER_MAX_PAGES", "0"),
    ("BROWSER_MAX_PAGES", "6"),
    ("WORKER_POLL_SECONDS", "0"),
    ("USASPENDING_MAX_AWARDS", "11"),
    ("CSV_MAX_ROWS", "-1"),
    ("BROWSER_TIMEOUT_MS", "not-a-number"),
])
def test_invalid_resource_settings_fail_fast(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        RuntimeConfig.from_env()
