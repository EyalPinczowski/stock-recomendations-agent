"""Stop-loss / take-profit levels: a blend of ATR-based volatility stops and
recent support/resistance (swing pivot) levels. These are suggested levels for
you to set as actual stop/limit orders at your broker — this module never
monitors prices or fires alerts itself.
"""

from __future__ import annotations

import pandas as pd

from portfolio_agent.analysis.technical import atr
from portfolio_agent.models import StopTakeLevels

ATR_STOP_MULTIPLE = 2.0
ATR_TARGET_MULTIPLE = 3.0
PIVOT_LOOKBACK = 40
PIVOT_WINDOW = 3  # a point is a pivot if it's the extreme within +/- this many bars


def _find_pivots(df: pd.DataFrame, lookback: int = PIVOT_LOOKBACK, window: int = PIVOT_WINDOW):
    recent = df.tail(lookback)
    highs, lows = recent["High"], recent["Low"]
    swing_highs, swing_lows = [], []
    values_h, values_l = highs.values, lows.values
    n = len(recent)
    for i in range(window, n - window):
        if values_h[i] == max(values_h[i - window : i + window + 1]):
            swing_highs.append(values_h[i])
        if values_l[i] == min(values_l[i - window : i + window + 1]):
            swing_lows.append(values_l[i])
    return swing_highs, swing_lows


def _nearest_support(price: float, swing_lows: list[float]) -> float | None:
    below = [v for v in swing_lows if v < price]
    return max(below) if below else None


def _nearest_resistance(price: float, swing_highs: list[float]) -> float | None:
    above = [v for v in swing_highs if v > price]
    return min(above) if above else None


def compute_stop_take(df: pd.DataFrame, current_price: float) -> StopTakeLevels:
    if df is None or df.empty or current_price <= 0:
        return StopTakeLevels()

    atr_14 = atr(df)
    swing_highs, swing_lows = _find_pivots(df)
    support = _nearest_support(current_price, swing_lows)
    resistance = _nearest_resistance(current_price, swing_highs)

    stop_atr = current_price - ATR_STOP_MULTIPLE * atr_14 if atr_14 else None
    target_atr = current_price + ATR_TARGET_MULTIPLE * atr_14 if atr_14 else None

    # Stop-loss: the tighter (higher) of the ATR stop and nearest support.
    if support is not None and (stop_atr is None or support >= stop_atr):
        stop_loss = support
        stop_basis = "nearest support level"
        method = "support_resistance" if stop_atr is None else "blended"
    elif stop_atr is not None:
        stop_loss = stop_atr
        stop_basis = f"{ATR_STOP_MULTIPLE:.0f}x ATR below current price"
        method = "atr" if support is None else "blended"
    else:
        stop_loss, stop_basis, method = None, "", None

    # Take-profit: the ATR target, unless resistance sits closer (more conservative).
    candidates_target = [v for v in (target_atr, resistance) if v is not None]
    if candidates_target:
        if resistance is not None and (target_atr is None or resistance < target_atr):
            take_profit = resistance
            target_basis = "nearest resistance level"
        else:
            take_profit = target_atr
            target_basis = f"{ATR_TARGET_MULTIPLE:.0f}x ATR above current price"
    else:
        take_profit, target_basis = None, ""

    return StopTakeLevels(
        stop_loss=stop_loss,
        take_profit=take_profit,
        method=method,
        stop_basis=stop_basis,
        target_basis=target_basis,
    )
