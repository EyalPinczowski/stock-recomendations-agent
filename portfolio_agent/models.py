"""Core data models shared across providers, analysis, optimization, and reporting."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Bucket(str, Enum):
    CONSERVATIVE = "conservative"
    AGGRESSIVE = "aggressive"
    UNCLASSIFIED = "unclassified"


class Currency(str, Enum):
    USD = "USD"
    ILS = "ILS"


class Holding(BaseModel):
    ticker: str
    # As shown by the broker. TASE funds are listed under an opaque security
    # number, so the Hebrew name is the only human-readable label there.
    name: str | None = None
    quantity: float
    cost_basis: float
    purchase_date: date | None = None
    currency: Currency = Currency.USD
    bucket: Bucket = Bucket.UNCLASSIFIED
    sector: str | None = None
    notes: str | None = None


class PortfolioSnapshot(BaseModel):
    holdings: list[Holding]
    captured_at: datetime
    source: Literal["screenshot", "file"]
    # Uninvested balances by currency, e.g. {"USD": 8561.64, "ILS": -897.31}.
    # Not part of allocation math (that's about invested capital) but it's what
    # says how much is actually available to act on a BUY.
    cash_balances: dict[str, float] = Field(default_factory=dict)


class RiskProfile(BaseModel):
    """The single risk-reward dial threaded through optimization/reward-risk filtering."""

    name: str = "balanced"
    target_conservative_pct: float = 0.6
    target_aggressive_pct: float = 0.4
    min_reward_risk_ratio: float = 1.5
    max_position_pct: float = 0.15
    max_sector_pct: float = 0.25
    rebalance_drift_threshold_pct: float = 0.05


class TechnicalSignal(BaseModel):
    sma_50: float | None = None
    sma_200: float | None = None
    ema_12: float | None = None
    ema_26: float | None = None
    rsi_14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    momentum_63d: float | None = None
    atr_14: float | None = None
    volatility_annualized: float | None = None
    trend_score: float = 0.0


class AnalystSignal(BaseModel):
    mean_rating: float | None = None
    price_target_mean: float | None = None
    price_target_upside_pct: float | None = None
    num_analysts: int | None = None
    analyst_score: float = 0.0


class SentimentSignal(BaseModel):
    headline_count: int = 0
    sentiment_score: float = 0.0
    geopolitical_risk_score: float = 0.0
    summary: str = ""
    degraded: bool = True


class MarketContextSignal(BaseModel):
    benchmark_ticker: str = "SPY"
    relative_strength_63d: float = 0.0
    beta: float | None = None


class StopTakeLevels(BaseModel):
    stop_loss: float | None = None
    take_profit: float | None = None
    method: Literal["atr", "support_resistance", "blended"] | None = None
    stop_basis: str = ""
    target_basis: str = ""


class AnalysisResult(BaseModel):
    ticker: str
    as_of: date
    current_price: float
    technical: TechnicalSignal
    analyst: AnalystSignal
    sentiment: SentimentSignal
    market_context: MarketContextSignal
    stop_take: StopTakeLevels
    composite_score: float
    bucket: Bucket
    sector: str | None = None
    volatility_annualized: float | None = None
    beta: float | None = None


class Action(str, Enum):
    BUY = "buy"
    ADD = "add"
    HOLD = "hold"
    TRIM = "trim"
    SELL = "sell"


class ReviewVerdict(BaseModel):
    outcome: Literal["confirmed", "revised", "downgraded"] = "confirmed"
    notes: str = ""
    alternative_ticker: str | None = None


class Recommendation(BaseModel):
    ticker: str
    action: Action
    conviction: float
    reward_risk_ratio: float | None = None
    rationale: str
    stop_take: StopTakeLevels
    suggested_shares_delta: float | None = None
    suggested_dollar_delta: float | None = None
    related_result: AnalysisResult
    review: ReviewVerdict | None = None


class RebalanceSuggestion(BaseModel):
    kind: Literal["bucket", "sector"]
    label: str
    current_pct: float
    target_pct: float
    drift_pct: float
    action_summary: str


class PortfolioHealth(BaseModel):
    sharpe_ratio: float | None = None
    volatility_annualized: float | None = None
    max_drawdown_pct: float | None = None
    bucket_allocation: dict[str, float] = Field(default_factory=dict)
    sector_allocation: dict[str, float] = Field(default_factory=dict)
    concentration_warnings: list[str] = Field(default_factory=list)


class PortfolioReport(BaseModel):
    generated_at: datetime
    total_value: float
    currency: Currency = Currency.USD
    risk_profile: RiskProfile
    health: PortfolioHealth
    holding_recommendations: list[Recommendation]
    rebalance_suggestions: list[RebalanceSuggestion]
    # Uninvested balances by currency, carried through from the snapshot: the
    # allocation percentages are about invested capital, but what's available
    # to fund a BUY belongs in the report.
    cash_balances: dict[str, float] = Field(default_factory=dict)
    overall_assessment: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ShortTermCandidate(BaseModel):
    ticker: str
    setup_score: float
    entry_zone_low: float
    entry_zone_high: float
    stop_take: StopTakeLevels
    horizon_days: int = 10
    rationale: str
    sector: str | None = None
    review: ReviewVerdict | None = None


class ScreenReport(BaseModel):
    generated_at: datetime
    candidates: list[ShortTermCandidate]
    warnings: list[str] = Field(default_factory=list)


class NewStockSuggestion(BaseModel):
    ticker: str
    sector: str | None
    bucket: Bucket
    fit_reason: str
    composite_score: float
    suggested_allocation_pct: float
    rationale: str
    review: ReviewVerdict | None = None


class NewStockIdeasReport(BaseModel):
    generated_at: datetime
    gaps_identified: list[str]
    suggestions: list[NewStockSuggestion]
    warnings: list[str] = Field(default_factory=list)


class LoggedRecommendation(BaseModel):
    ticker: str
    action: str
    conviction: float
    price_at_recommendation: float
    recommended_at: datetime
    run_type: Literal["analyze", "screen", "newstocks"]
