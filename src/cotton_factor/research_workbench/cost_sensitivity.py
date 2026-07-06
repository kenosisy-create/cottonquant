"""R18 research-mode CF cost sensitivity summaries."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.core.schemas import (
    ResearchForwardReturnDailyRow,
    ResearchMultifactorScoreDailyRow,
)
from cotton_factor.research_workbench.config import load_research_mode_config
from cotton_factor.research_workbench.forward_returns import RETURNS_OUTPUT_DIR
from cotton_factor.research_workbench.multifactor_diagnostics import MULTIFACTOR_OUTPUT_DIR

PRODUCT_CODE = "CF"
UNIVERSE = "CF_MAIN"
COST_SENSITIVITY_OUTPUT_DIR = "cost_sensitivity"
COST_SENSITIVITY_RULE_VERSION = "cost_sensitivity_round_turn_bps_v1"
WARNING_SEVERITY = "WARN"
DEFAULT_SCENARIO_COST_BPS = {
    "no_cost": 0.0,
    "normal_cost": 5.0,
    "conservative_cost": 10.0,
}
COST_SENSITIVITY_HUMAN_REVIEW_FIELDS = (
    "cost_scenario_bps",
    "round_turn_cost_definition",
    "score_direction_to_position_mapping",
)

SUMMARY_COLUMNS = [
    "run_id",
    "scenario_id",
    "product_code",
    "universe",
    "signal_object_id",
    "horizon",
    "observation_count",
    "signal_count",
    "long_count",
    "short_count",
    "flat_count",
    "round_turn_cost_bps",
    "gross_mean_return",
    "net_mean_return",
    "gross_hit_rate",
    "net_hit_rate",
    "average_abs_score",
    "sensitivity_rule_version",
    "input_snapshot_ids",
]

WARNING_COLUMNS = [
    "run_id",
    "scenario_id",
    "horizon",
    "severity",
    "warning_code",
    "warning_message",
    "human_review_required",
    "input_snapshot_ids",
]


@dataclass(frozen=True)
class CostSensitivitySummaryRow:
    """One R18 cost-sensitivity summary row."""

    run_id: str
    scenario_id: str
    product_code: str
    universe: str
    signal_object_id: str
    horizon: int
    observation_count: int
    signal_count: int
    long_count: int
    short_count: int
    flat_count: int
    round_turn_cost_bps: float
    gross_mean_return: float
    net_mean_return: float
    gross_hit_rate: float
    net_hit_rate: float
    average_abs_score: float
    sensitivity_rule_version: str
    input_snapshot_ids: tuple[str, ...]

    def to_record(self) -> dict[str, object]:
        """Return a table-safe summary record."""
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "product_code": self.product_code,
            "universe": self.universe,
            "signal_object_id": self.signal_object_id,
            "horizon": self.horizon,
            "observation_count": self.observation_count,
            "signal_count": self.signal_count,
            "long_count": self.long_count,
            "short_count": self.short_count,
            "flat_count": self.flat_count,
            "round_turn_cost_bps": self.round_turn_cost_bps,
            "gross_mean_return": self.gross_mean_return,
            "net_mean_return": self.net_mean_return,
            "gross_hit_rate": self.gross_hit_rate,
            "net_hit_rate": self.net_hit_rate,
            "average_abs_score": self.average_abs_score,
            "sensitivity_rule_version": self.sensitivity_rule_version,
            "input_snapshot_ids": ";".join(self.input_snapshot_ids),
        }


@dataclass(frozen=True)
class CostSensitivityWarningRecord:
    """Warning row for R18 cost sensitivity summaries."""

    run_id: str
    scenario_id: str
    horizon: int
    severity: str
    warning_code: str
    warning_message: str
    human_review_required: tuple[str, ...]
    input_snapshot_ids: tuple[str, ...]

    def to_csv_row(self) -> dict[str, str]:
        """Return a CSV-safe warning row."""
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "horizon": str(self.horizon),
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "human_review_required": ";".join(self.human_review_required),
            "input_snapshot_ids": ";".join(self.input_snapshot_ids),
        }


@dataclass(frozen=True)
class ResearchCostSensitivityResult:
    """Result of building R18 cost sensitivity summaries."""

    product_code: str
    run_id: str
    start: date
    end: date
    scenario_cost_bps: dict[str, float]
    horizons: tuple[int, ...]
    rows: tuple[CostSensitivitySummaryRow, ...]
    warning_records: tuple[CostSensitivityWarningRecord, ...]
    summary_parquet_path: Path
    summary_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    score_path: Path
    forward_return_path: Path
    human_review_required: tuple[str, ...]

    @property
    def row_count_by_scenario(self) -> dict[str, int]:
        """Return summary row count by scenario."""
        counts = {scenario_id: 0 for scenario_id in self.scenario_cost_bps}
        for row in self.rows:
            counts[row.scenario_id] = counts.get(row.scenario_id, 0) + 1
        return counts

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable CLI summary."""
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "scenario_cost_bps": self.scenario_cost_bps,
            "horizons": list(self.horizons),
            "row_count": len(self.rows),
            "row_count_by_scenario": self.row_count_by_scenario,
            "warning_count": len(self.warning_records),
            "summary_parquet_path": str(self.summary_parquet_path),
            "summary_csv_path": str(self.summary_csv_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "score_path": str(self.score_path),
            "forward_return_path": str(self.forward_return_path),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_cost_sensitivity(
    *,
    start: date,
    end: date,
    horizons: tuple[int, ...] = (1, 3, 5),
    score_path: Path | None = None,
    forward_return_path: Path | None = None,
    scenario_cost_bps: dict[str, float] | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    use_processed_score: bool = True,
) -> ResearchCostSensitivityResult:
    """Build R18 cost sensitivity summaries from R17 scores and R15 labels."""
    if start > end:
        raise ResearchWorkbenchError("start must be <= end")
    normalized_horizons = _normalize_horizons(horizons)
    normalized_scenarios = _normalize_scenarios(scenario_cost_bps)
    cost_run_id = run_id or _default_run_id(start=start, end=end)

    score_input_path = score_path or _default_score_path(start=start, end=end)
    forward_input_path = forward_return_path or _default_forward_return_path(
        start=start,
        end=end,
    )
    score_rows = _load_score_rows(input_path=score_input_path, start=start, end=end)
    forward_rows = _load_forward_return_rows(
        input_path=forward_input_path,
        start=start,
        end=end,
        horizons=normalized_horizons,
    )

    joined = _join_scores_and_returns(
        score_rows=score_rows,
        forward_rows=forward_rows,
        use_processed_score=use_processed_score,
    )
    warnings = _scenario_review_warnings(
        run_id=cost_run_id,
        scenario_cost_bps=normalized_scenarios,
        input_snapshot_ids=_snapshot_ids_from_joined(joined),
    )
    if not joined:
        warnings.append(
            _warning_record(
                run_id=cost_run_id,
                scenario_id="ALL",
                horizon=0,
                warning_code="COST_SENSITIVITY_JOINED_NO_OBSERVATIONS",
                warning_message="R17 scores and R15 forward returns have no overlapping dates",
                input_snapshot_ids=_merge_snapshot_ids(
                    _snapshot_ids_from_scores(score_rows),
                    _snapshot_ids_from_forward_returns(forward_rows),
                ),
            )
        )

    # R18 成本敏感性只比较研究假设，不替代真实手续费/滑点/冲击成本模型。
    rows = _build_summary_rows(
        run_id=cost_run_id,
        joined=joined,
        scenario_cost_bps=normalized_scenarios,
        horizons=normalized_horizons,
    )
    paths = _output_paths(start=start, end=end, output_dir=output_dir)
    markdown_path = _markdown_path(start=start, end=end, report_output_dir=report_output_dir)
    rows_tuple = tuple(
        sorted(rows, key=lambda row: (row.scenario_id, row.horizon, row.signal_object_id))
    )
    _write_summary_table(
        rows=rows_tuple,
        parquet_path=paths["summary_parquet"],
        csv_path=paths["summary_csv"],
    )
    _write_warning_csv(warnings=tuple(warnings), csv_path=paths["warning_csv"])

    result = ResearchCostSensitivityResult(
        product_code=PRODUCT_CODE,
        run_id=cost_run_id,
        start=start,
        end=end,
        scenario_cost_bps=normalized_scenarios,
        horizons=normalized_horizons,
        rows=rows_tuple,
        warning_records=tuple(warnings),
        summary_parquet_path=paths["summary_parquet"],
        summary_csv_path=paths["summary_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=markdown_path,
        score_path=score_input_path,
        forward_return_path=forward_input_path,
        human_review_required=COST_SENSITIVITY_HUMAN_REVIEW_FIELDS,
    )
    _write_markdown(markdown_path=markdown_path, result=result)
    return result


def _normalize_horizons(horizons: tuple[int, ...]) -> tuple[int, ...]:
    if not horizons:
        raise ResearchWorkbenchError("at least one horizon is required")
    values = tuple(sorted(set(horizons)))
    invalid = [horizon for horizon in values if horizon <= 0]
    if invalid:
        raise ResearchWorkbenchError(f"horizons must be positive integers: {invalid}")
    return values


def _normalize_scenarios(scenario_cost_bps: dict[str, float] | None) -> dict[str, float]:
    raw = scenario_cost_bps or _default_scenarios_from_config()
    normalized: dict[str, float] = {}
    for scenario_id, cost_bps in raw.items():
        scenario = scenario_id.strip()
        if not scenario:
            raise ResearchWorkbenchError("scenario id must not be empty")
        value = float(cost_bps)
        if value < 0:
            raise ResearchWorkbenchError(f"scenario cost bps must be non-negative: {scenario}")
        normalized[scenario] = value
    if not normalized:
        raise ResearchWorkbenchError("at least one cost scenario is required")
    return normalized


def _default_scenarios_from_config() -> dict[str, float]:
    config = load_research_mode_config()
    return {
        scenario_id: DEFAULT_SCENARIO_COST_BPS.get(scenario_id, 0.0)
        for scenario_id in config.cost_scenarios
    }


def _load_score_rows(
    *,
    input_path: Path,
    start: date,
    end: date,
) -> tuple[ResearchMultifactorScoreDailyRow, ...]:
    if not input_path.exists():
        raise ResearchWorkbenchError(f"multifactor score parquet not found: {input_path}")
    frame = pd.read_parquet(input_path)
    if "trade_date" not in frame.columns:
        raise ResearchWorkbenchError(f"multifactor score table missing trade_date: {input_path}")
    selected = _date_slice(frame, start=start, end=end)
    rows: list[ResearchMultifactorScoreDailyRow] = []
    for record in selected.to_dict(orient="records"):
        cleaned = _clean_record(record)
        if str(cleaned.get("product_code", "")).upper() == PRODUCT_CODE:
            rows.append(ResearchMultifactorScoreDailyRow.model_validate(cleaned))
    if not rows:
        raise ResearchWorkbenchError(
            f"no {PRODUCT_CODE} multifactor score rows from {start.isoformat()} to "
            f"{end.isoformat()}"
        )
    return tuple(sorted(rows, key=lambda row: row.trade_date))


def _load_forward_return_rows(
    *,
    input_path: Path,
    start: date,
    end: date,
    horizons: tuple[int, ...],
) -> tuple[ResearchForwardReturnDailyRow, ...]:
    if not input_path.exists():
        raise ResearchWorkbenchError(f"forward return parquet not found: {input_path}")
    frame = pd.read_parquet(input_path)
    if "trade_date" not in frame.columns:
        raise ResearchWorkbenchError(f"forward return table missing trade_date: {input_path}")
    selected = _date_slice(frame, start=start, end=end)
    rows: list[ResearchForwardReturnDailyRow] = []
    for record in selected.to_dict(orient="records"):
        cleaned = _clean_record(record)
        if (
            str(cleaned.get("product_code", "")).upper() == PRODUCT_CODE
            and int(cleaned.get("horizon", 0)) in horizons
        ):
            rows.append(ResearchForwardReturnDailyRow.model_validate(cleaned))
    if not rows:
        raise ResearchWorkbenchError(
            f"no {PRODUCT_CODE} forward return rows from {start.isoformat()} to "
            f"{end.isoformat()}"
        )
    return tuple(sorted(rows, key=lambda row: (row.trade_date, row.horizon)))


@dataclass(frozen=True)
class _JoinedObservation:
    trade_date: date
    signal_object_id: str
    horizon: int
    score: float
    direction: int
    forward_return: float
    input_snapshot_ids: tuple[str, ...]


def _join_scores_and_returns(
    *,
    score_rows: tuple[ResearchMultifactorScoreDailyRow, ...],
    forward_rows: tuple[ResearchForwardReturnDailyRow, ...],
    use_processed_score: bool,
) -> tuple[_JoinedObservation, ...]:
    scores_by_key = {
        (row.trade_date, row.product_code, row.universe, row.signal_object_id): row
        for row in score_rows
    }
    joined: list[_JoinedObservation] = []
    for forward_row in forward_rows:
        score_row = scores_by_key.get(
            (
                forward_row.trade_date,
                forward_row.product_code,
                forward_row.universe,
                forward_row.signal_object_id,
            )
        )
        if score_row is None:
            continue
        score = _score_value(row=score_row, use_processed_score=use_processed_score)
        joined.append(
            _JoinedObservation(
                trade_date=forward_row.trade_date,
                signal_object_id=forward_row.signal_object_id,
                horizon=forward_row.horizon,
                score=score,
                direction=_signal_direction(score),
                forward_return=forward_row.forward_return,
                input_snapshot_ids=_merge_snapshot_ids(
                    tuple(score_row.input_snapshot_ids),
                    tuple(forward_row.input_snapshot_ids),
                ),
            )
        )
    return tuple(sorted(joined, key=lambda row: (row.horizon, row.trade_date)))


def _score_value(*, row: ResearchMultifactorScoreDailyRow, use_processed_score: bool) -> float:
    if use_processed_score and row.processed_score is not None:
        return row.processed_score
    return row.raw_score


def _signal_direction(score: float) -> int:
    if score > 0:
        return 1
    if score < 0:
        return -1
    return 0


def _build_summary_rows(
    *,
    run_id: str,
    joined: tuple[_JoinedObservation, ...],
    scenario_cost_bps: dict[str, float],
    horizons: tuple[int, ...],
) -> list[CostSensitivitySummaryRow]:
    rows: list[CostSensitivitySummaryRow] = []
    signal_objects = sorted({row.signal_object_id for row in joined})
    for scenario_id, cost_bps in scenario_cost_bps.items():
        for horizon in horizons:
            for signal_object_id in signal_objects:
                selected = [
                    row
                    for row in joined
                    if row.horizon == horizon and row.signal_object_id == signal_object_id
                ]
                if not selected:
                    continue
                gross_returns = [row.direction * row.forward_return for row in selected]
                net_returns = [
                    gross_return - _cost_fraction(cost_bps, direction=row.direction)
                    for gross_return, row in zip(gross_returns, selected, strict=True)
                ]
                rows.append(
                    CostSensitivitySummaryRow(
                        run_id=run_id,
                        scenario_id=scenario_id,
                        product_code=PRODUCT_CODE,
                        universe=UNIVERSE,
                        signal_object_id=signal_object_id,
                        horizon=horizon,
                        observation_count=len(selected),
                        signal_count=sum(1 for row in selected if row.direction != 0),
                        long_count=sum(1 for row in selected if row.direction > 0),
                        short_count=sum(1 for row in selected if row.direction < 0),
                        flat_count=sum(1 for row in selected if row.direction == 0),
                        round_turn_cost_bps=cost_bps,
                        gross_mean_return=_mean(gross_returns),
                        net_mean_return=_mean(net_returns),
                        gross_hit_rate=_hit_rate(gross_returns),
                        net_hit_rate=_hit_rate(net_returns),
                        average_abs_score=_mean([abs(row.score) for row in selected]),
                        sensitivity_rule_version=COST_SENSITIVITY_RULE_VERSION,
                        input_snapshot_ids=_snapshot_ids_from_joined(selected),
                    )
                )
    return rows


def _cost_fraction(cost_bps: float, *, direction: int) -> float:
    if direction == 0:
        return 0.0
    return cost_bps / 10_000


def _mean(values: Iterable[float]) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(items) / len(items)


def _hit_rate(values: Iterable[float]) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(1 for value in items if value > 0) / len(items)


def _scenario_review_warnings(
    *,
    run_id: str,
    scenario_cost_bps: dict[str, float],
    input_snapshot_ids: tuple[str, ...],
) -> list[CostSensitivityWarningRecord]:
    return [
        _warning_record(
            run_id=run_id,
            scenario_id=scenario_id,
            horizon=0,
            warning_code="COST_SCENARIO_ASSUMPTION_REQUIRES_REVIEW",
            warning_message=(
                f"{scenario_id} uses hypothetical round-turn cost "
                f"{cost_bps:g} bps for research sensitivity"
            ),
            input_snapshot_ids=input_snapshot_ids,
        )
        for scenario_id, cost_bps in scenario_cost_bps.items()
    ]


def _warning_record(
    *,
    run_id: str,
    scenario_id: str,
    horizon: int,
    warning_code: str,
    warning_message: str,
    input_snapshot_ids: tuple[str, ...],
) -> CostSensitivityWarningRecord:
    return CostSensitivityWarningRecord(
        run_id=run_id,
        scenario_id=scenario_id,
        horizon=horizon,
        severity=WARNING_SEVERITY,
        warning_code=warning_code,
        warning_message=warning_message,
        human_review_required=COST_SENSITIVITY_HUMAN_REVIEW_FIELDS,
        input_snapshot_ids=input_snapshot_ids,
    )


def _write_summary_table(
    *,
    rows: tuple[CostSensitivitySummaryRow, ...],
    parquet_path: Path,
    csv_path: Path,
) -> None:
    frame = pd.DataFrame(
        [row.to_record() for row in rows],
        columns=SUMMARY_COLUMNS,
    )
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False, encoding="utf-8")


def _write_warning_csv(
    *,
    warnings: tuple[CostSensitivityWarningRecord, ...],
    csv_path: Path,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows([warning.to_csv_row() for warning in warnings])


def _write_markdown(
    *,
    markdown_path: Path,
    result: ResearchCostSensitivityResult,
) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# CF Cost Sensitivity - {result.start.isoformat()} to {result.end.isoformat()}",
        "",
        f"- Product: `{result.product_code}`",
        f"- Run ID: `{result.run_id}`",
        f"- Horizons: `{', '.join(str(horizon) for horizon in result.horizons)}`",
        f"- Summary rows: `{len(result.rows)}`",
        f"- Warnings: `{len(result.warning_records)}`",
        f"- Summary parquet: `{result.summary_parquet_path}`",
        f"- Warning CSV: `{result.warning_csv_path}`",
        "",
        "## Cost Scenarios",
        "",
    ]
    lines.extend(
        f"- `{scenario_id}`: `{cost_bps:g}` bps round-turn"
        for scenario_id, cost_bps in result.scenario_cost_bps.items()
    )
    lines.extend(
        [
            "",
            "## Research Boundary",
            "",
            "R18 compares hypothetical cost sensitivity on R17 score directions and "
            "R15 forward returns. It does not replace a reviewed production fee, "
            "slippage, or market-impact model.",
            "",
            "## Human Review Required",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _date_slice(frame: pd.DataFrame, *, start: date, end: date) -> pd.DataFrame:
    working = frame.copy()
    working["_trade_date_obj"] = pd.to_datetime(working["trade_date"]).dt.date
    selected = working.loc[
        (working["_trade_date_obj"] >= start) & (working["_trade_date_obj"] <= end)
    ].drop(columns=["_trade_date_obj"])
    if selected.empty:
        raise ResearchWorkbenchError(
            f"no rows found from {start.isoformat()} to {end.isoformat()}"
        )
    return selected


def _output_paths(*, start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / COST_SENSITIVITY_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return {
        "summary_parquet": root / f"{stem}_cost_sensitivity_summary.parquet",
        "summary_csv": root / f"{stem}_cost_sensitivity_summary.csv",
        "warning_csv": root / f"{stem}_cost_sensitivity_warnings.csv",
    }


def _markdown_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / COST_SENSITIVITY_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_cost_sensitivity"
    return root / f"{stem}.md"


def _default_score_path(*, start: date, end: date) -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / MULTIFACTOR_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return root / f"{stem}_multifactor_score_daily.parquet"


def _default_forward_return_path(*, start: date, end: date) -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / RETURNS_OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return root / f"{stem}_forward_return_daily.parquet"


def _default_run_id(*, start: date, end: date) -> str:
    return f"r18_cost_sensitivity_{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"


def _clean_record(record: dict[str, object]) -> dict[str, object]:
    cleaned: dict[str, object] = {}
    for key, value in record.items():
        if key in {"input_snapshot_ids", "input_factor_ids"}:
            cleaned[key] = _coerce_list(value)
        elif _is_missing(value):
            cleaned[key] = None
        elif key in {"trade_date", "execution_date", "exit_date"}:
            cleaned[key] = pd.to_datetime(value).date()
        else:
            cleaned[key] = value
    return cleaned


def _coerce_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item for item in value.split(";") if item]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    if hasattr(value, "tolist"):
        listed = value.tolist()  # type: ignore[attr-defined]
        if isinstance(listed, list):
            return [str(item) for item in listed]
        return [] if _is_missing(listed) else [str(listed)]
    if _is_missing(value):
        return []
    return [str(value)]


def _is_missing(value: object) -> bool:
    if isinstance(value, (list, tuple, dict, set)) or hasattr(value, "tolist"):
        return False
    missing = pd.isna(value)
    if isinstance(missing, bool):
        return missing
    return False


def _snapshot_ids_from_scores(
    rows: Iterable[ResearchMultifactorScoreDailyRow],
) -> tuple[str, ...]:
    return tuple(
        _unique_values(snapshot_id for row in rows for snapshot_id in row.input_snapshot_ids)
    )


def _snapshot_ids_from_forward_returns(
    rows: Iterable[ResearchForwardReturnDailyRow],
) -> tuple[str, ...]:
    return tuple(
        _unique_values(snapshot_id for row in rows for snapshot_id in row.input_snapshot_ids)
    )


def _snapshot_ids_from_joined(rows: Iterable[_JoinedObservation]) -> tuple[str, ...]:
    return tuple(
        _unique_values(snapshot_id for row in rows for snapshot_id in row.input_snapshot_ids)
    )


def _merge_snapshot_ids(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(_unique_values(snapshot_id for group in groups for snapshot_id in group))


def _unique_values(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
