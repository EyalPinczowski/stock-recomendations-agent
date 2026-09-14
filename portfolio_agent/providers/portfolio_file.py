"""Manual CSV/JSON portfolio provider — fallback/testing path, and the bootstrap
before a first screenshot has been sent.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from portfolio_agent.models import Bucket, Currency, Holding, PortfolioSnapshot
from portfolio_agent.providers.base import PortfolioProvider


class PortfolioFileError(ValueError):
    pass


class FilePortfolioProvider(PortfolioProvider):
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def get_snapshot(self) -> PortfolioSnapshot:
        if not self.path.exists():
            raise PortfolioFileError(
                f"Portfolio file not found: {self.path}. "
                "Create it (see examples/portfolio.csv) or send a screenshot to the bot."
            )
        if self.path.suffix.lower() == ".json":
            holdings = self._load_json()
        elif self.path.suffix.lower() == ".csv":
            holdings = self._load_csv()
        else:
            raise PortfolioFileError(f"Unsupported portfolio file type: {self.path.suffix}")

        captured_at = datetime.fromtimestamp(self.path.stat().st_mtime, tz=timezone.utc)
        return PortfolioSnapshot(holdings=holdings, captured_at=captured_at, source="file")

    def _load_json(self) -> list[Holding]:
        raw = json.loads(self.path.read_text())
        rows = raw.get("holdings", raw) if isinstance(raw, dict) else raw
        return [self._parse_row(i, row) for i, row in enumerate(rows)]

    def _load_csv(self) -> list[Holding]:
        with self.path.open(newline="") as f:
            reader = csv.DictReader(f)
            return [self._parse_row(i, row) for i, row in enumerate(reader)]

    def _parse_row(self, index: int, row: dict) -> Holding:
        try:
            ticker = str(row["ticker"]).strip().upper()
            quantity = float(row["quantity"])
            cost_basis = float(row["cost_basis"])
        except (KeyError, ValueError, TypeError) as exc:
            raise PortfolioFileError(
                f"Malformed portfolio row {index} in {self.path}: {row!r} ({exc})"
            ) from exc

        purchase_date = row.get("purchase_date") or None
        currency_raw = (row.get("currency") or "USD").strip().upper()
        try:
            currency = Currency(currency_raw)
        except ValueError:
            currency = Currency.USD
        bucket_raw = (row.get("bucket") or "unclassified").strip().lower()
        try:
            bucket = Bucket(bucket_raw)
        except ValueError:
            bucket = Bucket.UNCLASSIFIED

        return Holding(
            ticker=ticker,
            quantity=quantity,
            cost_basis=cost_basis,
            purchase_date=purchase_date,
            currency=currency,
            bucket=bucket,
            notes=row.get("notes") or None,
        )
