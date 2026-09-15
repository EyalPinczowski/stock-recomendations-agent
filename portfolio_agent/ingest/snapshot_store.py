"""Persists/reads the current portfolio snapshot. On a new parse, the previous
snapshot is archived (audit trail) before being overwritten.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from portfolio_agent.models import Holding, PortfolioSnapshot

SNAPSHOT_FILENAME = "current_portfolio.json"
HISTORY_DIRNAME = "portfolio_history"


def load_snapshot(state_dir: Path) -> PortfolioSnapshot | None:
    path = Path(state_dir) / SNAPSHOT_FILENAME
    if not path.exists():
        return None
    return PortfolioSnapshot.model_validate_json(path.read_text())


def save_snapshot(
    holdings: list[Holding], state_dir: Path, cash_balances: dict[str, float] | None = None
) -> PortfolioSnapshot:
    state_dir = Path(state_dir)
    history_dir = state_dir / HISTORY_DIRNAME
    history_dir.mkdir(parents=True, exist_ok=True)

    path = state_dir / SNAPSHOT_FILENAME
    if path.exists():
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy(path, history_dir / f"{timestamp}.json")

    snapshot = PortfolioSnapshot(
        holdings=holdings,
        captured_at=datetime.now(UTC),
        source="screenshot",
        cash_balances=cash_balances or {},
    )
    path.write_text(snapshot.model_dump_json(indent=2))
    return snapshot
