"""Explainable 3-factor vote (volatility, beta, market cap) that classifies a
holding as conservative or aggressive. An explicit user-set bucket in the
portfolio file/screenshot always wins over this — callers should only invoke
this for holdings still marked UNCLASSIFIED.
"""

from __future__ import annotations

from portfolio_agent.models import Bucket

HIGH_VOLATILITY_THRESHOLD = 0.35
HIGH_BETA_THRESHOLD = 1.2
LOW_BETA_THRESHOLD = 0.8
SMALL_CAP_THRESHOLD = 10_000_000_000
LARGE_CAP_THRESHOLD = 100_000_000_000


def classify_bucket(
    volatility_annualized: float | None,
    beta: float | None,
    market_cap: float | None,
) -> Bucket:
    score = 0
    if volatility_annualized is not None:
        score += 1 if volatility_annualized > HIGH_VOLATILITY_THRESHOLD else -1
    if beta is not None:
        if beta > HIGH_BETA_THRESHOLD:
            score += 1
        elif beta < LOW_BETA_THRESHOLD:
            score -= 1
    if market_cap is not None:
        if market_cap < SMALL_CAP_THRESHOLD:
            score += 1
        elif market_cap > LARGE_CAP_THRESHOLD:
            score -= 1

    if volatility_annualized is None and beta is None and market_cap is None:
        return Bucket.UNCLASSIFIED
    return Bucket.AGGRESSIVE if score > 0 else Bucket.CONSERVATIVE
