"""Extracts holdings from a portfolio screenshot via the Anthropic vision API,
then resolves each identifier to a Yahoo Finance-compatible ticker: US tickers
pass through as-is, TASE names/security numbers are looked up in
data/tase_ticker_map.csv (OCR/vision alone can't reliably produce
exchange-correct symbols). An unmatched TASE entry is kept with
bucket=UNCLASSIFIED and a warning rather than silently dropped.
"""

from __future__ import annotations

import csv
import json
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
    import base64

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=2048,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64.standard_b64encode(image_bytes).decode(),
                        },
                    },
                    {"type": "text", "text": "Extract the holdings table from this screenshot."},
                ],
            }
        ],
    )
    return "".join(block.text for block in message.content if block.type == "text")


def parse_extraction_response(
    raw_text: str, ticker_map: dict[str, str]
) -> tuple[list[Holding], list[str]]:
    warnings: list[str] = []
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?|\n?```$", "", text.strip())

    try:
        rows = json.loads(text)
    except json.JSONDecodeError:
        return [], [f"Could not parse vision response as JSON: {text[:200]!r}"]

    holdings: list[Holding] = []
    for row in rows:
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
