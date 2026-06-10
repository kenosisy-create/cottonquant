"""Momentum factor implementation."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from cotton_factor.common.exceptions import FactorError
from cotton_factor.core.schemas import ResearchContinuousPriceDailyRow
from cotton_factor.research.factor_base import (
    FactorDefinition,
    FactorInputBundle,
    FactorObservation,
    FactorResult,
    build_factor_rows,
    load_factor_registry,
    validate_factor_dependencies,
)

MOMENTUM_FACTOR_ID = "mom_20_v1"
DEFAULT_MOMENTUM_LOOKBACK_PERIODS = 20
DEFAULT_SIGNAL_OBJECT_ID = "CF.C1"
DEFAULT_UNIVERSE = "CF_MAIN"


def compute_momentum_factor(
    *,
    inputs: FactorInputBundle,
    run_id: str,
    product_code: str,
    universe: str = DEFAULT_UNIVERSE,
    signal_object_id: str = DEFAULT_SIGNAL_OBJECT_ID,
    price_field: str = "settle",
    lookback_periods: int = DEFAULT_MOMENTUM_LOOKBACK_PERIODS,
    definition: FactorDefinition | None = None,
) -> FactorResult:
    """Compute T-day momentum from adjusted continuous prices."""
    if lookback_periods <= 0:
        raise FactorError("lookback_periods must be > 0")

    factor_definition = definition or load_factor_registry().get(MOMENTUM_FACTOR_ID)
    validate_factor_dependencies(factor_definition, inputs)

    rows = cast(
        Sequence[ResearchContinuousPriceDailyRow],
        inputs.rows("research_continuous_price_daily"),
    )
    selected_rows = _selected_price_rows(
        rows=rows,
        product_code=product_code,
        signal_object_id=signal_object_id,
        price_field=price_field,
    )

    warnings: list[str] = []
    if len(selected_rows) <= lookback_periods:
        warnings.append(
            f"{factor_definition.factor_id}: need more than {lookback_periods} rows; "
            f"got {len(selected_rows)}"
        )

    observations: list[FactorObservation] = []
    for index in range(lookback_periods, len(selected_rows)):
        previous = selected_rows[index - lookback_periods]
        current = selected_rows[index]
        if previous.adjusted_price <= 0:
            raise FactorError(
                f"{current.trade_date}: previous adjusted price must be > 0 for momentum"
            )

        # 动量只使用当前 T 日和过去 lookback 日的连续价格，不能读取 T+1 或更晚数据。
        observations.append(
            FactorObservation(
                signal_object_id=current.signal_object_id,
                trade_date=current.trade_date,
                raw_value=current.adjusted_price / previous.adjusted_price - 1,
                processed_value=None,
                input_snapshot_ids=_unique_snapshot_ids(
                    previous.input_snapshot_ids,
                    current.input_snapshot_ids,
                ),
            )
        )

    return FactorResult(
        definition=factor_definition,
        rows=build_factor_rows(
            definition=factor_definition,
            run_id=run_id,
            product_code=product_code,
            universe=universe,
            observations=observations,
        ),
        warnings=warnings,
    )


def _selected_price_rows(
    *,
    rows: Sequence[ResearchContinuousPriceDailyRow],
    product_code: str,
    signal_object_id: str,
    price_field: str,
) -> list[ResearchContinuousPriceDailyRow]:
    product = product_code.upper()
    selected = [
        row
        for row in rows
        if row.product_code == product
        and row.signal_object_id == signal_object_id
        and row.price_field == price_field
    ]
    selected.sort(key=lambda row: row.trade_date)

    seen_dates: set[object] = set()
    duplicate_dates: list[object] = []
    for row in selected:
        if row.trade_date in seen_dates:
            duplicate_dates.append(row.trade_date)
        seen_dates.add(row.trade_date)
    if duplicate_dates:
        raise FactorError(f"duplicate continuous price rows for dates {duplicate_dates}")
    return selected


def _unique_snapshot_ids(*snapshot_groups: Sequence[str]) -> tuple[str, ...]:
    values: list[str] = []
    for group in snapshot_groups:
        for snapshot_id in group:
            if snapshot_id not in values:
                values.append(snapshot_id)
    return tuple(values)
