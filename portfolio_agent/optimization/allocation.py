"""Bucket- and sector-level allocation, and the resulting rebalance suggestions.
This is the portfolio-level (not per-stock) piece that keeps the conservative/
aggressive mix and sector concentration on target.
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_agent.models import Bucket, RebalanceSuggestion


@dataclass
class ValuedHolding:
    ticker: str
    value_usd: float
    bucket: Bucket
    sector: str | None


def compute_bucket_allocation(holdings: list[ValuedHolding]) -> dict[str, float]:
    total = sum(h.value_usd for h in holdings)
    if total <= 0:
        return {}
    totals: dict[str, float] = {}
    for h in holdings:
        totals[h.bucket.value] = totals.get(h.bucket.value, 0.0) + h.value_usd
    return {k: v / total for k, v in totals.items()}


def compute_sector_allocation(holdings: list[ValuedHolding]) -> dict[str, float]:
    total = sum(h.value_usd for h in holdings)
    if total <= 0:
        return {}
    totals: dict[str, float] = {}
    for h in holdings:
        sector = h.sector or "Unknown"
        totals[sector] = totals.get(sector, 0.0) + h.value_usd
    return {k: v / total for k, v in totals.items()}


def bucket_rebalance_suggestions(
    bucket_pcts: dict[str, float],
    target_conservative_pct: float,
    target_aggressive_pct: float,
    drift_threshold_pct: float,
) -> list[RebalanceSuggestion]:
    targets = {
        Bucket.CONSERVATIVE.value: target_conservative_pct,
        Bucket.AGGRESSIVE.value: target_aggressive_pct,
    }
    suggestions = []
    for bucket, target in targets.items():
        current = bucket_pcts.get(bucket, 0.0)
        drift = current - target
        if abs(drift) >= drift_threshold_pct:
            direction = "Trim" if drift > 0 else "Add to"
            suggestions.append(
                RebalanceSuggestion(
                    kind="bucket",
                    label=bucket,
                    current_pct=current,
                    target_pct=target,
                    drift_pct=drift,
                    action_summary=f"{direction} {bucket} bucket by {abs(drift):.1%} to reach target.",
                )
            )
    return suggestions


def sector_concentration_suggestions(
    sector_pcts: dict[str, float],
    max_sector_pct: float,
) -> list[RebalanceSuggestion]:
    suggestions = []
    for sector, current in sector_pcts.items():
        if current > max_sector_pct:
            drift = current - max_sector_pct
            suggestions.append(
                RebalanceSuggestion(
                    kind="sector",
                    label=sector,
                    current_pct=current,
                    target_pct=max_sector_pct,
                    drift_pct=drift,
                    action_summary=f"{sector} is {current:.0%} of portfolio, exceeds your {max_sector_pct:.0%} cap.",
                )
            )
    return suggestions
