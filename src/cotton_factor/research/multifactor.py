"""Equal-weight multifactor score construction."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from cotton_factor.common.exceptions import FactorError
from cotton_factor.core.schemas import (
    ResearchFactorValueDailyRow,
    ResearchMultifactorScoreDailyRow,
)

DEFAULT_EQUAL_WEIGHT_SCORE_ID = "cf_equal_weight_v1"
DEFAULT_EQUAL_WEIGHT_SCORE_VERSION = "v1"
DEFAULT_EQUAL_WEIGHT_SCORE_RULE_VERSION = "equal_weight_multifactor_v1"
DEFAULT_UNIVERSE = "CF_MAIN"


@dataclass(frozen=True)
class MultifactorScoreBuildResult:
    """Equal-weight score build output."""

    rows: list[ResearchMultifactorScoreDailyRow]
    warnings: list[str]


def build_equal_weight_scores(
    *,
    factor_rows: Sequence[ResearchFactorValueDailyRow],
    run_id: str,
    product_code: str,
    universe: str = DEFAULT_UNIVERSE,
    signal_object_id: str = "CF.C1",
    factor_ids: Sequence[str] | None = None,
    score_id: str = DEFAULT_EQUAL_WEIGHT_SCORE_ID,
    score_version: str = DEFAULT_EQUAL_WEIGHT_SCORE_VERSION,
    score_rule_version: str = DEFAULT_EQUAL_WEIGHT_SCORE_RULE_VERSION,
    use_processed_value: bool = True,
    require_all_factors: bool = True,
) -> MultifactorScoreBuildResult:
    """Build equal-weight daily scores from factor value rows."""
    if not run_id:
        raise FactorError("run_id is required for equal-weight scores")
    product = product_code.upper()
    selected_factor_ids = tuple(sorted(factor_ids or _factor_ids(factor_rows)))
    if not selected_factor_ids:
        raise FactorError("at least one factor_id is required")

    grouped = _factor_rows_by_date(
        factor_rows=factor_rows,
        product_code=product,
        universe=universe,
        signal_object_id=signal_object_id,
        selected_factor_ids=selected_factor_ids,
    )

    rows: list[ResearchMultifactorScoreDailyRow] = []
    warnings: list[str] = []
    for trade_date in sorted(grouped):
        rows_by_factor = grouped[trade_date]
        missing = [
            factor_id for factor_id in selected_factor_ids if factor_id not in rows_by_factor
        ]
        if missing and require_all_factors:
            warnings.append(f"{trade_date}: missing factors {missing}; score skipped")
            continue

        included_rows = [
            rows_by_factor[factor_id]
            for factor_id in selected_factor_ids
            if factor_id in rows_by_factor
        ]
        if not included_rows:
            continue

        values = [
            _factor_value(row=factor_row, use_processed_value=use_processed_value)
            for factor_row in included_rows
        ]
        # D17 等权分数仍然是信号对象层的研究衍生值，不能直接当作真实合约持仓。
        rows.append(
            ResearchMultifactorScoreDailyRow(
                run_id=run_id,
                score_id=score_id,
                score_version=score_version,
                product_code=product,
                universe=universe,
                signal_object_id=signal_object_id,
                trade_date=trade_date,
                raw_score=sum(values) / len(values),
                processed_score=None,
                factor_count=len(included_rows),
                input_factor_ids=[row.factor_id for row in included_rows],
                score_rule_version=score_rule_version,
                input_snapshot_ids=_unique_snapshot_ids(
                    *(row.input_snapshot_ids for row in included_rows)
                ),
            )
        )

    if not rows:
        warnings.append("equal-weight score produced no rows")
    return MultifactorScoreBuildResult(rows=rows, warnings=_unique_warnings(warnings))


def _factor_ids(factor_rows: Sequence[ResearchFactorValueDailyRow]) -> list[str]:
    values: list[str] = []
    for row in factor_rows:
        if row.factor_id not in values:
            values.append(row.factor_id)
    return values


def _factor_rows_by_date(
    *,
    factor_rows: Sequence[ResearchFactorValueDailyRow],
    product_code: str,
    universe: str,
    signal_object_id: str,
    selected_factor_ids: Sequence[str],
) -> dict[date, dict[str, ResearchFactorValueDailyRow]]:
    grouped: dict[date, dict[str, ResearchFactorValueDailyRow]] = {}
    duplicates: list[tuple[date, str]] = []
    selected = set(selected_factor_ids)
    for row in factor_rows:
        if row.product_code != product_code or row.universe != universe:
            continue
        if row.signal_object_id != signal_object_id or row.factor_id not in selected:
            continue
        rows_by_factor = grouped.setdefault(row.trade_date, {})
        if row.factor_id in rows_by_factor:
            duplicates.append((row.trade_date, row.factor_id))
        rows_by_factor[row.factor_id] = row

    if duplicates:
        raise FactorError(f"duplicate factor rows for {duplicates}")
    if not grouped:
        raise FactorError("no factor rows found for equal-weight score")
    return grouped


def _factor_value(*, row: ResearchFactorValueDailyRow, use_processed_value: bool) -> float:
    value = (
        row.processed_value
        if use_processed_value and row.processed_value is not None
        else row.raw_value
    )
    return float(value)


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
