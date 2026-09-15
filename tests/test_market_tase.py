"""Yahoo doesn't reliably carry Tel Aviv listings, so `.TA` tickers are served
from TASE's own API instead — keyed by the security number the broker's
screenshot already shows.

The API is undocumented (read from how tase.co.il calls it), so these tests
pin the parts that would silently corrupt a portfolio if they drifted: the
agorot-to-shekel conversion, lenient field matching, and the routing.
"""

from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest

from portfolio_agent.providers import market_tase
from portfolio_agent.providers.market_composite import CompositeMarketDataProvider
from portfolio_agent.providers.market_tase import (
    TaseMarketDataProvider,
    is_tase_ticker,
    security_id_from_ticker,
)

# Shaped like TASE's EOD feed: prices in agorot, dd/mm/yyyy dates.
EOD_ROWS = [
    {"TradeDate": "01/09/2026", "OpenRate": 6300, "HighRate": 6350, "LowRate": 6280,
     "CloseRate": 6317, "Volume": 12345},
    {"TradeDate": "02/09/2026", "OpenRate": 6320, "HighRate": 6400, "LowRate": 6310,
     "CloseRate": 6380, "Volume": 9876},
]


@pytest.fixture(autouse=True)
def _no_retry_sleeps(monkeypatch):
    """Backoff is real behaviour, but waiting through it in tests is not."""
    monkeypatch.setattr(market_tase.time, "sleep", lambda _s: None)


def _provider(payloads):
    """A provider whose HTTP layer replays canned responses."""
    session = MagicMock()

    def request(_method, url, **_kwargs):
        response = MagicMock()
        response.status_code = 200
        for fragment, payload in payloads.items():
            if fragment in url:
                response.json.return_value = payload
                return response
        response.status_code = 404
        return response

    session.request.side_effect = request
    return TaseMarketDataProvider(session=session), session


# --- identifiers ------------------------------------------------------------


def test_security_number_comes_straight_from_the_ticker():
    assert security_id_from_ticker("1159714.TA") == "1159714"
    assert is_tase_ticker("1159714.TA") is True


def test_letter_symbols_have_no_security_number_to_query():
    """TEVA.TA is a Yahoo symbol; TASE's API needs the numeric id."""
    assert security_id_from_ticker("TEVA.TA") is None
    assert security_id_from_ticker("AAPL") is None


# --- price history ----------------------------------------------------------


def test_prices_are_converted_from_agorot_to_shekels():
    """The exchange quotes in agorot. Left unconverted, every Israeli holding
    would be valued 100x too high."""
    provider, _session = _provider({"historyeod": {"Items": EOD_ROWS}})

    history = provider.get_price_history("1159714.TA")

    assert list(history["Close"]) == [63.17, 63.80]
    assert list(history["High"]) == [63.50, 64.00]


