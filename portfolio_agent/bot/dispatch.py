"""Routes a Telegram update (photo or text command) to the right pipeline and
replies. Every command's handling is wrapped in its own try/except so an
error in one never crashes the bot's long-poll loop for the next message.
"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path

from portfolio_agent.cli import (
    _build_market_provider,
    _build_news_provider,
    _build_portfolio_provider,
    _review_fn,
    _sentiment_batch_fn,
)
from portfolio_agent.config import load_risk_profile
from portfolio_agent.notify.telegram import TelegramNotifier

logger = logging.getLogger(__name__)

LAST_REQUEST_FILENAME = "last_request.json"

HELP_TEXT = """Commands:
/analyze — full portfolio analysis + recommendations (sends a .pptx deck)
/screen — short-term setups across the broad market (sends a .pptx deck)
/newstocks — new stock ideas that fill portfolio gaps (sends a .pptx deck)
/scorecard — accuracy of past recommendations vs. actual price moves
/status — last request handled, current portfolio value, open warnings
/riskprofile — show the current risk profile
/help — this message

Send a photo of your portfolio at any time to update your holdings."""


def _record_last_request(state_dir: Path, command: str, outcome: str) -> None:
    path = Path(state_dir) / LAST_REQUEST_FILENAME
    path.write_text(json.dumps({
        "command": command, "outcome": outcome,
        "at": datetime.now(timezone.utc).isoformat(),
    }))


def _read_last_request(state_dir: Path) -> dict | None:
    path = Path(state_dir) / LAST_REQUEST_FILENAME
    if not path.exists():
        return None
    return json.loads(path.read_text())


def handle_photo(image_bytes: bytes, settings, notifier: TelegramNotifier) -> None:
    from portfolio_agent.ingest.snapshot_store import save_snapshot
    from portfolio_agent.ingest.vision_extract import extract_holdings_from_image

    try:
        holdings, warnings = extract_holdings_from_image(image_bytes, settings)
        save_snapshot(holdings, settings.state_dir)
        _record_last_request(settings.state_dir, "photo", "ok")
        logger.info("Parsed %d holdings from screenshot (%d warnings).", len(holdings), len(warnings))
    except Exception as exc:  # noqa: BLE001
        logger.error("Screenshot ingest failed: %s\n%s", exc, traceback.format_exc())
        _record_last_request(settings.state_dir, "photo", f"failed: {exc}")
        notifier.send_message(f"Couldn't process that screenshot: {exc}")


def _run_report_command(kind: str, settings, notifier: TelegramNotifier) -> None:
    risk_profile = load_risk_profile(settings.risk_profile_path)
    market = _build_market_provider(mock=False)

    from portfolio_agent.report.presentation import build_presentation

    if kind == "analyze":
        from portfolio_agent.pipeline import run_analyze

        portfolio_provider = _build_portfolio_provider("screenshot", settings, mock=False)
        news_provider = _build_news_provider(settings, mock=False)
        report = run_analyze(
            portfolio_provider, market, risk_profile,
            news_provider=news_provider,
            sentiment_batch_fn=_sentiment_batch_fn(settings, mock=False),
            review_fn=_review_fn(settings, mock=False, kind="analyze"),
            state_dir=str(settings.state_dir),
        )
    elif kind == "screen":
        from portfolio_agent.screen_pipeline import run_screen

        report = run_screen(
            market, risk_profile,
            universe_path=settings.data_dir / "sp500_constituents.csv",
            review_fn=_review_fn(settings, mock=False, kind="screen"),
            state_dir=str(settings.state_dir),
        )
    elif kind == "newstocks":
        from portfolio_agent.newideas_pipeline import run_newstocks

        portfolio_provider = _build_portfolio_provider("screenshot", settings, mock=False)
        report = run_newstocks(
            portfolio_provider, market, risk_profile,
            universe_path=settings.data_dir / "sp500_constituents.csv",
            review_fn=_review_fn(settings, mock=False, kind="newstocks"),
            state_dir=str(settings.state_dir),
        )
    else:
        raise ValueError(f"Unknown report kind: {kind}")

    path = build_presentation(report, kind, output_path=f"/tmp/{kind}_{datetime.now():%Y%m%d_%H%M%S}.pptx")
    notifier.send_document(str(path), caption=f"{kind} report")


def dispatch_command(text: str, settings, notifier: TelegramNotifier) -> None:
    command = text.strip().split()[0].lower() if text.strip() else ""

    try:
        if command == "/analyze":
            notifier.send_message("Analyzing your portfolio…")
            _run_report_command("analyze", settings, notifier)
        elif command == "/screen":
            notifier.send_message("Scanning the market for short-term setups…")
            _run_report_command("screen", settings, notifier)
        elif command == "/newstocks":
            notifier.send_message("Scanning for new stock ideas — this takes a bit longer…")
            _run_report_command("newstocks", settings, notifier)
        elif command == "/scorecard":
            from portfolio_agent.tracking.scorecard import build_scorecard_text

            market = _build_market_provider(mock=False)
            notifier.send_message(build_scorecard_text(settings.state_dir, market))
        elif command == "/status":
            notifier.send_message(_build_status_text(settings))
        elif command == "/riskprofile":
            path = Path(settings.risk_profile_path)
            notifier.send_message(path.read_text() if path.exists() else "Using default risk profile (no risk_profile.yaml found).")
        elif command in ("/help", "/start"):
            notifier.send_message(HELP_TEXT)
        else:
            notifier.send_message(f"Unknown command: {command}\n\n{HELP_TEXT}")
            return

        _record_last_request(settings.state_dir, command, "ok")
    except Exception as exc:  # noqa: BLE001
        logger.error("Command %s failed: %s\n%s", command, exc, traceback.format_exc())
        _record_last_request(settings.state_dir, command, f"failed: {exc}")
        try:
            notifier.send_message(f"{command} failed: {exc}")
        except Exception:  # noqa: BLE001
            logger.error("Also failed to send the error message to Telegram.")


def _build_status_text(settings) -> str:
    from portfolio_agent.ingest.snapshot_store import load_snapshot

    last = _read_last_request(settings.state_dir)
    snapshot = load_snapshot(settings.state_dir)

    lines = []
    if last:
        lines.append(f"Last request: {last['command']} at {last['at']} — {last['outcome']}")
    else:
        lines.append("No requests handled yet.")

    if snapshot:
        lines.append(f"Portfolio snapshot from {snapshot.captured_at.isoformat()} ({len(snapshot.holdings)} holdings).")
    else:
        lines.append("No portfolio snapshot yet — send a screenshot to get started.")

    return "\n".join(lines)
