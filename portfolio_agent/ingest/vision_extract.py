"""Extracts holdings from a portfolio screenshot via the configured vision
model (Gemini by default — see portfolio_agent/llm.py), then resolves each
identifier to a Yahoo Finance-compatible ticker: US tickers pass through as-is, TASE names/security numbers are looked up in
data/tase_ticker_map.csv (OCR/vision alone can't reliably produce
exchange-correct symbols). An unmatched TASE entry is kept with
bucket=UNCLASSIFIED and a warning rather than silently dropped.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from portfolio_agent.models import Bucket, Currency, Holding

EXTRACTION_SYSTEM_PROMPT = """You are extracting a stock portfolio holdings table from a screenshot of a
brokerage app. Respond with ONLY a JSON array, no prose, no markdown fences. Each element:
{"identifier": "<ticker, company name, or TASE security number as shown>",
 "quantity": <number>,
 "cost_basis": <number or null>,
 "currency": "USD" or "ILS"}
If a field is not visible, use null for cost_basis (quantity and identifier are required).
If you cannot find any holdings rows, return []."""


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


def _resolve_ticker(identifier: str, currency: str, ticker_map: dict[str, str]) -> tuple[str | None, str | None]:
    identifier = identifier.strip()
    if currency == "USD" and _looks_like_us_ticker(identifier):
        return identifier.upper(), None
    if identifier in ticker_map:
        return ticker_map[identifier], None
    if identifier.upper().endswith(".TA"):
        return identifier.upper(), None
    if _looks_like_us_ticker(identifier):
        return identifier.upper(), None
    return None, f"'{identifier}' unmapped in tase_ticker_map.csv — add it manually to include in analysis."


def _call_vision_api(image_bytes: bytes, media_type: str, settings) -> str:
    from portfolio_agent.llm import ImagePart, complete

    return complete(
        settings,
        system=EXTRACTION_SYSTEM_PROMPT,
        user="Extract the holdings table from this screenshot.",
        image=ImagePart(data=image_bytes, media_type=media_type),
        max_tokens=4096,
    )


def parse_extraction_response(
    raw_text: str, ticker_map: dict[str, str]
) -> tuple[list[Holding], list[str]]:
    from portfolio_agent.llm import parse_json_response, strip_json_fences

    warnings: list[str] = []
    rows = parse_json_response(raw_text, default=None)
    if rows is None:
        return [], [
            f"Could not parse vision response as JSON: {strip_json_fences(raw_text)[:200]!r}"
        ]
    if isinstance(rows, dict):
        # Some models wrap the array in an object despite the prompt.
        rows = next((v for v in rows.values() if isinstance(v, list)), [])

    holdings: list[Holding] = []
    for row in rows:
        if not isinstance(row, dict):
            warnings.append(f"Skipped malformed row: {row!r}")
            continue
        identifier = str(row.get("identifier", "")).strip()
        quantity = row.get("quantity")
        if not identifier or quantity is None:
            warnings.append(f"Skipped malformed row: {row!r}")
            continue

        currency = (row.get("currency") or "USD").strip().upper()
        if currency not in ("USD", "ILS"):
            currency = "USD"

        ticker, warning = _resolve_ticker(identifier, currency, ticker_map)
        bucket = Bucket.UNCLASSIFIED
        if warning:
            warnings.append(warning)
            ticker = identifier  # keep it visible even though it can't be priced yet

        holdings.append(
            Holding(
                ticker=ticker,
                quantity=float(quantity),
                cost_basis=float(row["cost_basis"]) if row.get("cost_basis") is not None else 0.0,
                currency=Currency(currency),
                bucket=bucket,
            )
        )

    return holdings, warnings


def extract_holdings_from_image(
    image_bytes: bytes, settings, media_type: str = "image/jpeg"
) -> tuple[list[Holding], list[str]]:
    ticker_map = load_tase_ticker_map(settings.data_dir / "tase_ticker_map.csv")
    raw_text = _call_vision_api(image_bytes, media_type, settings)
    return parse_extraction_response(raw_text, ticker_map)
