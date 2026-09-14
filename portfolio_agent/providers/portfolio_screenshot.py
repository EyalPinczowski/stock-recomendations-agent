"""Primary PortfolioProvider: reads whatever holdings snapshot was last parsed
from a Telegram screenshot. If none has ever arrived, raises a clear,
actionable error rather than silently falling back.
"""

from __future__ import annotations

from pathlib import Path

from portfolio_agent.ingest.snapshot_store import load_snapshot
from portfolio_agent.models import PortfolioSnapshot
from portfolio_agent.providers.base import PortfolioProvider


class NoPortfolioSnapshotError(RuntimeError):
    pass


class ScreenshotPortfolioProvider(PortfolioProvider):
    def __init__(self, current_snapshot_path: Path | str):
        # current_snapshot_path historically pointed at the file directly; we only
        # need its parent directory since snapshot_store manages the filename.
        self.state_dir = Path(current_snapshot_path).parent

    def get_snapshot(self) -> PortfolioSnapshot:
        snapshot = load_snapshot(self.state_dir)
        if snapshot is None:
            raise NoPortfolioSnapshotError(
                "No portfolio snapshot yet — send a screenshot of your portfolio to the "
                "bot first, or run with --portfolio-provider file to use examples/portfolio.csv."
            )
        return snapshot
