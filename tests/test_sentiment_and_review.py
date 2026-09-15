import json
from datetime import UTC, datetime
from unittest.mock import patch

from portfolio_agent.analysis.sentiment import (
    _parse_sentiment_response,
    build_sentiment_signals,
    fetch_headlines_for_tickers,
)
from portfolio_agent.models import (
    Action,
    AnalysisResult,
    AnalystSignal,
    Bucket,
    MarketContextSignal,
    Recommendation,
    SentimentSignal,
    StopTakeLevels,
    TechnicalSignal,
)
from portfolio_agent.review.reviewer import review_candidates, review_recommendations


class _FakeNewsProvider:
    def __init__(self, headlines_by_ticker):
        self._headlines = headlines_by_ticker

    @property
    def available(self):
        return True

    def get_headlines(self, query, limit=15):
        return self._headlines.get(query, [])


def test_fetch_headlines_skips_tickers_with_none():
    provider = _FakeNewsProvider({"AAPL": [{"title": "Apple beats earnings"}]})
    result = fetch_headlines_for_tickers(["AAPL", "MSFT"], provider)
    assert "AAPL" in result
    assert "MSFT" not in result


def test_fetch_headlines_returns_empty_when_provider_unavailable():
    class Unavailable(_FakeNewsProvider):
        @property
        def available(self):
            return False

    result = fetch_headlines_for_tickers(["AAPL"], Unavailable({}))
    assert result == {}


def test_parse_sentiment_response_handles_fenced_json():
    raw = '```json\n{"AAPL": {"sentiment_score": 0.5, "geopolitical_risk_score": 0.1, "summary": "Positive"}}\n```'
    parsed = _parse_sentiment_response(raw)
    assert parsed["AAPL"]["sentiment_score"] == 0.5


def test_build_sentiment_signals_neutral_when_no_headlines():
    class Settings:
        llm_provider = "gemini"
        gemini_api_key = "x"
        gemini_model = "m"

    signals = build_sentiment_signals(["AAPL"], _FakeNewsProvider({}), Settings())
    assert signals["AAPL"].degraded is True


def test_build_sentiment_signals_applies_mocked_llm_response():
    class Settings:
        llm_provider = "gemini"
        gemini_api_key = "x"
        gemini_model = "m"

    provider = _FakeNewsProvider({"AAPL": [{"title": "Apple beats earnings"}]})
    mocked_response = json.dumps(
        {"AAPL": {"sentiment_score": 0.6, "geopolitical_risk_score": 0.0, "summary": "Good quarter"}}
    )
    with patch("portfolio_agent.analysis.sentiment._call_sentiment_api", return_value=mocked_response):
        signals = build_sentiment_signals(["AAPL"], provider, Settings())
    assert signals["AAPL"].degraded is False
    assert signals["AAPL"].sentiment_score == 0.6


def _make_recommendation(ticker="AAPL", action=Action.BUY):
    result = AnalysisResult(
        ticker=ticker, as_of=datetime.now(UTC).date(), current_price=100.0,
        technical=TechnicalSignal(), analyst=AnalystSignal(), sentiment=SentimentSignal(),
        market_context=MarketContextSignal(), stop_take=StopTakeLevels(),
        composite_score=0.6, bucket=Bucket.CONSERVATIVE,
    )
    return Recommendation(
        ticker=ticker, action=action, conviction=0.6, rationale="test rationale",
        stop_take=StopTakeLevels(), related_result=result,
    )


def test_review_recommendations_downgrades_on_downgraded_verdict():
    class Settings:
        llm_provider = "gemini"
        gemini_api_key = "x"
        gemini_model = "m"

    rec = _make_recommendation()
    mocked_response = json.dumps(
        {
            "items": [{"ticker": "AAPL", "outcome": "downgraded", "notes": "Earnings risk", "alternative_ticker": None}],
            "overall_assessment": "Portfolio looks fine overall.",
        }
    )
    with patch("portfolio_agent.review.reviewer._call_review_api", return_value=mocked_response):
        updated, overall = review_recommendations([rec], health=None, warnings=[], settings=Settings())

    assert updated[0].action == Action.HOLD
    assert updated[0].review.outcome == "downgraded"
    assert overall == "Portfolio looks fine overall."


def test_review_recommendations_confirmed_keeps_action():
    class Settings:
        llm_provider = "gemini"
        gemini_api_key = "x"
        gemini_model = "m"

    rec = _make_recommendation(action=Action.SELL)
    mocked_response = json.dumps({"items": [{"ticker": "AAPL", "outcome": "confirmed", "notes": "Agreed"}]})
    with patch("portfolio_agent.review.reviewer._call_review_api", return_value=mocked_response):
        updated, _ = review_recommendations([rec], health=None, warnings=[], settings=Settings())
    assert updated[0].action == Action.SELL


def test_review_recommendations_api_failure_returns_unreviewed():
    class Settings:
        llm_provider = "gemini"
        gemini_api_key = "x"
        gemini_model = "m"

    rec = _make_recommendation()
    with patch("portfolio_agent.review.reviewer._call_review_api", side_effect=RuntimeError("boom")):
        updated, overall = review_recommendations([rec], health=None, warnings=[], settings=Settings())
    assert updated == [rec]
    assert overall is None


def test_review_candidates_parse_failure_returns_unreviewed():
    from portfolio_agent.models import ShortTermCandidate

    class Settings:
        llm_provider = "gemini"
        gemini_api_key = "x"
        gemini_model = "m"

    candidate = ShortTermCandidate(
        ticker="NVDA", setup_score=0.6, entry_zone_low=100, entry_zone_high=105,
        stop_take=StopTakeLevels(), rationale="momentum setup",
    )
    with patch("portfolio_agent.review.reviewer._call_review_api", return_value="not json"):
        result = review_candidates([candidate], [], Settings())
    assert result == [candidate]
