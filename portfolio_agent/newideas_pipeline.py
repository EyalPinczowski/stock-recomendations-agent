"""Orchestrates the `newstocks` flow: current portfolio gap analysis ->
universe scan -> long-horizon technical+analyst scoring -> (optional) review
pass -> NewStockIdeasReport. Kept as its own command (not folded into
`analyze`) since scanning the universe is real added latency/API load.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from portfolio_agent.analysis import analyst as analyst_mod
from portfolio_agent.analysis import technical as technical_mod
from portfolio_agent.models import NewStockIdeasReport, RiskProfile
from portfolio_agent.optimization import allocation as allocation_mod
from portfolio_agent.optimization import classify as classify_mod
from portfolio_agent.optimization import new_ideas as new_ideas_mod
from portfolio_agent.pipeline import _build_holding_context
from portfolio_agent.providers.base import MarketDataProvider, PortfolioProvider
from portfolio_agent.screening.universe import load_universe


def run_newstocks(
    portfolio_provider: PortfolioProvider,
    market: MarketDataProvider,
    risk_profile: RiskProfile,
    universe_path: str | Path = "data/sp500_constituents.csv",
    review_fn=None,
    state_dir: str = "state",
) -> NewStockIdeasReport:
    warnings: list[str] = []
    snapshot = portfolio_provider.get_snapshot()

    contexts = []
    for holding in snapshot.holdings:
        ctx = _build_holding_context(holding, market, None, warnings)
        if ctx is not None:
            contexts.append(ctx)

    held_tickers = {c.holding.ticker for c in contexts}
    valued_holdings = [
        allocation_mod.ValuedHolding(
            ticker=c.holding.ticker, value_usd=c.value_usd,
            bucket=c.analysis_result.bucket, sector=c.analysis_result.sector,
        )
        for c in contexts
    ]
    bucket_pcts = allocation_mod.compute_bucket_allocation(valued_holdings)
    sector_pcts = allocation_mod.compute_sector_allocation(valued_holdings)

    gaps, target_sectors = new_ideas_mod.identify_gaps(bucket_pcts, sector_pcts, risk_profile)
    bucket_gap = any("bucket" in g for g in gaps)

    entries = load_universe(universe_path)
    if not entries:
        warnings.append(f"Universe file not found or empty: {universe_path}")

    scored = []
    for entry in entries:
        if entry.ticker in held_tickers:
            continue
        try:
            df = market.get_price_history(entry.ticker)
            price = market.get_current_price(entry.ticker)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{entry.ticker}: market data fetch failed ({exc}), skipped.")
            continue
        if df is None or df.empty or price is None:
            continue

        technical_signal = technical_mod.build_technical_signal(df)
        analyst_data = market.get_analyst_data(entry.ticker)
        analyst_signal = analyst_mod.build_analyst_signal(analyst_data, price)

        beta = market.get_beta(entry.ticker)
        market_cap = market.get_market_cap(entry.ticker)
        vol = technical_mod.annualized_volatility(df["Close"])
        bucket = classify_mod.classify_bucket(vol, beta, market_cap)

        score = new_ideas_mod.compute_idea_score(technical_signal.trend_score, analyst_signal.analyst_score)
        if score < new_ideas_mod.MIN_IDEA_SCORE:
            continue

        sector_gap = entry.sector in target_sectors
        rationale = (
            f"Trend score {technical_signal.trend_score:+.2f}, analyst score {analyst_signal.analyst_score:+.2f}"
            + (f" ({analyst_signal.num_analysts} analysts)" if analyst_signal.num_analysts else "")
            + f". Classified {bucket.value}."
        )
        suggestion = new_ideas_mod.build_new_stock_suggestion(
            ticker=entry.ticker, sector=entry.sector, bucket=bucket,
            trend_score=technical_signal.trend_score, analyst_score=analyst_signal.analyst_score,
            risk_profile=risk_profile, bucket_gap=bucket_gap, sector_gap=sector_gap, rationale=rationale,
        )
        scored.append((sector_gap, suggestion))

    # Prefer candidates that fill an identified sector gap, then by score.
    scored.sort(key=lambda t: (t[0], t[1].composite_score), reverse=True)
    suggestions = [s for _, s in scored[: new_ideas_mod.MAX_SUGGESTIONS]]

    if review_fn is not None:
        try:
            suggestions = review_fn(suggestions, warnings)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Review pass failed ({exc}), using unreviewed suggestions.")

    try:
        from portfolio_agent.tracking.log import log_new_stock_suggestions

        log_new_stock_suggestions(suggestions, market, state_dir)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Failed to write recommendation log: {exc}")

    return NewStockIdeasReport(
        generated_at=datetime.now(timezone.utc),
        gaps_identified=gaps,
        suggestions=suggestions,
        warnings=warnings,
    )
