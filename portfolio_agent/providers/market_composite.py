"""Routes each ticker to the provider that actually carries it.

Yahoo covers the US listings well and Israeli ones poorly or not at all, so
`.TA` tickers with a TASE security number go to TASE's own API instead. Every
other ticker — including Israeli listings that only have a letter symbol, which
TASE's API can't look up — stays with the default provider.

FX always goes to the default provider: a currency pair belongs to neither
exchange, and Yahoo carries USD/ILS fine.
"""

from __future__ import annotations

import logging

import pandas as pd

from portfolio_agent.providers.base import MarketDataProvider
from portfolio_agent.providers.market_tase import (
    TaseMarketDataProvider,
    is_tase_ticker,
    security_id_from_ticker,
)

logger = logging.getLogger(__name__)


class CompositeMarketDataProvider(MarketDataProvider):
    def __init__(self, default: MarketDataProvider, tase: MarketDataProvider | None = None):
        self.default = default
        self.tase = tase if tase is not None else TaseMarketDataProvider()

    def provider_for(self, ticker: str) -> MarketDataProvider:
        if is_tase_ticker(ticker) and security_id_from_ticker(ticker) is not None:
            return self.tase
        return self.default

    def source_name(self, ticker: str) -> str:
        return "tase" if self.provider_for(ticker) is self.tase else "yahoo"

    def get_price_history(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        return self.provider_for(ticker).get_price_history(ticker, period)

    def get_current_price(self, ticker: str) -> float | None:
        return self.provider_for(ticker).get_current_price(ticker)

    def get_analyst_data(self, ticker: str) -> dict:
        return self.provider_for(ticker).get_analyst_data(ticker)

    def get_market_cap(self, ticker: str) -> float | None:
        return self.provider_for(ticker).get_market_cap(ticker)

    def get_beta(self, ticker: str) -> float | None:
        return self.provider_for(ticker).get_beta(ticker)

    def get_sector(self, ticker: str) -> str | None:
        return self.provider_for(ticker).get_sector(ticker)

    def get_fx_rate(self, from_currency: str, to_currency: str) -> float:
        return self.default.get_fx_rate(from_currency, to_currency)
