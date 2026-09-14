"""Environment/settings loading and RiskProfile loading."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from portfolio_agent.models import RiskProfile

load_dotenv()


class Settings:
    def __init__(self):
        self.anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY") or None
        self.anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
        self.news_api_key: str | None = os.getenv("NEWS_API_KEY") or None
        self.telegram_bot_token: str | None = os.getenv("TELEGRAM_BOT_TOKEN") or None
        self.telegram_chat_id: str | None = os.getenv("TELEGRAM_CHAT_ID") or None
        self.portfolio_path: Path = Path(os.getenv("PORTFOLIO_PATH", "examples/portfolio.csv"))
        self.risk_profile_path: Path = Path(os.getenv("RISK_PROFILE_PATH", "risk_profile.yaml"))
        self.state_dir: Path = Path(os.getenv("STATE_DIR", "state"))
        self.data_dir: Path = Path(os.getenv("DATA_DIR", "data"))

    def require_telegram(self) -> tuple[str, str]:
        if not self.telegram_bot_token or not self.telegram_chat_id:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set (see .env.example)."
            )
        return self.telegram_bot_token, self.telegram_chat_id


def load_risk_profile(path: Path | str) -> RiskProfile:
    path = Path(path)
    if not path.exists():
        return RiskProfile()
    data = yaml.safe_load(path.read_text()) or {}
    return RiskProfile(**data)


def get_settings() -> Settings:
    return Settings()
