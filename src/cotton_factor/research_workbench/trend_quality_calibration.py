"""R32 historical calibration for the R31 CF trend quality score."""

from __future__ import annotations

import csv
import json
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.common.time import utc_now
from cotton_factor.research_workbench import latest_signal_brief as r23
from cotton_factor.research_workbench import trend_continuity_board as r29
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME

PRODUCT_CODE = "CF"
TREND_QUALITY_CALIBRATION_VERSION = "R32_trend_quality_calibration_v1"
DEFAULT_HORIZONS = (1, 3, 5, 10, 20)
OUTPUT_DIR = "trend_quality_calibration"
WARNING_SEVERITY = "WARN"
INFO_SEVERITY = "INFO"
HUMAN_REVIEW_REQUIRED = (
    "trend_quality_scoring",
    "trend_quality_calibration",
    "trend_phase_rules",
    "factor_thresholds",
    "forward_return_horizon_set",
    "main_contract_target_assumption",
    "main_contract_roll_reason",
    "contract_rule_assumptions",
)

WARNING_COLUMNS = [
    "run_id",
    "section",
    "severity",
    "warning_code",
    "warning_message",
    "affected_count",
    "human_review_required",
]


@dataclass(frozen=True)
class TrendQualityCalibrationWarningRecord:
    """Warning row for R32 trend quality calibration."""

    run_id: str
    section: str
    severity: str
    warning_code: str
    warning_message: str
    affected_count: int
    human_review_required: tuple[str, ...]

    def to_csv_row(self) -> dict[str, str]:
        """Return a CSV-safe warning row."""
        return {
            "run_id": self.run_id,
            "section": self.section,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "affected_count": str(self.affected_count),
            "human_review_required": ";".join(self.human_review_required),
        }


