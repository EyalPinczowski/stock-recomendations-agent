from datetime import datetime, timedelta, timezone

from portfolio_agent.models import Action, LoggedRecommendation
from portfolio_agent.providers.market_mock import MockMarketDataProvider
from portfolio_agent.tracking.log import log_recommendations, read_log
from portfolio_agent.tracking.scorecard import build_scorecard_text, compute_scorecard_stats


class _FixedPriceMarket(MockMarketDataProvider):
    def __init__(self, prices):
        super().__init__()
        self._prices = prices

    def get_current_price(self, ticker):
        return self._prices.get(ticker)


def test_log_and_read_roundtrip(tmp_path):
    entries = [
        LoggedRecommendation(
            ticker="AAPL", action="buy", conviction=0.6, price_at_recommendation=100.0,
            recommended_at=datetime.now(timezone.utc), run_type="analyze",
        )
    ]
    from portfolio_agent.tracking.log import _append

    _append(entries, tmp_path)
    loaded = read_log(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].ticker == "AAPL"


def test_compute_scorecard_stats_buy_correct_when_price_rose():
    entries = [
        LoggedRecommendation(
            ticker="AAPL", action="buy", conviction=0.6, price_at_recommendation=100.0,
            recommended_at=datetime.now(timezone.utc), run_type="analyze",
        )
    ]
    market = _FixedPriceMarket({"AAPL": 110.0})
    stats = compute_scorecard_stats(entries, market)
    assert stats["buy"]["correct"] == 1
    assert abs(stats["buy"]["total_change"] - 0.10) < 1e-9


def test_build_scorecard_text_empty_log(tmp_path):
    market = MockMarketDataProvider()
    text = build_scorecard_text(tmp_path, market, since_days=30)
    assert "No recommendations logged" in text


def test_build_scorecard_text_with_entries(tmp_path):
    entries = [
        LoggedRecommendation(
            ticker="AAPL", action="buy", conviction=0.6, price_at_recommendation=100.0,
            recommended_at=datetime.now(timezone.utc), run_type="analyze",
        ),
        LoggedRecommendation(
            ticker="OLD", action="sell", conviction=0.6, price_at_recommendation=100.0,
            recommended_at=datetime.now(timezone.utc) - timedelta(days=90), run_type="analyze",
        ),
    ]
    from portfolio_agent.tracking.log import _append

    _append(entries, tmp_path)
    market = _FixedPriceMarket({"AAPL": 105.0, "OLD": 50.0})
    text = build_scorecard_text(tmp_path, market, since_days=30)
    assert "BUY: 1 calls" in text
    assert "OLD" not in text
