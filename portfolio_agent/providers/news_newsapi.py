"""Key-gated headline source via NewsAPI.org, preferred over GDELT when
NEWS_API_KEY is set (generally better relevance/quality)."""

from __future__ import annotations

import requests

from portfolio_agent.providers.base import NewsProvider

NEWSAPI_URL = "https://newsapi.org/v2/everything"
REQUEST_TIMEOUT = 15


class NewsAPIProvider(NewsProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def get_headlines(self, query: str, limit: int = 15) -> list[dict]:
        try:
            resp = requests.get(
                NEWSAPI_URL,
                params={
                    "q": query,
                    "pageSize": limit,
                    "sortBy": "publishedAt",
                    "language": "en",
                    "apiKey": self.api_key,
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            articles = resp.json().get("articles", [])
        except Exception:  # noqa: BLE001
            return []

        return [
            {
                "title": a.get("title", ""),
                "source": (a.get("source") or {}).get("name", ""),
                "published_at": a.get("publishedAt", ""),
                "url": a.get("url", ""),
            }
            for a in articles
        ]
