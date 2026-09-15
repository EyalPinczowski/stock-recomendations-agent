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


# --- screenshot batching ----------------------------------------------------
# A portfolio doesn't fit in one screenshot. Reading each photo on its own
# would leave the snapshot holding only whatever the last image showed.


def _photo_update(update_id, file_id):
    return {
        "update_id": update_id,
        "message": {"chat": {"id": "chat"}, "photo": [{"file_id": file_id, "file_size": 100}]},
    }


def _text_update(update_id, text):
    return {"update_id": update_id, "message": {"chat": {"id": "chat"}, "text": text}}


@pytest.fixture
def batched(monkeypatch):
    """Runs the loop with downloads and handlers faked, returning what the
    screenshot handler was called with."""
    monkeypatch.setattr(server, "download_file", lambda _t, file_id: file_id.encode())
    monkeypatch.setattr(server, "TelegramNotifier", MagicMock())
    handled = []
    monkeypatch.setattr(server, "handle_photos", lambda images, *_a: handled.append(images))
    monkeypatch.setattr(server, "dispatch_command", MagicMock())
    return handled


def test_photos_arriving_together_are_read_as_one_portfolio(batched, tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(server.time, "monotonic", lambda: clock[0])

    _run_until(
        _Settings(),
        [[_photo_update(1, "a"), _photo_update(2, "b"), _photo_update(3, "c")], []],
        tmp_path,
        monkeypatch,
    )

    assert batched == [], "nothing should be read while more photos may still arrive"


def test_batch_is_read_once_the_photos_stop(batched, tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(server.time, "monotonic", lambda: clock[0])

    calls = [[_photo_update(1, "a"), _photo_update(2, "b")], []]

    def fake_get_updates(*_args, **_kwargs):
        if not calls:
            raise _StopLoop
        if len(calls) == 1:  # the poll after the photos: time has moved on
            clock[0] += server.PHOTO_BATCH_SECONDS + 1
        return calls.pop(0)

    monkeypatch.setattr(server, "get_updates", fake_get_updates)
    settings = _Settings()
    settings.state_dir = str(tmp_path)
    with pytest.raises(_StopLoop):
        server.run_bot(settings)

    assert batched == [[b"a", b"b"]]


def test_a_command_closes_the_batch_first(batched, tmp_path, monkeypatch):
    """/analyze right after sending screenshots must analyze those screenshots,
    not the previous portfolio."""
    monkeypatch.setattr(server.time, "monotonic", lambda: 1000.0)  # no timeout elapses

    _run_until(
        _Settings(),
        [[_photo_update(1, "a"), _photo_update(2, "b"), _text_update(3, "/analyze")]],
        tmp_path,
        monkeypatch,
    )

    assert batched == [[b"a", b"b"]]
    server.dispatch_command.assert_called_once()


def test_polling_stays_responsive_while_a_batch_is_open(batched, tmp_path, monkeypatch):
    """The batch can only be closed by a later poll, so that poll can't block
    for the full long-poll timeout."""
    monkeypatch.setattr(server.time, "monotonic", lambda: 1000.0)
    timeouts = []

    calls = [[_photo_update(1, "a")], []]

    def fake_get_updates(_token, offset=None, timeout=None):
        timeouts.append(timeout)
        if not calls:
            raise _StopLoop
        return calls.pop(0)

    monkeypatch.setattr(server, "get_updates", fake_get_updates)
    settings = _Settings()
    settings.state_dir = str(tmp_path)
    with pytest.raises(_StopLoop):
        server.run_bot(settings)

    assert timeouts[0] == server.LONG_POLL_TIMEOUT  # idle: block for a while
    assert timeouts[1] == server.SHORT_POLL_TIMEOUT  # batch open: check back soon
