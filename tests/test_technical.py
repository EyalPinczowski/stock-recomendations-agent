import pandas as pd

from portfolio_agent.analysis.technical import (
    annualized_volatility,
    atr,
    build_technical_signal,
    ema,
    momentum,
    rsi,
    sma,
)


def _make_df(prices, highs=None, lows=None):
    n = len(prices)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    close = pd.Series(prices, index=idx, dtype=float)
    high = pd.Series(highs if highs else [p * 1.01 for p in prices], index=idx, dtype=float)
    low = pd.Series(lows if lows else [p * 0.99 for p in prices], index=idx, dtype=float)
    return pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close, "Volume": 1000})


def test_sma_basic():
    s = pd.Series([1, 2, 3, 4, 5])
    result = sma(s, 3)
    assert result.iloc[-1] == 4.0


def test_ema_converges_toward_recent_values():
    s = pd.Series([10.0] * 50 + [20.0] * 50)
    result = ema(s, 12)
    assert result.iloc[-1] > 15


def test_rsi_strong_uptrend_is_high():
    prices = [100 + i for i in range(30)]
    s = pd.Series(prices, dtype=float)
    result = rsi(s)
    assert result.iloc[-1] > 60


def test_rsi_strong_downtrend_is_low():
    prices = [100 - i for i in range(30)]
    s = pd.Series(prices, dtype=float)
    result = rsi(s)
    assert result.iloc[-1] < 40


def test_momentum_positive():
    prices = [100.0] * 63 + [120.0]
    s = pd.Series(prices)
    m = momentum(s, window=63)
    assert m is not None and abs(m - 0.2) < 1e-6


def test_momentum_none_when_insufficient_history():
    s = pd.Series([1.0, 2.0, 3.0])
    assert momentum(s, window=63) is None


def test_atr_positive_for_volatile_series():
    prices = [100 + (i % 5) * 3 for i in range(40)]
    df = _make_df(prices)
    result = atr(df)
    assert result is not None and result > 0


def test_annualized_volatility_higher_for_noisier_series():
    calm = [100 + 0.01 * i for i in range(60)]
    noisy = [100 + (10 if i % 2 == 0 else -10) for i in range(60)]
    calm_vol = annualized_volatility(pd.Series(calm))
    noisy_vol = annualized_volatility(pd.Series(noisy))
    assert noisy_vol > calm_vol


def test_build_technical_signal_empty_df_returns_neutral():
    result = build_technical_signal(pd.DataFrame())
    assert result.trend_score == 0.0


def test_build_technical_signal_uptrend_has_positive_trend_score():
    prices = [100 + i * 0.8 for i in range(220)]
    df = _make_df(prices)
    signal = build_technical_signal(df)
    assert signal.trend_score > 0
    assert signal.sma_50 is not None
    assert signal.sma_200 is not None
