"""Interactive first-time setup: validates the bot token, discovers your chat
ID by watching for a message you send the bot, and writes .env. Run once on
the machine that will host the bot.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

API_BASE = "https://api.telegram.org/bot{token}"
ENV_FILENAME = ".env"
CHAT_DISCOVERY_TIMEOUT_SECONDS = 180
POLL_INTERVAL_SECONDS = 2


class SetupError(RuntimeError):
    pass


def validate_token(token: str) -> str:
    """Returns the bot's @username, or raises SetupError."""
    try:
        resp = requests.get(f"{API_BASE.format(token=token)}/getMe", timeout=30)
    except requests.RequestException as exc:
        raise SetupError(f"Couldn't reach Telegram: {exc}") from exc

    data = resp.json()
    if not data.get("ok"):
        raise SetupError(f"Telegram rejected the token: {data.get('description')}")
    return data["result"].get("username", "")


def find_chat_id(token: str, timeout_seconds: int = CHAT_DISCOVERY_TIMEOUT_SECONDS) -> str:
    """Polls getUpdates until a message arrives, and returns its chat ID."""
    deadline = time.monotonic() + timeout_seconds
    offset = None

    while time.monotonic() < deadline:
        params = {"timeout": 10}
        if offset is not None:
            params["offset"] = offset
        try:
            resp = requests.get(f"{API_BASE.format(token=token)}/getUpdates", params=params, timeout=40)
            updates = resp.json().get("result", [])
        except requests.RequestException:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message") or update.get("edited_message") or {}
            chat_id = (message.get("chat") or {}).get("id")
            if chat_id:
                return str(chat_id)

        time.sleep(POLL_INTERVAL_SECONDS)

    raise SetupError(
        f"No message arrived within {timeout_seconds}s. Send your bot a message, then run setup again."
    )


def send_confirmation(token: str, chat_id: str) -> bool:
    try:
        resp = requests.post(
            f"{API_BASE.format(token=token)}/sendMessage",
            data={"chat_id": chat_id, "text": "Portfolio Agent is connected. Send /help to see what I can do."},
            timeout=30,
        )
        return bool(resp.json().get("ok"))
    except requests.RequestException:
        return False


def write_env_file(values: dict[str, str], path: Path) -> None:
    """Writes/updates .env, preserving any keys already present that we aren't setting."""
    existing: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.strip().startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                existing[key.strip()] = value.strip()

    existing.update({k: v for k, v in values.items() if v})

    lines = [
        "# Written by `portfolio-agent setup`. Keep this file private — it holds secrets.",
        "",
    ]
    lines.extend(f"{key}={value}" for key, value in existing.items())
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)


def run_setup(project_dir: Path | str = ".") -> None:
    project_dir = Path(project_dir)
    env_path = project_dir / ENV_FILENAME

    print("Portfolio Agent — first-time setup\n")

    token = input("Paste your Telegram bot token (from @BotFather): ").strip()
    if not token:
        raise SetupError("No token entered.")

    print("Checking the token…")
    username = validate_token(token)
    print(f"  Token is valid — bot is @{username}\n")

    print(f"Now open Telegram, find @{username}, and send it any message (e.g. 'hi').")
    print("Waiting for your message…")
    chat_id = find_chat_id(token)
    print(f"  Got it — your chat ID is {chat_id}\n")

    print("Optional keys (press Enter to skip):")
    anthropic_key = input("  ANTHROPIC_API_KEY (enables sentiment + review pass): ").strip()
    news_key = input("  NEWS_API_KEY (better news coverage than the free source): ").strip()

    write_env_file(
        {
            "TELEGRAM_BOT_TOKEN": token,
            "TELEGRAM_CHAT_ID": chat_id,
            "ANTHROPIC_API_KEY": anthropic_key,
            "NEWS_API_KEY": news_key,
            "ANTHROPIC_MODEL": "claude-sonnet-4-5" if anthropic_key else "",
        },
        env_path,
    )
    print(f"\nWrote {env_path} (permissions set to 0600).")

    if send_confirmation(token, chat_id):
        print("Sent a confirmation message to your Telegram — check it arrived.")
    else:
        print("Couldn't send the confirmation message; check the token/chat ID.", file=sys.stderr)

    print("\nSetup complete. Start the bot with:")
    print("  python -m portfolio_agent.cli bot")
    print("\nThen send it a photo of your portfolio, followed by /analyze.")
