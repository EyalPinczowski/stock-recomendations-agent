"""Free, no-key headline source via GDELT's document search API. Used as the
fallback when NEWS_API_KEY isn't set — still gives some sentiment signal
without requiring you to sign up for anything.
"""

from __future__ import annotations

import requests

from portfolio_agent.providers.base import NewsProvider

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
REQUEST_TIMEOUT = 15


class GDELTNewsProvider(NewsProvider):
    @property
    def available(self) -> bool:
        return True

    def get_headlines(self, query: str, limit: int = 15) -> list[dict]:
        try:
            resp = requests.get(
                GDELT_URL,
                params={"query": query, "mode": "artlist", "maxrecords": limit, "format": "json"},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            articles = resp.json().get("articles", [])
        except Exception:  # noqa: BLE001
            return []

        return [
            {
                "title": a.get("title", ""),
                "source": a.get("domain", ""),
                "published_at": a.get("seendate", ""),
                "url": a.get("url", ""),
            }
            for a in articles
        ]
