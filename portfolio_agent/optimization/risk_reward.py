"""Reward:risk filtering (any BUY/ADD below the profile's minimum ratio gets
downgraded to HOLD) and bounded, conviction-scaled position sizing.
"""

from __future__ import annotations

from portfolio_agent.models import Action, RiskProfile, StopTakeLevels


def reward_risk_ratio(stop_take: StopTakeLevels, current_price: float) -> float | None:
    if not stop_take.stop_loss or not stop_take.take_profit or current_price <= 0:
        return None
    risk = current_price - stop_take.stop_loss
    reward = stop_take.take_profit - current_price
    if risk <= 0:
        return None
    return reward / risk


def apply_reward_risk_filter(
    action: Action,
    ratio: float | None,
    min_ratio: float,
) -> Action:
    if action in (Action.BUY, Action.ADD) and (ratio is None or ratio < min_ratio):
        return Action.HOLD
    return action


def suggested_dollar_delta(
    action: Action,
    conviction: float,
    total_portfolio_value: float,
    current_position_value: float,
    risk_profile: RiskProfile,
) -> float | None:
    if action not in (Action.BUY, Action.ADD, Action.TRIM, Action.SELL):
        return None

    max_position_value = risk_profile.max_position_pct * total_portfolio_value

    if action in (Action.BUY, Action.ADD):
        headroom = max(0.0, max_position_value - current_position_value)
        raw = conviction * total_portfolio_value * 0.05
        return round(min(headroom, raw), 2)

    if action == Action.SELL:
        return round(-current_position_value, 2)

    if action == Action.TRIM:
        trim_amount = conviction * current_position_value * 0.5
        return round(-min(trim_amount, current_position_value), 2)

    return None