@dataclass(frozen=True)
class ResearchTrendQualityCalibrationResult:
    """Result of building R32 trend quality calibration artifacts."""

    product_code: str
    run_id: str
    start: date
    end: date
    horizons: tuple[int, ...]
    daily_row_count: int
    bucket_summary_row_count: int
    phase_distribution_row_count: int
    latest_trade_date: date
    latest_main_contract: str
    latest_trend_quality_score: int
    latest_trend_quality_label: str
    latest_score_bucket: str
    latest_score_bucket_label: str
    latest_score_percentile: float
    latest_score_context_label: str
    warning_records: tuple[TrendQualityCalibrationWarningRecord, ...]
    daily_parquet_path: Path
    daily_csv_path: Path
    bucket_summary_parquet_path: Path
    bucket_summary_csv_path: Path
    phase_distribution_parquet_path: Path
    phase_distribution_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    core_quote_path: Path
    trend_rule_candidate_path: Path | None
    human_review_required: tuple[str, ...]

    @property
    def warning_count(self) -> int:
        """Return non-info warning count."""
        return sum(1 for warning in self.warning_records if warning.severity != INFO_SEVERITY)

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI summary."""
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "horizons": list(self.horizons),
            "daily_row_count": self.daily_row_count,
            "bucket_summary_row_count": self.bucket_summary_row_count,
            "phase_distribution_row_count": self.phase_distribution_row_count,
            "latest_trade_date": self.latest_trade_date.isoformat(),
            "latest_main_contract": self.latest_main_contract,
            "latest_trend_quality_score": self.latest_trend_quality_score,
            "latest_trend_quality_label": self.latest_trend_quality_label,
            "latest_score_bucket": self.latest_score_bucket,
            "latest_score_bucket_label": self.latest_score_bucket_label,
            "latest_score_percentile": self.latest_score_percentile,
            "latest_score_context_label": self.latest_score_context_label,
            "warning_count": self.warning_count,
            "daily_parquet_path": str(self.daily_parquet_path),
            "daily_csv_path": str(self.daily_csv_path),
            "bucket_summary_parquet_path": str(self.bucket_summary_parquet_path),
            "bucket_summary_csv_path": str(self.bucket_summary_csv_path),
            "phase_distribution_parquet_path": str(self.phase_distribution_parquet_path),
            "phase_distribution_csv_path": str(self.phase_distribution_csv_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "core_quote_path": str(self.core_quote_path),
            "trend_rule_candidate_path": (
                None
                if self.trend_rule_candidate_path is None
                else str(self.trend_rule_candidate_path)
            ),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_trend_quality_calibration(
    *,
    start: date | None = None,
    end: date | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    core_quote_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    trend_rule_candidate_path: Path | None = None,
) -> ResearchTrendQualityCalibrationResult:
    """Build R32 historical calibration artifacts for the R31 quality score."""
    normalized_horizons = _normalize_horizons(horizons)
    quote_path = core_quote_path or data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    quotes = r23._load_core_quotes(input_path=quote_path)
    available_dates = sorted(set(quotes["trade_date"]))
    if not available_dates:
        raise ResearchWorkbenchError(f"no {PRODUCT_CODE} core rows available")

    active_start = start or available_dates[0]
    active_end = end or available_dates[-1]
    if active_start > active_end:
        raise ResearchWorkbenchError("start must be <= end")

    output_dates = [value for value in available_dates if active_start <= value <= active_end]
    if not output_dates:
        raise ResearchWorkbenchError(
            f"no {PRODUCT_CODE} core rows from {active_start.isoformat()} to "
            f"{active_end.isoformat()}"
        )

    calibration_run_id = run_id or _default_run_id(start=active_start, end=active_end)
    candidates = (
        None
        if trend_rule_candidate_path is None
        else r23._load_trend_rule_candidates(input_path=trend_rule_candidate_path)
    )
    score_dates = [value for value in available_dates if value <= active_end]

    # R32 复用 R29/R31 逐日可观察评分，并从真实历史起点向前滚动，避免指定窗口首日重置阶段持续天数。
    score_rows = r29._board_rows(
        quotes=quotes,
        trade_dates=score_dates,
        run_id=calibration_run_id,
        candidates=candidates,
    )
    daily_rows = _calibration_daily_rows(
        rows=score_rows,
        quotes=quotes,
        start=active_start,
        end=active_end,
        horizons=normalized_horizons,
    )
    bucket_summary_rows = _bucket_summary_rows(
        daily_rows=daily_rows,
        horizons=normalized_horizons,
    )
    phase_distribution_rows = _phase_distribution_rows(daily_rows=daily_rows)
    latest_context = _latest_context(daily_rows=daily_rows)
    warnings = _warning_records(
        run_id=calibration_run_id,
        daily_rows=daily_rows,
        horizons=normalized_horizons,
        trend_rule_candidate_path=trend_rule_candidate_path,
    )
    paths = _output_paths(start=active_start, end=active_end, output_dir=output_dir)
    markdown_path = _markdown_path(
        start=active_start,
        end=active_end,
        report_output_dir=report_output_dir,
    )
    json_path = _json_path(
        start=active_start,
        end=active_end,
        report_output_dir=report_output_dir,
    )

    result = ResearchTrendQualityCalibrationResult(
        product_code=PRODUCT_CODE,
        run_id=calibration_run_id,
        start=active_start,
        end=active_end,
        horizons=normalized_horizons,
        daily_row_count=len(daily_rows),
        bucket_summary_row_count=len(bucket_summary_rows),
        phase_distribution_row_count=len(phase_distribution_rows),
        latest_trade_date=date.fromisoformat(str(latest_context["latest_trade_date"])),
        latest_main_contract=str(latest_context["latest_main_contract"]),
        latest_trend_quality_score=int(latest_context["latest_trend_quality_score"]),
        latest_trend_quality_label=str(latest_context["latest_trend_quality_label"]),
        latest_score_bucket=str(latest_context["latest_score_bucket"]),
        latest_score_bucket_label=str(latest_context["latest_score_bucket_label"]),
        latest_score_percentile=float(latest_context["latest_score_percentile"]),
        latest_score_context_label=str(latest_context["latest_score_context_label"]),
        warning_records=warnings,
        daily_parquet_path=paths["daily_parquet"],
        daily_csv_path=paths["daily_csv"],
        bucket_summary_parquet_path=paths["bucket_summary_parquet"],
        bucket_summary_csv_path=paths["bucket_summary_csv"],
        phase_distribution_parquet_path=paths["phase_distribution_parquet"],
        phase_distribution_csv_path=paths["phase_distribution_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=markdown_path,
        json_path=json_path,
        manifest_path=paths["manifest"],
        core_quote_path=quote_path,
        trend_rule_candidate_path=trend_rule_candidate_path,
        human_review_required=_human_review_required(warnings),
    )

    _write_table(
        rows=daily_rows,
        parquet_path=result.daily_parquet_path,
        csv_path=result.daily_csv_path,
    )
    _write_table(
        rows=bucket_summary_rows,
        parquet_path=result.bucket_summary_parquet_path,
        csv_path=result.bucket_summary_csv_path,
    )
    _write_table(
        rows=phase_distribution_rows,
        parquet_path=result.phase_distribution_parquet_path,
        csv_path=result.phase_distribution_csv_path,
    )
    _write_warning_csv(warnings=warnings, csv_path=result.warning_csv_path)
    _write_markdown(
        result=result,
        daily_rows=daily_rows,
        bucket_summary_rows=bucket_summary_rows,
        phase_distribution_rows=phase_distribution_rows,
    )
    _write_json(
        result=result,
        daily_rows=daily_rows,
        bucket_summary_rows=bucket_summary_rows,
        phase_distribution_rows=phase_distribution_rows,
        latest_context=latest_context,
    )
    _write_manifest(result=result)
    return result


def _calibration_daily_rows(
    *,
    rows: list[dict[str, object]],
    quotes: pd.DataFrame,
    start: date,
    end: date,
    horizons: tuple[int, ...],
) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for row in rows:
        trade_date = date.fromisoformat(str(row["trade_date"]))
        if trade_date < start or trade_date > end:
            continue
        value = dict(row)
        bucket = _score_bucket(int(value["trend_quality_score"]))
        value["trend_quality_score_bucket"] = bucket[0]
        value["trend_quality_score_bucket_label"] = bucket[1]
        value["calibration_rule_version"] = TREND_QUALITY_CALIBRATION_VERSION
        # forward_return_* 是历史后验标签，只在 R32 校准输出中出现，不能反哺 R23/R29 当日信号。
        value.update(
            _forward_labels(
                quotes=quotes,
                trade_date=trade_date,
                contract_code=str(value["main_contract"]),
                horizons=horizons,
            )
        )
        values.append(value)
    return values


def _forward_labels(
    *,
    quotes: pd.DataFrame,
    trade_date: date,
    contract_code: str,
    horizons: tuple[int, ...],
) -> dict[str, object]:
    series = quotes.loc[quotes["contract_code"].astype(str) == contract_code].copy()
    series = series.sort_values("trade_date").reset_index(drop=True)
    matches = series.index[series["trade_date"] == trade_date].tolist()
    if not matches:
        return _empty_forward_labels(horizons)

    labels: dict[str, object] = {}
    signal_index = int(matches[0])
    entry_index = signal_index + 1
    for horizon in horizons:
        prefix = f"h{horizon}"
        exit_index = entry_index + horizon
        if entry_index >= len(series) or exit_index >= len(series):
            labels[f"forward_return_{prefix}"] = None
            labels[f"forward_label_available_{prefix}"] = False
            labels[f"execution_date_{prefix}"] = None
            labels[f"exit_date_{prefix}"] = None
            labels[f"label_input_snapshot_ids_{prefix}"] = ""
            continue
        entry = series.iloc[entry_index]
        exit_row = series.iloc[exit_index]
        entry_price = r23._float_or_none(entry["settle"])
        exit_price = r23._float_or_none(exit_row["settle"])
        forward_return = (
            None
            if entry_price is None or exit_price is None or entry_price <= 0
            else exit_price / entry_price - 1
        )
        labels[f"forward_return_{prefix}"] = forward_return
        labels[f"forward_label_available_{prefix}"] = forward_return is not None
        labels[f"execution_date_{prefix}"] = entry["trade_date"].isoformat()
        labels[f"exit_date_{prefix}"] = exit_row["trade_date"].isoformat()
        labels[f"label_input_snapshot_ids_{prefix}"] = ";".join(
            r23._unique_values(
                [
                    str(entry["source_snapshot_id"]),
                    str(exit_row["source_snapshot_id"]),
                ]
            )
        )
    return labels


def _empty_forward_labels(horizons: tuple[int, ...]) -> dict[str, object]:
    labels: dict[str, object] = {}
    for horizon in horizons:
        prefix = f"h{horizon}"
        labels[f"forward_return_{prefix}"] = None
        labels[f"forward_label_available_{prefix}"] = False
        labels[f"execution_date_{prefix}"] = None
        labels[f"exit_date_{prefix}"] = None
        labels[f"label_input_snapshot_ids_{prefix}"] = ""
    return labels


def _bucket_summary_rows(
    *,
    daily_rows: list[dict[str, object]],
    horizons: tuple[int, ...],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    frame = pd.DataFrame(daily_rows)
    if frame.empty:
        return rows
    group_columns = ["trend_quality_score_bucket", "trend_quality_score_bucket_label"]
    for key, group in frame.groupby(group_columns, dropna=False, sort=True):
        score_bucket, score_bucket_label = key
        scores = pd.to_numeric(group["trend_quality_score"], errors="coerce").dropna()
        for horizon in horizons:
            return_column = f"forward_return_h{horizon}"
            values = pd.to_numeric(group[return_column], errors="coerce").dropna()
            direction_stats = _directional_stats(group=group, return_column=return_column)
            row = {
                "score_bucket": score_bucket,
                "score_bucket_label": score_bucket_label,
                "horizon": horizon,
                "signal_day_count": int(len(group)),
                "observation_count": int(len(values)),
                "score_min": _float_from_series(scores, "min"),
                "score_median": _float_from_series(scores, "median"),
                "score_max": _float_from_series(scores, "max"),
                "mean_forward_return": None,
                "median_forward_return": None,
                "positive_rate": None,
                "negative_rate": None,
                "directional_observation_count": direction_stats["observation_count"],
                "directional_hit_rate": direction_stats["hit_rate"],
                "calibration_rule_version": TREND_QUALITY_CALIBRATION_VERSION,
            }
            if len(values):
                row["mean_forward_return"] = float(values.mean())
                row["median_forward_return"] = float(values.median())
                row["positive_rate"] = float((values > 0).mean())
                row["negative_rate"] = float((values < 0).mean())
            rows.append(row)
    return rows


def _phase_distribution_rows(*, daily_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    frame = pd.DataFrame(daily_rows)
    if frame.empty:
        return rows
    group_columns = [
        "trend_phase_code",
        "trend_phase_label",
        "trend_quality_score_bucket",
        "trend_quality_score_bucket_label",
    ]
    for key, group in frame.groupby(group_columns, dropna=False, sort=True):
        phase_code, phase_label, score_bucket, score_bucket_label = key
        scores = pd.to_numeric(group["trend_quality_score"], errors="coerce").dropna()
        rows.append(
            {
                "trend_phase_code": phase_code,
                "trend_phase_label": phase_label,
                "score_bucket": score_bucket,
                "score_bucket_label": score_bucket_label,
                "signal_day_count": int(len(group)),
                "score_min": _float_from_series(scores, "min"),
                "score_median": _float_from_series(scores, "median"),
                "score_max": _float_from_series(scores, "max"),
                "calibration_rule_version": TREND_QUALITY_CALIBRATION_VERSION,
            }
        )
    return rows


def _directional_stats(*, group: pd.DataFrame, return_column: str) -> dict[str, object]:
    observation_count = 0
    hit_count = 0
    for row in group.to_dict(orient="records"):
        forward_return = r23._float_or_none(row.get(return_column))
        direction = _calibration_direction(row)
        if forward_return is None or direction not in {"long", "short"}:
            continue
        observation_count += 1
        if direction == "long" and forward_return > 0:
            hit_count += 1
        elif direction == "short" and forward_return < 0:
            hit_count += 1
    return {
        "observation_count": observation_count,
        "hit_rate": None if observation_count == 0 else hit_count / observation_count,
    }


def _calibration_direction(row: dict[str, object]) -> str:
    phase_direction = str(row.get("trend_phase_direction"))
    if phase_direction in {"long", "short"}:
        return phase_direction
    multi_direction = str(row.get("multi_factor_direction"))
    if multi_direction in {"long", "short"}:
        return multi_direction
    return "neutral"


def _latest_context(*, daily_rows: list[dict[str, object]]) -> dict[str, object]:
    if not daily_rows:
        raise ResearchWorkbenchError("trend quality calibration has no rows")
    latest = daily_rows[-1]
    latest_score = int(latest["trend_quality_score"])
    scores = [int(row["trend_quality_score"]) for row in daily_rows]
    percentile = sum(1 for score in scores if score <= latest_score) / len(scores)
    bucket = _score_bucket(latest_score)
    return {
        "latest_trade_date": latest["trade_date"],
        "latest_main_contract": latest["main_contract"],
        "latest_trend_phase_code": latest["trend_phase_code"],
        "latest_trend_phase_label": latest["trend_phase_label"],
        "latest_trend_quality_score": latest_score,
        "latest_trend_quality_label": latest["trend_quality_label"],
        "latest_score_bucket": bucket[0],
        "latest_score_bucket_label": bucket[1],
        "latest_score_percentile": percentile,
        "latest_score_context_label": _percentile_label(percentile),
    }


def _score_bucket(score: int) -> tuple[str, str]:
    if score >= 75:
        return "B4_75_100", "75-100 强趋势质量"
    if score >= 60:
        return "B3_60_74", "60-74 趋势质量改善"
    if score >= 45:
        return "B2_45_59", "45-59 震荡观察"
    if score >= 30:
        return "B1_30_44", "30-44 趋势质量偏弱"
    return "B0_00_29", "0-29 趋势解释失效风险"


def _percentile_label(percentile: float) -> str:
    if percentile <= 1 / 3:
        return "历史低位"
    if percentile <= 2 / 3:
        return "历史中位"
    return "历史高位"


def _warning_records(
    *,
    run_id: str,
    daily_rows: list[dict[str, object]],
    horizons: tuple[int, ...],
    trend_rule_candidate_path: Path | None,
) -> tuple[TrendQualityCalibrationWarningRecord, ...]:
    records = [
        _warning(
            run_id=run_id,
            section="research_boundary",
            severity=INFO_SEVERITY,
            warning_code="R32_FORWARD_RETURNS_ARE_VALIDATION_LABELS",
            warning_message="forward_return_* 仅用于 R32 历史后验校准，不参与当日趋势质量评分。",
            affected_count=len(daily_rows),
            human_review_required=(),
        ),
        _warning(
            run_id=run_id,
            section="trend_quality",
            severity=INFO_SEVERITY,
            warning_code="R32_TREND_QUALITY_IS_HEURISTIC",
            warning_message="R31 趋势质量评分仍是研究解释启发式，不构成交易规则或交易指令。",
            affected_count=len(daily_rows),
            human_review_required=("trend_quality_scoring", "trend_quality_calibration"),
        ),
    ]
    if len(daily_rows) < 30:
        records.append(
            _warning(
                run_id=run_id,
                section="sample_size",
                severity=WARNING_SEVERITY,
                warning_code="R32_SMALL_CALIBRATION_WINDOW",
                warning_message="校准窗口少于 30 个交易日，分位数和分数段表现仅可作为临时观察。",
                affected_count=len(daily_rows),
                human_review_required=("trend_quality_calibration",),
            )
        )
    for horizon in horizons:
        missing_count = sum(
            1 for row in daily_rows if not bool(row.get(f"forward_label_available_h{horizon}"))
        )
        if missing_count:
            records.append(
                _warning(
                    run_id=run_id,
                    section="forward_returns",
                    severity=WARNING_SEVERITY,
                    warning_code=f"R32_FORWARD_LABEL_MISSING_H{horizon}",
                    warning_message=(
                        f"horizon={horizon} 有 {missing_count} 个交易日缺少后验收益标签。"
                    ),
                    affected_count=missing_count,
                    human_review_required=("forward_return_horizon_set",),
                )
            )
    if trend_rule_candidate_path is not None:
        records.append(
            _warning(
                run_id=run_id,
                section="trend_rule_context",
                severity=INFO_SEVERITY,
                warning_code="R32_R27_CANDIDATE_CONTEXT_ONLY",
                warning_message="R27 候选规则只作为阶段切换解释上下文，不构成交易规则或交易指令。",
                affected_count=len(daily_rows),
                human_review_required=("trend_rule_candidate_thresholds",),
            )
        )
    return tuple(records)


def _warning(
    *,
    run_id: str,
    section: str,
    severity: str,
    warning_code: str,
    warning_message: str,
    affected_count: int,
    human_review_required: tuple[str, ...],
) -> TrendQualityCalibrationWarningRecord:
    return TrendQualityCalibrationWarningRecord(
        run_id=run_id,
        section=section,
        severity=severity,
        warning_code=warning_code,
        warning_message=warning_message,
        affected_count=affected_count,
        human_review_required=human_review_required,
    )


def _write_table(
    *,
    rows: list[dict[str, object]],
    parquet_path: Path,
    csv_path: Path,
) -> None:
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False, encoding="utf-8")


def _write_warning_csv(
    *,
    warnings: tuple[TrendQualityCalibrationWarningRecord, ...],
    csv_path: Path,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows([warning.to_csv_row() for warning in warnings])


def _write_markdown(
    *,
    result: ResearchTrendQualityCalibrationResult,
    daily_rows: list[dict[str, object]],
    bucket_summary_rows: list[dict[str, object]],
    phase_distribution_rows: list[dict[str, object]],
) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    latest = daily_rows[-1]
    lines = [
        f"# CF 趋势质量历史校准 - {result.start.isoformat()} 至 {result.end.isoformat()}",
        "",
        "## 一、数据状态",
        "",
        "- 报告类型：`trend_quality_calibration`",
        f"- Run ID：`{result.run_id}`",
        f"- 核心表：`{result.core_quote_path}`",
        f"- R27 候选表：`{result.trend_rule_candidate_path or '未接入'}`",
        f"- 校准交易日：`{result.daily_row_count}`",
        f"- 验证 horizon：`{','.join(str(item) for item in result.horizons)}`",
        "- 当日趋势质量评分是否使用未来收益：`否`",
        "- forward_return_* 是否仅用于历史后验校准：`是`",
        "",
        "## 二、最新分数历史位置",
        "",
        f"- 最新日期：`{result.latest_trade_date.isoformat()}`",
        f"- 主力合约：`{result.latest_main_contract}`",
        f"- 当前阶段：`{latest['trend_phase_code']} {latest['trend_phase_label']}`",
        f"- 趋势质量：`{result.latest_trend_quality_score} / {result.latest_trend_quality_label}`",
        f"- 分数段：`{result.latest_score_bucket_label}`",
        f"- 历史分位：`{result.latest_score_percentile:.2%}`",
        f"- 历史位置：`{result.latest_score_context_label}`",
        f"- 质量说明：{latest['trend_quality_reason']}",
        "",
        "## 三、分数段后验表现",
        "",
        "| 分数段 | Horizon | 信号日 | 标签样本 | 平均后验收益 | 中位后验收益 | 方向命中率 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in bucket_summary_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["score_bucket_label"]),
                    str(row["horizon"]),
                    str(row["signal_day_count"]),
                    str(row["observation_count"]),
                    _fmt_percent(row["mean_forward_return"]),
                    _fmt_percent(row["median_forward_return"]),
                    _fmt_percent(row["directional_hit_rate"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 四、阶段内分数分布",
            "",
            "| 阶段 | 分数段 | 交易日 | 分数中位数 | 分数区间 |",
            "| --- | --- | ---: | ---: | --- |",
        ]
    )
    for row in phase_distribution_rows:
        score_range = f"{_fmt_number(row['score_min'])} - {_fmt_number(row['score_max'])}"
        lines.append(
            "| "
            + " | ".join(
                [
                    f"{row['trend_phase_code']} {row['trend_phase_label']}",
                    str(row["score_bucket_label"]),
                    str(row["signal_day_count"]),
                    _fmt_number(row["score_median"]),
                    score_range,
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 五、最新样本明细",
            "",
            "| 日期 | 主力 | 阶段 | 质量 | 分数段 | h1 | h3 | h5 | h10 | h20 |",
            "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in daily_rows[-10:]:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["trade_date"]),
                    str(row["main_contract"]),
                    f"{row['trend_phase_code']} {row['trend_phase_label']}",
                    f"{row['trend_quality_score']} {row['trend_quality_label']}",
                    str(row["trend_quality_score_bucket_label"]),
                    _fmt_percent(row.get("forward_return_h1")),
                    _fmt_percent(row.get("forward_return_h3")),
                    _fmt_percent(row.get("forward_return_h5")),
                    _fmt_percent(row.get("forward_return_h10")),
                    _fmt_percent(row.get("forward_return_h20")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 六、研究边界",
            "",
            "- R32 的趋势质量评分来自 R29/R31 逐日可观察数据，不使用未来收益。",
            "- forward_return_* 仅用于历史后验校准，不参与 R23 最新日报或 R29 最新观察板。",
            "- 后验收益按当日主力合约的 T+1 后结算价窗口估算，合约切换和临近交割风险需人工复核。",
            "- R27 候选规则只用于解释阶段切换上下文，不构成交易规则。",
            "- 本报告不构成交易指令。",
            "",
            "## 七、人工复核项",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_json(
    *,
    result: ResearchTrendQualityCalibrationResult,
    daily_rows: list[dict[str, object]],
    bucket_summary_rows: list[dict[str, object]],
    phase_distribution_rows: list[dict[str, object]],
    latest_context: dict[str, object],
) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **result.to_summary(),
        "report_type": "trend_quality_calibration",
        "rule_version": TREND_QUALITY_CALIBRATION_VERSION,
        "trend_quality_rule_version": r29.TREND_QUALITY_RULE_VERSION,
        "score_no_lookahead": True,
        "forward_returns_are_validation_labels": True,
        "latest_context": latest_context,
        "bucket_summary_rows": bucket_summary_rows,
        "phase_distribution_rows": phase_distribution_rows,
        "daily_rows": daily_rows,
        "warnings": [warning.to_csv_row() for warning in result.warning_records],
    }
    result.json_path.write_text(
        json.dumps(
            _json_safe(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_manifest(*, result: ResearchTrendQualityCalibrationResult) -> None:
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **result.to_summary(),
        "report_type": "trend_quality_calibration",
        "rule_version": TREND_QUALITY_CALIBRATION_VERSION,
        "trend_quality_rule_version": r29.TREND_QUALITY_RULE_VERSION,
        "generated_at": utc_now().isoformat(),
        "score_no_lookahead": True,
        "forward_returns_are_validation_labels": True,
    }
    result.manifest_path.write_text(
        json.dumps(
            _json_safe(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _normalize_horizons(horizons: tuple[int, ...]) -> tuple[int, ...]:
    if not horizons:
        raise ResearchWorkbenchError("at least one horizon is required")
    values = tuple(sorted(set(horizons)))
    invalid = [horizon for horizon in values if horizon <= 0]
    if invalid:
        raise ResearchWorkbenchError(f"horizons must be positive integers: {invalid}")
    return values


def _output_paths(*, start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_trend_quality_calibration"
    return {
        "daily_parquet": root / f"{stem}_daily.parquet",
        "daily_csv": root / f"{stem}_daily.csv",
        "bucket_summary_parquet": root / f"{stem}_bucket_summary.parquet",
        "bucket_summary_csv": root / f"{stem}_bucket_summary.csv",
        "phase_distribution_parquet": root / f"{stem}_phase_distribution.parquet",
        "phase_distribution_csv": root / f"{stem}_phase_distribution.csv",
        "warning_csv": root / f"{stem}_warnings.csv",
        "manifest": root / f"{stem}_manifest.json",
    }


def _markdown_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_trend_quality_calibration"
    return root / f"{stem}.md"


def _json_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_trend_quality_calibration"
    return root / f"{stem}.json"


def _human_review_required(
    warnings: tuple[TrendQualityCalibrationWarningRecord, ...],
) -> tuple[str, ...]:
    values = list(HUMAN_REVIEW_REQUIRED)
    values.extend(item for warning in warnings for item in warning.human_review_required)
    return tuple(r23._unique_values(values))


def _float_from_series(values: pd.Series, method: str) -> float | None:
    if len(values) == 0:
        return None
    if method == "min":
        return float(values.min())
    if method == "median":
        return float(values.median())
    if method == "max":
        return float(values.max())
    raise ResearchWorkbenchError(f"unsupported series method: {method}")


def _fmt_number(value: object) -> str:
    return r23._fmt_number(value)


def _fmt_percent(value: object) -> str:
    return r23._fmt_percent(value)


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if _is_scalar_missing(value):
        return None
    return value


def _is_scalar_missing(value: object) -> bool:
    if isinstance(value, (list, tuple, dict, str, Path, date)):
        return False
    return bool(pd.isna(value))


def _default_run_id(*, start: date, end: date) -> str:
    timestamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    suffix = uuid.uuid4().hex[:8]
    return (
        f"r32_trend_quality_calibration_{PRODUCT_CODE}_"
        f"{start.isoformat()}_{end.isoformat()}_{timestamp}_{suffix}"
    )
