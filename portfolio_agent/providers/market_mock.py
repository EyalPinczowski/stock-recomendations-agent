"""Deterministic, offline MarketDataProvider used by --mock. Generates a
synthetic-but-stable price series per ticker (seeded by the ticker's hash) so
tests and demos never touch the network.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from portfolio_agent.providers.base import MarketDataProvider

MOCK_SECTORS = ["Technology", "Healthcare", "Financial Services", "Consumer Cyclical", "Energy"]


def _seed_for(ticker: str) -> int:
    return int(hashlib.sha256(ticker.encode()).hexdigest(), 16) % (2**32)


class MockMarketDataProvider(MarketDataProvider):
    def __init__(self):
        self._history_cache: dict[str, pd.DataFrame] = {}

    def get_price_history(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        if ticker in self._history_cache:
            return self._history_cache[ticker]

        rng = np.random.default_rng(_seed_for(ticker))
        n = 260
        drift = rng.uniform(-0.0003, 0.0008)
        daily_returns = rng.normal(loc=drift, scale=0.015, size=n)
        base_price = 50 + (_seed_for(ticker) % 400)
        close = base_price * np.cumprod(1 + daily_returns)
        idx = pd.date_range(end=pd.Timestamp.today(), periods=n, freq="B")
        high = close * (1 + rng.uniform(0.005, 0.02, size=n))
        low = close * (1 - rng.uniform(0.005, 0.02, size=n))
        df = pd.DataFrame(
            {"Open": close, "High": high, "Low": low, "Close": close, "Volume": 1_000_000},
            index=idx,
        )
        self._history_cache[ticker] = df
        return df

    def get_current_price(self, ticker: str) -> float | None:
        df = self.get_price_history(ticker)
        return float(df["Close"].iloc[-1]) if not df.empty else None

    def get_analyst_data(self, ticker: str) -> dict:
        rng = np.random.default_rng(_seed_for(ticker) + 1)
        price = self.get_current_price(ticker) or 100.0
        return {
            "recommendationMean": round(float(rng.uniform(1.5, 3.5)), 2),
            "numberOfAnalystOpinions": int(rng.integers(3, 30)),
            "targetMeanPrice": round(price * float(rng.uniform(0.9, 1.25)), 2),
        }

    def get_market_cap(self, ticker: str) -> float | None:
        rng = np.random.default_rng(_seed_for(ticker) + 2)
        return float(rng.uniform(2e9, 2e12))

    def get_beta(self, ticker: str) -> float | None:
        rng = np.random.default_rng(_seed_for(ticker) + 3)
        return round(float(rng.uniform(0.5, 1.8)), 2)

    def get_sector(self, ticker: str) -> str | None:
        return MOCK_SECTORS[_seed_for(ticker) % len(MOCK_SECTORS)]

    def get_fx_rate(self, from_currency: str, to_currency: str) -> float:
        if from_currency == to_currency:
            return 1.0
        return 0.27 if from_currency == "ILS" else 3.7
