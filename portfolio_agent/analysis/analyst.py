"""Normalizes yfinance's aggregated analyst recommendations/price targets into
an AnalystSignal. Coverage is often missing for smaller tickers — treated as
neutral (0) rather than an error.
"""

from __future__ import annotations

from portfolio_agent.models import AnalystSignal


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def build_analyst_signal(analyst_data: dict, current_price: float | None) -> AnalystSignal:
    mean_rating = analyst_data.get("recommendationMean")
    num_analysts = analyst_data.get("numberOfAnalystOpinions")
    target_mean = analyst_data.get("targetMeanPrice")

    rating_component = 0.0
    if mean_rating is not None:
        # yfinance: 1 = Strong Buy .. 5 = Strong Sell
        rating_component = _clip((3 - float(mean_rating)) / 2)

    upside_pct = None
    upside_component = 0.0
    if target_mean and current_price:
        upside_pct = (float(target_mean) - current_price) / current_price
        upside_component = _clip(upside_pct / 0.20)

    if mean_rating is not None and upside_pct is not None:
        analyst_score = 0.5 * rating_component + 0.5 * upside_component
    elif mean_rating is not None:
        analyst_score = rating_component
    elif upside_pct is not None:
        analyst_score = upside_component
    else:
        analyst_score = 0.0

    return AnalystSignal(
        mean_rating=float(mean_rating) if mean_rating is not None else None,
        price_target_mean=float(target_mean) if target_mean is not None else None,
        price_target_upside_pct=upside_pct,
        num_analysts=int(num_analysts) if num_analysts is not None else None,
        analyst_score=analyst_score,
    )
