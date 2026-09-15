"""The Gemini backend talks to Google's REST API directly (no SDK, so nothing
to compile on Termux). These tests pin the request shape and — more
importantly — that every failure mode produces something the user can act on
rather than a bare HTTP error.
"""

import base64
import json
from unittest.mock import MagicMock

import pytest
import requests

from portfolio_agent import llm


class _Settings:
    llm_provider = "gemini"
    gemini_api_key = "test-key"
    gemini_model = "gemini-3.8-flash"
    gemini_thinking_level = ""
    anthropic_api_key = None
    anthropic_model = "claude-opus-5"


def _response(status_code=200, payload=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload if payload is not None else {}
    return resp


def _ok(text, finish_reason="STOP"):
    return _response(
        200,
        {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish_reason}]},
    )


@pytest.fixture
def post(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(llm.requests, "post", mock)
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)
    return mock


def test_sends_the_documented_request_shape(post):
    post.return_value = _ok('{"ok": true}')

    result = llm.complete(_Settings(), system="be terse", user="hello", max_tokens=1234)

    assert result == '{"ok": true}'
    url = post.call_args.args[0]
    assert url.endswith("/models/gemini-3.8-flash:generateContent")
    assert post.call_args.kwargs["headers"]["x-goog-api-key"] == "test-key"

    body = post.call_args.kwargs["json"]
    assert body["systemInstruction"]["parts"][0]["text"] == "be terse"
    assert body["contents"][0]["parts"][-1]["text"] == "hello"
    assert body["generationConfig"]["maxOutputTokens"] == 1234
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["temperature"] == 0


def test_json_only_false_omits_the_mime_type(post):
    post.return_value = _ok("plain prose")

    llm.complete(_Settings(), system="s", user="u", json_only=False)

    assert "responseMimeType" not in post.call_args.kwargs["json"]["generationConfig"]


def test_image_is_sent_as_inline_base64_data(post):
    post.return_value = _ok("[]")

    llm.complete(
        _Settings(),
        system="s",
        user="extract",
        image=llm.ImagePart(data=b"\x89PNG-bytes", media_type="image/png"),
    )

    parts = post.call_args.kwargs["json"]["contents"][0]["parts"]
    assert parts[0]["inlineData"]["mimeType"] == "image/png"
    assert base64.standard_b64decode(parts[0]["inlineData"]["data"]) == b"\x89PNG-bytes"
    assert parts[1]["text"] == "extract"  # image first, then the instruction


def test_thinking_level_only_sent_when_configured(post):
    post.return_value = _ok("x")

    llm.complete(_Settings(), system="s", user="u")
    assert "thinkingConfig" not in post.call_args.kwargs["json"]["generationConfig"]

    settings = _Settings()
    settings.gemini_thinking_level = "minimal"
    llm.complete(settings, system="s", user="u")
    config = post.call_args.kwargs["json"]["generationConfig"]["thinkingConfig"]
    assert config == {"thinkingLevel": "MINIMAL"}


def test_thought_parts_are_not_treated_as_the_answer(post):
    post.return_value = _response(
        200,
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "let me think...", "thought": True},
                            {"text": '{"answer": 1}'},
                        ]
                    },
                    "finishReason": "STOP",
                }
            ]
        },
    )

    assert llm.complete(_Settings(), system="s", user="u") == '{"answer": 1}'


def test_retries_with_more_room_when_thinking_ate_the_budget(post):
    """A thinking model can spend the whole output budget and return nothing —
    one retry with more room is cheaper than losing the report stage."""
    post.side_effect = [_ok("", finish_reason="MAX_TOKENS"), _ok('{"ok": true}')]

    assert llm.complete(_Settings(), system="s", user="u", max_tokens=100) == '{"ok": true}'
    assert post.call_count == 2
    assert post.call_args_list[1].kwargs["json"]["generationConfig"]["maxOutputTokens"] == 200


def test_gives_up_with_a_clear_message_if_still_empty(post):
    post.return_value = _ok("", finish_reason="MAX_TOKENS")

    with pytest.raises(llm.LLMUnavailableError, match="MAX_TOKENS"):
        llm.complete(_Settings(), system="s", user="u")


