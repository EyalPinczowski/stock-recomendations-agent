from pptx import Presentation

from portfolio_agent.models import RiskProfile
from portfolio_agent.pipeline import run_analyze
from portfolio_agent.providers.market_mock import MockMarketDataProvider
from portfolio_agent.providers.portfolio_file import FilePortfolioProvider
from portfolio_agent.report.presentation import build_presentation


def test_build_presentation_produces_valid_pptx(tmp_path):
    provider = FilePortfolioProvider("examples/portfolio.csv")
    market = MockMarketDataProvider()
    report = run_analyze(provider, market, RiskProfile())

    out = tmp_path / "report.pptx"
    path = build_presentation(report, "analyze", str(out))
    assert path.exists()

    prs = Presentation(str(path))
    slide_count = len(prs.slides._sldIdLst)
    # title + overall assessment + health + (rebalance?) + recs/holds (+warnings?)
    assert slide_count >= 4
