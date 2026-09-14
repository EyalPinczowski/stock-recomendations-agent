"""Combines technical, analyst, sentiment, and market-context signals into one
composite score, maps that to an Action, and writes a deterministic (non-LLM)
rationale from the underlying signal values — reproducible and unit-testable.
"""

from __future__ import annotations

from datetime import date

from portfolio_agent.models import (
    Action,
    AnalysisResult,
    AnalystSignal,
    Bucket,
    MarketContextSignal,
    SentimentSignal,
    StopTakeLevels,
    TechnicalSignal,
)

WEIGHTS = {
    "technical": 0.35,
    "analyst": 0.25,
    "sentiment": 0.15,
    "market_context": 0.25,
}

BUY_THRESHOLD = 0.5
MILD_POSITIVE_THRESHOLD = 0.15
MILD_NEGATIVE_THRESHOLD = -0.15
SELL_THRESHOLD = -0.5


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def composite_score(
    technical: TechnicalSignal,
    analyst: AnalystSignal,
    sentiment: SentimentSignal,
    market_context: MarketContextSignal,
) -> float:
    parts: list[float] = []
    weights: list[float] = []

    parts.append(technical.trend_score)
    weights.append(WEIGHTS["technical"])

    if analyst.mean_rating is not None or analyst.price_target_upside_pct is not None:
        parts.append(analyst.analyst_score)
        weights.append(WEIGHTS["analyst"])

    sentiment_component = sentiment.sentiment_score - 0.5 * sentiment.geopolitical_risk_score
    parts.append(_clip(sentiment_component))
    weights.append(WEIGHTS["sentiment"])

    market_component = _clip(market_context.relative_strength_63d / 0.15)
    parts.append(market_component)
    weights.append(WEIGHTS["market_context"])

    total_weight = sum(weights)
    if total_weight == 0:
        return 0.0
    return _clip(sum(p * w for p, w in zip(parts, weights)) / total_weight)


def to_action(score: float, holding_exists: bool) -> Action:
    if score >= BUY_THRESHOLD:
        return Action.ADD if holding_exists else Action.BUY
    if score > MILD_NEGATIVE_THRESHOLD:
        return Action.HOLD
    if score > SELL_THRESHOLD:
        return Action.TRIM
    return Action.SELL


def build_rationale(
    ticker: str,
    technical: TechnicalSignal,
    analyst: AnalystSignal,
    sentiment: SentimentSignal,
    market_context: MarketContextSignal,
    stop_take: StopTakeLevels,
    action: Action,
) -> str:
    parts: list[str] = []

    if technical.rsi_14 is not None:
        if technical.rsi_14 > 70:
            parts.append(f"RSI at {technical.rsi_14:.0f} (overbought)")
        elif technical.rsi_14 < 30:
            parts.append(f"RSI at {technical.rsi_14:.0f} (oversold)")
        else:
            parts.append(f"RSI at {technical.rsi_14:.0f}")

    if technical.sma_50 is not None and technical.sma_200 is not None:
        if technical.sma_50 > technical.sma_200:
            parts.append("50-day SMA above 200-day SMA (up-trend)")
        else:
            parts.append("50-day SMA below 200-day SMA (down-trend)")

    if technical.momentum_63d is not None:
        parts.append(f"{technical.momentum_63d:+.0%} over the trailing ~3 months")

    if analyst.mean_rating is not None:
        rating_word = (
            "Strong Buy" if analyst.mean_rating <= 1.5 else
            "Buy" if analyst.mean_rating <= 2.5 else
            "Hold" if analyst.mean_rating <= 3.5 else
            "Sell" if analyst.mean_rating <= 4.5 else "Strong Sell"
        )
        upside = f", {analyst.price_target_upside_pct:+.0%} to mean target" if analyst.price_target_upside_pct is not None else ""
        parts.append(f"analyst consensus {rating_word}{upside}")

    if not sentiment.degraded and sentiment.headline_count > 0:
        tone = "positive" if sentiment.sentiment_score > 0.15 else "negative" if sentiment.sentiment_score < -0.15 else "neutral"
        parts.append(f"news sentiment {tone}")
        if sentiment.geopolitical_risk_score > 0.4:
            parts.append("elevated geopolitical risk flagged")

    if market_context.relative_strength_63d:
        vs = "outperforming" if market_context.relative_strength_63d > 0 else "underperforming"
        parts.append(f"{vs} {market_context.benchmark_ticker} by {abs(market_context.relative_strength_63d):.0%} over 3 months")

    sentence = ", ".join(parts) if parts else "insufficient signal data"
    return f"{sentence} → {action.value.upper()}."


def build_analysis_result(
    ticker: str,
    as_of: date,
    current_price: float,
    technical: TechnicalSignal,
    analyst: AnalystSignal,
    sentiment: SentimentSignal,
    market_context: MarketContextSignal,
    stop_take: StopTakeLevels,
    bucket: Bucket,
    sector: str | None,
    volatility_annualized: float | None,
    beta: float | None,
) -> AnalysisResult:
    score = composite_score(technical, analyst, sentiment, market_context)
    return AnalysisResult(
        ticker=ticker,
        as_of=as_of,
        current_price=current_price,
        technical=technical,
        analyst=analyst,
        sentiment=sentiment,
        market_context=market_context,
        stop_take=stop_take,
        composite_score=score,
        bucket=bucket,
        sector=sector,
        volatility_annualized=volatility_annualized,
        beta=beta,
    )
