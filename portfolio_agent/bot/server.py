"""The persistent Telegram bot process — the primary way this is normally
run. Long-polls Telegram's getUpdates (blocking server-side until something
arrives), dispatching photos to screenshot ingest and text commands to
bot/dispatch.py. Kept alive via the systemd unit in
deploy/portfolio-agent-bot.service (Restart=on-failure); a crash in this
loop itself is the one failure mode systemd handles — everything else is
caught per-message inside dispatch.py so the loop keeps running.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

from portfolio_agent.bot.dispatch import dispatch_command, handle_photo
from portfolio_agent.notify.telegram import (
    LONG_POLL_TIMEOUT,
    TelegramNotifier,
    download_file,
    get_updates,
)
from portfolio_agent.notify.telegram_offset import load_offset, save_offset

logger = logging.getLogger(__name__)

RETRY_SLEEP_SECONDS = 5
CONFLICT_SLEEP_SECONDS = 15


def _handle_update(update: dict, settings, notifier: TelegramNotifier) -> None:
    message = update.get("message")
    if not message:
        return

    chat_id = str(message.get("chat", {}).get("id", ""))
    if settings.telegram_chat_id and chat_id != str(settings.telegram_chat_id):
        logger.info("Ignoring message from unrecognized chat %s", chat_id)
        return

    if "photo" in message:
        largest = max(message["photo"], key=lambda p: p.get("file_size", 0))
        image_bytes = download_file(settings.telegram_bot_token, largest["file_id"])
        handle_photo(image_bytes, settings, notifier)
    elif "text" in message:
        dispatch_command(message["text"], settings, notifier)


def run_bot(settings) -> None:
    settings.require_telegram()
    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    state_dir = Path(settings.state_dir)
    offset = load_offset(state_dir)

    logger.info("Bot started — long-polling Telegram for messages.")
    conflicts = 0
    while True:
        try:
            updates = get_updates(settings.telegram_bot_token, offset=offset, timeout=LONG_POLL_TIMEOUT)
            conflicts = 0
        except requests.HTTPError as exc:
            # 409 means another process is already polling this bot token.
            # Telegram allows only one. Retrying won't fix it on its own, so say
            # what's actually wrong instead of looping with a cryptic warning.
            if exc.response is not None and exc.response.status_code == 409:
                if conflicts == 0:
                    logger.error(
                        "Another instance of this bot is already polling Telegram "
                        "(409 Conflict). Only one process can use a bot token at a "
                        "time. Stop the other one — Ctrl+C in its session, or run: "
                        "pkill -f 'portfolio_agent.cli bot' — then start this one again. "
                        "Retrying every %ds until it goes away.",
                        CONFLICT_SLEEP_SECONDS,
                    )
                else:
                    logger.warning("Still conflicting with another running bot instance.")
                conflicts += 1
                time.sleep(CONFLICT_SLEEP_SECONDS)
                continue
            logger.warning("getUpdates failed (%s), retrying in %ds.", exc, RETRY_SLEEP_SECONDS)
            time.sleep(RETRY_SLEEP_SECONDS)
            continue
        except Exception as exc:  # noqa: BLE001
            logger.warning("getUpdates failed (%s), retrying in %ds.", exc, RETRY_SLEEP_SECONDS)
            time.sleep(RETRY_SLEEP_SECONDS)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            save_offset(state_dir, offset)
            try:
                _handle_update(update, settings, notifier)
            except Exception as exc:  # noqa: BLE001
                logger.error("Unhandled error processing update %s: %s", update.get("update_id"), exc)
