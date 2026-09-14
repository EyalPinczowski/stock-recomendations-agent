"""Whole-portfolio health: Sharpe ratio, annualized volatility, max drawdown
(reconstructed from a weighted daily value series), plus sector-concentration
warnings. Pure computation over already-fetched price history — no new
provider calls.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from portfolio_agent.models import PortfolioHealth
from portfolio_agent.optimization.allocation import (
    ValuedHolding,
    compute_bucket_allocation,
    compute_sector_allocation,
    sector_concentration_suggestions,
)

RISK_FREE_RATE_ANNUAL = 0.04


def build_portfolio_value_series(
    holding_histories: dict[str, pd.Series], quantities: dict[str, float]
) -> pd.Series:
    """holding_histories: ticker -> Close price Series (already in USD). Returns
    the portfolio's total value over the intersection of available dates."""
    if not holding_histories:
        return pd.Series(dtype=float)

    frames = []
    for ticker, series in holding_histories.items():
        qty = quantities.get(ticker, 0.0)
        if series is None or series.empty or qty == 0:
            continue
        frames.append((series * qty).rename(ticker))

    if not frames:
        return pd.Series(dtype=float)

    combined = pd.concat(frames, axis=1, join="inner")
    if combined.empty:
        return pd.Series(dtype=float)
    return combined.sum(axis=1)


def sharpe_ratio(value_series: pd.Series) -> float | None:
    if value_series is None or len(value_series) < 20:
        return None
    returns = value_series.pct_change().dropna()
    if returns.std() == 0 or len(returns) < 5:
        return None
    daily_rf = RISK_FREE_RATE_ANNUAL / 252
    excess = returns - daily_rf
    annualized_excess = excess.mean() * 252
    annualized_vol = returns.std() * np.sqrt(252)
    if annualized_vol == 0:
        return None
    return float(annualized_excess / annualized_vol)


def annualized_volatility(value_series: pd.Series) -> float | None:
    if value_series is None or len(value_series) < 5:
        return None
    returns = value_series.pct_change().dropna()
    if len(returns) < 5:
        return None
    return float(returns.std() * np.sqrt(252))


def max_drawdown_pct(value_series: pd.Series) -> float | None:
    if value_series is None or value_series.empty:
        return None
    running_max = value_series.cummax()
    drawdown = (value_series - running_max) / running_max
    return float(drawdown.min())


def build_portfolio_health(
    value_series: pd.Series,
    valued_holdings: list[ValuedHolding],
    max_sector_pct: float,
) -> PortfolioHealth:
    bucket_alloc = compute_bucket_allocation(valued_holdings)
    sector_alloc = compute_sector_allocation(valued_holdings)
    concentration = sector_concentration_suggestions(sector_alloc, max_sector_pct)

    return PortfolioHealth(
        sharpe_ratio=sharpe_ratio(value_series),
        volatility_annualized=annualized_volatility(value_series),
        max_drawdown_pct=max_drawdown_pct(value_series),
        bucket_allocation=bucket_alloc,
        sector_allocation=sector_alloc,
        concentration_warnings=[s.action_summary for s in concentration],
    )
