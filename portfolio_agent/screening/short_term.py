"""Short-horizon technical scoring for the broad-universe screen. Deliberately
technical/price-action only — no sentiment or per-candidate analyst weighting,
since that would mean one LLM/network call per ticker across hundreds of
names. Reuses analysis/technical.py and analysis/stop_take.py, parameterized
for a shorter horizon than the holdings analysis.
"""

from __future__ import annotations

import pandas as pd

from portfolio_agent.analysis.stop_take import compute_stop_take
from portfolio_agent.analysis.technical import momentum, rsi, sma
from portfolio_agent.models import ShortTermCandidate, StopTakeLevels
from portfolio_agent.screening.universe import UniverseEntry

SHORT_WINDOW = "3mo"
SETUP_SCORE_THRESHOLD = 0.5
TOP_N_CANDIDATES = 12
HORIZON_DAYS = 10


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def compute_setup_score(df: pd.DataFrame) -> float:
    if df is None or len(df) < 25:
        return 0.0
    close = df["Close"]

    sma_10 = sma(close, 10).iloc[-1]
    sma_20 = sma(close, 20).iloc[-1]
    cross_component = _clip((sma_10 - sma_20) / sma_20 * 8) if pd.notna(sma_20) and sma_20 else 0.0

    rsi_series = rsi(close)
    rsi_value = rsi_series.iloc[-1] if len(rsi_series.dropna()) else 50
    rsi_component = _clip((rsi_value - 50) / 25)

    mom_5 = momentum(close, window=5) or 0.0
    mom_10 = momentum(close, window=10) or 0.0
    momentum_component = _clip((mom_5 * 0.6 + mom_10 * 0.4) / 0.08)

    volume_component = 0.0
    if "Volume" in df.columns and len(df) >= 20:
        avg_vol = df["Volume"].tail(20).mean()
        last_vol = df["Volume"].iloc[-1]
        if avg_vol:
            volume_component = _clip((last_vol / avg_vol - 1) / 2)

    return _clip(
        0.35 * cross_component + 0.3 * rsi_component + 0.25 * momentum_component + 0.1 * volume_component
    )


def build_candidate(entry: UniverseEntry, df: pd.DataFrame, current_price: float) -> ShortTermCandidate | None:
    score = compute_setup_score(df)
    if score < SETUP_SCORE_THRESHOLD:
        return None

    stop_take: StopTakeLevels = compute_stop_take(df, current_price)
    entry_low = current_price * 0.995
    entry_high = current_price * 1.01

    rationale = (
        f"Short-term momentum score {score:.2f}: 10/20-day moving average cross "
        f"and RSI both trending up over the last {HORIZON_DAYS} trading days."
    )

    return ShortTermCandidate(
        ticker=entry.ticker,
        setup_score=score,
        entry_zone_low=entry_low,
        entry_zone_high=entry_high,
        stop_take=stop_take,
        horizon_days=HORIZON_DAYS,
        rationale=rationale,
        sector=entry.sector,
    )
