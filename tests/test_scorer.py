from portfolio_agent.analysis.scorer import composite_score, to_action
from portfolio_agent.models import (
    Action,
    AnalystSignal,
    MarketContextSignal,
    SentimentSignal,
    TechnicalSignal,
)


def _neutral_signals():
    return (
        TechnicalSignal(trend_score=0.0),
        AnalystSignal(),
        SentimentSignal(degraded=True),
        MarketContextSignal(),
    )


def test_all_positive_signals_yield_buy():
    tech = TechnicalSignal(trend_score=0.8)
    analyst = AnalystSignal(mean_rating=1.5, price_target_upside_pct=0.15, analyst_score=0.7)
    sentiment = SentimentSignal(sentiment_score=0.5, degraded=False, headline_count=3)
    market = MarketContextSignal(relative_strength_63d=0.1)
    score = composite_score(tech, analyst, sentiment, market)
    assert score > 0.5
    assert to_action(score, holding_exists=False) == Action.BUY
    assert to_action(score, holding_exists=True) == Action.ADD


def test_all_negative_signals_yield_sell():
    tech = TechnicalSignal(trend_score=-0.8)
    analyst = AnalystSignal(mean_rating=4.5, price_target_upside_pct=-0.2, analyst_score=-0.7)
    sentiment = SentimentSignal(sentiment_score=-0.5, degraded=False, headline_count=3)
    market = MarketContextSignal(relative_strength_63d=-0.1)
    score = composite_score(tech, analyst, sentiment, market)
    assert score < -0.5
    assert to_action(score, holding_exists=True) == Action.SELL


def test_neutral_signals_yield_hold():
    tech, analyst, sentiment, market = _neutral_signals()
    score = composite_score(tech, analyst, sentiment, market)
    assert to_action(score, holding_exists=True) == Action.HOLD


def test_missing_analyst_data_does_not_crash_and_renormalizes():
    tech = TechnicalSignal(trend_score=0.6)
    analyst = AnalystSignal()  # no mean_rating, no upside -> excluded from weighting
    sentiment = SentimentSignal(degraded=True)
    market = MarketContextSignal(relative_strength_63d=0.05)
    score = composite_score(tech, analyst, sentiment, market)
    assert -1.0 <= score <= 1.0
