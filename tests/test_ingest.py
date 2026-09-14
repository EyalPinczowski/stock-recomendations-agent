import json

from portfolio_agent.ingest.snapshot_store import load_snapshot, save_snapshot
from portfolio_agent.ingest.vision_extract import (
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


def test_parse_extraction_response_us_and_tase():
    ticker_map = {"טבע": "TEVA.TA"}
    raw = json.dumps(
        [
            {"identifier": "AAPL", "quantity": 10, "cost_basis": 150, "currency": "USD"},
            {"identifier": "טבע", "quantity": 200, "cost_basis": 20, "currency": "ILS"},
            {"identifier": "בלתי ידוע", "quantity": 5, "cost_basis": None, "currency": "ILS"},
        ]
    )
    holdings, warnings = parse_extraction_response(raw, ticker_map)
    assert len(holdings) == 3
    aapl = next(h for h in holdings if h.ticker == "AAPL")
    assert aapl.currency == Currency.USD
    teva = next(h for h in holdings if h.ticker == "TEVA.TA")
    assert teva.quantity == 200
    assert len(warnings) == 1
    assert "unmapped" in warnings[0]


def test_parse_extraction_response_handles_markdown_fence():
    raw = "```json\n[{\"identifier\": \"MSFT\", \"quantity\": 3, \"cost_basis\": 300, \"currency\": \"USD\"}]\n```"
    holdings, _warnings = parse_extraction_response(raw, {})
    assert len(holdings) == 1
    assert holdings[0].ticker == "MSFT"


def test_parse_extraction_response_invalid_json_returns_warning():
    holdings, warnings = parse_extraction_response("not json", {})
    assert holdings == []
    assert len(warnings) == 1


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
