import json
from pathlib import Path

import pytest

from portfolio_agent.ingest.snapshot_store import load_snapshot, save_snapshot
from portfolio_agent.ingest.vision_extract import (
    derive_quantity,
    load_tase_ticker_map,
    parse_extraction_response,
)
from portfolio_agent.models import Currency, Holding
from portfolio_agent.providers.portfolio_screenshot import (
    NoPortfolioSnapshotError,
    ScreenshotPortfolioProvider,
)


def test_load_tase_ticker_map():
    mapping = load_tase_ticker_map("data/tase_ticker_map.csv")
    assert mapping["טבע"] == "TEVA.TA"


# Rows as they actually appear in Meitav Trade: no quantity column and no cost
# basis, so both are worked out from the price and the position's value.
REAL_ROWS = [
    {"ticker": "CEG", "exchange": "NASDAQ", "security_number": None,
     "name": "Constellation Energy Corp", "price": 264.57, "position_value": 3174.84,
     "total_return_pct": -5.85, "currency": "USD", "kind": "security"},
    {"ticker": "GTLB", "exchange": "NASDAQ", "security_number": None, "name": "Gitlab Inc",
     "price": 49.25, "position_value": 7387.5, "total_return_pct": 46.83,
     "currency": "USD", "kind": "security"},
    {"ticker": None, "exchange": "TLV", "security_number": "1159714", "name": "MTF.כשתא125",
     "price": 6317, "position_value": 30890.13, "total_return_pct": 59.12,
     "currency": "ILS", "kind": "security"},
    {"ticker": None, "exchange": "TLV", "security_number": "99028", "name": 'דולר ארה"ב',
     "price": None, "position_value": 8561.64, "total_return_pct": 1.84,
     "currency": "USD", "kind": "cash"},
    {"ticker": None, "exchange": None, "security_number": None, "name": "מגן מס 26",
     "price": 325.7, "position_value": 325.7, "total_return_pct": None,
     "currency": "ILS", "kind": "other"},
]


def test_quantity_is_derived_from_price_and_position_value():
    """The app shows what the position is worth, not how many shares it is."""
    result = parse_extraction_response(json.dumps(REAL_ROWS), {})

    ceg = next(h for h in result.holdings if h.ticker == "CEG")
    assert ceg.quantity == 12.0  # 3174.84 / 264.57
    assert ceg.name == "Constellation Energy Corp"
    assert ceg.currency == Currency.USD


def test_cost_basis_is_backed_out_of_the_total_return():
    result = parse_extraction_response(json.dumps(REAL_ROWS), {})

    ceg = next(h for h in result.holdings if h.ticker == "CEG")
    assert ceg.cost_basis == pytest.approx(264.57 / (1 - 0.0585), rel=1e-6)

    gtlb = next(h for h in result.holdings if h.ticker == "GTLB")
    assert gtlb.cost_basis == pytest.approx(49.25 / 1.4683, rel=1e-6)
    assert gtlb.cost_basis < 49.25  # it's up 46.8%, so it was bought lower


def test_tase_prices_are_read_as_agorot():
    """TASE quotes in agorot but the app shows shekel values — a 100x gap that
    would otherwise make the holding look 100x smaller."""
    result = parse_extraction_response(json.dumps(REAL_ROWS), {})

    fund = next(h for h in result.holdings if h.ticker == "1159714.TA")
    assert fund.quantity == 489.0  # 30,890.13 / 63.17, not / 6317
    assert fund.currency == Currency.ILS
    assert fund.name == "MTF.כשתא125"


def test_tase_security_number_resolves_without_a_map_entry():
    """Israeli funds are listed on Yahoo under their TASE security number, so a
    hand-maintained mapping isn't needed for them."""
    result = parse_extraction_response(json.dumps(REAL_ROWS), {})
    assert "1159714.TA" in [h.ticker for h in result.holdings]


