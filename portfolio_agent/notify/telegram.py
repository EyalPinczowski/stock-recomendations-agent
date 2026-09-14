"""Telegram Bot API wrapper: sending (TelegramNotifier) and the low-level HTTP
helpers used for receiving (getUpdates/getFile), shared by both the one-shot
`ingest-portfolio` CLI command and the persistent bot/server.py loop.
"""

from __future__ import annotations

import requests

API_BASE = "https://api.telegram.org/bot{token}"
REQUEST_TIMEOUT = 30
LONG_POLL_TIMEOUT = 30


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._base = API_BASE.format(token=bot_token)

    def send_message(self, text: str) -> None:
        for i in range(0, len(text), 4000):
            requests.post(
                f"{self._base}/sendMessage",
                data={"chat_id": self.chat_id, "text": text[i : i + 4000]},
                timeout=REQUEST_TIMEOUT,
            )

    def send_document(self, path: str, caption: str | None = None) -> None:
        with open(path, "rb") as f:
            requests.post(
                f"{self._base}/sendDocument",
                data={"chat_id": self.chat_id, **({"caption": caption} if caption else {})},
                files={"document": f},
                timeout=REQUEST_TIMEOUT * 4,
            )


def get_updates(bot_token: str, offset: int | None = None, timeout: int = LONG_POLL_TIMEOUT) -> list[dict]:
    params = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    resp = requests.get(
        f"{API_BASE.format(token=bot_token)}/getUpdates",
        params=params,
        timeout=timeout + REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("result", [])


def download_file(bot_token: str, file_id: str) -> bytes:
    base = API_BASE.format(token=bot_token)
    resp = requests.get(f"{base}/getFile", params={"file_id": file_id}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    file_path = resp.json()["result"]["file_path"]
    file_resp = requests.get(
        f"https://api.telegram.org/file/bot{bot_token}/{file_path}", timeout=REQUEST_TIMEOUT
    )
    file_resp.raise_for_status()
    return file_resp.content
