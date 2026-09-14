"""Telegram allows only one process to poll a bot token. A second instance gets
409 Conflict forever, so the message has to say what's wrong rather than
looping with a generic warning."""

import logging
from unittest.mock import MagicMock

import pytest
import requests

from portfolio_agent.bot import server


class _Settings:
    telegram_bot_token = "token"
    telegram_chat_id = "chat"
    state_dir = "state"

    def require_telegram(self):
        return self.telegram_bot_token, self.telegram_chat_id


def _http_error(status_code):
    response = MagicMock()
    response.status_code = status_code
    return requests.HTTPError(f"{status_code} Client Error", response=response)


class _StopLoop(BaseException):
    """BaseException, not Exception: run_bot's catch-all would otherwise swallow
    it and spin forever (which is correct behaviour for a long-running bot)."""


def _run_until(settings, side_effects, tmp_path, monkeypatch):
    """Runs the poll loop over a canned sequence of getUpdates outcomes."""
    settings.state_dir = str(tmp_path)
    calls = list(side_effects)

    def fake_get_updates(*_args, **_kwargs):
        if not calls:
            raise _StopLoop
        outcome = calls.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(server, "get_updates", fake_get_updates)
    monkeypatch.setattr(server.time, "sleep", lambda _s: None)
    monkeypatch.setattr(server, "TelegramNotifier", MagicMock())

    with pytest.raises(_StopLoop):
        server.run_bot(settings)


def test_409_explains_the_duplicate_instance(tmp_path, monkeypatch, caplog):
    with caplog.at_level(logging.ERROR):
        _run_until(_Settings(), [_http_error(409)], tmp_path, monkeypatch)

    message = " ".join(r.getMessage() for r in caplog.records)
    assert "already polling" in message
    assert "pkill" in message  # gives the actual way out


def test_409_does_not_repeat_the_long_explanation(tmp_path, monkeypatch, caplog):
    with caplog.at_level(logging.DEBUG):
        _run_until(_Settings(), [_http_error(409)] * 3, tmp_path, monkeypatch)

    detailed = [r for r in caplog.records if "pkill" in r.getMessage()]
    assert len(detailed) == 1, "the full explanation should be logged once, not per retry"


def test_409_uses_the_longer_conflict_backoff(tmp_path, monkeypatch):
    slept = []
    monkeypatch.setattr(server.time, "sleep", slept.append)
    settings = _Settings()
    settings.state_dir = str(tmp_path)

    calls = [_http_error(409)]

    def fake_get_updates(*_a, **_k):
        if not calls:
            raise _StopLoop
        raise calls.pop(0)

    monkeypatch.setattr(server, "get_updates", fake_get_updates)
    monkeypatch.setattr(server, "TelegramNotifier", MagicMock())
    with pytest.raises(_StopLoop):
        server.run_bot(settings)

    assert server.CONFLICT_SLEEP_SECONDS in slept
    assert server.CONFLICT_SLEEP_SECONDS > server.RETRY_SLEEP_SECONDS


def test_other_http_errors_keep_the_generic_retry(tmp_path, monkeypatch, caplog):
    with caplog.at_level(logging.WARNING):
        _run_until(_Settings(), [_http_error(500)], tmp_path, monkeypatch)

    message = " ".join(r.getMessage() for r in caplog.records)
    assert "getUpdates failed" in message
    assert "pkill" not in message


def test_network_errors_still_retry(tmp_path, monkeypatch, caplog):
    with caplog.at_level(logging.WARNING):
        _run_until(
            _Settings(), [requests.ConnectionError("network down")], tmp_path, monkeypatch
        )

    assert "getUpdates failed" in " ".join(r.getMessage() for r in caplog.records)


def test_recovery_after_conflict_resets_the_counter(tmp_path, monkeypatch, caplog):
    """Once the other instance stops, a later conflict should explain itself again."""
    with caplog.at_level(logging.DEBUG):
        _run_until(
            _Settings(),
            [_http_error(409), [], _http_error(409)],
            tmp_path,
            monkeypatch,
        )

    detailed = [r for r in caplog.records if "pkill" in r.getMessage()]
    assert len(detailed) == 2