def test_cash_balance_is_kept_but_not_treated_as_a_holding():
    result = parse_extraction_response(json.dumps(REAL_ROWS), {})

    assert result.cash_balances == {"USD": 8561.64}
    assert all('דולר' not in (h.name or "") for h in result.holdings)


def test_non_tradable_rows_are_skipped_with_a_warning():
    """מגן מס is a tax product, not something that can be analyzed or sold."""
    result = parse_extraction_response(json.dumps(REAL_ROWS), {})

    assert all("מגן מס" not in (h.name or "") for h in result.holdings)
    assert any("מגן מס" in w for w in result.warnings)


def test_holdings_repeated_across_screenshots_appear_once():
    """Consecutive screenshots overlap, so the same row is seen twice."""
    rows = REAL_ROWS + [REAL_ROWS[0]]
    result = parse_extraction_response(json.dumps(rows), {})

    assert [h.ticker for h in result.holdings].count("CEG") == 1


def test_fractional_positions_are_not_rounded_away():
    """Warrant stubs really are fractional; rounding would invent shares."""
    rows = [{"ticker": "OPENL", "exchange": "NASDAQ", "name": "Opendoor Technologies Inc",
             "price": 0.0977, "position_value": 0.03, "total_return_pct": 31.49,
             "currency": "USD", "kind": "security"}]
    result = parse_extraction_response(json.dumps(rows), {})

    assert result.holdings[0].quantity == pytest.approx(0.3071, rel=1e-3)


def test_named_tase_holding_uses_the_ticker_map():
    rows = [{"ticker": None, "exchange": "TLV", "security_number": None, "name": "טבע",
             "price": 1000, "position_value": 2000, "total_return_pct": None,
             "currency": "ILS", "kind": "security"}]
    result = parse_extraction_response(json.dumps(rows), {"טבע": "TEVA.TA"})

    assert result.holdings[0].ticker == "TEVA.TA"
    assert result.holdings[0].quantity == 200.0  # 2000 / 10.00 (agorot)


def test_unresolvable_tase_row_warns_instead_of_disappearing():
    rows = [{"ticker": None, "exchange": "TLV", "security_number": None, "name": "קרן לא ידועה",
             "price": 100, "position_value": 500, "currency": "ILS", "kind": "security"}]
    result = parse_extraction_response(json.dumps(rows), {})

    assert result.holdings == []
    assert "tase_ticker_map.csv" in result.warnings[0]


def test_a_row_without_a_price_cannot_be_sized_and_says_so():
    rows = [{"ticker": "AAPL", "exchange": "NASDAQ", "name": "Apple",
             "price": None, "position_value": 1000, "currency": "USD", "kind": "security"}]
    result = parse_extraction_response(json.dumps(rows), {})

    assert result.holdings == []
    assert "quantity" in result.warnings[0]


def test_numbers_with_currency_symbols_and_separators_are_read():
    """Models sometimes echo the display text rather than a bare number."""
    rows = [{"ticker": "LLY", "exchange": "NYSE", "name": "Eli Lilly & Co",
             "price": "1,138.28", "position_value": "$6,829.68", "total_return_pct": "11.1",
             "currency": "USD", "kind": "security"}]
    result = parse_extraction_response(json.dumps(rows), {})

    assert result.holdings[0].quantity == 6.0


def test_derive_quantity_converts_agorot_only_for_tase_rows():
    assert derive_quantity(6317, 30890.13, is_tase=True) == (489.0, 63.17)
    assert derive_quantity(2113, 21869.55, is_tase=True) == (1035.0, 21.13)
    # A US price is already in dollars — dividing it would be 100x wrong.
    assert derive_quantity(264.57, 3174.84, is_tase=False) == (12.0, 264.57)


def test_derive_quantity_snaps_display_rounding_but_not_real_fractions():
    """Price and value are both shown rounded, so an exact count lands slightly
    off — but a warrant stub is fractional for real."""
    quantity, _price = derive_quantity(100.004, 1000.0, is_tase=False)
    assert quantity == 10.0

    quantity, _price = derive_quantity(0.0977, 0.03, is_tase=False)
    assert quantity == pytest.approx(0.3071, rel=1e-3)


