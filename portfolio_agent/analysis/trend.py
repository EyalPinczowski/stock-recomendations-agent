"""Relative strength vs a benchmark (SPY by default, or a sector ETF), plus beta."""

from __future__ import annotations

import pandas as pd

from portfolio_agent.analysis.technical import momentum
from portfolio_agent.models import MarketContextSignal

SECTOR_ETF = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financial Services": "XLF",
    "Financials": "XLF",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Basic Materials": "XLB",
    "Communication Services": "XLC",
}

DEFAULT_BENCHMARK = "SPY"


def benchmark_for_sector(sector: str | None) -> str:
    if sector and sector in SECTOR_ETF:
        return SECTOR_ETF[sector]
    return DEFAULT_BENCHMARK


def compute_beta(holding_close: pd.Series, benchmark_close: pd.Series) -> float | None:
    holding_returns = holding_close.pct_change().dropna()
    benchmark_returns = benchmark_close.pct_change().dropna()
    joined = pd.concat([holding_returns, benchmark_returns], axis=1, join="inner")
    joined.columns = ["h", "b"]
    if len(joined) < 20 or joined["b"].var() == 0:
        return None
    cov = joined["h"].cov(joined["b"])
    var = joined["b"].var()
    return float(cov / var) if var else None


def build_market_context_signal(
    holding_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    benchmark_ticker: str,
    provided_beta: float | None = None,
) -> MarketContextSignal:
    if holding_df is None or holding_df.empty or benchmark_df is None or benchmark_df.empty:
        return MarketContextSignal(benchmark_ticker=benchmark_ticker, beta=provided_beta)

    holding_mom = momentum(holding_df["Close"])
    benchmark_mom = momentum(benchmark_df["Close"])
    relative_strength = 0.0
    if holding_mom is not None and benchmark_mom is not None:
        relative_strength = float(holding_mom - benchmark_mom)

    beta = provided_beta
    if beta is None:
        beta = compute_beta(holding_df["Close"], benchmark_df["Close"])

    return MarketContextSignal(
        benchmark_ticker=benchmark_ticker,
        relative_strength_63d=relative_strength,
        beta=beta,
    )
