import pytest

from portfolio_agent.models import Bucket, Currency
from portfolio_agent.providers.portfolio_file import (
    FilePortfolioProvider,
    PortfolioFileError,
)


def test_loads_example_portfolio():
    provider = FilePortfolioProvider("examples/portfolio.csv")
    snapshot = provider.get_snapshot()
    assert snapshot.source == "file"
    assert len(snapshot.holdings) == 4
    aapl = next(h for h in snapshot.holdings if h.ticker == "AAPL")
    assert aapl.quantity == 15
    assert aapl.cost_basis == 168.20
    assert aapl.bucket == Bucket.CONSERVATIVE
    teva = next(h for h in snapshot.holdings if h.ticker == "TEVA.TA")
    assert teva.currency == Currency.ILS


def test_missing_file_raises_clear_error(tmp_path):
    provider = FilePortfolioProvider(tmp_path / "nope.csv")
    with pytest.raises(PortfolioFileError):
        provider.get_snapshot()


def test_malformed_row_raises(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("ticker,quantity,cost_basis\nAAPL,not-a-number,100\n")
    provider = FilePortfolioProvider(bad)
    with pytest.raises(PortfolioFileError):
        provider.get_snapshot()


def test_json_portfolio(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(
        '{"holdings": [{"ticker": "MSFT", "quantity": 5, "cost_basis": 300}]}'
    )
    snapshot = FilePortfolioProvider(p).get_snapshot()
    assert snapshot.holdings[0].ticker == "MSFT"
