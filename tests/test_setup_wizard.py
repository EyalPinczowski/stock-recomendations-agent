from unittest.mock import MagicMock, patch

import pytest
import requests

from portfolio_agent.setup_wizard import (
    SetupError,
    find_chat_id,
    validate_token,
    write_env_file,
)


def test_write_env_file_creates_file_with_secrets(tmp_path):
    env_path = tmp_path / ".env"
    write_env_file({"TELEGRAM_BOT_TOKEN": "abc", "TELEGRAM_CHAT_ID": "123"}, env_path)

    content = env_path.read_text()
    assert "TELEGRAM_BOT_TOKEN=abc" in content
    assert "TELEGRAM_CHAT_ID=123" in content


def test_write_env_file_is_owner_only_readable(tmp_path):
    env_path = tmp_path / ".env"
    write_env_file({"TELEGRAM_BOT_TOKEN": "abc"}, env_path)
    assert oct(env_path.stat().st_mode)[-3:] == "600"


def test_write_env_file_skips_empty_values(tmp_path):
    env_path = tmp_path / ".env"
    write_env_file({"TELEGRAM_BOT_TOKEN": "abc", "NEWS_API_KEY": ""}, env_path)
    assert "NEWS_API_KEY" not in env_path.read_text()


def test_write_env_file_preserves_unrelated_existing_keys(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("# comment\nPORTFOLIO_PATH=custom.csv\nTELEGRAM_BOT_TOKEN=old\n")

    write_env_file({"TELEGRAM_BOT_TOKEN": "new"}, env_path)

    content = env_path.read_text()
    assert "PORTFOLIO_PATH=custom.csv" in content
    assert "TELEGRAM_BOT_TOKEN=new" in content
    assert "TELEGRAM_BOT_TOKEN=old" not in content


def test_validate_token_returns_username_on_success():
    response = MagicMock()
    response.json.return_value = {"ok": True, "result": {"username": "my_bot"}}
    with patch("portfolio_agent.setup_wizard.requests.get", return_value=response):
        assert validate_token("token") == "my_bot"


def test_validate_token_raises_on_rejection():
    response = MagicMock()
    response.json.return_value = {"ok": False, "description": "Unauthorized"}
    with patch("portfolio_agent.setup_wizard.requests.get", return_value=response), \
         pytest.raises(SetupError, match="Unauthorized"):
        validate_token("bad-token")


def test_validate_token_raises_when_telegram_unreachable():
    with patch(
        "portfolio_agent.setup_wizard.requests.get",
        side_effect=requests.RequestException("blocked by proxy"),
    ), pytest.raises(SetupError, match="Couldn't reach Telegram"):
        validate_token("token")


def test_find_chat_id_returns_first_message_chat():
    response = MagicMock()
    response.json.return_value = {
        "result": [{"update_id": 1, "message": {"chat": {"id": 4242}, "text": "hi"}}]
    }
    with patch("portfolio_agent.setup_wizard.requests.get", return_value=response):
        assert find_chat_id("token", timeout_seconds=5) == "4242"


def test_find_chat_id_times_out_with_actionable_message():
    response = MagicMock()
    response.json.return_value = {"result": []}
    with patch("portfolio_agent.setup_wizard.requests.get", return_value=response), \
         patch("portfolio_agent.setup_wizard.time.sleep"), \
         pytest.raises(SetupError, match="Send your bot a message"):
        find_chat_id("token", timeout_seconds=0)
