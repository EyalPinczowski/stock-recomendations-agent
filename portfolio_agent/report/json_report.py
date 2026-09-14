"""Machine-readable JSON renderer, for scripting/tests."""

from __future__ import annotations

from portfolio_agent.models import NewStockIdeasReport, PortfolioReport, ScreenReport


def render_json(report: PortfolioReport | ScreenReport | NewStockIdeasReport) -> str:
    return report.model_dump_json(indent=2)
