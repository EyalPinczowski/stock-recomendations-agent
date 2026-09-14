"""One-shot fetch of the latest pending portfolio-photo message from Telegram,
used by the `ingest-portfolio` CLI command. bot/server.py's persistent loop
handles this the same way but continuously, as part of its long-poll cycle.
"""

from __future__ import annotations

from pathlib import Path

from portfolio_agent.notify.telegram import download_file, get_updates
from portfolio_agent.notify.telegram_offset import load_offset, save_offset


def fetch_latest_screenshot(settings) -> bytes | None:
    settings.require_telegram()
    state_dir = Path(settings.state_dir)
    offset = load_offset(state_dir)

    updates = get_updates(settings.telegram_bot_token, offset=offset, timeout=1)
    if not updates:
        return None

    new_offset = updates[-1]["update_id"] + 1
    photo_updates = [u for u in updates if "message" in u and "photo" in u["message"]]

    save_offset(state_dir, new_offset)

    if not photo_updates:
        return None

    largest_photo = max(photo_updates[-1]["message"]["photo"], key=lambda p: p.get("file_size", 0))
    return download_file(settings.telegram_bot_token, largest_photo["file_id"])
