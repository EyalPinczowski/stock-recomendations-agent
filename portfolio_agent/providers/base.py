"""Provider interfaces. These are the only places allowed to talk to the outside
world (yfinance, news APIs, the filesystem for portfolio state) — analysis and
optimization code stays pure and testable by depending only on these interfaces.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from portfolio_agent.models import PortfolioSnapshot


class PortfolioProvider(ABC):
    @abstractmethod
    def get_snapshot(self) -> PortfolioSnapshot: ...


class MarketDataProvider(ABC):
    @abstractmethod
    def get_price_history(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        """OHLCV DataFrame indexed by date, columns: Open High Low Close Volume."""

    @abstractmethod
    def get_current_price(self, ticker: str) -> float | None: ...

    @abstractmethod
    def get_analyst_data(self, ticker: str) -> dict: ...

    @abstractmethod
    def get_market_cap(self, ticker: str) -> float | None: ...

    @abstractmethod
    def get_beta(self, ticker: str) -> float | None: ...

    @abstractmethod
    def get_sector(self, ticker: str) -> str | None: ...

    @abstractmethod
    def get_fx_rate(self, from_currency: str, to_currency: str) -> float: ...


class NewsProvider(ABC):
    @abstractmethod
    def get_headlines(self, query: str, limit: int = 15) -> list[dict]:
        """Each item: {title, source, published_at, url}."""

    @property
    @abstractmethod
    def available(self) -> bool: ...
