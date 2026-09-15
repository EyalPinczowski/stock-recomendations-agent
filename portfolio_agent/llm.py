"""The one place that talks to an LLM.

Three features need one — screenshot parsing, news sentiment, and the review
pass — and all three are optional: the pipeline is designed to produce a full
report without them.

Two backends are supported, chosen with LLM_PROVIDER:

  gemini    (default) — plain REST over `requests`, which is already a core
                        dependency. Nothing to compile, which matters a lot on
                        Termux/Android, and its free tier covers this app's
                        handful of calls per report.
  anthropic            — the official SDK, an optional extra. Needs `jiter`,
                        which needs a Rust toolchain where no wheel exists.

Callers use `complete()` and never see the difference.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_DEFAULT_MODEL = "gemini-3.8-flash"
REQUEST_TIMEOUT_SECONDS = 180
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 2

ANTHROPIC_INSTALL_HINT = (
    "LLM_PROVIDER is 'anthropic' but the 'anthropic' package isn't installed.\n"
    "Install it with:  pip install 'anthropic>=0.34'\n"
    "On Termux it needs a Rust toolchain first (pkg install rust) — "
    "run  bash deploy/termux/install-llm.sh  to do both and show the full build output.\n"
    "Or switch to Gemini, which needs no extra package: set LLM_PROVIDER=gemini "
    "and GEMINI_API_KEY in .env."
)


class LLMUnavailableError(RuntimeError):
    """Raised when an LLM-backed feature is used but can't reach a model —
    no key, missing package, or the API refused the request."""


# Kept so older imports/messages keep working; the Anthropic path raises it too.
AnthropicUnavailableError = LLMUnavailableError


@dataclass(frozen=True)
class ImagePart:
    """An image to send alongside the prompt (portfolio screenshots)."""

    data: bytes
    media_type: str = "image/jpeg"


def provider_name(settings) -> str:
    return (getattr(settings, "llm_provider", "") or "gemini").strip().lower()


def anthropic_available() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def llm_available(settings) -> bool:
    """True when the configured provider is actually usable right now."""
    if provider_name(settings) == "anthropic":
        return bool(getattr(settings, "anthropic_api_key", None)) and anthropic_available()
    return bool(getattr(settings, "gemini_api_key", None))


def unavailable_reason(settings) -> str | None:
    """A short, actionable explanation of why LLM features are off, or None."""
    if llm_available(settings):
        return None
    if provider_name(settings) == "anthropic":
        if not getattr(settings, "anthropic_api_key", None):
            return "ANTHROPIC_API_KEY is not set"
        return "the 'anthropic' package isn't installed"
    return "GEMINI_API_KEY is not set — get one free at https://aistudio.google.com/apikey"


def complete(
    settings,
    *,
    system: str,
    user: str,
    image: ImagePart | None = None,
    max_tokens: int = 2048,
    json_only: bool = True,
) -> str:
    """Sends one prompt and returns the model's text. Provider-agnostic.

    json_only asks the provider for raw JSON where it can enforce that;
    callers still tolerate markdown fences, since not every model honours it.
    """
    if provider_name(settings) == "anthropic":
        return _complete_anthropic(settings, system, user, image, max_tokens)
    return _complete_gemini(settings, system, user, image, max_tokens, json_only)


# --- Gemini (REST, no extra dependency) -------------------------------------


def _gemini_parts(user: str, image: ImagePart | None) -> list[dict]:
    parts: list[dict] = []
    if image is not None:
        import base64

        parts.append(
            {
                "inlineData": {
                    "mimeType": image.media_type,
                    "data": base64.standard_b64encode(image.data).decode(),
                }
            }
        )
    parts.append({"text": user})
    return parts


def _gemini_body(
    system: str, user: str, image: ImagePart | None, max_tokens: int, json_only: bool, settings
) -> dict:
    generation_config: dict = {
        "temperature": 0,
        "maxOutputTokens": max_tokens,
    }
    if json_only:
        generation_config["responseMimeType"] = "application/json"

    thinking_level = (getattr(settings, "gemini_thinking_level", "") or "").strip().upper()
    if thinking_level:
        generation_config["thinkingConfig"] = {"thinkingLevel": thinking_level}

    return {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": _gemini_parts(user, image)}],
        "generationConfig": generation_config,
    }


def _gemini_error_message(status_code: int, payload: dict, model: str) -> str:
    detail = (payload.get("error") or {}).get("message", "")
    if status_code in (400, 401) and "api key" in detail.lower():
        return (
            "Gemini rejected the API key. Check GEMINI_API_KEY in .env — "
            f"get a fresh one at https://aistudio.google.com/apikey. ({detail})"
        )
    if status_code == 403:
        return f"Gemini denied access to model '{model}': {detail}"
    if status_code == 404:
        return (
            f"Gemini has no model called '{model}'. Set GEMINI_MODEL in .env to one "
            "your key can use — `portfolio-agent setup` lists them. "
            f"({detail})"
        )
    if status_code == 429:
        return (
            "Gemini rate-limited this request (the free tier allows a limited number "
            f"per minute). Try again in a minute. ({detail})"
        )
    return f"Gemini request failed ({status_code}): {detail or 'no detail given'}"


def _gemini_text(payload: dict) -> tuple[str, str]:
    """Returns (text, finish_reason). Thought parts carry no answer text."""
    candidates = payload.get("candidates") or []
    if not candidates:
        blocked = (payload.get("promptFeedback") or {}).get("blockReason")
        if blocked:
            raise LLMUnavailableError(f"Gemini blocked the prompt ({blocked}).")
        return "", ""
    candidate = candidates[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    return text, candidate.get("finishReason", "")


def _gemini_post(url: str, headers: dict, body: dict) -> dict:
    """POSTs with retries on the transient statuses, and maps errors to
    LLMUnavailableError with something the user can act on."""
    model = url.rsplit("/", 1)[-1].split(":")[0]
    last_error = ""

    for attempt in range(MAX_ATTEMPTS):
        try:
            response = requests.post(
                url, headers=headers, json=body, timeout=REQUEST_TIMEOUT_SECONDS
            )
        except requests.RequestException as exc:
            last_error = f"Couldn't reach the Gemini API: {exc}"
            if attempt == MAX_ATTEMPTS - 1:
                raise LLMUnavailableError(last_error) from exc
            time.sleep(BACKOFF_BASE_SECONDS * (2**attempt))
            continue

        if response.status_code == 200:
            return response.json()

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        message = _gemini_error_message(response.status_code, payload, model)
        if response.status_code in (429, 500, 502, 503, 504) and attempt < MAX_ATTEMPTS - 1:
            logger.warning("Gemini %s — retrying.", response.status_code)
            time.sleep(BACKOFF_BASE_SECONDS * (2**attempt))
            last_error = message
            continue
        raise LLMUnavailableError(message)

    raise LLMUnavailableError(last_error or "Gemini request failed.")


def _complete_gemini(
    settings, system: str, user: str, image: ImagePart | None, max_tokens: int, json_only: bool
) -> str:
    api_key = getattr(settings, "gemini_api_key", None)
    if not api_key:
        raise LLMUnavailableError(
            "GEMINI_API_KEY is not set — run `portfolio-agent setup` or add it to .env. "
            "Keys are free at https://aistudio.google.com/apikey."
        )

    model = getattr(settings, "gemini_model", None) or GEMINI_DEFAULT_MODEL
    url = f"{GEMINI_API_BASE}/models/{model}:generateContent"
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

    body = _gemini_body(system, user, image, max_tokens, json_only, settings)
    text, finish_reason = _gemini_text(_gemini_post(url, headers, body))

    # Thinking models spend the output budget before answering; one retry with
    # more room is cheaper than losing the whole report stage.
    if not text.strip() and finish_reason == "MAX_TOKENS":
        logger.warning("Gemini hit the output limit before answering — retrying with more room.")
        body = _gemini_body(system, user, image, max_tokens * 2, json_only, settings)
        text, finish_reason = _gemini_text(_gemini_post(url, headers, body))

    if not text.strip():
        raise LLMUnavailableError(
            f"Gemini returned no text (finish reason: {finish_reason or 'unknown'})."
        )
    return text


def list_gemini_models(api_key: str) -> list[str]:
    """Model IDs this key can call generateContent on. Used by setup to pick a
    default instead of guessing a name that may have been retired."""
    response = requests.get(
        f"{GEMINI_API_BASE}/models",
        headers={"x-goog-api-key": api_key},
        params={"pageSize": 200},
        timeout=60,
    )
    response.raise_for_status()
    models = []
    for model in response.json().get("models", []):
        if "generateContent" not in (model.get("supportedGenerationMethods") or []):
            continue
        models.append(model["name"].removeprefix("models/"))
    return models


def _model_sort_key(name: str) -> tuple:
    """Newest first, by the version number embedded in the name."""
    digits = "".join(c if c.isdigit() or c == "." else " " for c in name).split()
    try:
        version = max(float(d) for d in digits if d.replace(".", "", 1).isdigit())
    except ValueError:
        version = 0.0
    return (version, len(name) * -1)


def pick_gemini_model(available: list[str], preferred: str = GEMINI_DEFAULT_MODEL) -> str | None:
    """Chooses a sensible default: the preferred model if the key has it, else
    the newest plain 'flash' (cheap, vision-capable, generous free tier)."""
    if preferred in available:
        return preferred

    def usable(name: str) -> bool:
        return not any(
            word in name
            for word in ("embedding", "aqa", "imagen", "tts", "image-generation", "live", "gemma")
        )

    flash = [m for m in available if "flash" in m and "lite" not in m and usable(m)]
    lite = [m for m in available if "flash" in m and usable(m)]
    rest = [m for m in available if usable(m)]
    for group in (flash, lite, rest):
        if group:
            return sorted(group, key=_model_sort_key, reverse=True)[0]
    return None


# --- Anthropic (optional SDK) -----------------------------------------------


def build_client(settings):
    """Returns an Anthropic client, or raises with an actionable message."""
    try:
        import anthropic
    except ImportError as exc:
        raise LLMUnavailableError(ANTHROPIC_INSTALL_HINT) from exc

    if not getattr(settings, "anthropic_api_key", None):
        raise LLMUnavailableError(
            "ANTHROPIC_API_KEY is not set — run `portfolio-agent setup` or add it to .env."
        )
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _complete_anthropic(
    settings, system: str, user: str, image: ImagePart | None, max_tokens: int
) -> str:
    client = build_client(settings)

    content: list[dict] = []
    if image is not None:
        import base64

        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image.media_type,
                    "data": base64.standard_b64encode(image.data).decode(),
                },
            }
        )
    content.append({"type": "text", "text": user})

    message = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    return "".join(block.text for block in message.content if block.type == "text")


def strip_json_fences(raw_text: str) -> str:
    """Models sometimes wrap JSON in markdown fences despite being told not to."""
    import re

    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?|\n?```$", "", text.strip())
    return text


def parse_json_response(raw_text: str, default):
    """Parses a JSON response, returning `default` if the model didn't comply."""
    try:
        return json.loads(strip_json_fences(raw_text))
    except json.JSONDecodeError:
        return default
