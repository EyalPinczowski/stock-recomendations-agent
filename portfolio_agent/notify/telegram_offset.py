"""Shared Telegram update-offset persistence, used by both the one-shot
`ingest-portfolio` CLI command and the persistent bot/server.py loop so a
restart doesn't reprocess or miss messages.
"""

from __future__ import annotations

import json
from pathlib import Path

OFFSET_FILENAME = "telegram_offset.json"


def load_offset(state_dir: Path) -> int | None:
    path = Path(state_dir) / OFFSET_FILENAME
    if not path.exists():
        return None
    return json.loads(path.read_text()).get("offset")


def save_offset(state_dir: Path, offset: int) -> None:
    path = Path(state_dir) / OFFSET_FILENAME
    path.write_text(json.dumps({"offset": offset}))
