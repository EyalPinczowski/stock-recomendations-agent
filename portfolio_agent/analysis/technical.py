"""Technical indicators computed from an OHLCV price history DataFrame.

Everything here is a pure function over pandas data — no network calls, fully
unit-testable against fixture/synthetic series.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from portfolio_agent.models import TechnicalSignal

TREND_WEIGHTS = {
    "sma_cross": 0.4,
    "rsi": 0.3,
    "momentum": 0.3,
}


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    # avg_loss == 0: pure uptrend -> RSI 100; avg_gain == 0 too (flat) -> neutral 50.
    result = result.where(avg_loss != 0, other=np.where(avg_gain > 0, 100.0, 50.0))
    return pd.Series(result, index=series.index).fillna(50)


def macd(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    macd_line = ema(series, 12) - ema(series, 26)
    signal_line = ema(macd_line, 9)
    return macd_line, signal_line


def momentum(series: pd.Series, window: int = 63) -> float | None:
    if len(series) <= window:
        return None
    return float(series.iloc[-1] / series.iloc[-window] - 1)


def true_range(df: pd.DataFrame) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr


def atr(df: pd.DataFrame, window: int = 14) -> float | None:
    tr = true_range(df)
    if len(tr.dropna()) < window:
        return None
    value = tr.ewm(alpha=1 / window, min_periods=window, adjust=False).mean().iloc[-1]
    return float(value) if pd.notna(value) else None


def annualized_volatility(series: pd.Series) -> float | None:
    returns = series.pct_change().dropna()
    if len(returns) < 5:
        return None
    return float(returns.std() * np.sqrt(252))


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _sma_cross_component(sma_50: float | None, sma_200: float | None) -> float:
    if sma_50 is None or sma_200 is None or sma_200 == 0:
        return 0.0
    return _clip((sma_50 - sma_200) / sma_200 * 5)


def _rsi_component(rsi_value: float | None) -> float:
    if rsi_value is None:
        return 0.0
    # Momentum-aligned: above 50 mildly positive, but penalize extreme overbought/oversold.
    centered = (rsi_value - 50) / 50
    if rsi_value > 70:
        centered -= (rsi_value - 70) / 30
    elif rsi_value < 30:
        centered += (30 - rsi_value) / 30
    return _clip(centered)


def _momentum_component(momentum_value: float | None) -> float:
    if momentum_value is None:
        return 0.0
    return _clip(momentum_value / 0.20)


def build_technical_signal(df: pd.DataFrame) -> TechnicalSignal:
    if df is None or df.empty or "Close" not in df.columns:
        return TechnicalSignal()

    close = df["Close"]
    sma_50 = sma(close, 50).iloc[-1] if len(close) >= 50 else None
    sma_200 = sma(close, 200).iloc[-1] if len(close) >= 200 else None
    ema_12 = ema(close, 12).iloc[-1] if len(close) >= 12 else None
    ema_26 = ema(close, 26).iloc[-1] if len(close) >= 26 else None
    rsi_series = rsi(close)
    rsi_14 = rsi_series.iloc[-1] if len(rsi_series.dropna()) else None
    macd_line, signal_line = macd(close)
    mom = momentum(close)
    atr_14 = atr(df)
    vol = annualized_volatility(close)

    trend_score = _clip(
        TREND_WEIGHTS["sma_cross"] * _sma_cross_component(sma_50, sma_200)
        + TREND_WEIGHTS["rsi"] * _rsi_component(rsi_14)
        + TREND_WEIGHTS["momentum"] * _momentum_component(mom)
    )

    return TechnicalSignal(
        sma_50=float(sma_50) if sma_50 is not None and pd.notna(sma_50) else None,
        sma_200=float(sma_200) if sma_200 is not None and pd.notna(sma_200) else None,
        ema_12=float(ema_12) if ema_12 is not None and pd.notna(ema_12) else None,
        ema_26=float(ema_26) if ema_26 is not None and pd.notna(ema_26) else None,
        rsi_14=float(rsi_14) if rsi_14 is not None and pd.notna(rsi_14) else None,
        macd=float(macd_line.iloc[-1]) if pd.notna(macd_line.iloc[-1]) else None,
        macd_signal=float(signal_line.iloc[-1]) if pd.notna(signal_line.iloc[-1]) else None,
        momentum_63d=mom,
        atr_14=atr_14,
        volatility_annualized=vol,
        trend_score=trend_score,
    )
