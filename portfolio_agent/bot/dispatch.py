"""Routes a Telegram update (photo or text command) to the right pipeline and
replies. Every command's handling is wrapped in its own try/except so an
error in one never crashes the bot's long-poll loop for the next message.
"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import UTC, datetime
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

Send screenshots of your portfolio at any time to update your holdings — one
per screenful is fine, they're read together as one portfolio."""


def _record_last_request(state_dir: Path, command: str, outcome: str) -> None:
    path = Path(state_dir) / LAST_REQUEST_FILENAME
    path.write_text(json.dumps({
        "command": command, "outcome": outcome,
        "at": datetime.now(UTC).isoformat(),
    }))


def _read_last_request(state_dir: Path) -> dict | None:
    path = Path(state_dir) / LAST_REQUEST_FILENAME
    if not path.exists():
        return None
    return json.loads(path.read_text())


def handle_photos(images: list[bytes], settings, notifier: TelegramNotifier) -> None:
    """A portfolio rarely fits in one screenshot, so a run of them is read as a
    single portfolio and replaces the snapshot together — never one at a time,
    which would leave only whatever the last image happened to show."""
    from portfolio_agent.ingest.snapshot_store import save_snapshot
    from portfolio_agent.ingest.vision_extract import extract_holdings_from_images

    label = f"{len(images)} screenshot(s)"
    try:
        extracted = extract_holdings_from_images(images, settings)
        if not extracted.holdings:
            detail = extracted.warnings[0] if extracted.warnings else "no holdings rows found"
            _record_last_request(settings.state_dir, "photo", f"no holdings: {detail}")
            notifier.send_message(
                f"I couldn't find any holdings in {label}. {detail}\n"
                "Your previous portfolio is unchanged."
            )
            return

        save_snapshot(extracted.holdings, settings.state_dir, extracted.cash_balances)
        _record_last_request(
            settings.state_dir, "photo", f"ok: {len(extracted.holdings)} holdings"
        )
        logger.info(
            "Parsed %d holdings from %s (%d warnings).",
            len(extracted.holdings), label, len(extracted.warnings),
        )
        for warning in extracted.warnings:
            logger.warning("Screenshot: %s", warning)
    except Exception as exc:  # noqa: BLE001
        logger.error("Screenshot ingest failed: %s\n%s", exc, traceback.format_exc())
        _record_last_request(settings.state_dir, "photo", f"failed: {exc}")
        notifier.send_message(f"Couldn't read {label}: {exc}")


def handle_photo(image_bytes: bytes, settings, notifier: TelegramNotifier) -> None:
    handle_photos([image_bytes], settings, notifier)


REPORTS_DIRNAME = "reports"
REPORTS_TO_KEEP = 10


def _report_path(settings, kind: str) -> Path:
    """Decks are written under the state directory, not /tmp.

    Android has no /tmp, and TMPDIR differs per host — but the state directory
    is already known-writable (the portfolio snapshot lives there). Keeping the
    last few also means a deck can be re-sent without re-running the analysis.
    """
    directory = Path(settings.state_dir) / REPORTS_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{kind}_{datetime.now(UTC):%Y%m%d_%H%M%S}.pptx"


def _prune_old_reports(settings) -> None:
    directory = Path(settings.state_dir) / REPORTS_DIRNAME
    decks = sorted(directory.glob("*.pptx"), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in decks[REPORTS_TO_KEEP:]:
        stale.unlink(missing_ok=True)


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

    path = build_presentation(report, kind, output_path=str(_report_path(settings, kind)))
    notifier.send_document(str(path), caption=f"{kind} report")
    _prune_old_reports(settings)


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
        lines.append(
            f"Portfolio snapshot from {snapshot.captured_at.isoformat()} "
            f"({len(snapshot.holdings)} holdings)."
        )
        # Worth seeing at a glance: a wrong count is the clearest sign a
        # screenshot was missed or misread.
        tickers = ", ".join(sorted(h.ticker for h in snapshot.holdings))
        if tickers:
            lines.append(tickers)
        if snapshot.cash_balances:
            balances = ", ".join(
                f"{amount:,.2f} {currency}"
                for currency, amount in sorted(snapshot.cash_balances.items())
            )
            lines.append(f"Cash: {balances}")
    else:
        lines.append("No portfolio snapshot yet — send a screenshot to get started.")

    return "\n".join(lines)
