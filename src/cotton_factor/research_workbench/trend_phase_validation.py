"""R25 rolling validation for CF trend phase signals."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.common.time import utc_now
from cotton_factor.research_workbench import latest_signal_brief as r23
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME

PRODUCT_CODE = "CF"
SIGNAL_OBJECT_ID = "CF.C1"
UNIVERSE = "CF_MAIN"
TREND_PHASE_VALIDATION_RULE_VERSION = "R25_trend_phase_validation_v1"
DEFAULT_HORIZONS = (1, 3, 5, 10, 20)
OUTPUT_DIR = "trend_phase_validation"
WARNING_SEVERITY = "WARN"
INFO_SEVERITY = "INFO"
HUMAN_REVIEW_REQUIRED = (
    "trend_phase_rules",
    "factor_thresholds",
    "forward_return_horizon_set",
    "main_contract_target_assumption",
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
class TrendPhaseValidationWarningRecord:
    """Warning row for R25 trend phase validation."""

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
class ResearchTrendPhaseValidationResult:
    """Result of building R25 trend phase validation artifacts."""

    product_code: str
    run_id: str
    start: date
    end: date
    horizons: tuple[int, ...]
    daily_row_count: int
    summary_row_count: int
    warning_records: tuple[TrendPhaseValidationWarningRecord, ...]
    daily_parquet_path: Path
    daily_csv_path: Path
    summary_parquet_path: Path
    summary_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    manifest_path: Path
    core_quote_path: Path
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
            "summary_row_count": self.summary_row_count,
            "warning_count": self.warning_count,
            "daily_parquet_path": str(self.daily_parquet_path),
            "daily_csv_path": str(self.daily_csv_path),
            "summary_parquet_path": str(self.summary_parquet_path),
            "summary_csv_path": str(self.summary_csv_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "manifest_path": str(self.manifest_path),
            "core_quote_path": str(self.core_quote_path),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_trend_phase_validation(
    *,
    start: date,
    end: date,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    core_quote_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchTrendPhaseValidationResult:
    """Build rolling R25 phase rows and historical validation summaries."""
    if start > end:
        raise ResearchWorkbenchError("start must be <= end")
    normalized_horizons = _normalize_horizons(horizons)
    quote_path = core_quote_path or data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    quotes = r23._load_core_quotes(input_path=quote_path)
    dates = [value for value in sorted(set(quotes["trade_date"])) if start <= value <= end]
    if not dates:
        raise ResearchWorkbenchError(
            f"no {PRODUCT_CODE} core rows from {start.isoformat()} to {end.isoformat()}"
        )

    validation_run_id = run_id or _default_run_id(start=start, end=end)
    daily_rows = _daily_rows(
        quotes=quotes,
        trade_dates=dates,
        horizons=normalized_horizons,
        run_id=validation_run_id,
    )
    summary_rows = _summary_rows(daily_rows=daily_rows, horizons=normalized_horizons)
    warnings = _warning_records(
        run_id=validation_run_id,
        daily_rows=daily_rows,
        summary_rows=summary_rows,
        horizons=normalized_horizons,
    )
    paths = _output_paths(start=start, end=end, output_dir=output_dir)
    markdown_path = _markdown_path(start=start, end=end, report_output_dir=report_output_dir)

    # R25 的阶段判断只看 T 日及以前；forward_return_* 只作为后验验证标签写入。
    _write_table(rows=daily_rows, parquet_path=paths["daily_parquet"], csv_path=paths["daily_csv"])
    _write_table(
        rows=summary_rows,
        parquet_path=paths["summary_parquet"],
        csv_path=paths["summary_csv"],
    )
    _write_warning_csv(warnings=warnings, csv_path=paths["warning_csv"])
    result = ResearchTrendPhaseValidationResult(
        product_code=PRODUCT_CODE,
        run_id=validation_run_id,
        start=start,
        end=end,
        horizons=normalized_horizons,
        daily_row_count=len(daily_rows),
        summary_row_count=len(summary_rows),
        warning_records=warnings,
        daily_parquet_path=paths["daily_parquet"],
        daily_csv_path=paths["daily_csv"],
        summary_parquet_path=paths["summary_parquet"],
        summary_csv_path=paths["summary_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=markdown_path,
        manifest_path=paths["manifest"],
        core_quote_path=quote_path,
        human_review_required=HUMAN_REVIEW_REQUIRED,
    )
    _write_markdown(result=result, daily_rows=daily_rows, summary_rows=summary_rows)
    _write_manifest(result=result)
    return result


def _daily_rows(
    *,
    quotes: pd.DataFrame,
    trade_dates: list[date],
    horizons: tuple[int, ...],
    run_id: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for trade_date in trade_dates:
        visible_quotes = quotes.loc[quotes["trade_date"] <= trade_date].copy()
        latest_quotes = visible_quotes.loc[visible_quotes["trade_date"] == trade_date].copy()
        activity_rows = r23._activity_rows(
            visible_quotes=visible_quotes,
            active_date=trade_date,
        )
        main_contract = str(activity_rows[0]["contract_code"])
        main_history = r23._main_contract_history(
            visible_quotes=visible_quotes,
            contract_code=main_contract,
            active_date=trade_date,
        )
        main_metrics = r23._main_metrics(main_history=main_history)
        term_structure = r23._term_structure(
            latest_quotes=latest_quotes,
            main_contract=main_contract,
        )
        factor_signals = r23._factor_signals(
            main_metrics=main_metrics,
            term_structure=term_structure,
        )
        multi_factor = r23._multi_factor_summary(factor_signals)
        returns = main_metrics["returns"]
        assert isinstance(returns, dict)
        trend_phase = r23.classify_cf_trend_phase(
            signal_states=factor_signals,
            latest_settle=main_metrics["latest_settle"],
            ma20=main_metrics["ma20"],
            momentum_20=returns.get("20"),
            latest_return=returns.get("1"),
            oi_pressure=main_metrics["oi_pressure"],
        )
        forward_labels = _forward_labels(
            quotes=quotes,
            trade_date=trade_date,
            contract_code=main_contract,
            horizons=horizons,
        )
        snapshot_ids = r23._unique_values(latest_quotes["source_snapshot_id"].dropna().astype(str))
        row = {
            "run_id": run_id,
            "product_code": PRODUCT_CODE,
            "universe": UNIVERSE,
            "signal_object_id": SIGNAL_OBJECT_ID,
            "trade_date": trade_date.isoformat(),
            "main_contract": main_contract,
            "main_contract_rank_reason": "latest_open_interest_desc_volume_desc",
            "main_settle": main_metrics["latest_settle"],
            "main_volume": main_metrics["latest_volume"],
            "main_open_interest": main_metrics["latest_open_interest"],
            "main_oi_change": main_metrics["oi_change"],
            "main_oi_pressure": main_metrics["oi_pressure"],
            "return_1d": returns.get("1"),
            "return_3d": returns.get("3"),
            "return_5d": returns.get("5"),
            "return_10d": returns.get("10"),
            "return_20d": returns.get("20"),
            "ma20": main_metrics["ma20"],
            "near_contract": term_structure["near_contract"],
            "far_contract": term_structure["far_contract"],
            "main_minus_near": term_structure["main_minus_near"],
            "far_minus_main": term_structure["far_minus_main"],
            "curve_slope": term_structure["curve_slope"],
            "carry_annualized": term_structure["carry_annualized"],
            "momentum_signal": factor_signals["momentum"],
            "carry_signal": factor_signals["carry"],
            "curve_signal": factor_signals["curve"],
            "oi_pressure_signal": factor_signals["oi_pressure"],
            "multi_factor_score": multi_factor["score"],
            "multi_factor_direction": multi_factor["direction"],
            "multi_factor_confidence": multi_factor["confidence"],
            "trend_phase_code": trend_phase.phase_code,
            "trend_phase_label": trend_phase.phase_label,
            "trend_phase_direction": trend_phase.direction,
            "trend_phase_confidence": trend_phase.confidence,
            "trend_phase_support_count": trend_phase.support_count,
            "trend_phase_available_signal_count": trend_phase.available_signal_count,
            "trend_phase_reason": trend_phase.reason,
            "signal_input_snapshot_ids": ";".join(snapshot_ids),
            "validation_rule_version": TREND_PHASE_VALIDATION_RULE_VERSION,
        }
        row.update(forward_labels)
        rows.append(row)
    return rows


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
    labels: dict[str, object] = {}
    if not matches:
        return _empty_forward_labels(horizons)
    signal_index = matches[0]
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
        value = (
            None
            if entry_price is None or exit_price is None or entry_price <= 0
            else exit_price / entry_price - 1
        )
        labels[f"forward_return_{prefix}"] = value
        labels[f"forward_label_available_{prefix}"] = value is not None
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


def _summary_rows(
    *,
    daily_rows: list[dict[str, object]],
    horizons: tuple[int, ...],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    frame = pd.DataFrame(daily_rows)
    if frame.empty:
        return rows
    group_columns = ["trend_phase_code", "trend_phase_label", "trend_phase_direction"]
    for key, group in frame.groupby(group_columns, dropna=False):
        phase_code, phase_label, phase_direction = key
        for horizon in horizons:
            return_column = f"forward_return_h{horizon}"
            values = pd.to_numeric(group[return_column], errors="coerce").dropna()
            observation_count = int(len(values))
            row = {
                "phase_code": phase_code,
                "phase_label": phase_label,
                "phase_direction": phase_direction,
                "horizon": horizon,
                "signal_day_count": int(len(group)),
                "observation_count": observation_count,
                "mean_forward_return": None,
                "median_forward_return": None,
                "positive_rate": None,
                "negative_rate": None,
                "directional_hit_rate": None,
                "validation_rule_version": TREND_PHASE_VALIDATION_RULE_VERSION,
            }
            if observation_count:
                row["mean_forward_return"] = float(values.mean())
                row["median_forward_return"] = float(values.median())
                row["positive_rate"] = float((values > 0).mean())
                row["negative_rate"] = float((values < 0).mean())
                if phase_direction == "long":
                    row["directional_hit_rate"] = float((values > 0).mean())
                elif phase_direction == "short":
                    row["directional_hit_rate"] = float((values < 0).mean())
            rows.append(row)
    return sorted(rows, key=lambda item: (str(item["phase_code"]), int(item["horizon"])))


def _warning_records(
    *,
    run_id: str,
    daily_rows: list[dict[str, object]],
    summary_rows: list[dict[str, object]],
    horizons: tuple[int, ...],
) -> tuple[TrendPhaseValidationWarningRecord, ...]:
    records = [
        _warning(
            run_id=run_id,
            section="research_boundary",
            severity=INFO_SEVERITY,
            warning_code="R25_FORWARD_RETURNS_ARE_VALIDATION_LABELS",
            warning_message="forward_return_* 仅用于后验验证，趋势阶段判断未使用未来数据。",
            affected_count=len(daily_rows),
            human_review_required=(),
        )
    ]
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
                    warning_code=f"R25_FORWARD_LABEL_MISSING_H{horizon}",
                    warning_message=(
                        f"horizon={horizon} 有 {missing_count} 个交易日缺少后验收益标签。"
                    ),
                    affected_count=missing_count,
                    human_review_required=("forward_return_horizon_set",),
                )
            )
    s0_count = sum(1 for row in daily_rows if row.get("trend_phase_code") == "S0")
    if s0_count:
        records.append(
            _warning(
                run_id=run_id,
                section="trend_phase",
                severity=WARNING_SEVERITY,
                warning_code="R25_S0_UNCONFIRMED_PRESENT",
                warning_message=f"窗口内有 {s0_count} 个交易日处于 S0 未确认状态。",
                affected_count=s0_count,
                human_review_required=("trend_phase_rules", "factor_thresholds"),
            )
        )
    if not summary_rows:
        records.append(
            _warning(
                run_id=run_id,
                section="summary",
                severity=WARNING_SEVERITY,
                warning_code="R25_EMPTY_SUMMARY",
                warning_message="未生成趋势阶段表现汇总。",
                affected_count=0,
                human_review_required=HUMAN_REVIEW_REQUIRED,
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
) -> TrendPhaseValidationWarningRecord:
    return TrendPhaseValidationWarningRecord(
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
    warnings: tuple[TrendPhaseValidationWarningRecord, ...],
    csv_path: Path,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows([warning.to_csv_row() for warning in warnings])


def _write_markdown(
    *,
    result: ResearchTrendPhaseValidationResult,
    daily_rows: list[dict[str, object]],
    summary_rows: list[dict[str, object]],
) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    phase_counts = _phase_counts(daily_rows)
    lines = [
        f"# CF 趋势阶段滚动验证 - {result.start.isoformat()} 至 {result.end.isoformat()}",
        "",
        "## 一、数据状态",
        "",
        f"- Run ID：`{result.run_id}`",
        f"- 核心表：`{result.core_quote_path}`",
        f"- 逐日阶段行数：`{result.daily_row_count}`",
        f"- 汇总行数：`{result.summary_row_count}`",
        f"- 验证 horizon：`{','.join(str(item) for item in result.horizons)}`",
        "",
        "## 二、阶段分布",
        "",
        "| 阶段 | 天数 |",
        "| --- | ---: |",
    ]
    lines.extend(f"| {phase} | {count} |" for phase, count in phase_counts)
    lines.extend(
        [
            "",
            "## 三、阶段后验表现",
            "",
            "| 阶段 | 方向 | Horizon | 样本数 | 平均后验收益 | 方向命中率 |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in summary_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"{row['phase_code']} {row['phase_label']}",
                    str(row["phase_direction"]),
                    str(row["horizon"]),
                    str(row["observation_count"]),
                    _fmt_percent(row["mean_forward_return"]),
                    _fmt_percent(row["directional_hit_rate"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 四、最新样本",
            "",
            "| 日期 | 主力 | 多因子方向 | 阶段 | 后验标签可用性 |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in daily_rows[-10:]:
        availability = ", ".join(
            f"h{horizon}={bool(row.get(f'forward_label_available_h{horizon}'))}"
            for horizon in result.horizons
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["trade_date"]),
                    str(row["main_contract"]),
                    str(row["multi_factor_direction"]),
                    f"{row['trend_phase_code']} {row['trend_phase_label']}",
                    availability,
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 五、研究边界",
            "",
            "- 趋势阶段判断只使用 T 日及以前可观察数据。",
            "- forward_return_* 是后验验证标签，不参与当日阶段判断。",
            "- 主力合约按当日持仓量优先、成交量次优识别，仍需人工复核合约规则。",
            "- 本报告不构成交易指令。",
            "",
            "## 六、人工复核项",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_manifest(*, result: ResearchTrendPhaseValidationResult) -> None:
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **result.to_summary(),
        "report_type": "trend_phase_validation",
        "rule_version": TREND_PHASE_VALIDATION_RULE_VERSION,
        "generated_at": utc_now().isoformat(),
        "phase_no_lookahead": True,
        "forward_returns_are_validation_labels": True,
    }
    result.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
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


def _phase_counts(daily_rows: list[dict[str, object]]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for row in daily_rows:
        label = f"{row['trend_phase_code']} {row['trend_phase_label']}"
        counts[label] = counts.get(label, 0) + 1
    return sorted(counts.items())


def _output_paths(*, start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_trend_phase_validation"
    return {
        "daily_parquet": root / f"{stem}_daily.parquet",
        "daily_csv": root / f"{stem}_daily.csv",
        "summary_parquet": root / f"{stem}_summary.parquet",
        "summary_csv": root / f"{stem}_summary.csv",
        "warning_csv": root / f"{stem}_warnings.csv",
        "manifest": root / f"{stem}_manifest.json",
    }


def _markdown_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_trend_phase_validation"
    return root / f"{stem}.md"


def _fmt_percent(value: object) -> str:
    numeric = r23._float_or_none(value)
    if numeric is None:
        return "NA"
    return f"{numeric:.2%}"


def _default_run_id(*, start: date, end: date) -> str:
    return f"r25_trend_phase_validation_{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
