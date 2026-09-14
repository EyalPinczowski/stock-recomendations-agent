"""yfinance-backed MarketDataProvider. yfinance is an unofficial Yahoo Finance
scraper and does periodically break/rate-limit, so every call is retried with a
short backoff and per-ticker fetch failures are isolated (caller decides what to
do with a None/empty result) rather than raising and killing the whole run.
"""

from __future__ import annotations

import logging
import time

import pandas as pd
import yfinance as yf

from portfolio_agent.providers.base import MarketDataProvider

logger = logging.getLogger(__name__)

RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 1.5


def _retry(fn, *args, **kwargs):
    last_exc = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - yfinance raises assorted exceptions
            last_exc = exc
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_BASE_DELAY * (2**attempt))
    logger.warning("yfinance call failed after %d attempts: %s", RETRY_ATTEMPTS, last_exc)
    return None


class YFinanceMarketDataProvider(MarketDataProvider):
    def __init__(self):
        self._ticker_cache: dict[str, yf.Ticker] = {}
        self._history_cache: dict[tuple[str, str], pd.DataFrame] = {}
        self._fx_cache: dict[tuple[str, str], float] = {}

    def _get_ticker(self, ticker: str) -> yf.Ticker:
        if ticker not in self._ticker_cache:
            self._ticker_cache[ticker] = yf.Ticker(ticker)
        return self._ticker_cache[ticker]

    def get_price_history(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        key = (ticker, period)
        if key in self._history_cache:
            return self._history_cache[key]

        def _fetch():
            df = self._get_ticker(ticker).history(period=period, auto_adjust=True)
            if df is None or df.empty:
                raise ValueError(f"No price history for {ticker}")
            return df

        df = _retry(_fetch)
        result = df if df is not None else pd.DataFrame()
        self._history_cache[key] = result
        return result

    def get_current_price(self, ticker: str) -> float | None:
        def _fetch():
            fi = self._get_ticker(ticker).fast_info
            price = fi.get("lastPrice") or fi.get("last_price")
            if price is None:
                raise ValueError(f"No current price for {ticker}")
            return float(price)

        return _retry(_fetch)

    def get_analyst_data(self, ticker: str) -> dict:
        def _fetch():
            info = self._get_ticker(ticker).info
            return {
                "recommendationMean": info.get("recommendationMean"),
                "numberOfAnalystOpinions": info.get("numberOfAnalystOpinions"),
                "targetMeanPrice": info.get("targetMeanPrice"),
            }

        return _retry(_fetch) or {}

    def get_market_cap(self, ticker: str) -> float | None:
        def _fetch():
            fi = self._get_ticker(ticker).fast_info
            cap = fi.get("marketCap") or fi.get("market_cap")
            return float(cap) if cap else None

        return _retry(_fetch)

    def get_beta(self, ticker: str) -> float | None:
        def _fetch():
            beta = self._get_ticker(ticker).info.get("beta")
            return float(beta) if beta is not None else None

        return _retry(_fetch)

    def get_sector(self, ticker: str) -> str | None:
        def _fetch():
            return self._get_ticker(ticker).info.get("sector")

        return _retry(_fetch)

    def get_fx_rate(self, from_currency: str, to_currency: str) -> float:
        if from_currency == to_currency:
            return 1.0
        key = (from_currency, to_currency)
        if key in self._fx_cache:
            return self._fx_cache[key]

        def _fetch():
            pair = f"{from_currency}{to_currency}=X"
            fi = yf.Ticker(pair).fast_info
            rate = fi.get("lastPrice") or fi.get("last_price")
            if rate is None:
                raise ValueError(f"No FX rate for {pair}")
            return float(rate)

        rate = _retry(_fetch)
        result = rate if rate is not None else 1.0
        self._fx_cache[key] = result
        return result
