"""Loads the bundled, manually-updatable scan universe used by both short-term
screening and new-stock-idea gap filling.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UniverseEntry:
    ticker: str
    name: str
    sector: str


def load_universe(path: str | Path = "data/sp500_constituents.csv") -> list[UniverseEntry]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [
            UniverseEntry(ticker=row["ticker"].strip(), name=row["name"].strip(), sector=row["sector"].strip())
            for row in csv.DictReader(f)
        ]
