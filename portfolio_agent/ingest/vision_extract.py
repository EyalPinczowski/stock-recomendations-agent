"""Turns Meitav Trade portfolio screenshots into Holdings.

The app's holdings list shows, per row: the exchange and ticker, the company
name, the position's total return and market value, and — on the far side —
the current price and today's change. Notably it shows **no quantity and no
cost basis**, so both are derived here rather than read:

    quantity   = position value / price
    cost/share = price / (1 + total return)

That works because both numbers come from the same broker at the same moment;
every position in a real screenshot resolves to a whole share count this way.
TASE rows need one extra step: the exchange quotes in agorot (1/100 ILS) while
the app shows values in shekels, so the price is divided by 100 — chosen by
which reading yields a whole number of units, not assumed.

Several screenshots are normally needed to cover a whole portfolio, so they're
sent to the model together, in one call, and de-duplicated by ticker here.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from portfolio_agent.models import Bucket, Currency, Holding

EXTRACTION_SYSTEM_PROMPT = """You are reading holdings from screenshots of an Israeli brokerage app
(Meitav Trade). The interface is right-to-left Hebrew. One or more screenshots of the same
portfolio are given; they overlap, so the same holding may appear more than once.

Each holding row shows:
- the exchange and ticker (e.g. "NASDAQ • CEG"), or for Tel Aviv holdings a Hebrew fund name
  with "TLV" and a security number ("מספר ני"ע 1159714")
- the company/fund name
- the position's total return percentage and its total market value, next to a briefcase icon
  (e.g. "-5.85% ↓ $3,174.84" means the position is worth $3,174.84 and is down 5.85% overall)
- on the opposite side, the current price per unit and today's change percentage
  (e.g. "264.57" above "-7.09%")

Report the numbers exactly as displayed — do NOT convert currencies or compute quantities.

Respond with ONLY a JSON array, no prose, no markdown fences. One element per DISTINCT holding
(merge duplicates across screenshots):
{"ticker": "<ticker symbol, or null for Tel Aviv rows that show none>",
 "exchange": "<NASDAQ|NYSE|TLV|null>",
 "security_number": "<the מספר ני\\"ע digits, or null>",
 "name": "<company or fund name as shown>",
 "price": <current price per unit as shown, number>,
 "position_value": <total market value of the position, number>,
 "total_return_pct": <overall return percent as shown, negative if down, or null>,
 "currency": "USD" or "ILS",
 "kind": "security" | "cash" | "other"}

kind rules:
- "security" for anything tradable: stocks, ETFs, funds (קרן סל), warrants.
- "cash" for currency balances — a row named "דולר ארה"ב" / "שקל", or figures under a
  balances heading ("יתרות"). Put the balance in position_value and leave price null.
- "other" for anything that isn't either, such as "מגן מס" (a tax-shield product).

If a screenshot shows no holdings rows at all, contribute nothing for it. Return [] only if
none of the screenshots contain any."""

# Below this the derived share count is kept as-is rather than rounded: real
# positions come out whole, and a fractional result means something unusual
# (a warrant stub, a rounded display) that shouldn't be silently "corrected".
QUANTITY_ROUNDING_TOLERANCE = 0.01


@dataclass
class ExtractedPortfolio:
    holdings: list[Holding] = field(default_factory=list)
    cash_balances: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def load_tase_ticker_map(path: str | Path = "data/tase_ticker_map.csv") -> dict[str, str]:
    path = Path(path)
    if not path.exists():
        return {}
    mapping = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            mapping[row["identifier"].strip()] = row["yahoo_ticker"].strip()
    return mapping


def _looks_like_us_ticker(identifier: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", identifier.strip()))


def _resolve_ticker(row: dict, ticker_map: dict[str, str]) -> tuple[str | None, str | None]:
    """Returns (yahoo_ticker, warning). Anything unresolvable is kept, not dropped."""
    ticker = (row.get("ticker") or "").strip()
    name = (row.get("name") or "").strip()
    security_number = (row.get("security_number") or "").strip()
    exchange = (row.get("exchange") or "").strip().upper()
    is_tase = exchange == "TLV" or (row.get("currency") or "").upper() == "ILS"

    for key in (ticker, name, security_number):
        if key and key in ticker_map:
            return ticker_map[key], None

    if is_tase:
        # Yahoo lists Israeli funds under their TASE security number.
        if security_number.isdigit():
            return f"{security_number}.TA", None
        if ticker.upper().endswith(".TA"):
            return ticker.upper(), None
        label = name or ticker or "?"
        return None, (
            f"'{label}' has no security number and isn't in tase_ticker_map.csv — "
            "add it there to include it in the analysis."
        )

    if ticker and _looks_like_us_ticker(ticker):
        return ticker.upper(), None
    if ticker:
        return ticker.upper(), None
    return None, f"'{name or '?'}' has no ticker — skipped."


def _to_float(value) -> float | None:
    """Numbers may arrive as '1,138.28' or '$3,174.84' depending on the model."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^\d.\-]", "", str(value))
    try:
        return float(cleaned)
    except ValueError:
        return None


