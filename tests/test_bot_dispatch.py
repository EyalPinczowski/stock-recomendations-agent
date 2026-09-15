from unittest.mock import MagicMock, patch

from portfolio_agent.bot.dispatch import _build_status_text, dispatch_command


class _FakeSettings:
    def __init__(self, state_dir, risk_profile_path):
        self.state_dir = state_dir
        self.risk_profile_path = risk_profile_path
        self.telegram_bot_token = "fake-token"
        self.telegram_chat_id = "fake-chat"
        self.anthropic_api_key = None
        self.data_dir = "data"


def test_dispatch_help_sends_help_text(tmp_path):
    settings = _FakeSettings(tmp_path, tmp_path / "risk_profile.yaml")
    notifier = MagicMock()
    dispatch_command("/help", settings, notifier)
    notifier.send_message.assert_called_once()
    assert "Commands:" in notifier.send_message.call_args[0][0]


def test_dispatch_unknown_command_sends_help_fallback(tmp_path):
    settings = _FakeSettings(tmp_path, tmp_path / "risk_profile.yaml")
    notifier = MagicMock()
    dispatch_command("/bogus", settings, notifier)
    assert "Unknown command" in notifier.send_message.call_args[0][0]


def test_dispatch_riskprofile_echoes_file(tmp_path):
    rp_path = tmp_path / "risk_profile.yaml"
    rp_path.write_text("name: balanced\n")
    settings = _FakeSettings(tmp_path, rp_path)
    notifier = MagicMock()
    dispatch_command("/riskprofile", settings, notifier)
    assert "balanced" in notifier.send_message.call_args[0][0]


def test_dispatch_status_no_requests_yet(tmp_path):
    settings = _FakeSettings(tmp_path, tmp_path / "risk_profile.yaml")
    text = _build_status_text(settings)
    assert "No requests handled yet" in text
    assert "No portfolio snapshot yet" in text


def test_dispatch_failure_sends_error_and_records_status(tmp_path):
    settings = _FakeSettings(tmp_path, tmp_path / "risk_profile.yaml")
    notifier = MagicMock()

    with patch("portfolio_agent.bot.dispatch._run_report_command", side_effect=RuntimeError("boom")):
        dispatch_command("/analyze", settings, notifier)

    # First call is the "Analyzing..." ack, second is the error.
    error_calls = [c.args[0] for c in notifier.send_message.call_args_list if "failed" in c.args[0]]
    assert error_calls, "expected an error message to be sent"

    import json

    last_request = json.loads((tmp_path / "last_request.json").read_text())
    assert last_request["command"] == "/analyze"
    assert "failed" in last_request["outcome"]


def test_dispatch_does_not_crash_the_loop_when_telegram_send_also_fails(tmp_path):
    settings = _FakeSettings(tmp_path, tmp_path / "risk_profile.yaml")
    notifier = MagicMock()
    notifier.send_message.side_effect = RuntimeError("telegram down")

    with patch("portfolio_agent.bot.dispatch._run_report_command", side_effect=RuntimeError("boom")):
        dispatch_command("/analyze", settings, notifier)  # should not raise


def test_status_lists_the_tickers_and_cash_it_parsed(tmp_path):
    """A wrong holding count is the clearest sign a screenshot was missed, so
    /status has to show what was actually read — not just how many."""
    from portfolio_agent.bot.dispatch import _build_status_text
    from portfolio_agent.ingest.snapshot_store import save_snapshot
    from portfolio_agent.models import Currency, Holding

    save_snapshot(
        [
            Holding(ticker="CEG", quantity=12, cost_basis=281.01),
            Holding(ticker="1159714.TA", quantity=489, cost_basis=39.7, currency=Currency.ILS),
        ],
        tmp_path,
        {"USD": 8561.64, "ILS": -897.31},
    )

    class Settings:
        state_dir = tmp_path

    text = _build_status_text(Settings())

    assert "2 holdings" in text
    assert "CEG" in text and "1159714.TA" in text
    assert "8,561.64 USD" in text
    assert "-897.31 ILS" in text


# --- where decks get written ------------------------------------------------
# /tmp doesn't exist on Android, so a hardcoded path there failed after the
# whole analysis had already run — the most expensive possible place to fail.


def test_decks_are_written_under_the_state_directory(tmp_path):
    from portfolio_agent.bot.dispatch import _report_path

    class Settings:
        state_dir = tmp_path / "state"

    path = _report_path(Settings(), "analyze")

    assert path.parent == tmp_path / "state" / "reports"
    assert path.parent.is_dir()  # created, not assumed
    assert path.name.startswith("analyze_") and path.suffix == ".pptx"


def test_report_paths_do_not_collide(tmp_path):
    from portfolio_agent.bot.dispatch import _report_path

    class Settings:
        state_dir = tmp_path

    assert _report_path(Settings(), "analyze") != _report_path(Settings(), "screen")


def test_old_decks_are_pruned_but_recent_ones_kept(tmp_path):
    """They'd otherwise accumulate forever on a phone."""
    import os

    from portfolio_agent.bot.dispatch import REPORTS_TO_KEEP, _prune_old_reports

    directory = tmp_path / "reports"
    directory.mkdir()
    for i in range(REPORTS_TO_KEEP + 5):
        deck = directory / f"analyze_{i:03d}.pptx"
        deck.write_bytes(b"x")
        os.utime(deck, (i, i))  # oldest first

    class Settings:
        state_dir = tmp_path

    _prune_old_reports(Settings())

    remaining = sorted(p.name for p in directory.glob("*.pptx"))
    assert len(remaining) == REPORTS_TO_KEEP
    assert remaining[-1] == f"analyze_{REPORTS_TO_KEEP + 4:03d}.pptx"  # newest survives


def test_pruning_a_missing_directory_is_harmless(tmp_path):
    from portfolio_agent.bot.dispatch import _prune_old_reports

    class Settings:
        state_dir = tmp_path / "nothing-here"

    _prune_old_reports(Settings())  # must not raise