def test_parse_extraction_response_handles_markdown_fence():
    raw = '```json\n[{"ticker": "MSFT", "exchange": "NASDAQ", "name": "Microsoft", "price": 100, "position_value": 300, "currency": "USD", "kind": "security"}]\n```'
    result = parse_extraction_response(raw, {})
    assert [h.ticker for h in result.holdings] == ["MSFT"]
    assert result.holdings[0].quantity == 3.0


def test_parse_extraction_response_invalid_json_returns_warning():
    result = parse_extraction_response("not json", {})
    assert result.holdings == []
    assert len(result.warnings) == 1


def test_snapshot_store_roundtrip_and_history(tmp_path):
    holdings1 = [Holding(ticker="AAPL", quantity=5, cost_basis=150)]
    snap1 = save_snapshot(holdings1, tmp_path)
    assert snap1.holdings[0].ticker == "AAPL"

    holdings2 = [Holding(ticker="MSFT", quantity=2, cost_basis=300)]
    save_snapshot(holdings2, tmp_path)

    loaded = load_snapshot(tmp_path)
    assert loaded.holdings[0].ticker == "MSFT"

    history_files = list((tmp_path / "portfolio_history").glob("*.json"))
    assert len(history_files) == 1


def test_screenshot_provider_raises_clear_error_when_no_snapshot(tmp_path):
    provider = ScreenshotPortfolioProvider(tmp_path / "current_portfolio.json")
    try:
        provider.get_snapshot()
        assert False, "expected NoPortfolioSnapshotError"
    except NoPortfolioSnapshotError as exc:
        assert "screenshot" in str(exc)


def test_screenshot_provider_reads_saved_snapshot(tmp_path):
    save_snapshot([Holding(ticker="AAPL", quantity=1, cost_basis=100)], tmp_path)
    provider = ScreenshotPortfolioProvider(tmp_path / "current_portfolio.json")
    snapshot = provider.get_snapshot()
    assert snapshot.holdings[0].ticker == "AAPL"


def test_extract_holdings_from_image_end_to_end_over_gemini(tmp_path, monkeypatch):
    """The whole screenshot path with only the HTTP call faked: a real-shaped
    Gemini response in, resolved Holdings out."""
    from unittest.mock import MagicMock

    from portfolio_agent import llm
    from portfolio_agent.ingest.vision_extract import extract_holdings_from_image

    rows = [
        {"ticker": "AAPL", "exchange": "NASDAQ", "name": "Apple Inc", "price": 180.5,
         "position_value": 1805.0, "total_return_pct": None, "currency": "USD",
         "kind": "security"},
        {"ticker": None, "exchange": "TLV", "security_number": None, "name": "טבע",
         "price": 1000, "position_value": 2000, "total_return_pct": None,
         "currency": "ILS", "kind": "security"},
    ]
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "candidates": [
            {"content": {"parts": [{"text": json.dumps(rows)}]}, "finishReason": "STOP"}
        ]
    }
    post = MagicMock(return_value=response)
    monkeypatch.setattr(llm.requests, "post", post)

    class Settings:
        llm_provider = "gemini"
        gemini_api_key = "k"
        gemini_model = "gemini-3.8-flash"
        gemini_thinking_level = ""
        data_dir = Path("data")

    result = extract_holdings_from_image(b"\xff\xd8jpeg", Settings())

    assert [h.ticker for h in result.holdings] == ["AAPL", "TEVA.TA"]
    assert result.holdings[0].quantity == 10  # 1805.0 / 180.5
    assert result.holdings[1].currency == Currency.ILS
    assert result.holdings[1].cost_basis == 0.0  # no return shown, so nothing to back out
    assert result.warnings == []
    # The screenshot itself actually went up with the prompt.
    assert "inlineData" in post.call_args.kwargs["json"]["contents"][0]["parts"][0]