def _wholeness(quantity: float) -> float:
    """How far this share count is from a whole number, relatively."""
    nearest = round(quantity)
    if nearest < 1:
        return float("inf")
    return abs(quantity - nearest) / nearest


def derive_quantity(price: float, position_value: float, is_tase: bool) -> tuple[float, float]:
    """Returns (quantity, price per unit in the displayed currency).

    Tel Aviv quotes in agorot (1/100 of a shekel) while the app values
    positions in shekels, so a TASE price has to be divided by 100 before the
    two can be combined — otherwise every Israeli holding comes out 100x too
    small. Checked against real screenshots: both TASE funds then resolve to a
    whole number of units, as do all fifteen US positions without it.
    """
    price_per_unit = price / 100 if is_tase else price
    quantity = position_value / price_per_unit

    # Price and value are both displayed rounded, so an exact share count
    # arrives slightly off. Snap it back — but only when it's genuinely close,
    # since warrant stubs really are fractional.
    if _wholeness(quantity) <= QUANTITY_ROUNDING_TOLERANCE:
        quantity = float(round(quantity))
    return quantity, price_per_unit


def _build_holding(row: dict, ticker: str, result: ExtractedPortfolio) -> Holding | None:
    price = _to_float(row.get("price"))
    position_value = _to_float(row.get("position_value"))
    name = (row.get("name") or "").strip() or None
    currency = (row.get("currency") or "USD").strip().upper()
    if currency not in ("USD", "ILS"):
        currency = "USD"

    if not price or not position_value:
        result.warnings.append(
            f"{ticker}: no price or value visible, so the quantity couldn't be worked out."
        )
        return None

    is_tase = (row.get("exchange") or "").strip().upper() == "TLV" or currency == "ILS"
    quantity, price_per_unit = derive_quantity(price, position_value, is_tase)

    # The app shows total return, not what was paid — so back out the entry price.
    total_return_pct = _to_float(row.get("total_return_pct"))
    cost_basis = 0.0
    if total_return_pct is not None and total_return_pct > -100:
        cost_basis = price_per_unit / (1 + total_return_pct / 100)

    return Holding(
        ticker=ticker,
        name=name,
        quantity=quantity,
        cost_basis=cost_basis,
        currency=Currency(currency),
        bucket=Bucket.UNCLASSIFIED,
    )


def parse_extraction_response(raw_text: str, ticker_map: dict[str, str]) -> ExtractedPortfolio:
    from portfolio_agent.llm import parse_json_response, strip_json_fences

    result = ExtractedPortfolio()

    rows = parse_json_response(raw_text, default=None)
    if rows is None:
        result.warnings.append(
            f"Could not read the screenshot as JSON: {strip_json_fences(raw_text)[:200]!r}"
        )
        return result
    if isinstance(rows, dict):
        # Some models wrap the array in an object despite the prompt.
        rows = next((v for v in rows.values() if isinstance(v, list)), [])

    by_ticker: dict[str, Holding] = {}
    for row in rows:
        if not isinstance(row, dict):
            result.warnings.append(f"Skipped an unreadable row: {row!r}")
            continue

        kind = (row.get("kind") or "security").strip().lower()
        name = (row.get("name") or "").strip()
        value = _to_float(row.get("position_value"))

        if kind == "cash":
            currency = (row.get("currency") or "USD").strip().upper()
            if value is not None:
                result.cash_balances[currency] = value
            continue
        if kind == "other":
            result.warnings.append(
                f"Ignored '{name or 'unnamed row'}' — not a tradable security."
            )
            continue

        ticker, warning = _resolve_ticker(row, ticker_map)
        if warning:
            result.warnings.append(warning)
        if ticker is None:
            continue

        holding = _build_holding(row, ticker, result)
        if holding is not None:
            # Screenshots overlap, so the same holding shows up more than once.
            by_ticker[holding.ticker] = holding

    result.holdings = list(by_ticker.values())
    return result


def extract_holdings_from_images(
    images: list[bytes], settings, media_type: str = "image/jpeg"
) -> ExtractedPortfolio:
    """All screenshots go up in a single call: it costs less than one call each,
    and the model can merge rows that appear in more than one of them."""
    from portfolio_agent.llm import ImagePart, complete

    if not images:
        return ExtractedPortfolio(warnings=["No screenshots to read."])

    raw_text = complete(
        settings,
        system=EXTRACTION_SYSTEM_PROMPT,
        user=(
            f"{len(images)} screenshot(s) of one portfolio, in order. "
            "Extract every holding row you can see."
        ),
        images=[ImagePart(data=data, media_type=media_type) for data in images],
        max_tokens=8192,
    )
    ticker_map = load_tase_ticker_map(Path(settings.data_dir) / "tase_ticker_map.csv")
    return parse_extraction_response(raw_text, ticker_map)


def extract_holdings_from_image(
    image_bytes: bytes, settings, media_type: str = "image/jpeg"
) -> ExtractedPortfolio:
    return extract_holdings_from_images([image_bytes], settings, media_type)
