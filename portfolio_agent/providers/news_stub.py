"""Default no-op NewsProvider: no key needed, returns nothing, and the pipeline
degrades gracefully (sentiment neutral, a warning noted) whenever this is used.
"""

from __future__ import annotations

from portfolio_agent.providers.base import NewsProvider


class NoOpNewsProvider(NewsProvider):
    def get_headlines(self, query: str, limit: int = 15) -> list[dict]:
        return []

    @property
    def available(self) -> bool:
        return False
