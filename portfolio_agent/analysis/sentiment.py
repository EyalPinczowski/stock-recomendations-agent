"""News/geopolitical sentiment, scored via one batched LLM call across
every ticker in a run (not one call per ticker) — cost stays bounded
regardless of portfolio size. Skipped entirely (neutral, degraded=True) when
no news provider is available or no headlines were found for a ticker.
"""

from __future__ import annotations

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
    from portfolio_agent.llm import complete

    lines = []
    for ticker, headlines in ticker_headlines.items():
        titles = "; ".join(h["title"] for h in headlines[:10])
        lines.append(f"{ticker}: {titles}")

    return complete(
        settings,
        system=SENTIMENT_SYSTEM_PROMPT,
        user="\n".join(lines),
        max_tokens=4096,
    )


def _parse_sentiment_response(raw_text: str) -> dict[str, dict]:
    from portfolio_agent.llm import parse_json_response

    parsed = parse_json_response(raw_text, default={})
    return parsed if isinstance(parsed, dict) else {}


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
