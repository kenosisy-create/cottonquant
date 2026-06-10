"""Single factor evaluator for research diagnostics."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from cotton_factor.common.exceptions import FactorEvaluationError
from cotton_factor.core.schemas import (
    ResearchFactorEvaluationRow,
    ResearchFactorValueDailyRow,
    ResearchForwardReturnDailyRow,
)
from cotton_factor.research.preprocessing import rank_series

DEFAULT_EVALUATION_RULE_VERSION = "single_factor_eval_v1"
DEFAULT_UNIVERSE = "CF_MAIN"


@dataclass(frozen=True)
class SingleFactorEvaluationResult:
    """Single factor evaluation output."""

    rows: list[ResearchFactorEvaluationRow]
    joined_observation_count: int
    warnings: list[str]


@dataclass(frozen=True)
class _JoinedObservation:
    factor_value: float
    forward_return: float
    input_snapshot_ids: tuple[str, ...]


def evaluate_single_factor(
    *,
    factor_rows: Sequence[ResearchFactorValueDailyRow],
    forward_returns: Sequence[ResearchForwardReturnDailyRow],
    run_id: str,
    factor_id: str,
    product_code: str,
    universe: str = DEFAULT_UNIVERSE,
    horizon: int = 1,
    use_processed_value: bool = True,
    evaluation_rule_version: str = DEFAULT_EVALUATION_RULE_VERSION,
) -> SingleFactorEvaluationResult:
    """Evaluate one factor against forward returns."""
    if horizon <= 0:
        raise FactorEvaluationError("horizon must be >= 1")

    product = product_code.upper()
    selected_factors = _selected_factor_rows(
        factor_rows=factor_rows,
        factor_id=factor_id,
        product_code=product,
        universe=universe,
    )
    selected_returns = _selected_forward_returns(
        forward_returns=forward_returns,
        product_code=product,
        universe=universe,
        horizon=horizon,
    )

    warnings: list[str] = []
    joined = _join_observations(
        factor_rows=selected_factors,
        forward_returns=selected_returns,
        use_processed_value=use_processed_value,
    )
    if not joined:
        return SingleFactorEvaluationResult(
            rows=[],
            joined_observation_count=0,
            warnings=["single factor evaluation joined no observations"],
        )

    factor_version = selected_factors[0].factor_version
    metric_inputs = _unique_snapshot_ids(
        *(observation.input_snapshot_ids for observation in joined)
    )

    metric_values = _metric_values(joined=joined, warnings=warnings)
    rows = [
        _evaluation_row(
            run_id=run_id,
            factor_id=factor_id,
            factor_version=factor_version,
            product_code=product,
            universe=universe,
            horizon=horizon,
            metric_name=metric_name,
            metric_value=metric_value,
            observation_count=len(joined),
            evaluation_rule_version=evaluation_rule_version,
            input_snapshot_ids=metric_inputs,
        )
        for metric_name, metric_value in metric_values
    ]

    # D14 评估器只做研究诊断，不生成订单、不改变 D9 trade mapping 的真实合约执行边界。
    return SingleFactorEvaluationResult(
        rows=rows,
        joined_observation_count=len(joined),
        warnings=_unique_warnings(warnings),
    )


def _selected_factor_rows(
    *,
    factor_rows: Sequence[ResearchFactorValueDailyRow],
    factor_id: str,
    product_code: str,
    universe: str,
) -> list[ResearchFactorValueDailyRow]:
    selected = [
        row
        for row in factor_rows
        if row.factor_id == factor_id
        and row.product_code == product_code
        and row.universe == universe
    ]
    if not selected:
        raise FactorEvaluationError(f"no factor rows found for {factor_id}")
    versions = {row.factor_version for row in selected}
    if len(versions) > 1:
        raise FactorEvaluationError(f"{factor_id}: mixed factor versions {sorted(versions)}")
    _reject_duplicate_keys(
        keys=[(row.signal_object_id, row.trade_date) for row in selected],
        label="factor rows",
    )
    return sorted(selected, key=lambda row: (row.signal_object_id, row.trade_date))


def _selected_forward_returns(
    *,
    forward_returns: Sequence[ResearchForwardReturnDailyRow],
    product_code: str,
    universe: str,
    horizon: int,
) -> list[ResearchForwardReturnDailyRow]:
    selected = [
        row
        for row in forward_returns
        if row.product_code == product_code and row.universe == universe and row.horizon == horizon
    ]
    if not selected:
        raise FactorEvaluationError(f"no forward returns found for horizon {horizon}")
    _reject_duplicate_keys(
        keys=[(row.signal_object_id, row.trade_date) for row in selected],
        label="forward returns",
    )
    return sorted(selected, key=lambda row: (row.signal_object_id, row.trade_date))


def _join_observations(
    *,
    factor_rows: Sequence[ResearchFactorValueDailyRow],
    forward_returns: Sequence[ResearchForwardReturnDailyRow],
    use_processed_value: bool,
) -> list[_JoinedObservation]:
    return_by_key = {
        (row.signal_object_id, row.trade_date): row for row in forward_returns
    }

    joined: list[_JoinedObservation] = []
    for factor_row in factor_rows:
        return_row = return_by_key.get((factor_row.signal_object_id, factor_row.trade_date))
        if return_row is None:
            continue
        factor_value = (
            factor_row.processed_value
            if use_processed_value and factor_row.processed_value is not None
            else factor_row.raw_value
        )
        _validate_finite(factor_value, label="factor_value")
        _validate_finite(return_row.forward_return, label="forward_return")
        joined.append(
            _JoinedObservation(
                factor_value=float(factor_value),
                forward_return=float(return_row.forward_return),
                input_snapshot_ids=tuple(
                    _unique_snapshot_ids(
                        factor_row.input_snapshot_ids,
                        return_row.input_snapshot_ids,
                    )
                ),
            )
        )
    return joined


def _metric_values(
    *,
    joined: Sequence[_JoinedObservation],
    warnings: list[str],
) -> list[tuple[str, float]]:
    factor_values = [observation.factor_value for observation in joined]
    forward_returns = [observation.forward_return for observation in joined]
    values: list[tuple[str, float]] = [
        ("observation_count", float(len(joined))),
        ("mean_factor_value", _mean(factor_values)),
        ("mean_forward_return", _mean(forward_returns)),
    ]

    pearson = _correlation(factor_values, forward_returns)
    if pearson is None:
        warnings.append("pearson_ic is not computable because one series is constant")
    else:
        values.append(("pearson_ic", pearson))

    rank_ic = _correlation(rank_series(factor_values), rank_series(forward_returns))
    if rank_ic is None:
        warnings.append("spearman_rank_ic is not computable because one rank series is constant")
    else:
        values.append(("spearman_rank_ic", rank_ic))

    directional_accuracy = _directional_accuracy(factor_values, forward_returns)
    if directional_accuracy is None:
        warnings.append("directional_accuracy has no non-zero sign pairs")
    else:
        values.append(("directional_accuracy", directional_accuracy))
    return values


def _evaluation_row(
    *,
    run_id: str,
    factor_id: str,
    factor_version: str,
    product_code: str,
    universe: str,
    horizon: int,
    metric_name: str,
    metric_value: float,
    observation_count: int,
    evaluation_rule_version: str,
    input_snapshot_ids: Sequence[str],
) -> ResearchFactorEvaluationRow:
    return ResearchFactorEvaluationRow(
        run_id=run_id,
        factor_id=factor_id,
        factor_version=factor_version,
        product_code=product_code,
        universe=universe,
        horizon=horizon,
        metric_name=metric_name,
        metric_value=metric_value,
        observation_count=observation_count,
        evaluation_rule_version=evaluation_rule_version,
        input_snapshot_ids=list(input_snapshot_ids),
    )


def _correlation(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right):
        raise FactorEvaluationError("correlation inputs must have same length")
    if len(left) < 2:
        return None
    left_mean = _mean(left)
    right_mean = _mean(right)
    left_centered = [value - left_mean for value in left]
    right_centered = [value - right_mean for value in right]
    numerator = sum(
        left_value * right_value
        for left_value, right_value in zip(left_centered, right_centered, strict=True)
    )
    left_ss = sum(value * value for value in left_centered)
    right_ss = sum(value * value for value in right_centered)
    denominator = math.sqrt(left_ss * right_ss)
    if denominator == 0:
        return None
    return numerator / denominator


def _directional_accuracy(left: Sequence[float], right: Sequence[float]) -> float | None:
    pairs = [
        (_sign(left_value), _sign(right_value))
        for left_value, right_value in zip(left, right, strict=True)
        if _sign(left_value) != 0 and _sign(right_value) != 0
    ]
    if not pairs:
        return None
    hits = sum(1 for left_sign, right_sign in pairs if left_sign == right_sign)
    return hits / len(pairs)


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise FactorEvaluationError("mean requires at least one value")
    return sum(values) / len(values)


def _validate_finite(value: float, *, label: str) -> None:
    if not math.isfinite(value):
        raise FactorEvaluationError(f"{label} must be finite")


def _reject_duplicate_keys(*, keys: Sequence[tuple[object, object]], label: str) -> None:
    seen: set[tuple[object, object]] = set()
    duplicates: list[tuple[object, object]] = []
    for key in keys:
        if key in seen:
            duplicates.append(key)
        seen.add(key)
    if duplicates:
        raise FactorEvaluationError(f"duplicate {label} for keys {duplicates}")


def _unique_snapshot_ids(*snapshot_groups: Sequence[str]) -> list[str]:
    values: list[str] = []
    for group in snapshot_groups:
        for snapshot_id in group:
            if snapshot_id not in values:
                values.append(snapshot_id)
    return values


def _unique_warnings(warnings: Sequence[str]) -> list[str]:
    values: list[str] = []
    for warning in warnings:
        if warning not in values:
            values.append(warning)
    return values
