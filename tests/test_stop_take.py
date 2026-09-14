import pandas as pd

from portfolio_agent.analysis.stop_take import compute_stop_take


def _make_df(prices):
    n = len(prices)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    close = pd.Series(prices, index=idx, dtype=float)
    high = close * 1.02
    low = close * 0.98
    return pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close, "Volume": 1000})


def test_stop_below_and_target_above_current_price():
    prices = [100 + (i % 10) for i in range(60)]
    df = _make_df(prices)
    current_price = prices[-1]
    levels = compute_stop_take(df, current_price)
    assert levels.stop_loss is not None
    assert levels.take_profit is not None
    assert levels.stop_loss < current_price
    assert levels.take_profit > current_price
    assert levels.method in ("atr", "support_resistance", "blended")


def test_empty_df_returns_empty_levels():
    levels = compute_stop_take(pd.DataFrame(), 100.0)
    assert levels.stop_loss is None
    assert levels.take_profit is None
