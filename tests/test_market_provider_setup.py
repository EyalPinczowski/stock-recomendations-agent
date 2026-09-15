"""Without an IANA time-zone database yfinance can't timestamp anything, so
every ticker fails identically — which reads like twenty bad symbols rather
than one missing package. These tests pin the diagnosis.
"""

import zoneinfo
from unittest.mock import MagicMock

import pytest

from portfolio_agent.cli import _build_market_provider
from portfolio_agent.providers import market_yfinance
from portfolio_agent.providers.market_yfinance import (
    MissingTimeZoneDataError,
    check_timezone_database,
)


def _break_zoneinfo(monkeypatch):
    def raise_missing(_key):
        raise zoneinfo.ZoneInfoNotFoundError("'No time zone found with key America/New_York'")

    monkeypatch.setattr(market_yfinance.zoneinfo, "ZoneInfo", raise_missing)


def test_check_passes_on_a_host_with_a_timezone_database():
    assert check_timezone_database() is None


def test_check_names_the_package_that_fixes_it(monkeypatch):
    _break_zoneinfo(monkeypatch)

    message = check_timezone_database()

    assert "pip install tzdata" in message
    assert "Termux" in message  # where this actually happens


def test_missing_timezone_data_is_not_retried(monkeypatch):
    """It's deterministic — three attempts with backoff just wastes time."""
    _break_zoneinfo(monkeypatch)
    calls = []

    def fetch():
        calls.append(1)
        zoneinfo_error = zoneinfo.ZoneInfoNotFoundError("'No time zone found with key X'")
        raise zoneinfo_error

    with pytest.raises(MissingTimeZoneDataError, match="tzdata"):
        market_yfinance._retry(fetch)

    assert len(calls) == 1


def test_ordinary_failures_still_retry(monkeypatch):
    monkeypatch.setattr(market_yfinance.time, "sleep", lambda _s: None)
    calls = []

    def fetch():
        calls.append(1)
        raise ValueError("no data")

    assert market_yfinance._retry(fetch) is None
    assert len(calls) == market_yfinance.RETRY_ATTEMPTS


def test_building_the_provider_fails_early_with_the_fix(monkeypatch):
    """One clear error beats a warning per holding that looks like a bad symbol."""
    _break_zoneinfo(monkeypatch)

    with pytest.raises(MissingTimeZoneDataError, match="pip install tzdata"):
        _build_market_provider(mock=False)


def test_mock_provider_still_works_without_a_timezone_database(monkeypatch):
    """Offline runs shouldn't need one — they never call Yahoo."""
    _break_zoneinfo(monkeypatch)

    assert _build_market_provider(mock=True) is not None


def test_bot_says_so_at_startup_rather_than_at_the_first_report(monkeypatch, caplog, tmp_path):
    import logging

    from portfolio_agent.bot import server

    _break_zoneinfo(monkeypatch)
    monkeypatch.setattr(server, "TelegramNotifier", MagicMock())

    class _Stop(BaseException):
        pass

    def stop(*_a, **_k):
        raise _Stop

    monkeypatch.setattr(server, "get_updates", stop)

    class Settings:
        telegram_bot_token = "t"
        telegram_chat_id = "c"
        state_dir = str(tmp_path)

        def require_telegram(self):
            return self.telegram_bot_token, self.telegram_chat_id

    with caplog.at_level(logging.ERROR), pytest.raises(_Stop):
        server.run_bot(Settings())

    assert "tzdata" in " ".join(r.getMessage() for r in caplog.records)
