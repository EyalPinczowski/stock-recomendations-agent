"""News/geopolitical sentiment, scored via one batched Anthropic call across
every ticker in a run (not one call per ticker) — cost stays bounded
regardless of portfolio size. Skipped entirely (neutral, degraded=True) when
no news provider is available or no headlines were found for a ticker.
"""

from __future__ import annotations

import json
import re

from portfolio_agent.models import SentimentSignal
from portfolio_agent.providers.base import NewsProvider

SENTIMENT_SYSTEM_PROMPT = """You are scoring news sentiment and geopolitical risk for a set of stock
tickers, based on recent headlines. Respond with ONLY a JSON object, no prose, no markdown fences:
{"<TICKER>": {"sentiment_score": <-1..1>, "geopolitical_risk_score": <0..1>, "summary": "<=2 sentences"}, ...}
sentiment_score: -1 very negative, 0 neutral, 1 very positive.
geopolitical_risk_score: 0 none, 1 severe (war, sanctions, trade restrictions, regulatory crackdown).
Include an entry for every ticker given."""


def fetch_headlines_for_tickers(
    tickers: list[str], news_provider: NewsProvider | None, limit: int = 15
) -> dict[str, list[dict]]:
    if news_provider is None or not news_provider.available:
        return {}
    result = {}
    for ticker in tickers:
        headlines = news_provider.get_headlines(ticker, limit=limit)
        if headlines:
            result[ticker] = headlines
    return result


def _call_sentiment_api(ticker_headlines: dict[str, list[dict]], settings) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    lines = []
    for ticker, headlines in ticker_headlines.items():
        titles = "; ".join(h["title"] for h in headlines[:10])
        lines.append(f"{ticker}: {titles}")
    user_prompt = "\n".join(lines)

    message = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=2048,
        system=SENTIMENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in message.content if block.type == "text")


def _parse_sentiment_response(raw_text: str) -> dict[str, dict]:
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?|\n?```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def build_sentiment_signals(
    tickers: list[str], news_provider: NewsProvider | None, settings
) -> dict[str, SentimentSignal]:
    """Returns a SentimentSignal for every ticker (neutral/degraded for any
    that had no headlines or weren't scored)."""
    signals = {t: SentimentSignal(degraded=True) for t in tickers}

    ticker_headlines = fetch_headlines_for_tickers(tickers, news_provider)
    if not ticker_headlines:
        return signals

    try:
        raw = _call_sentiment_api(ticker_headlines, settings)
    except Exception:  # noqa: BLE001
        return signals

    parsed = _parse_sentiment_response(raw)
    for ticker, headlines in ticker_headlines.items():
        entry = parsed.get(ticker)
        if not entry:
            continue
        signals[ticker] = SentimentSignal(
            headline_count=len(headlines),
            sentiment_score=float(entry.get("sentiment_score", 0.0)),
            geopolitical_risk_score=float(entry.get("geopolitical_risk_score", 0.0)),
            summary=str(entry.get("summary", "")),
            degraded=False,
        )
    return signals
