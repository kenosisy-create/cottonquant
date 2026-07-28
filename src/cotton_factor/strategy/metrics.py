"""Shared strategy-level performance metrics."""

from __future__ import annotations

import math

import pandas as pd


def strategy_metrics(
    frame: pd.DataFrame,
    *,
    capital_base: float,
    starting_nav: float | None = None,
) -> dict[str, float | int]:
    """Calculate deterministic post-cost metrics from one scenario equity curve."""
    if frame.empty:
        return _empty_metrics()
    ordered = frame.sort_values("execution_date").reset_index(drop=True)
    nav = ordered["nav"].astype(float)
    base_nav = float(starting_nav if starting_nav is not None else capital_base)
    returns = nav.pct_change()
    returns.iloc[0] = nav.iloc[0] / base_nav - 1.0
    count = len(ordered)
    final_nav = float(nav.iloc[-1])
    cumulative_return = final_nav / base_nav - 1.0
    annualized_return = (
        (final_nav / base_nav) ** (252.0 / count) - 1.0
        if final_nav > 0 and count > 0
        else -1.0
    )
    annualized_volatility = float(returns.std(ddof=1) * math.sqrt(252)) if count > 1 else 0.0
    sharpe = (
        float(returns.mean() / returns.std(ddof=1) * math.sqrt(252))
        if count > 1 and float(returns.std(ddof=1)) > 0
        else 0.0
    )
    running_peak = nav.cummax().clip(lower=base_nav)
    drawdown = nav / running_peak - 1.0
    max_drawdown = float(drawdown.min())
    calmar = annualized_return / abs(max_drawdown) if max_drawdown < 0 else 0.0
    active = ordered["held_lots"].astype(float).ne(0)
    active_pnl = ordered.loc[active, "daily_net_pnl"].astype(float)
    daily_win_rate = float(active_pnl.gt(0).mean()) if not active_pnl.empty else 0.0
    completed_trades, average_holding_days = _position_episodes(ordered["held_lots"])
    return {
        "observation_count": count,
        "final_nav": final_nav,
        "cumulative_return": cumulative_return,
        "annualized_return": annualized_return,
        "annualized_volatility": annualized_volatility,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "daily_win_rate": daily_win_rate,
        "active_days": int(active.sum()),
        "active_day_ratio": float(active.mean()),
        "completed_trades": completed_trades,
        "average_holding_days": average_holding_days,
        "turnover_lots": float(ordered["turnover_lots"].abs().sum()),
        "turnover_notional": float(ordered["turnover_notional"].abs().sum()),
        "total_cost": float(ordered["daily_cost"].sum()),
    }


def _position_episodes(held_lots: pd.Series) -> tuple[int, float]:
    completed_lengths: list[int] = []
    current_sign = 0
    current_length = 0
    for value in held_lots.fillna(0).astype(int):
        sign = 1 if value > 0 else -1 if value < 0 else 0
        if current_sign == 0:
            if sign != 0:
                current_sign = sign
                current_length = 1
            continue
        if sign == current_sign:
            current_length += 1
            continue
        completed_lengths.append(current_length)
        current_sign = sign
        current_length = 1 if sign != 0 else 0
    if not completed_lengths:
        return 0, 0.0
    return len(completed_lengths), float(sum(completed_lengths) / len(completed_lengths))


def _empty_metrics() -> dict[str, float | int]:
    return {
        "observation_count": 0,
        "final_nav": 0.0,
        "cumulative_return": 0.0,
        "annualized_return": 0.0,
        "annualized_volatility": 0.0,
        "sharpe": 0.0,
        "max_drawdown": 0.0,
        "calmar": 0.0,
        "daily_win_rate": 0.0,
        "active_days": 0,
        "active_day_ratio": 0.0,
        "completed_trades": 0,
        "average_holding_days": 0.0,
        "turnover_lots": 0.0,
        "turnover_notional": 0.0,
        "total_cost": 0.0,
    }
