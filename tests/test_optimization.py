import pandas as pd

from portfolio_agent.models import Action, Bucket, RiskProfile, StopTakeLevels
from portfolio_agent.optimization.allocation import (
    ValuedHolding,
    bucket_rebalance_suggestions,
    compute_bucket_allocation,
    sector_concentration_suggestions,
)
from portfolio_agent.optimization.classify import classify_bucket
from portfolio_agent.optimization.risk_metrics import (
    build_portfolio_value_series,
    max_drawdown_pct,
    sharpe_ratio,
)
from portfolio_agent.optimization.risk_reward import (
    apply_reward_risk_filter,
    reward_risk_ratio,
    suggested_dollar_delta,
)


def test_classify_high_vol_high_beta_small_cap_is_aggressive():
    assert classify_bucket(0.5, 1.5, 5_000_000_000) == Bucket.AGGRESSIVE


def test_classify_low_vol_low_beta_large_cap_is_conservative():
    assert classify_bucket(0.15, 0.6, 500_000_000_000) == Bucket.CONSERVATIVE


def test_classify_no_data_is_unclassified():
    assert classify_bucket(None, None, None) == Bucket.UNCLASSIFIED


def test_bucket_allocation_sums_to_one():
    holdings = [
        ValuedHolding("A", 600.0, Bucket.CONSERVATIVE, "Tech"),
        ValuedHolding("B", 400.0, Bucket.AGGRESSIVE, "Tech"),
    ]
    alloc = compute_bucket_allocation(holdings)
    assert abs(sum(alloc.values()) - 1.0) < 1e-9
    assert alloc["conservative"] == 0.6


def test_bucket_rebalance_flags_drift_over_threshold():
    suggestions = bucket_rebalance_suggestions(
        {"conservative": 0.9, "aggressive": 0.1}, 0.6, 0.4, 0.05
    )
    assert len(suggestions) == 2
    assert any(s.label == "conservative" and s.drift_pct > 0 for s in suggestions)


def test_bucket_rebalance_no_flag_within_threshold():
    suggestions = bucket_rebalance_suggestions(
        {"conservative": 0.61, "aggressive": 0.39}, 0.6, 0.4, 0.05
    )
    assert suggestions == []


def test_sector_concentration_flags_over_cap():
    sector_pcts = {"Technology": 0.5, "Healthcare": 0.5}
    suggestions = sector_concentration_suggestions(sector_pcts, 0.25)
    assert len(suggestions) == 2


def test_reward_risk_ratio_basic():
    st = StopTakeLevels(stop_loss=90.0, take_profit=120.0)
    ratio = reward_risk_ratio(st, 100.0)
    assert ratio == 2.0


def test_reward_risk_ratio_none_without_levels():
    assert reward_risk_ratio(StopTakeLevels(), 100.0) is None


def test_apply_reward_risk_filter_downgrades_low_ratio_buy():
    result = apply_reward_risk_filter(Action.BUY, 1.0, min_ratio=1.5)
    assert result == Action.HOLD


def test_apply_reward_risk_filter_keeps_high_ratio_buy():
    result = apply_reward_risk_filter(Action.BUY, 2.0, min_ratio=1.5)
    assert result == Action.BUY


def test_suggested_dollar_delta_bounded_by_max_position():
    profile = RiskProfile(max_position_pct=0.1)
    delta = suggested_dollar_delta(Action.ADD, conviction=1.0, total_portfolio_value=100_000,
                                    current_position_value=9_900, risk_profile=profile)
    assert delta is not None and delta <= 100.0 + 1e-6


def test_portfolio_value_series_and_metrics():
    idx = pd.date_range("2024-01-01", periods=100, freq="B")
    prices_a = pd.Series([100 + i * 0.1 for i in range(100)], index=idx)
    prices_b = pd.Series([50 - i * 0.05 for i in range(100)], index=idx)
    series = build_portfolio_value_series({"A": prices_a, "B": prices_b}, {"A": 10, "B": 20})
    assert len(series) == 100
    sr = sharpe_ratio(series)
    dd = max_drawdown_pct(series)
    assert dd is not None and dd <= 0
    assert sr is None or isinstance(sr, float)
