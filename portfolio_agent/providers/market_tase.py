"""Market data for Tel Aviv securities, straight from TASE.

Yahoo Finance doesn't reliably carry Israeli listings, so `.TA` tickers get
their data here instead — from the same API the TASE website itself uses. It
takes the security number (`מספר ני"ע`), which is exactly what the broker's
screenshot shows, so no symbol translation is needed at all.

Two endpoints, tried in order, because TASE splits its instruments:
  api.tase.co.il/api/security/historyeod   — shares and ETFs (קרנות סל)
  maya.tase.co.il/api/v1/funds/mutual/…    — mutual funds (קרנות נאמנות)

Plain REST over `requests`, for the same reason the LLM layer is: nothing to
compile on Termux.

Prices come back in agorot (1/100 ILS), as the exchange quotes them, and are
converted to shekels here so everything downstream is in one unit.

Field names are matched leniently rather than pinned. This is an undocumented
API read from how the site calls it, so a renamed key should cost a column,
not the whole holding — and any row that can't be read logs the keys it did
see, which is enough to fix it.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests

from portfolio_agent.providers.base import MarketDataProvider

logger = logging.getLogger(__name__)

SECURITIES_API = "https://api.tase.co.il/api/"
FUNDS_API = "https://maya.tase.co.il/api/v1/"
FUND_DETAILS_API = "https://mayaapi.tase.co.il/api/"

# The API rejects requests that don't look like they came from the site.
BASE_HEADERS = {
    "Cache-Control": "no-cache",
    "Referer": "https://www.tase.co.il/",
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

REQUEST_TIMEOUT = 45
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 1.5

AGOROT_PER_SHEKEL = 100

# Candidate key names per column, most specific first. Compared with
# punctuation and case stripped, so "TradeDate", "tradeDate" and "trade_date"
# all match the same entry.
FIELD_CANDIDATES = {
    "Close": ("closingrate", "closerate", "close", "baserate", "sellprice", "rate", "price", "purchaseprice"),
    "Open": ("openrate", "openingrate", "open"),
    "High": ("highrate", "high", "maxrate", "highprice"),
    "Low": ("lowrate", "low", "minrate", "lowprice"),
    "Volume": ("volume", "tradedunits", "turnover", "unitsvolume", "marketvalue"),
}
DATE_CANDIDATES = ("tradedate", "date", "tradingdate", "dealdate", "dt")

PERIOD_DAYS = {"1mo": 31, "3mo": 93, "6mo": 186, "1y": 366, "2y": 731, "5y": 1827}


class TaseUnavailableError(RuntimeError):
    """TASE's API couldn't be reached or returned nothing usable."""


def is_tase_ticker(ticker: str) -> bool:
    return ticker.upper().endswith(".TA")


def security_id_from_ticker(ticker: str) -> str | None:
    """'1159714.TA' -> '1159714'. Letter symbols (TEVA.TA) have no security
    number to work with, so they stay with the default provider."""
    stem = ticker.rsplit(".", 1)[0]
    return stem if stem.isdigit() else None


def _normalize(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _pick(row: dict, candidates: tuple[str, ...]) -> object | None:
    normalized = {_normalize(k): v for k, v in row.items()}
    for candidate in candidates:
        value = normalized.get(candidate)
        if value not in (None, ""):
            return value
    return None


def _parse_number(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^\d.\-]", "", str(value))
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):  # epoch milliseconds
        return datetime.fromtimestamp(value / 1000).date()
    text = str(value).strip()
    # "/Date(1694......)/" turns up in some ASP.NET-shaped responses.
    epoch = re.match(r"^/Date\((\d+)", text)
    if epoch:
        return datetime.fromtimestamp(int(epoch.group(1)) / 1000).date()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[: len(fmt) + 2].rstrip("Z"), fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "")).date()
    except ValueError:
        return None


def _rows_to_frame(rows: list[dict], security_id: str) -> pd.DataFrame:
    """Rows -> an OHLCV frame in shekels. Missing columns fall back to Close so
    downstream maths still runs; a row with no date or close is dropped."""
    records = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        day = _parse_date(_pick(row, DATE_CANDIDATES))
        close = _parse_number(_pick(row, FIELD_CANDIDATES["Close"]))
        if day is None or close is None:
            continue

        record = {"date": day, "Close": close / AGOROT_PER_SHEKEL}
        for column in ("Open", "High", "Low"):
            value = _parse_number(_pick(row, FIELD_CANDIDATES[column]))
            record[column] = value / AGOROT_PER_SHEKEL if value else record["Close"]
        volume = _parse_number(_pick(row, FIELD_CANDIDATES["Volume"]))
        record["Volume"] = volume or 0.0
        records.append(record)

    if not records:
        # Worth the noise: this is the one thing that would need fixing if TASE
        # renames a field, and the keys are what identify the new name.
        sample = sorted(rows[0].keys()) if rows and isinstance(rows[0], dict) else []
        logger.warning(
            "TASE returned %d rows for %s but none could be read. Keys seen: %s",
            len(rows), security_id, sample,
        )
        return pd.DataFrame()

    frame = pd.DataFrame(records).drop_duplicates(subset="date")
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date").sort_index()[["Open", "High", "Low", "Close", "Volume"]]


def _extract_rows(payload) -> list[dict]:
    """The two endpoints wrap their rows differently."""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("Items", "items", "Data", "data", "Result", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _extract_rows(value)
            if nested:
                return nested
    return []


class TaseMarketDataProvider(MarketDataProvider):
    """Reads Tel Aviv securities by their TASE security number."""

    def __init__(self, session: requests.Session | None = None):
        self._session = session or requests.Session()
        self._history_cache: dict[tuple[str, str], pd.DataFrame] = {}
        self._details_cache: dict[str, dict] = {}

    # --- HTTP ---------------------------------------------------------------

    def _request(self, method: str, url: str, **kwargs) -> object | None:
        last_error: Exception | None = None
        for attempt in range(RETRY_ATTEMPTS):
            try:
                response = self._session.request(
                    method, url, headers=BASE_HEADERS, timeout=REQUEST_TIMEOUT, **kwargs
                )
                if response.status_code == 200:
                    return response.json()
                last_error = TaseUnavailableError(f"{response.status_code} from {url}")
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_BASE_DELAY * (2**attempt))
        logger.warning("TASE request failed (%s): %s", url, last_error)
        return None

    def _fetch_security_history(self, security_id: str, start: date, end: date) -> list[dict]:
        payload = self._request(
            "POST",
            f"{SECURITIES_API}security/historyeod",
            json={
                "dFrom": start.isoformat(),
                "dTo": end.isoformat(),
                "oId": security_id,
                "pageNum": 1,
                "pType": "8",
                "TotalRec": 1,
                "lang": "1",
            },
        )
        return _extract_rows(payload)

    def _fetch_fund_history(self, security_id: str, start: date, end: date) -> list[dict]:
        payload = self._request(
            "POST",
            f"{FUNDS_API}funds/mutual/{security_id}/history",
            json={
                "pageSize": 500,
                "pageNumber": 1,
                "period": 4,  # custom range
                "fromDate": f"{start.isoformat()}T00:00:00.000Z",
                "toDate": f"{end.isoformat()}T00:00:00.000Z",
            },
        )
        return _extract_rows(payload)

    # --- MarketDataProvider -------------------------------------------------

    def get_price_history(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        key = (ticker, period)
        if key in self._history_cache:
            return self._history_cache[key]

        security_id = security_id_from_ticker(ticker)
        if security_id is None:
            return pd.DataFrame()

        end = date.today()
        start = end - timedelta(days=PERIOD_DAYS.get(period, 366))

        frame = _rows_to_frame(self._fetch_security_history(security_id, start, end), security_id)
        if frame.empty:
            # Not a traded security — try the mutual-fund side before giving up.
            frame = _rows_to_frame(self._fetch_fund_history(security_id, start, end), security_id)

        self._history_cache[key] = frame
        return frame

    def get_current_price(self, ticker: str) -> float | None:
        # The EOD feed is the same data the app shows outside trading hours,
        # and this app is on-demand rather than intraday.
        history = self.get_price_history(ticker, period="1mo")
        if history.empty:
            return None
        return float(history["Close"].iloc[-1])

    def _get_details(self, ticker: str) -> dict:
        security_id = security_id_from_ticker(ticker)
        if security_id is None:
            return {}
        if security_id in self._details_cache:
            return self._details_cache[security_id]

        payload = self._request(
            "GET",
            f"{SECURITIES_API}company/securitydata",
            params={"securityId": security_id, "lang": 1},
        )
        if not isinstance(payload, dict):
            payload = self._request(
                "GET", f"{FUND_DETAILS_API}fund/details", params={"fundId": security_id}
            )
        details = payload if isinstance(payload, dict) else {}
        self._details_cache[security_id] = details
        return details

    def get_analyst_data(self, ticker: str) -> dict:
        # TASE publishes no analyst consensus; the analyst signal degrades to
        # neutral, which is honest rather than a silent zero.
        return {}

    def get_market_cap(self, ticker: str) -> float | None:
        value = _pick(self._get_details(ticker), ("marketcap", "companyvalue", "capitalization"))
        parsed = _parse_number(value)
        return parsed / AGOROT_PER_SHEKEL if parsed else None

    def get_beta(self, ticker: str) -> float | None:
        return _parse_number(_pick(self._get_details(ticker), ("beta",)))

    def get_sector(self, ticker: str) -> str | None:
        value = _pick(
            self._get_details(ticker),
            ("branchname", "subbranchname", "sector", "branch", "fundclassification"),
        )
        return str(value) if value else None

    def get_fx_rate(self, from_currency: str, to_currency: str) -> float:
        # FX isn't TASE's job — the composite provider keeps this on Yahoo.
        return 1.0 if from_currency == to_currency else 0.0
