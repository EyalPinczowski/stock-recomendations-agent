from portfolio_agent.models import RiskProfile
from portfolio_agent.pipeline import run_analyze
from portfolio_agent.providers.market_mock import MockMarketDataProvider
from portfolio_agent.providers.portfolio_file import FilePortfolioProvider


def test_run_analyze_end_to_end_mock():
    provider = FilePortfolioProvider("examples/portfolio.csv")
    market = MockMarketDataProvider()
    report = run_analyze(provider, market, RiskProfile())

    assert report.total_value > 0
    assert len(report.holding_recommendations) == 4
    assert report.overall_assessment
    assert report.health.bucket_allocation
    for rec in report.holding_recommendations:
        assert rec.action is not None
        assert rec.rationale
