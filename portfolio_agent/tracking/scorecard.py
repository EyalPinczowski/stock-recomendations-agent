"""Lightweight accountability check: compares past recommendations against
what the price actually did since. Not a full backtester — a fast,
low-complexity stand-in that still gives a real, honest read on the track
record.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from portfolio_agent.models import LoggedRecommendation
from portfolio_agent.providers.base import MarketDataProvider
from portfolio_agent.tracking.log import read_log

BULLISH_ACTIONS = {"buy", "add"}
BEARISH_ACTIONS = {"sell", "trim"}


def _price_change_pct(entry: LoggedRecommendation, current_price: float) -> float:
    if entry.price_at_recommendation == 0:
        return 0.0
    return (current_price - entry.price_at_recommendation) / entry.price_at_recommendation


def compute_scorecard_stats(entries: list[LoggedRecommendation], market: MarketDataProvider) -> dict:
    stats: dict[str, dict] = {}
    price_cache: dict[str, float | None] = {}

    for entry in entries:
        if entry.ticker not in price_cache:
            price_cache[entry.ticker] = market.get_current_price(entry.ticker)
        current_price = price_cache[entry.ticker]
        if current_price is None:
            continue

        change = _price_change_pct(entry, current_price)
        bucket = stats.setdefault(entry.action, {"count": 0, "total_change": 0.0, "correct": 0})
        bucket["count"] += 1
        bucket["total_change"] += change
        if entry.action in BULLISH_ACTIONS and change > 0:
            bucket["correct"] += 1
        elif entry.action in BEARISH_ACTIONS and change < 0:
            bucket["correct"] += 1

    return stats


def build_scorecard_text(state_dir: Path, market: MarketDataProvider, since_days: int = 30) -> str:
    entries = read_log(state_dir)
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    entries = [e for e in entries if e.recommended_at >= cutoff]

    if not entries:
        return f"No recommendations logged in the last {since_days} days yet."

    stats = compute_scorecard_stats(entries, market)
    lines = [f"Scorecard — last {since_days} days ({len(entries)} recommendations logged)"]
    for action, s in sorted(stats.items()):
        avg_change = s["total_change"] / s["count"] if s["count"] else 0.0
        hit_rate = s["correct"] / s["count"] if s["count"] else 0.0
        lines.append(
            f"  {action.upper()}: {s['count']} calls, avg return since recommendation "
            f"{avg_change:+.1%}, directionally correct {hit_rate:.0%}"
        )
    return "\n".join(lines)