def test_history_is_a_sorted_ohlcv_frame():
    provider, _session = _provider({"historyeod": {"Items": list(reversed(EOD_ROWS))}})

    history = provider.get_price_history("1159714.TA")

    assert list(history.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert history.index.is_monotonic_increasing
    assert history.index[0] == pd.Timestamp("2026-09-01")


def test_current_price_is_the_latest_close():
    provider, _session = _provider({"historyeod": {"Items": EOD_ROWS}})

    assert provider.get_current_price("1159714.TA") == 63.80


def test_falls_back_to_the_mutual_fund_endpoint():
    """TASE splits traded securities from mutual funds across two APIs."""
    provider, session = _provider(
        {
            "historyeod": {"Items": []},
            "funds/mutual": [{"date": "2026-09-01T00:00:00", "sellPrice": 1250}],
        }
    )

    history = provider.get_price_history("5118393.TA")

    assert list(history["Close"]) == [12.50]
    assert any("funds/mutual" in str(call) for call in session.request.call_args_list)


def test_field_names_are_matched_leniently():
    """Undocumented API: a renamed key should cost a column, not the holding."""
    provider, _session = _provider(
        {"historyeod": {"items": [{"tradeDate": "2026-09-01", "closingRate": 5000}]}}
    )

    history = provider.get_price_history("1234567.TA")

    assert list(history["Close"]) == [50.0]
    # Nothing else was given, so OHLC collapses to the close rather than 0.
    assert list(history["Open"]) == [50.0]


def test_epoch_and_dotnet_dates_are_understood():
    provider, _session = _provider(
        {"historyeod": {"Items": [{"TradeDate": "/Date(1788307200000)/", "CloseRate": 100}]}}
    )

    history = provider.get_price_history("1234567.TA")
    assert len(history) == 1


def test_unreadable_rows_log_the_keys_that_were_seen(caplog):
    """The one thing that would need fixing if TASE renames a field is knowing
    what it renamed it to."""
    import logging

    provider, _session = _provider(
        {"historyeod": {"Items": [{"somethingNew": 1, "alsoNew": 2}]}, "funds/mutual": []}
    )

    with caplog.at_level(logging.WARNING):
        history = provider.get_price_history("1234567.TA")

    assert history.empty
    assert "somethingNew" in caplog.text


def test_a_failed_request_yields_no_data_rather_than_raising():
    """One dead ticker must not take the whole report down."""
    session = MagicMock()
    session.request.side_effect = market_tase.requests.ConnectionError("offline")
    provider = TaseMarketDataProvider(session=session)

    assert provider.get_price_history("1159714.TA").empty
    assert provider.get_current_price("1159714.TA") is None


def test_history_is_cached_per_ticker_and_period():
    provider, session = _provider({"historyeod": {"Items": EOD_ROWS}})

    provider.get_price_history("1159714.TA")
    provider.get_price_history("1159714.TA")

    assert session.request.call_count == 1


def test_requested_period_bounds_the_query():
    provider, session = _provider({"historyeod": {"Items": EOD_ROWS}})

    provider.get_price_history("1159714.TA", period="3mo")

    body = session.request.call_args.kwargs["json"]
    span = date.fromisoformat(body["dTo"]) - date.fromisoformat(body["dFrom"])
    assert 90 <= span.days <= 95
    assert body["oId"] == "1159714"


def test_analyst_data_is_empty_because_tase_publishes_none():
    """Better an honestly neutral signal than a fabricated zero."""
    provider, _session = _provider({})
    assert provider.get_analyst_data("1159714.TA") == {}


# --- routing ----------------------------------------------------------------


class _Recorder:
    def __init__(self, name):
        self.name = name
        self.seen = []

    def get_price_history(self, ticker, period="1y"):
        self.seen.append(ticker)
        return pd.DataFrame()

    def get_current_price(self, ticker):
        self.seen.append(ticker)
        return 1.0

    def get_analyst_data(self, ticker):
        return {}

    def get_market_cap(self, ticker):
        return None

    def get_beta(self, ticker):
        return None

    def get_sector(self, ticker):
        return None

    def get_fx_rate(self, from_currency, to_currency):
        self.seen.append(f"fx:{from_currency}{to_currency}")
        return 3.05


@pytest.fixture
def composite():
    default, tase = _Recorder("yahoo"), _Recorder("tase")
    return CompositeMarketDataProvider(default, tase), default, tase


def test_numeric_tase_tickers_go_to_tase(composite):
    provider, default, tase = composite

    provider.get_price_history("1159714.TA")

    assert tase.seen == ["1159714.TA"]
    assert default.seen == []
    assert provider.source_name("1159714.TA") == "tase"


def test_us_tickers_stay_with_the_default_provider(composite):
    provider, default, tase = composite

    provider.get_current_price("AAPL")

    assert default.seen == ["AAPL"]
    assert tase.seen == []
    assert provider.source_name("AAPL") == "yahoo"


def test_letter_suffixed_israeli_symbols_stay_on_yahoo(composite):
    """TEVA.TA has no security number, so TASE's API can't look it up."""
    provider, default, tase = composite

    provider.get_price_history("TEVA.TA")

    assert default.seen == ["TEVA.TA"]
    assert tase.seen == []


def test_fx_never_goes_to_tase(composite):
    """A currency pair belongs to neither exchange."""
    provider, default, tase = composite

    assert provider.get_fx_rate("USD", "ILS") == 3.05
    assert default.seen == ["fx:USDILS"]
    assert tase.seen == []
