import pandas as pd

from portfolio_agent.models import Bucket, RiskProfile
from portfolio_agent.optimization.new_ideas import (
    compute_idea_score,
    identify_gaps,
    suggested_allocation_pct,
)
from portfolio_agent.screening.short_term import compute_setup_score
from portfolio_agent.screening.universe import load_universe


def _uptrend_df(n=60):
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = pd.Series([100 + i * 0.6 for i in range(n)], index=idx)
    volume = pd.Series([1_000_000] * (n - 1) + [3_000_000], index=idx)
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": volume})


def test_load_universe():
    entries = load_universe("data/sp500_constituents.csv")
    assert len(entries) > 20
    assert any(e.ticker == "AAPL" for e in entries)


def test_setup_score_positive_for_uptrend_with_volume_spike():
    score = compute_setup_score(_uptrend_df())
    assert score > 0.3


def test_setup_score_zero_for_too_short_series():
    df = _uptrend_df(n=10)
    assert compute_setup_score(df) == 0.0


def test_identify_gaps_flags_underweight_bucket_and_sectors():
    profile = RiskProfile(target_conservative_pct=0.6, target_aggressive_pct=0.4)
    bucket_pcts = {Bucket.CONSERVATIVE.value: 0.95, Bucket.AGGRESSIVE.value: 0.05}
    sector_pcts = {"Technology": 0.9}
    gaps, target_sectors = identify_gaps(bucket_pcts, sector_pcts, profile)
    assert any("Aggressive" in g for g in gaps)
    assert "Healthcare" in target_sectors


def test_compute_idea_score_averages_when_analyst_present():
    assert compute_idea_score(0.6, 0.2) == 0.4


def test_compute_idea_score_falls_back_to_technical_only():
    assert compute_idea_score(0.6, None) == 0.6


def test_suggested_allocation_pct_bounded_by_max_position():
    profile = RiskProfile(max_position_pct=0.1)
    assert suggested_allocation_pct(1.0, profile) == 0.1
