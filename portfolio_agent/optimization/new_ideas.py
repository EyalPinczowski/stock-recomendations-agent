"""Scans the universe for stocks that would fill an identified gap in the
portfolio (underweight bucket, missing/underweight sector) — a distinct
question from "what should I do with what I own" or "what's a good short-term
trade." Reuses long-horizon technical + analyst scoring (no sentiment/LLM per
candidate, same cost discipline as short-term screening).
"""

from __future__ import annotations

from portfolio_agent.analysis.trend import SECTOR_ETF
from portfolio_agent.models import Bucket, NewStockSuggestion, RiskProfile

SECTOR_UNDERWEIGHT_THRESHOLD = 0.05
MIN_IDEA_SCORE = 0.35
MAX_SUGGESTIONS = 6
REFERENCE_SECTORS = sorted({s for s in SECTOR_ETF if s not in ("Financials",)})


def identify_gaps(
    bucket_pcts: dict[str, float],
    sector_pcts: dict[str, float],
    risk_profile: RiskProfile,
) -> tuple[list[str], set[str]]:
    """Returns (plain-language gap descriptions, set of sectors to target)."""
    gaps: list[str] = []
    target_sectors: set[str] = set()

    conservative_pct = bucket_pcts.get(Bucket.CONSERVATIVE.value, 0.0)
    aggressive_pct = bucket_pcts.get(Bucket.AGGRESSIVE.value, 0.0)
    if conservative_pct < risk_profile.target_conservative_pct - risk_profile.rebalance_drift_threshold_pct:
        gaps.append(
            f"Conservative bucket {conservative_pct:.0%} vs target {risk_profile.target_conservative_pct:.0%}"
        )
    if aggressive_pct < risk_profile.target_aggressive_pct - risk_profile.rebalance_drift_threshold_pct:
        gaps.append(
            f"Aggressive bucket {aggressive_pct:.0%} vs target {risk_profile.target_aggressive_pct:.0%}"
        )

    for sector in REFERENCE_SECTORS:
        current = sector_pcts.get(sector, 0.0)
        if current < SECTOR_UNDERWEIGHT_THRESHOLD:
            gaps.append(f"{sector} exposure is {current:.0%} (underweight)")
            target_sectors.add(sector)

    return gaps, target_sectors


def compute_idea_score(trend_score: float, analyst_score: float | None) -> float:
    if analyst_score is None:
        return trend_score
    return 0.5 * trend_score + 0.5 * analyst_score


def suggested_allocation_pct(score: float, risk_profile: RiskProfile) -> float:
    raw = 0.03 + 0.07 * max(0.0, score)
    return min(risk_profile.max_position_pct, raw)


def build_fit_reason(
    ticker: str, bucket: Bucket, sector: str | None, bucket_gap: bool, sector_gap: bool
) -> str:
    reasons = []
    if bucket_gap:
        reasons.append(f"fills underweight {bucket.value} bucket")
    if sector_gap and sector:
        reasons.append(f"adds {sector} exposure, currently underweight")
    if not reasons:
        reasons.append("strong long-term technical/analyst signal")
    return "; ".join(reasons)


def build_new_stock_suggestion(
    ticker: str,
    sector: str | None,
    bucket: Bucket,
    trend_score: float,
    analyst_score: float | None,
    risk_profile: RiskProfile,
    bucket_gap: bool,
    sector_gap: bool,
    rationale: str,
) -> NewStockSuggestion:
    score = compute_idea_score(trend_score, analyst_score)
    return NewStockSuggestion(
        ticker=ticker,
        sector=sector,
        bucket=bucket,
        fit_reason=build_fit_reason(ticker, bucket, sector, bucket_gap, sector_gap),
        composite_score=score,
        suggested_allocation_pct=suggested_allocation_pct(score, risk_profile),
        rationale=rationale,
    )
