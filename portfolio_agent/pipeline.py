"""Orchestrates the `analyze` flow: portfolio snapshot -> per-holding signals ->
composite scoring -> reward/risk filtering & sizing -> portfolio-level
rebalancing/health -> (optional) review pass -> PortfolioReport.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone

import pandas as pd

from portfolio_agent.analysis import analyst as analyst_mod
from portfolio_agent.analysis import scorer
from portfolio_agent.analysis import stop_take as stop_take_mod
from portfolio_agent.analysis import technical as technical_mod
from portfolio_agent.analysis import trend as trend_mod
from portfolio_agent.models import (
    AnalysisResult,
    Bucket,
    Holding,
    PortfolioReport,
    RebalanceSuggestion,
    RiskProfile,
    Recommendation,
    SentimentSignal,
)
from portfolio_agent.optimization import allocation as allocation_mod
from portfolio_agent.optimization import classify as classify_mod
from portfolio_agent.optimization import risk_metrics as risk_metrics_mod
from portfolio_agent.optimization import risk_reward as risk_reward_mod
from portfolio_agent.providers.base import MarketDataProvider, NewsProvider, PortfolioProvider

logger = logging.getLogger(__name__)


@dataclass
class _HoldingContext:
    holding: Holding
    price_usd: float
    value_usd: float
    df: pd.DataFrame
    analysis_result: AnalysisResult


def _build_holding_context(
    holding: Holding,
    market: MarketDataProvider,
    news_provider: NewsProvider | None,
    warnings: list[str],
) -> _HoldingContext | None:
    try:
        df = market.get_price_history(holding.ticker)
        price = market.get_current_price(holding.ticker)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"{holding.ticker}: market data fetch failed ({exc}), skipped.")
        return None

    if df is None or df.empty or price is None:
        warnings.append(f"{holding.ticker}: no market data available, skipped.")
        return None

    fx = market.get_fx_rate(holding.currency.value, "USD")
    price_usd = price * fx
    value_usd = price_usd * holding.quantity

    sector = holding.sector or market.get_sector(holding.ticker)
    beta = market.get_beta(holding.ticker)
    market_cap = market.get_market_cap(holding.ticker)
    vol = technical_mod.annualized_volatility(df["Close"])

    bucket = holding.bucket
    if bucket == Bucket.UNCLASSIFIED:
        bucket = classify_mod.classify_bucket(vol, beta, market_cap)

    technical_signal = technical_mod.build_technical_signal(df)
    analyst_data = market.get_analyst_data(holding.ticker)
    analyst_signal = analyst_mod.build_analyst_signal(analyst_data, price)
    sentiment_signal = SentimentSignal(degraded=True)  # filled in by a batched call after all contexts are built

    benchmark_ticker = trend_mod.benchmark_for_sector(sector)
    benchmark_df = market.get_price_history(benchmark_ticker)
    market_context = trend_mod.build_market_context_signal(df, benchmark_df, benchmark_ticker, beta)
    stop_take = stop_take_mod.compute_stop_take(df, price)

    analysis_result = scorer.build_analysis_result(
        ticker=holding.ticker,
        as_of=date.today(),
        current_price=price,
        technical=technical_signal,
        analyst=analyst_signal,
        sentiment=sentiment_signal,
        market_context=market_context,
        stop_take=stop_take,
        bucket=bucket,
        sector=sector,
        volatility_annualized=vol,
        beta=beta,
    )

    return _HoldingContext(
        holding=holding,
        price_usd=price_usd,
        value_usd=value_usd,
        df=df,
        analysis_result=analysis_result,
    )


def _build_fallback_overall_assessment(
    health, recommendations: list[Recommendation], warnings: list[str]
) -> str:
    action_counts: dict[str, int] = {}
    for r in recommendations:
        action_counts[r.action.value] = action_counts.get(r.action.value, 0) + 1
    actions_desc = ", ".join(f"{v} {k}" for k, v in sorted(action_counts.items())) or "no actionable signals"

    parts = [f"Today's scan: {actions_desc}."]
    if health.sharpe_ratio is not None:
        parts.append(f"Sharpe ratio {health.sharpe_ratio:.2f}, annualized volatility "
                      f"{(health.volatility_annualized or 0):.0%}.")
    if health.concentration_warnings:
        parts.append(f"{len(health.concentration_warnings)} sector concentration warning(s).")
    if warnings:
        parts.append(f"{len(warnings)} item(s) skipped or degraded this run.")
    return " ".join(parts)


def run_analyze(
    portfolio_provider: PortfolioProvider,
    market: MarketDataProvider,
    risk_profile: RiskProfile,
    news_provider: NewsProvider | None = None,
    sentiment_batch_fn=None,
    review_fn=None,
    state_dir: str = "state",
) -> PortfolioReport:
    warnings: list[str] = []
    snapshot = portfolio_provider.get_snapshot()

    contexts: list[_HoldingContext] = []
    for holding in snapshot.holdings:
        ctx = _build_holding_context(holding, market, news_provider, warnings)
        if ctx is not None:
            contexts.append(ctx)

    if sentiment_batch_fn is not None and contexts:
        try:
            sentiment_by_ticker = sentiment_batch_fn([c.holding.ticker for c in contexts], news_provider)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Sentiment analysis failed ({exc}), skipped.")
            sentiment_by_ticker = {}
        for c in contexts:
            signal = sentiment_by_ticker.get(c.holding.ticker)
            if signal is not None:
                result = c.analysis_result
                updated = result.model_copy(update={"sentiment": signal})
                updated = updated.model_copy(update={
                    "composite_score": scorer.composite_score(
                        updated.technical, updated.analyst, updated.sentiment, updated.market_context
                    )
                })
                c.analysis_result = updated

    total_value = sum(c.value_usd for c in contexts)

    valued_holdings = [
        allocation_mod.ValuedHolding(
            ticker=c.holding.ticker,
            value_usd=c.value_usd,
            bucket=c.analysis_result.bucket,
            sector=c.analysis_result.sector,
        )
        for c in contexts
    ]

    recommendations: list[Recommendation] = []
    for c in contexts:
        result = c.analysis_result
        action = scorer.to_action(result.composite_score, holding_exists=True)
        ratio = risk_reward_mod.reward_risk_ratio(result.stop_take, result.current_price)
        action = risk_reward_mod.apply_reward_risk_filter(action, ratio, risk_profile.min_reward_risk_ratio)
        rationale = scorer.build_rationale(
            c.holding.ticker, result.technical, result.analyst, result.sentiment,
            result.market_context, result.stop_take, action,
        )
        dollar_delta = risk_reward_mod.suggested_dollar_delta(
            action, abs(result.composite_score), total_value, c.value_usd, risk_profile,
        )
        shares_delta = (dollar_delta / result.current_price) if dollar_delta and result.current_price else None

        recommendations.append(
            Recommendation(
                ticker=c.holding.ticker,
                action=action,
                conviction=abs(result.composite_score),
                reward_risk_ratio=ratio,
                rationale=rationale,
                stop_take=result.stop_take,
                suggested_shares_delta=shares_delta,
                suggested_dollar_delta=dollar_delta,
                related_result=result,
            )
        )

    bucket_pcts = allocation_mod.compute_bucket_allocation(valued_holdings)
    sector_pcts = allocation_mod.compute_sector_allocation(valued_holdings)
    rebalance_suggestions: list[RebalanceSuggestion] = [
        *allocation_mod.bucket_rebalance_suggestions(
            bucket_pcts, risk_profile.target_conservative_pct,
            risk_profile.target_aggressive_pct, risk_profile.rebalance_drift_threshold_pct,
        ),
        *allocation_mod.sector_concentration_suggestions(sector_pcts, risk_profile.max_sector_pct),
    ]

    holding_histories = {
        c.holding.ticker: c.df["Close"] * market.get_fx_rate(c.holding.currency.value, "USD")
        for c in contexts
    }
    quantities = {c.holding.ticker: c.holding.quantity for c in contexts}
    value_series = risk_metrics_mod.build_portfolio_value_series(holding_histories, quantities)
    health = risk_metrics_mod.build_portfolio_health(value_series, valued_holdings, risk_profile.max_sector_pct)

    overall_assessment = None
    if review_fn is not None:
        try:
            recommendations, overall_assessment = review_fn(recommendations, health, warnings)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Review pass failed ({exc}), using unreviewed recommendations.")

    if overall_assessment is None:
        overall_assessment = _build_fallback_overall_assessment(health, recommendations, warnings)

    try:
        from portfolio_agent.tracking.log import log_recommendations

        log_recommendations(recommendations, state_dir)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write recommendation log: %s", exc)

    return PortfolioReport(
        generated_at=datetime.now(timezone.utc),
        total_value=total_value,
        risk_profile=risk_profile,
        health=health,
        holding_recommendations=recommendations,
        rebalance_suggestions=rebalance_suggestions,
        overall_assessment=overall_assessment,
        warnings=warnings,
    )
