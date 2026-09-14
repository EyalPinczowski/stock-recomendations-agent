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
