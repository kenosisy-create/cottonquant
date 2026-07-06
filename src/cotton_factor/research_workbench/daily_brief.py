"""R19 daily CF research brief generation."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.core.schemas import (
    CoreChainMapDailyRow,
    CoreTradeMappingDailyRow,
    ResearchFactorDiagnosticDailyRow,
    ResearchFactorEvaluationRow,
    ResearchMultifactorScoreDailyRow,
)
from cotton_factor.research_workbench.cost_sensitivity import COST_SENSITIVITY_OUTPUT_DIR
from cotton_factor.research_workbench.data_quality import QUALITY_REPORT_DIR
from cotton_factor.research_workbench.factor_diagnostics import FACTOR_OUTPUT_DIR
from cotton_factor.research_workbench.mapping import MAPPING_OUTPUT_DIR
from cotton_factor.research_workbench.multifactor_diagnostics import MULTIFACTOR_OUTPUT_DIR
from cotton_factor.research_workbench.single_factor_backtest import BACKTEST_OUTPUT_DIR

PRODUCT_CODE = "CF"
UNIVERSE = "CF_MAIN"
DAILY_BRIEF_REPORT_DIR = "daily_brief"
WARNING_SEVERITY = "WARN"
BRIEF_HUMAN_REVIEW_FIELDS = (
    "daily_brief_interpretation",
    "factor_thresholds",
    "contract_rule_assumptions",
    "cost_scenario_bps",
)

WARNING_COLUMNS = [
    "run_id",
    "trade_date",
    "section",
    "severity",
    "warning_code",
    "warning_message",
    "human_review_required",
    "input_snapshot_ids",
]


@dataclass(frozen=True)
class DailyBriefWarningRecord:
    """Warning row for R19 daily brief generation."""

    run_id: str
    trade_date: date
    section: str
    severity: str
    warning_code: str
    warning_message: str
    human_review_required: tuple[str, ...]
    input_snapshot_ids: tuple[str, ...]

    def to_csv_row(self) -> dict[str, str]:
        """Return a CSV-safe warning row."""
        return {
            "run_id": self.run_id,
            "trade_date": self.trade_date.isoformat(),
            "section": self.section,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "human_review_required": ";".join(self.human_review_required),
            "input_snapshot_ids": ";".join(self.input_snapshot_ids),
        }


@dataclass(frozen=True)
class ResearchDailyBriefResult:
    """Result of building an R19 daily CF research brief."""

    product_code: str
    run_id: str
    trade_date: date
    start: date
    end: date
    brief_status: str
    summary: dict[str, object]
    warning_records: tuple[DailyBriefWarningRecord, ...]
    markdown_path: Path
    json_path: Path
    warning_csv_path: Path
    human_review_required: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable CLI summary."""
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "trade_date": self.trade_date.isoformat(),
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "brief_status": self.brief_status,
            "warning_count": len(self.warning_records),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "warning_csv_path": str(self.warning_csv_path),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_daily_brief(
    *,
    trade_date: date,
    start: date | None = None,
    end: date | None = None,
    quality_csv_path: Path | None = None,
    chain_map_path: Path | None = None,
    trade_mapping_path: Path | None = None,
    diagnostic_path: Path | None = None,
    single_factor_evaluation_path: Path | None = None,
    multifactor_score_path: Path | None = None,
    cost_sensitivity_path: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchDailyBriefResult:
    """Build the R19 daily CF research brief from R06-R18 artifacts."""
    window_start = start or trade_date
    window_end = end or trade_date
    if window_start > window_end:
        raise ResearchWorkbenchError("start must be <= end")
    if not (window_start <= trade_date <= window_end):
        raise ResearchWorkbenchError("trade_date must be inside start/end window")

    brief_run_id = run_id or f"r19_daily_brief_{PRODUCT_CODE}_{trade_date.isoformat()}"
    paths = _input_paths(
        trade_date=trade_date,
        start=window_start,
        end=window_end,
        quality_csv_path=quality_csv_path,
        chain_map_path=chain_map_path,
        trade_mapping_path=trade_mapping_path,
        diagnostic_path=diagnostic_path,
        single_factor_evaluation_path=single_factor_evaluation_path,
        multifactor_score_path=multifactor_score_path,
        cost_sensitivity_path=cost_sensitivity_path,
    )
    _require_paths(paths)

    quality = _quality_summary(paths["quality_csv_path"])
    chain_row = _chain_row(paths["chain_map_path"], trade_date=trade_date)
    trade_row = _trade_row(paths["trade_mapping_path"], trade_date=trade_date)
    diagnostics = _diagnostic_rows(paths["diagnostic_path"], trade_date=trade_date)
    evaluations = _evaluation_rows(paths["single_factor_evaluation_path"])
    score_row = _score_row(paths["multifactor_score_path"], trade_date=trade_date)
    cost_rows = _cost_rows(paths["cost_sensitivity_path"])

    summary = _build_summary(
        trade_date=trade_date,
        quality=quality,
        chain_row=chain_row,
        trade_row=trade_row,
        diagnostics=diagnostics,
        evaluations=evaluations,
        score_row=score_row,
        cost_rows=cost_rows,
        paths=paths,
    )
    warnings = tuple(
        _build_warnings(
            run_id=brief_run_id,
            trade_date=trade_date,
            quality=quality,
            trade_row=trade_row,
            diagnostics=diagnostics,
            score_row=score_row,
            cost_rows=cost_rows,
        )
    )
    brief_status = _brief_status(warnings=warnings, quality=quality)
    output_paths = _output_paths(trade_date=trade_date, report_output_dir=report_output_dir)

    # R19 简报只汇总研究证据和观察项，不生成买卖建议或生产执行许可。
    result = ResearchDailyBriefResult(
        product_code=PRODUCT_CODE,
        run_id=brief_run_id,
        trade_date=trade_date,
        start=window_start,
        end=window_end,
        brief_status=brief_status,
        summary=summary,
        warning_records=warnings,
        markdown_path=output_paths["markdown"],
        json_path=output_paths["json"],
        warning_csv_path=output_paths["warning_csv"],
        human_review_required=_human_review_required(warnings),
    )
    _write_markdown(result=result)
    _write_json(result=result)
    _write_warning_csv(warnings=warnings, csv_path=result.warning_csv_path)
    return result


def _input_paths(
    *,
    trade_date: date,
    start: date,
    end: date,
    quality_csv_path: Path | None,
    chain_map_path: Path | None,
    trade_mapping_path: Path | None,
    diagnostic_path: Path | None,
    single_factor_evaluation_path: Path | None,
    multifactor_score_path: Path | None,
    cost_sensitivity_path: Path | None,
) -> dict[str, Path]:
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return {
        "quality_csv_path": quality_csv_path
        or reports_dir()
        / "research"
        / QUALITY_REPORT_DIR
        / f"{PRODUCT_CODE}_{trade_date.isoformat()}_quality.csv",
        "chain_map_path": chain_map_path
        or data_dir()
        / "research"
        / PRODUCT_CODE
        / MAPPING_OUTPUT_DIR
        / f"{stem}_chain_map_daily.parquet",
        "trade_mapping_path": trade_mapping_path
        or data_dir()
        / "research"
        / PRODUCT_CODE
        / MAPPING_OUTPUT_DIR
        / f"{stem}_trade_mapping_daily.parquet",
        "diagnostic_path": diagnostic_path
        or data_dir()
        / "research"
        / PRODUCT_CODE
        / FACTOR_OUTPUT_DIR
        / f"{stem}_factor_diagnostic_daily.parquet",
        "single_factor_evaluation_path": single_factor_evaluation_path
        or data_dir()
        / "research"
        / PRODUCT_CODE
        / BACKTEST_OUTPUT_DIR
        / f"{stem}_single_factor_evaluation.parquet",
        "multifactor_score_path": multifactor_score_path
        or data_dir()
        / "research"
        / PRODUCT_CODE
        / MULTIFACTOR_OUTPUT_DIR
        / f"{stem}_multifactor_score_daily.parquet",
        "cost_sensitivity_path": cost_sensitivity_path
        or data_dir()
        / "research"
        / PRODUCT_CODE
        / COST_SENSITIVITY_OUTPUT_DIR
        / f"{stem}_cost_sensitivity_summary.parquet",
    }


def _require_paths(paths: dict[str, Path]) -> None:
    missing = {name: path for name, path in paths.items() if not path.exists()}
    if missing:
        joined = ", ".join(f"{name}={path}" for name, path in missing.items())
        raise ResearchWorkbenchError(f"daily brief required inputs are missing: {joined}")


def _quality_summary(path: Path) -> dict[str, object]:
    frame = pd.read_csv(path)
    if not {"severity", "status", "check_id", "message"}.issubset(frame.columns):
        raise ResearchWorkbenchError(f"quality CSV missing required columns: {path}")
    non_pass = frame.loc[frame["status"].astype(str) != "PASS"]
    severity_counts = {
        severity: int((non_pass["severity"].astype(str) == severity).sum())
        for severity in ("CRITICAL", "WARNING", "INFO")
    }
    failed_critical = frame.loc[
        (frame["severity"].astype(str) == "CRITICAL")
        & (frame["status"].astype(str) == "FAIL")
    ]
    return {
        "path": str(path),
        "passed": bool(failed_critical.empty),
        "issue_count": int(len(non_pass)),
        "severity_counts": severity_counts,
        "messages": non_pass["message"].astype(str).head(8).to_list(),
    }


def _chain_row(path: Path, *, trade_date: date) -> CoreChainMapDailyRow:
    rows = _typed_rows(path=path, row_type=CoreChainMapDailyRow, trade_date=trade_date)
    if len(rows) != 1:
        raise ResearchWorkbenchError(
            f"daily brief expected one chain row for {trade_date.isoformat()}, got {len(rows)}"
        )
    return rows[0]


def _trade_row(path: Path, *, trade_date: date) -> CoreTradeMappingDailyRow:
    rows = _typed_rows(path=path, row_type=CoreTradeMappingDailyRow, trade_date=trade_date)
    if len(rows) != 1:
        raise ResearchWorkbenchError(
            f"daily brief expected one trade mapping row for {trade_date.isoformat()}, "
            f"got {len(rows)}"
        )
    return rows[0]


def _diagnostic_rows(
    path: Path,
    *,
    trade_date: date,
) -> tuple[ResearchFactorDiagnosticDailyRow, ...]:
    rows = tuple(
        sorted(
            _typed_rows(
                path=path,
                row_type=ResearchFactorDiagnosticDailyRow,
                trade_date=trade_date,
            ),
            key=lambda row: row.factor_id,
        )
    )
    if not rows:
        raise ResearchWorkbenchError(
            f"daily brief found no factor diagnostics for {trade_date.isoformat()}"
        )
    return rows


def _evaluation_rows(path: Path) -> tuple[ResearchFactorEvaluationRow, ...]:
    return tuple(
        sorted(
            _typed_rows(path=path, row_type=ResearchFactorEvaluationRow, trade_date=None),
            key=lambda row: (row.factor_id, row.horizon, row.metric_name),
        )
    )


def _score_row(path: Path, *, trade_date: date) -> ResearchMultifactorScoreDailyRow:
    rows = _typed_rows(path=path, row_type=ResearchMultifactorScoreDailyRow, trade_date=trade_date)
    if len(rows) != 1:
        raise ResearchWorkbenchError(
            f"daily brief expected one multifactor score row for {trade_date.isoformat()}, "
            f"got {len(rows)}"
        )
    return rows[0]


def _cost_rows(path: Path) -> tuple[dict[str, object], ...]:
    frame = pd.read_parquet(path)
    required = {
        "scenario_id",
        "horizon",
        "observation_count",
        "round_turn_cost_bps",
        "gross_mean_return",
        "net_mean_return",
        "net_hit_rate",
    }
    if not required.issubset(frame.columns):
        raise ResearchWorkbenchError(f"cost sensitivity table missing required columns: {path}")
    return tuple(frame.to_dict(orient="records"))


def _typed_rows(path: Path, row_type: type, trade_date: date | None) -> list:
    frame = pd.read_parquet(path)
    if trade_date is not None and "trade_date" not in frame.columns:
        raise ResearchWorkbenchError(f"table missing trade_date column: {path}")
    if trade_date is not None:
        working = frame.copy()
        working["_trade_date_obj"] = pd.to_datetime(working["trade_date"]).dt.date
        frame = working.loc[working["_trade_date_obj"] == trade_date].drop(
            columns=["_trade_date_obj"]
        )
    rows = []
    for record in frame.to_dict(orient="records"):
        rows.append(row_type.model_validate(_clean_record(record)))
    return rows


def _build_summary(
    *,
    trade_date: date,
    quality: dict[str, object],
    chain_row: CoreChainMapDailyRow,
    trade_row: CoreTradeMappingDailyRow,
    diagnostics: tuple[ResearchFactorDiagnosticDailyRow, ...],
    evaluations: tuple[ResearchFactorEvaluationRow, ...],
    score_row: ResearchMultifactorScoreDailyRow,
    cost_rows: tuple[dict[str, object], ...],
    paths: dict[str, Path],
) -> dict[str, object]:
    state_counts = _value_counts(row.signal_state for row in diagnostics)
    return {
        "trade_date": trade_date.isoformat(),
        "quality": quality,
        "market_structure": {
            "mapped_contract": chain_row.mapped_contract,
            "switch_reason": chain_row.switch_reason,
            "execution_date": trade_row.execution_date.isoformat(),
            "target_contract": trade_row.target_contract,
            "execution_eligible": trade_row.execution_eligible,
            "is_blocked": trade_row.is_blocked,
            "block_reason": trade_row.block_reason,
        },
        "factor_diagnostics": {
            "state_counts": state_counts,
            "rows": [
                {
                    "factor_id": row.factor_id,
                    "state": row.signal_state,
                    "raw_value": row.raw_value,
                    "diagnostic_reason": row.diagnostic_reason,
                    "warning_flags": list(row.warning_flags),
                    "human_review_required": list(row.human_review_required),
                }
                for row in diagnostics
            ],
        },
        "single_factor_evidence": _evaluation_summary(evaluations),
        "multifactor_score": {
            "score_id": score_row.score_id,
            "raw_score": score_row.raw_score,
            "processed_score": score_row.processed_score,
            "direction": _score_direction(score_row),
            "factor_count": score_row.factor_count,
            "input_factor_ids": list(score_row.input_factor_ids),
        },
        "cost_sensitivity": _cost_summary(cost_rows),
        "watch_items": _watch_items(
            quality=quality,
            trade_row=trade_row,
            diagnostics=diagnostics,
            score_row=score_row,
            cost_rows=cost_rows,
        ),
        "input_paths": {name: str(path) for name, path in paths.items()},
    }


def _evaluation_summary(rows: tuple[ResearchFactorEvaluationRow, ...]) -> list[dict[str, object]]:
    selected_metrics = {
        "observation_count",
        "pearson_ic",
        "spearman_rank_ic",
        "directional_accuracy",
        "mean_forward_return",
    }
    return [
        {
            "factor_id": row.factor_id,
            "horizon": row.horizon,
            "metric_name": row.metric_name,
            "metric_value": row.metric_value,
            "observation_count": row.observation_count,
        }
        for row in rows
        if row.metric_name in selected_metrics
    ]


def _cost_summary(rows: tuple[dict[str, object], ...]) -> list[dict[str, object]]:
    return [
        {
            "scenario_id": str(row["scenario_id"]),
            "horizon": int(row["horizon"]),
            "observation_count": int(row["observation_count"]),
            "round_turn_cost_bps": float(row["round_turn_cost_bps"]),
            "gross_mean_return": float(row["gross_mean_return"]),
            "net_mean_return": float(row["net_mean_return"]),
            "net_hit_rate": float(row["net_hit_rate"]),
        }
        for row in rows
    ]


def _watch_items(
    *,
    quality: dict[str, object],
    trade_row: CoreTradeMappingDailyRow,
    diagnostics: tuple[ResearchFactorDiagnosticDailyRow, ...],
    score_row: ResearchMultifactorScoreDailyRow,
    cost_rows: tuple[dict[str, object], ...],
) -> list[str]:
    items: list[str] = []
    if not quality["passed"]:
        items.append("Resolve critical data-quality failures before relying on the brief.")
    if trade_row.is_blocked:
        items.append(f"Review blocked T+1 mapping: {trade_row.block_reason}.")
    unknown_factors = [row.factor_id for row in diagnostics if row.signal_state == "unknown"]
    if unknown_factors:
        items.append(f"Review unknown factor states: {', '.join(unknown_factors)}.")
    if score_row.raw_score == 0:
        items.append("Multifactor score is neutral; watch whether factor agreement improves.")
    if cost_rows and max(float(row["net_mean_return"]) for row in cost_rows) <= 0:
        items.append(
            "All cost scenarios have non-positive net mean return; review signal strength."
        )
    items.append("Keep factor thresholds, contract rules, and cost assumptions under human review.")
    return items


def _build_warnings(
    *,
    run_id: str,
    trade_date: date,
    quality: dict[str, object],
    trade_row: CoreTradeMappingDailyRow,
    diagnostics: tuple[ResearchFactorDiagnosticDailyRow, ...],
    score_row: ResearchMultifactorScoreDailyRow,
    cost_rows: tuple[dict[str, object], ...],
) -> list[DailyBriefWarningRecord]:
    warnings: list[DailyBriefWarningRecord] = []
    if not quality["passed"]:
        warnings.append(
            _warning_record(
                run_id=run_id,
                trade_date=trade_date,
                section="data_quality",
                warning_code="DAILY_BRIEF_CRITICAL_QUALITY_FAILURE",
                warning_message="critical data-quality check failed before daily brief review",
                input_snapshot_ids=(),
            )
        )
    if trade_row.is_blocked:
        warnings.append(
            _warning_record(
                run_id=run_id,
                trade_date=trade_date,
                section="mapping",
                warning_code="DAILY_BRIEF_TRADE_MAPPING_BLOCKED",
                warning_message=f"T+1 trade mapping is blocked: {trade_row.block_reason}",
                input_snapshot_ids=(trade_row.source_snapshot_id,),
            )
        )
    unknown_rows = [row for row in diagnostics if row.signal_state == "unknown"]
    if unknown_rows:
        warnings.append(
            _warning_record(
                run_id=run_id,
                trade_date=trade_date,
                section="factor_diagnostics",
                warning_code="DAILY_BRIEF_UNKNOWN_FACTOR_STATE",
                warning_message=(
                    "unknown factor states: "
                    + ", ".join(row.factor_id for row in unknown_rows)
                ),
                input_snapshot_ids=_snapshot_ids_from_diagnostics(unknown_rows),
            )
        )
    if score_row.factor_count < len(score_row.input_factor_ids):
        warnings.append(
            _warning_record(
                run_id=run_id,
                trade_date=trade_date,
                section="multifactor_score",
                warning_code="DAILY_BRIEF_SCORE_FACTOR_COUNT_MISMATCH",
                warning_message="multifactor score factor_count is below input factor ids",
                input_snapshot_ids=tuple(score_row.input_snapshot_ids),
            )
        )
    if cost_rows:
        warnings.append(
            _warning_record(
                run_id=run_id,
                trade_date=trade_date,
                section="cost_sensitivity",
                warning_code="DAILY_BRIEF_COST_ASSUMPTION_REQUIRES_REVIEW",
                warning_message="cost sensitivity rows use hypothetical scenario bps",
                input_snapshot_ids=(),
            )
        )
    return warnings


def _warning_record(
    *,
    run_id: str,
    trade_date: date,
    section: str,
    warning_code: str,
    warning_message: str,
    input_snapshot_ids: tuple[str, ...],
) -> DailyBriefWarningRecord:
    return DailyBriefWarningRecord(
        run_id=run_id,
        trade_date=trade_date,
        section=section,
        severity=WARNING_SEVERITY,
        warning_code=warning_code,
        warning_message=warning_message,
        human_review_required=BRIEF_HUMAN_REVIEW_FIELDS,
        input_snapshot_ids=input_snapshot_ids,
    )


def _brief_status(
    *,
    warnings: tuple[DailyBriefWarningRecord, ...],
    quality: dict[str, object],
) -> str:
    if not quality["passed"]:
        return "DATA_QUALITY_BLOCKED"
    if any(warning.warning_code == "DAILY_BRIEF_TRADE_MAPPING_BLOCKED" for warning in warnings):
        return "MAPPING_BLOCKED"
    if warnings:
        return "WATCH_REQUIRED"
    return "READY_FOR_RESEARCH_REVIEW"


def _write_markdown(*, result: ResearchDailyBriefResult) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    summary = result.summary
    lines = [
        f"# CF Daily Research Brief - {result.trade_date.isoformat()}",
        "",
        f"- Status: `{result.brief_status}`",
        f"- Run ID: `{result.run_id}`",
        f"- Window: `{result.start.isoformat()} -> {result.end.isoformat()}`",
        "",
        "## Data Quality",
        "",
        f"- Passed: `{summary['quality']['passed']}`",  # type: ignore[index]
        f"- Severity counts: `{summary['quality']['severity_counts']}`",  # type: ignore[index]
        "",
        "## Market Structure",
        "",
    ]
    market = summary["market_structure"]  # type: ignore[index]
    lines.extend(
        [
            f"- Mapped contract: `{market['mapped_contract']}`",
            f"- Switch reason: `{market['switch_reason']}`",
            f"- T+1 execution date: `{market['execution_date']}`",
            f"- Target contract: `{market['target_contract']}`",
            f"- Blocked: `{market['is_blocked']}`",
            f"- Block reason: `{market['block_reason']}`",
            "",
            "## Factor Diagnostics",
            "",
            "| Factor | State | Raw Value | Warnings |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in summary["factor_diagnostics"]["rows"]:  # type: ignore[index]
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["factor_id"]),
                    str(row["state"]),
                    str(row["raw_value"]),
                    ", ".join(row["warning_flags"]),
                ]
            )
            + " |"
        )
    score = summary["multifactor_score"]  # type: ignore[index]
    lines.extend(
        [
            "",
            "## Multifactor Score",
            "",
            f"- Direction: `{score['direction']}`",
            f"- Raw score: `{score['raw_score']}`",
            f"- Factor count: `{score['factor_count']}`",
            "",
            "## Cost Sensitivity",
            "",
            "| Scenario | Horizon | Cost bps | Gross Mean | Net Mean | Net Hit Rate |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in summary["cost_sensitivity"]:  # type: ignore[index]
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["scenario_id"]),
                    str(row["horizon"]),
                    f"{row['round_turn_cost_bps']:.6g}",
                    f"{row['gross_mean_return']:.6g}",
                    f"{row['net_mean_return']:.6g}",
                    f"{row['net_hit_rate']:.6g}",
                ]
            )
            + " |"
        )
    lines.extend(["", "## Watch Items", ""])
    lines.extend(f"- {item}" for item in summary["watch_items"])  # type: ignore[index]
    lines.extend(
        [
            "",
            "## Research Boundary",
            "",
            "R19 is an analyst-facing research brief. It summarizes existing "
            "R06-R18 evidence and does not approve trades, orders, target lots, "
            "or production execution.",
            "",
            "## Human Review Required",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_json(*, result: ResearchDailyBriefResult) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **result.to_summary(),
        "summary": result.summary,
        "warnings": [warning.to_csv_row() for warning in result.warning_records],
    }
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_warning_csv(
    *,
    warnings: tuple[DailyBriefWarningRecord, ...],
    csv_path: Path,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows([warning.to_csv_row() for warning in warnings])


def _output_paths(*, trade_date: date, report_output_dir: Path | None) -> dict[str, Path]:
    root = report_output_dir or reports_dir() / "research" / DAILY_BRIEF_REPORT_DIR
    stem = f"{PRODUCT_CODE}_{trade_date.isoformat()}_daily_research_brief"
    return {
        "markdown": root / f"{stem}.md",
        "json": root / f"{stem}.json",
        "warning_csv": root / f"{stem}_warnings.csv",
    }


def _score_direction(row: ResearchMultifactorScoreDailyRow) -> str:
    value = row.processed_score if row.processed_score is not None else row.raw_score
    if value > 0:
        return "long"
    if value < 0:
        return "short"
    return "neutral"


def _human_review_required(warnings: tuple[DailyBriefWarningRecord, ...]) -> tuple[str, ...]:
    values = [*BRIEF_HUMAN_REVIEW_FIELDS]
    values.extend(item for warning in warnings for item in warning.human_review_required)
    return tuple(_unique_values(values))


def _snapshot_ids_from_diagnostics(
    rows: Iterable[ResearchFactorDiagnosticDailyRow],
) -> tuple[str, ...]:
    return tuple(
        _unique_values(snapshot_id for row in rows for snapshot_id in row.input_snapshot_ids)
    )


def _clean_record(record: dict[str, object]) -> dict[str, object]:
    cleaned: dict[str, object] = {}
    for key, value in record.items():
        if key in {
            "input_snapshot_ids",
            "warning_flags",
            "human_review_required",
            "input_factor_ids",
        }:
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


def _value_counts(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _unique_values(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
