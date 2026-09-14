"""The anthropic SDK is an optional dependency (its jiter dependency needs Rust,
which is painful on Termux). These tests pin the contract: a clear, actionable
error when it's needed but absent — never a bare ImportError."""

import builtins

import pytest

from portfolio_agent.llm import (
    AnthropicUnavailableError,
    anthropic_available,
    build_client,
)


class _Settings:
    anthropic_api_key = "test-key"
    anthropic_model = "claude-opus-5"


def _hide_anthropic(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "anthropic" or name.startswith("anthropic."):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_anthropic_available_false_when_missing(monkeypatch):
    _hide_anthropic(monkeypatch)
    assert anthropic_available() is False


def test_build_client_raises_actionable_error_when_missing(monkeypatch):
    _hide_anthropic(monkeypatch)
    with pytest.raises(AnthropicUnavailableError) as exc:
        build_client(_Settings())
    message = str(exc.value)
    assert "pip install" in message
    assert "pkg install rust" in message  # the Termux-specific hint


def test_build_client_raises_when_api_key_missing():
    class NoKey:
        anthropic_api_key = None
        anthropic_model = "claude-opus-5"

    with pytest.raises(AnthropicUnavailableError, match="ANTHROPIC_API_KEY"):
        build_client(NoKey())