def test_missing_key_names_the_env_var_and_where_to_get_one():
    settings = _Settings()
    settings.gemini_api_key = None

    with pytest.raises(llm.LLMUnavailableError) as exc:
        llm.complete(settings, system="s", user="u")

    assert "GEMINI_API_KEY" in str(exc.value)
    assert "aistudio.google.com" in str(exc.value)


def test_bad_key_is_reported_as_a_key_problem(post):
    post.return_value = _response(400, {"error": {"message": "API key not valid. Pass a valid key."}})

    with pytest.raises(llm.LLMUnavailableError) as exc:
        llm.complete(_Settings(), system="s", user="u")

    assert "GEMINI_API_KEY" in str(exc.value)
    assert post.call_count == 1  # not retried — retrying a bad key is pointless


def test_unknown_model_points_at_the_setting_that_fixes_it(post):
    post.return_value = _response(404, {"error": {"message": "models/x is not found"}})

    with pytest.raises(llm.LLMUnavailableError) as exc:
        llm.complete(_Settings(), system="s", user="u")

    message = str(exc.value)
    assert "gemini-3.8-flash" in message
    assert "GEMINI_MODEL" in message


def test_rate_limit_is_retried_then_explained(post):
    post.return_value = _response(429, {"error": {"message": "Quota exceeded"}})

    with pytest.raises(llm.LLMUnavailableError, match="rate-limited"):
        llm.complete(_Settings(), system="s", user="u")

    assert post.call_count == llm.MAX_ATTEMPTS


def test_transient_server_error_recovers_on_retry(post):
    post.side_effect = [_response(503, {"error": {"message": "overloaded"}}), _ok("recovered")]

    assert llm.complete(_Settings(), system="s", user="u") == "recovered"
    assert post.call_count == 2


def test_network_failure_is_retried_then_wrapped(post):
    post.side_effect = requests.ConnectionError("no route to host")

    with pytest.raises(llm.LLMUnavailableError, match="Couldn't reach the Gemini API"):
        llm.complete(_Settings(), system="s", user="u")

    assert post.call_count == llm.MAX_ATTEMPTS


def test_blocked_prompt_is_explained(post):
    post.return_value = _response(200, {"promptFeedback": {"blockReason": "SAFETY"}})

    with pytest.raises(llm.LLMUnavailableError, match="SAFETY"):
        llm.complete(_Settings(), system="s", user="u")


# --- model discovery --------------------------------------------------------


def test_list_gemini_models_filters_to_generate_content(monkeypatch):
    response = MagicMock()
    response.json.return_value = {
        "models": [
            {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
        ]
    }
    monkeypatch.setattr(llm.requests, "get", MagicMock(return_value=response))

    assert llm.list_gemini_models("k") == ["gemini-3.8-flash"]


def test_pick_gemini_model_prefers_the_default_when_present():
    available = ["gemini-2.5-flash", llm.GEMINI_DEFAULT_MODEL]
    assert llm.pick_gemini_model(available) == llm.GEMINI_DEFAULT_MODEL


def test_pick_gemini_model_falls_back_to_the_newest_flash():
    """Model names get retired; setup asks the API rather than trusting ours."""
    available = ["gemini-2.5-flash", "gemini-4.1-flash", "gemini-4.1-flash-lite", "gemini-4.1-pro"]
    assert llm.pick_gemini_model(available) == "gemini-4.1-flash"


def test_pick_gemini_model_ignores_non_text_models():
    assert llm.pick_gemini_model(["imagen-4.0-generate", "gemma-3-27b-it"]) is None
    assert llm.pick_gemini_model([]) is None


# --- JSON helpers shared by all three callers -------------------------------


def test_parse_json_response_tolerates_markdown_fences():
    assert llm.parse_json_response('```json\n{"a": 1}\n```', default=None) == {"a": 1}
    assert llm.parse_json_response("not json", default={}) == {}


def test_strip_json_fences_leaves_plain_json_alone():
    assert llm.strip_json_fences(json.dumps({"a": 1})) == '{"a": 1}'
