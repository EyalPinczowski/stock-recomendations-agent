"""Shared Anthropic client construction.

The SDK is an optional dependency. It powers three features — screenshot
parsing, news sentiment, and the review pass — all of which the pipeline is
already designed to run without. It's optional because its `jiter` dependency
needs a Rust toolchain, which is painful to build on some hosts (Termux on
Android especially), and one hard-to-build dependency shouldn't block the
whole install.
"""

from __future__ import annotations

INSTALL_HINT = (
    "The 'anthropic' package isn't installed, so LLM-backed features "
    "(screenshot parsing, news sentiment, the review pass) are unavailable.\n"
    "Install it with:  pip install 'anthropic>=0.34'\n"
    "On Termux it needs a Rust toolchain first (pkg install rust) — "
    "run  bash deploy/termux/install-llm.sh  to do both and show the full build output.\n"
    "Meanwhile you can supply holdings as a CSV: --portfolio-provider file"
)


class AnthropicUnavailableError(RuntimeError):
    """Raised when an LLM-backed feature is used but the SDK isn't installed."""


def anthropic_available() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def build_client(settings):
    """Returns an Anthropic client, or raises with an actionable message."""
    try:
        import anthropic
    except ImportError as exc:
        raise AnthropicUnavailableError(INSTALL_HINT) from exc

    if not settings.anthropic_api_key:
        raise AnthropicUnavailableError(
            "ANTHROPIC_API_KEY is not set — run `portfolio-agent setup` or add it to .env."
        )
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)
