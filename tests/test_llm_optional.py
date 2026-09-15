"""LLM features are optional, and which backend serves them is configurable.
These tests pin the contract: a clear, actionable message whenever a feature
is asked for but can't run — never a bare ImportError or KeyError.
"""

import builtins
from unittest.mock import MagicMock

import pytest

from portfolio_agent.llm import (
    AnthropicUnavailableError,
    LLMUnavailableError,
    anthropic_available,
    build_client,
    complete,
    llm_available,
    provider_name,
    unavailable_reason,
)


class _Anthropic:
    llm_provider = "anthropic"
    anthropic_api_key = "test-key"
    anthropic_model = "claude-opus-5"
    gemini_api_key = None
    gemini_model = ""
    gemini_thinking_level = ""


class _Gemini(_Anthropic):
    llm_provider = "gemini"
    gemini_api_key = "test-key"


def _hide_anthropic(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "anthropic" or name.startswith("anthropic."):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_gemini_is_the_default_provider():
    class Bare:
        pass

    assert provider_name(Bare()) == "gemini"


def test_anthropic_available_false_when_missing(monkeypatch):
    _hide_anthropic(monkeypatch)
    assert anthropic_available() is False


def test_gemini_needs_no_package_only_a_key(monkeypatch):
    """The whole point of defaulting to Gemini: nothing to install."""
    _hide_anthropic(monkeypatch)
    assert llm_available(_Gemini()) is True

    no_key = _Gemini()
    no_key.gemini_api_key = None
    assert llm_available(no_key) is False
    assert "GEMINI_API_KEY" in unavailable_reason(no_key)


def test_anthropic_provider_needs_both_key_and_package(monkeypatch):
    _hide_anthropic(monkeypatch)
    assert llm_available(_Anthropic()) is False
    assert "anthropic" in unavailable_reason(_Anthropic())


def test_build_client_raises_actionable_error_when_missing(monkeypatch):
    _hide_anthropic(monkeypatch)
    with pytest.raises(LLMUnavailableError) as exc:
        build_client(_Anthropic())
    message = str(exc.value)
    assert "pip install" in message
    assert "pkg install rust" in message  # the Termux-specific hint
    assert "LLM_PROVIDER=gemini" in message  # the way out that needs no build


def test_build_client_raises_when_api_key_missing():
    no_key = _Anthropic()
    no_key.anthropic_api_key = None
    with pytest.raises(LLMUnavailableError, match="ANTHROPIC_API_KEY"):
        build_client(no_key)


def test_anthropic_error_alias_still_works():
    """Kept so existing except-clauses and messages don't silently stop matching."""
    assert AnthropicUnavailableError is LLMUnavailableError


def test_complete_routes_to_anthropic_when_configured(monkeypatch):
    block = MagicMock()
    block.type = "text"
    block.text = '{"ok": true}'
    client = MagicMock()
    client.messages.create.return_value = MagicMock(content=[block])
    monkeypatch.setattr("portfolio_agent.llm.build_client", lambda _s: client)

    assert complete(_Anthropic(), system="s", user="u", max_tokens=50) == '{"ok": true}'

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-opus-5"
    assert kwargs["system"] == "s"
    assert kwargs["messages"][0]["content"][-1]["text"] == "u"


def test_anthropic_image_uses_its_own_content_block_shape(monkeypatch):
    block = MagicMock()
    block.type = "text"
    block.text = "[]"
    client = MagicMock()
    client.messages.create.return_value = MagicMock(content=[block])
    monkeypatch.setattr("portfolio_agent.llm.build_client", lambda _s: client)

    from portfolio_agent.llm import ImagePart

    complete(_Anthropic(), system="s", user="u", images=[ImagePart(data=b"jpeg")])

    image_block = client.messages.create.call_args.kwargs["messages"][0]["content"][0]
    assert image_block["type"] == "image"
    assert image_block["source"]["media_type"] == "image/jpeg"
