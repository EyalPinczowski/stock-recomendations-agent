"""Append-only recommendation log — one line (JSON) per recommendation ever
made, read back by tracking/scorecard.py for after-the-fact accuracy checks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from portfolio_agent.models import LoggedRecommendation

LOG_FILENAME = "recommendation_log.jsonl"


def _append(entries: list[LoggedRecommendation], state_dir: Path) -> None:
    if not entries:
        return
    path = Path(state_dir) / LOG_FILENAME
    with path.open("a") as f:
        for entry in entries:
            f.write(entry.model_dump_json() + "\n")


def log_recommendations(recommendations, state_dir: Path) -> None:
    now = datetime.now(UTC)
    entries = [
        LoggedRecommendation(
            ticker=r.ticker, action=r.action.value, conviction=r.conviction,
            price_at_recommendation=r.related_result.current_price,
            recommended_at=now, run_type="analyze",
        )
        for r in recommendations
    ]
    _append(entries, state_dir)


def log_candidates(candidates, state_dir: Path) -> None:
    now = datetime.now(UTC)
    entries = [
        LoggedRecommendation(
            ticker=c.ticker, action="buy", conviction=c.setup_score,
            price_at_recommendation=(c.entry_zone_low + c.entry_zone_high) / 2,
            recommended_at=now, run_type="screen",
        )
        for c in candidates
    ]
    _append(entries, state_dir)


def log_new_stock_suggestions(suggestions, market, state_dir: Path) -> None:
    now = datetime.now(UTC)
    entries = []
    for s in suggestions:
        price = market.get_current_price(s.ticker)
        if price is None:
            continue
        entries.append(
            LoggedRecommendation(
                ticker=s.ticker, action="buy", conviction=s.composite_score,
                price_at_recommendation=price, recommended_at=now, run_type="newstocks",
            )
        )
    _append(entries, state_dir)


def read_log(state_dir: Path) -> list[LoggedRecommendation]:
    path = Path(state_dir) / LOG_FILENAME
    if not path.exists():
        return []
    entries = []
    for line in path.read_text().splitlines():
        if line.strip():
            entries.append(LoggedRecommendation.model_validate_json(line))
    return entries
