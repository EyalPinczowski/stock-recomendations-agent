"""Orchestrates the `screen` flow: universe -> short-horizon technical scoring
-> (optional) review pass -> ScreenReport.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from portfolio_agent.models import RiskProfile, ScreenReport
from portfolio_agent.providers.base import MarketDataProvider
from portfolio_agent.screening.short_term import TOP_N_CANDIDATES, build_candidate
from portfolio_agent.screening.universe import load_universe


def run_screen(
    market: MarketDataProvider,
    risk_profile: RiskProfile,
    universe_path: str | Path = "data/sp500_constituents.csv",
    review_fn=None,
    state_dir: str = "state",
) -> ScreenReport:
    warnings: list[str] = []
    entries = load_universe(universe_path)
    if not entries:
        warnings.append(f"Universe file not found or empty: {universe_path}")

    candidates = []
    for entry in entries:
        try:
            df = market.get_price_history(entry.ticker, period="3mo")
            price = market.get_current_price(entry.ticker)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{entry.ticker}: market data fetch failed ({exc}), skipped.")
            continue
        if df is None or df.empty or price is None:
            continue

        candidate = build_candidate(entry, df, price)
        if candidate is not None:
            candidates.append(candidate)

    candidates.sort(key=lambda c: c.setup_score, reverse=True)
    candidates = candidates[:TOP_N_CANDIDATES]

    if review_fn is not None:
        try:
            candidates = review_fn(candidates, warnings)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Review pass failed ({exc}), using unreviewed candidates.")

    try:
        from portfolio_agent.tracking.log import log_candidates

        log_candidates(candidates, state_dir)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Failed to write recommendation log: {exc}")

    return ScreenReport(
        generated_at=datetime.now(timezone.utc),
        candidates=candidates,
        warnings=warnings,
    )
