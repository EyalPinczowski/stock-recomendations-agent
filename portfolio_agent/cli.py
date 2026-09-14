"""CLI entry point. `bot` is the primary way this is normally run; the other
subcommands are directly invokable for local testing/dev and are exactly what
bot/dispatch.py calls under the hood.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from portfolio_agent.config import get_settings, load_risk_profile

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _build_portfolio_provider(provider_name: str, settings, mock: bool):
    from portfolio_agent.providers.portfolio_file import FilePortfolioProvider

    if provider_name == "file" or mock:
        path = settings.portfolio_path if provider_name == "file" else Path("examples/portfolio.csv")
        return FilePortfolioProvider(path)

    from portfolio_agent.providers.portfolio_screenshot import ScreenshotPortfolioProvider

    return ScreenshotPortfolioProvider(settings.state_dir / "current_portfolio.json")


def _build_market_provider(mock: bool):
    if mock:
        from portfolio_agent.providers.market_mock import MockMarketDataProvider

        return MockMarketDataProvider()
    from portfolio_agent.providers.market_yfinance import YFinanceMarketDataProvider

    return YFinanceMarketDataProvider()


def _build_news_provider(settings, mock: bool):
    if mock:
        from portfolio_agent.providers.news_stub import NoOpNewsProvider

        return NoOpNewsProvider()
    if settings.news_api_key:
        from portfolio_agent.providers.news_newsapi import NewsAPIProvider

        return NewsAPIProvider(settings.news_api_key)
    from portfolio_agent.providers.news_gdelt import GDELTNewsProvider

    return GDELTNewsProvider()


def _sentiment_batch_fn(settings, mock: bool):
    if mock or not settings.anthropic_api_key:
        return None
    from portfolio_agent.analysis.sentiment import build_sentiment_signals

    def _fn(tickers, news_provider):
        return build_sentiment_signals(tickers, news_provider, settings)

    return _fn


def _review_fn(settings, mock: bool, kind: str):
    if mock or not settings.anthropic_api_key:
        return None
    from portfolio_agent.review import reviewer

    if kind == "analyze":
        return lambda recommendations, health, warnings: reviewer.review_recommendations(
            recommendations, health, warnings, settings
        )
    if kind == "screen":
        return lambda candidates, warnings: reviewer.review_candidates(candidates, warnings, settings)
    if kind == "newstocks":
        return lambda suggestions, warnings: reviewer.review_new_stock_suggestions(
            suggestions, warnings, settings
        )
    raise ValueError(f"Unknown review kind: {kind}")


def _render_and_output(report, report_kind: str, output_format: str, output_file: str | None):
    if output_format == "json":
        from portfolio_agent.report.json_report import render_json

        text = render_json(report)
    elif output_format == "console":
        from portfolio_agent.report import console as console_mod

        renderer = {
            "analyze": console_mod.render_portfolio_report,
            "screen": console_mod.render_screen_report,
            "newstocks": console_mod.render_newstocks_report,
        }[report_kind]
        text = renderer(report)
    elif output_format in ("pptx", "markdown"):
        from portfolio_agent.report import presentation as presentation_mod

        if output_format == "pptx":
            path = presentation_mod.build_presentation(report, report_kind, output_file)
            print(f"Saved: {path}")
            return
        from portfolio_agent.report import markdown as markdown_mod

        text = markdown_mod.render(report, report_kind)
    else:
        raise ValueError(f"Unknown output format: {output_format}")

    if output_file and output_format != "pptx":
        Path(output_file).write_text(text)
        print(f"Saved: {output_file}")
    else:
        print(text)


def cmd_analyze(args):
    settings = get_settings()
    risk_profile = load_risk_profile(args.risk_profile or settings.risk_profile_path)
    portfolio_provider = _build_portfolio_provider(args.portfolio_provider, settings, args.mock)
    market = _build_market_provider(args.mock)
    news_provider = _build_news_provider(settings, args.mock)

    from portfolio_agent.pipeline import run_analyze

    report = run_analyze(
        portfolio_provider,
        market,
        risk_profile,
        news_provider=news_provider,
        sentiment_batch_fn=_sentiment_batch_fn(settings, args.mock),
        review_fn=_review_fn(settings, args.mock, "analyze"),
        state_dir=str(settings.state_dir),
    )
    _render_and_output(report, "analyze", args.output_format, args.output_file)
    return report


def cmd_screen(args):
    settings = get_settings()
    risk_profile = load_risk_profile(args.risk_profile or settings.risk_profile_path)
    market = _build_market_provider(args.mock)

    from portfolio_agent.screen_pipeline import run_screen

    report = run_screen(
        market,
        risk_profile,
        universe_path=args.universe or (settings.data_dir / "sp500_constituents.csv"),
        review_fn=_review_fn(settings, args.mock, "screen"),
        state_dir=str(settings.state_dir),
    )
    _render_and_output(report, "screen", args.output_format, args.output_file)
    return report


def cmd_newstocks(args):
    settings = get_settings()
    risk_profile = load_risk_profile(args.risk_profile or settings.risk_profile_path)
    portfolio_provider = _build_portfolio_provider(args.portfolio_provider, settings, args.mock)
    market = _build_market_provider(args.mock)

    from portfolio_agent.newideas_pipeline import run_newstocks

    report = run_newstocks(
        portfolio_provider,
        market,
        risk_profile,
        universe_path=args.universe or (settings.data_dir / "sp500_constituents.csv"),
        review_fn=_review_fn(settings, args.mock, "newstocks"),
        state_dir=str(settings.state_dir),
    )
    _render_and_output(report, "newstocks", args.output_format, args.output_file)
    return report


def cmd_ingest_portfolio(args):
    settings = get_settings()
    from portfolio_agent.ingest.telegram_fetch import fetch_latest_screenshot
    from portfolio_agent.ingest.vision_extract import extract_holdings_from_image
    from portfolio_agent.ingest.snapshot_store import save_snapshot

    image_bytes = fetch_latest_screenshot(settings)
    if image_bytes is None:
        print("No pending screenshot found.")
        return
    holdings, warnings = extract_holdings_from_image(image_bytes, settings)
    save_snapshot(holdings, settings.state_dir)
    print(f"Parsed {len(holdings)} holdings.")
    for w in warnings:
        print(f"  warning: {w}")


def cmd_scorecard(args):
    settings = get_settings()
    from portfolio_agent.tracking.scorecard import build_scorecard_text

    market = _build_market_provider(args.mock)
    text = build_scorecard_text(settings.state_dir, market, since_days=args.since)
    print(text)


def cmd_bot(args):
    settings = get_settings()
    from portfolio_agent.bot.server import run_bot

    run_bot(settings)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="portfolio-agent")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common_report_args(p):
        p.add_argument("--output-format", choices=["pptx", "console", "markdown", "json"], default="console")
        p.add_argument("--output-file", default=None)
        p.add_argument("--mock", action="store_true")
        p.add_argument("--risk-profile", default=None)

    p_analyze = sub.add_parser("analyze", help="Analyze current holdings and produce recommendations")
    p_analyze.add_argument("--portfolio-provider", choices=["screenshot", "file"], default="screenshot")
    add_common_report_args(p_analyze)
    p_analyze.set_defaults(func=cmd_analyze)

    p_screen = sub.add_parser("screen", help="Scan the broad universe for short-term setups")
    p_screen.add_argument("--universe", default=None)
    add_common_report_args(p_screen)
    p_screen.set_defaults(func=cmd_screen)

    p_new = sub.add_parser("newstocks", help="Suggest new stocks that fill portfolio gaps")
    p_new.add_argument("--portfolio-provider", choices=["screenshot", "file"], default="screenshot")
    p_new.add_argument("--universe", default=None)
    add_common_report_args(p_new)
    p_new.set_defaults(func=cmd_newstocks)

    p_ingest = sub.add_parser("ingest-portfolio", help="Parse the latest pending screenshot now")
    p_ingest.set_defaults(func=cmd_ingest_portfolio)

    p_score = sub.add_parser("scorecard", help="Accuracy of past recommendations vs. actual price moves")
    p_score.add_argument("--since", type=int, default=30, help="Days to look back")
    p_score.add_argument("--mock", action="store_true")
    p_score.set_defaults(func=cmd_scorecard)

    p_bot = sub.add_parser("bot", help="Start the persistent Telegram listener (primary way to run this)")
    p_bot.set_defaults(func=cmd_bot)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except Exception as exc:  # noqa: BLE001
        logger.error("Command failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
