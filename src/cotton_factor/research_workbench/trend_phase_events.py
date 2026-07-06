"""R26 event study for CF trend phase transitions."""

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
from cotton_factor.research_workbench.trend_phase_validation import (
    DEFAULT_HORIZONS,
    PRODUCT_CODE,
    TREND_PHASE_VALIDATION_RULE_VERSION,
    build_cf_trend_phase_validation,
)
from cotton_factor.research_workbench.trend_phase_validation import (
    OUTPUT_DIR as R25_OUTPUT_DIR,
)

TREND_PHASE_EVENT_RULE_VERSION = "R26_trend_phase_transition_events_v2_r30_taxonomy"
OUTPUT_DIR = "trend_phase_events"
WARNING_SEVERITY = "WARN"
INFO_SEVERITY = "INFO"
HUMAN_REVIEW_REQUIRED = (
    "trend_phase_transition_taxonomy",
    "trend_phase_rules",
    "event_outcome_horizon_set",
    "main_contract_target_assumption",
)

KEY_TRANSITIONS = {
    "S0_TO_S1": "起点观察出现",
    "S0_TO_S3": "未确认转衰竭观察",
    "S1_TO_S2": "趋势起点确认",
    "S2_TO_S3": "衰竭观察出现",
    "S3_TO_S0": "衰竭观察降级未确认",
    "S3_TO_S4": "趋势终点确认",
    "S4_TO_S0": "终点后重置观察",
}

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
class TrendPhaseEventWarningRecord:
    """Warning row for R26 trend phase event study."""

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
class ResearchTrendPhaseEventResult:
    """Result of building R26 trend phase transition event artifacts."""

    product_code: str
    run_id: str
    start: date
    end: date
    horizons: tuple[int, ...]
    event_count: int
    summary_row_count: int
    key_event_count: int
    warning_records: tuple[TrendPhaseEventWarningRecord, ...]
    event_parquet_path: Path
    event_csv_path: Path
    summary_parquet_path: Path
    summary_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    manifest_path: Path
    trend_phase_daily_path: Path
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
            "event_count": self.event_count,
            "summary_row_count": self.summary_row_count,
            "key_event_count": self.key_event_count,
            "warning_count": self.warning_count,
            "event_parquet_path": str(self.event_parquet_path),
            "event_csv_path": str(self.event_csv_path),
            "summary_parquet_path": str(self.summary_parquet_path),
            "summary_csv_path": str(self.summary_csv_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "manifest_path": str(self.manifest_path),
            "trend_phase_daily_path": str(self.trend_phase_daily_path),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_trend_phase_events(
    *,
    start: date,
    end: date,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    trend_phase_daily_path: Path | None = None,
    core_quote_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchTrendPhaseEventResult:
    """Build R26 transition event rows from R25 daily trend phase rows."""
    if start > end:
        raise ResearchWorkbenchError("start must be <= end")
    normalized_horizons = _normalize_horizons(horizons)
    daily_path = _resolve_daily_path(
        start=start,
        end=end,
        horizons=normalized_horizons,
        trend_phase_daily_path=trend_phase_daily_path,
        core_quote_path=core_quote_path,
    )
    daily_rows = _load_daily_rows(
        input_path=daily_path,
        start=start,
        end=end,
        horizons=normalized_horizons,
    )
    event_run_id = run_id or _default_run_id(start=start, end=end)
    event_rows = _event_rows(
        daily_rows=daily_rows,
        horizons=normalized_horizons,
        run_id=event_run_id,
    )
    summary_rows = _summary_rows(event_rows=event_rows, horizons=normalized_horizons)
    warnings = _warning_records(
        run_id=event_run_id,
        daily_rows=daily_rows,
        event_rows=event_rows,
        summary_rows=summary_rows,
    )
    paths = _output_paths(start=start, end=end, output_dir=output_dir)
    markdown_path = _markdown_path(start=start, end=end, report_output_dir=report_output_dir)

    # R26 只研究阶段切换事件，事件后收益标签仍是后验验证，不进入事件识别逻辑。
    _write_table(rows=event_rows, parquet_path=paths["event_parquet"], csv_path=paths["event_csv"])
    _write_table(
        rows=summary_rows,
        parquet_path=paths["summary_parquet"],
        csv_path=paths["summary_csv"],
    )
    _write_warning_csv(warnings=warnings, csv_path=paths["warning_csv"])
    result = ResearchTrendPhaseEventResult(
        product_code=PRODUCT_CODE,
        run_id=event_run_id,
        start=start,
        end=end,
        horizons=normalized_horizons,
        event_count=len(event_rows),
        summary_row_count=len(summary_rows),
        key_event_count=sum(1 for row in event_rows if bool(row["is_key_transition"])),
        warning_records=warnings,
        event_parquet_path=paths["event_parquet"],
        event_csv_path=paths["event_csv"],
        summary_parquet_path=paths["summary_parquet"],
        summary_csv_path=paths["summary_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=markdown_path,
        manifest_path=paths["manifest"],
        trend_phase_daily_path=daily_path,
        human_review_required=HUMAN_REVIEW_REQUIRED,
    )
    _write_markdown(result=result, event_rows=event_rows, summary_rows=summary_rows)
    _write_manifest(result=result)
    return result


def _resolve_daily_path(
    *,
    start: date,
    end: date,
    horizons: tuple[int, ...],
    trend_phase_daily_path: Path | None,
    core_quote_path: Path | None,
) -> Path:
    if trend_phase_daily_path is not None:
        if not trend_phase_daily_path.exists():
            raise ResearchWorkbenchError(
                f"trend phase daily parquet not found: {trend_phase_daily_path}"
            )
        return trend_phase_daily_path
    default_path = _default_r25_daily_path(start=start, end=end)
    if default_path.exists():
        return default_path
    if core_quote_path is None:
        raise ResearchWorkbenchError(
            f"trend phase daily parquet not found: {default_path}; "
            "provide --core-quote-path to build it"
        )
    validation = build_cf_trend_phase_validation(
        start=start,
        end=end,
        horizons=horizons,
        core_quote_path=core_quote_path,
        run_id=f"r26_auto_r25_{start.isoformat()}_{end.isoformat()}",
    )
    return validation.daily_parquet_path


def _load_daily_rows(
    *,
    input_path: Path,
    start: date,
    end: date,
    horizons: tuple[int, ...],
) -> list[dict[str, object]]:
    frame = pd.read_parquet(input_path)
    required = {
        "trade_date",
        "main_contract",
        "trend_phase_code",
        "trend_phase_label",
        "trend_phase_direction",
        "multi_factor_direction",
        "multi_factor_score",
        "validation_rule_version",
    }
    required.update(f"forward_return_h{horizon}" for horizon in horizons)
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"trend phase daily table missing columns: {missing}")
    working = frame.copy()
    working["_trade_date"] = pd.to_datetime(working["trade_date"]).dt.date
    selected = working.loc[
        (working["_trade_date"] >= start) & (working["_trade_date"] <= end)
    ].copy()
    if selected.empty:
        raise ResearchWorkbenchError(
            f"trend phase daily table has no rows from {start.isoformat()} to {end.isoformat()}"
        )
    selected = selected.sort_values("_trade_date").reset_index(drop=True)
    return selected.drop(columns=["_trade_date"]).to_dict(orient="records")


def _event_rows(
    *,
    daily_rows: list[dict[str, object]],
    horizons: tuple[int, ...],
    run_id: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(1, len(daily_rows)):
        previous = daily_rows[index - 1]
        current = daily_rows[index]
        previous_code = str(previous["trend_phase_code"])
        current_code = str(current["trend_phase_code"])
        previous_direction = str(previous["trend_phase_direction"])
        current_direction = str(current["trend_phase_direction"])
        if previous_code == current_code and previous_direction == current_direction:
            continue
        transition_code = f"{previous_code}_TO_{current_code}"
        event_type = _event_type(transition_code=transition_code)
        row = {
            "run_id": run_id,
            "product_code": PRODUCT_CODE,
            "event_date": current["trade_date"],
            "previous_date": previous["trade_date"],
            "main_contract": current["main_contract"],
            "previous_main_contract": previous["main_contract"],
            "contract_changed": current["main_contract"] != previous["main_contract"],
            "previous_phase_code": previous_code,
            "previous_phase_label": previous["trend_phase_label"],
            "previous_phase_direction": previous_direction,
            "new_phase_code": current_code,
            "new_phase_label": current["trend_phase_label"],
            "new_phase_direction": current_direction,
            "transition_code": transition_code,
            "event_type": event_type,
            "is_key_transition": transition_code in KEY_TRANSITIONS,
            "previous_multi_factor_direction": previous["multi_factor_direction"],
            "new_multi_factor_direction": current["multi_factor_direction"],
            "previous_multi_factor_score": previous["multi_factor_score"],
            "new_multi_factor_score": current["multi_factor_score"],
            "score_change": _numeric(current["multi_factor_score"])
            - _numeric(previous["multi_factor_score"]),
            "event_main_settle": current.get("main_settle"),
            "event_return_20d": current.get("return_20d"),
            "event_oi_pressure": current.get("main_oi_pressure"),
            "event_curve_slope": current.get("curve_slope"),
            "event_carry_annualized": current.get("carry_annualized"),
            "event_reason": _event_reason(transition_code=transition_code),
            "source_validation_rule_version": current["validation_rule_version"],
            "event_rule_version": TREND_PHASE_EVENT_RULE_VERSION,
        }
        for horizon in horizons:
            return_value = _maybe_float(current.get(f"forward_return_h{horizon}"))
            row[f"forward_return_h{horizon}"] = return_value
            row[f"forward_label_available_h{horizon}"] = return_value is not None
            row[f"event_direction_hit_h{horizon}"] = _direction_hit(
                direction=current_direction,
                forward_return=return_value,
            )
            row[f"execution_date_h{horizon}"] = current.get(f"execution_date_h{horizon}")
            row[f"exit_date_h{horizon}"] = current.get(f"exit_date_h{horizon}")
        rows.append(row)
    return rows


def _summary_rows(
    *,
    event_rows: list[dict[str, object]],
    horizons: tuple[int, ...],
) -> list[dict[str, object]]:
    if not event_rows:
        return []
    frame = pd.DataFrame(event_rows)
    rows: list[dict[str, object]] = []
    group_columns = ["transition_code", "event_type", "new_phase_direction"]
    for key, group in frame.groupby(group_columns, dropna=False):
        transition_code, event_type, new_direction = key
        for horizon in horizons:
            values = pd.to_numeric(group[f"forward_return_h{horizon}"], errors="coerce").dropna()
            hits = group[f"event_direction_hit_h{horizon}"].dropna()
            row = {
                "transition_code": transition_code,
                "event_type": event_type,
                "new_phase_direction": new_direction,
                "horizon": horizon,
                "event_count": int(len(group)),
                "observation_count": int(len(values)),
                "mean_forward_return": None,
                "median_forward_return": None,
                "positive_rate": None,
                "negative_rate": None,
                "directional_hit_rate": None,
                "event_rule_version": TREND_PHASE_EVENT_RULE_VERSION,
            }
            if len(values):
                row["mean_forward_return"] = float(values.mean())
                row["median_forward_return"] = float(values.median())
                row["positive_rate"] = float((values > 0).mean())
                row["negative_rate"] = float((values < 0).mean())
            if len(hits):
                row["directional_hit_rate"] = float(hits.astype(bool).mean())
            rows.append(row)
    return sorted(rows, key=lambda item: (str(item["transition_code"]), int(item["horizon"])))


def _warning_records(
    *,
    run_id: str,
    daily_rows: list[dict[str, object]],
    event_rows: list[dict[str, object]],
    summary_rows: list[dict[str, object]],
) -> tuple[TrendPhaseEventWarningRecord, ...]:
    records = [
        _warning(
            run_id=run_id,
            section="research_boundary",
            severity=INFO_SEVERITY,
            warning_code="R26_EVENTS_USE_R25_PHASE_ROWS",
            warning_message="事件识别只使用 R25 逐日阶段行，forward_return_* 仅用于事件后验验证。",
            affected_count=len(daily_rows),
            human_review_required=(),
        )
    ]
    if not event_rows:
        records.append(
            _warning(
                run_id=run_id,
                section="events",
                severity=WARNING_SEVERITY,
                warning_code="R26_NO_PHASE_TRANSITION_EVENTS",
                warning_message="窗口内没有阶段切换事件。",
                affected_count=0,
                human_review_required=("trend_phase_transition_taxonomy",),
            )
        )
    contract_change_count = sum(1 for row in event_rows if bool(row["contract_changed"]))
    if contract_change_count:
        records.append(
            _warning(
                run_id=run_id,
                section="contracts",
                severity=WARNING_SEVERITY,
                warning_code="R26_EVENT_CONTRACT_CHANGED",
                warning_message=f"有 {contract_change_count} 个阶段事件发生在主力合约切换日。",
                affected_count=contract_change_count,
                human_review_required=("main_contract_target_assumption",),
            )
        )
    if not summary_rows:
        records.append(
            _warning(
                run_id=run_id,
                section="summary",
                severity=WARNING_SEVERITY,
                warning_code="R26_EMPTY_EVENT_SUMMARY",
                warning_message="未生成阶段事件表现汇总。",
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
) -> TrendPhaseEventWarningRecord:
    return TrendPhaseEventWarningRecord(
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
    warnings: tuple[TrendPhaseEventWarningRecord, ...],
    csv_path: Path,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows([warning.to_csv_row() for warning in warnings])


def _write_markdown(
    *,
    result: ResearchTrendPhaseEventResult,
    event_rows: list[dict[str, object]],
    summary_rows: list[dict[str, object]],
) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# CF 趋势阶段切换事件研究 - {result.start.isoformat()} 至 {result.end.isoformat()}",
        "",
        "## 一、数据状态",
        "",
        f"- Run ID：`{result.run_id}`",
        f"- R25 逐日阶段表：`{result.trend_phase_daily_path}`",
        f"- 阶段切换事件数：`{result.event_count}`",
        f"- 关键切换事件数：`{result.key_event_count}`",
        f"- 验证 horizon：`{','.join(str(item) for item in result.horizons)}`",
        "",
        "## 二、关键事件列表",
        "",
        "| 日期 | 切换 | 事件类型 | 主力 | 多因子变化 |",
        "| --- | --- | --- | --- | ---: |",
    ]
    for row in [item for item in event_rows if bool(item["is_key_transition"])][-20:]:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["event_date"]),
                    f"{row['previous_phase_code']} -> {row['new_phase_code']}",
                    str(row["event_type"]),
                    str(row["main_contract"]),
                    _fmt_number(row["score_change"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 三、事件后验表现",
            "",
            "| 切换 | 事件类型 | Horizon | 样本数 | 平均后验收益 | 方向命中率 |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in summary_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["transition_code"]),
                    str(row["event_type"]),
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
            "## 四、研究边界",
            "",
            "- 阶段切换事件只来自 R25 逐日阶段表。",
            "- forward_return_* 是事件后的后验验证标签，不参与事件识别。",
            "- 事件类型映射仍是研究假设，需要人工复核。",
            "- 本报告不构成交易指令。",
            "",
            "## 五、人工复核项",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_manifest(*, result: ResearchTrendPhaseEventResult) -> None:
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **result.to_summary(),
        "report_type": "trend_phase_transition_events",
        "rule_version": TREND_PHASE_EVENT_RULE_VERSION,
        "source_validation_rule_version": TREND_PHASE_VALIDATION_RULE_VERSION,
        "generated_at": utc_now().isoformat(),
        "event_no_lookahead": True,
        "forward_returns_are_validation_labels": True,
    }
    result.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _event_type(*, transition_code: str) -> str:
    return KEY_TRANSITIONS.get(transition_code, "阶段切换观察")


def _event_reason(*, transition_code: str) -> str:
    if transition_code == "S0_TO_S3":
        return "未确认状态直接转入衰竭观察，重点验证是否属于震荡修复后的质量下降。"
    if transition_code == "S1_TO_S2":
        return "起点观察升级为趋势中，重点验证后续收益是否支持趋势起点。"
    if transition_code == "S2_TO_S3":
        return "趋势中转为衰竭观察，重点验证后续收益是否降温或反转。"
    if transition_code == "S3_TO_S0":
        return "衰竭观察降级为未确认，重点验证信号分歧是否导致趋势解释失效。"
    if transition_code == "S3_TO_S4":
        return "衰竭观察升级为终点确认，重点验证原方向趋势是否结束。"
    return "阶段发生切换，保留为研究事件等待样本验证。"


def _direction_hit(*, direction: str, forward_return: float | None) -> bool | None:
    if forward_return is None:
        return None
    if direction == "long":
        return forward_return > 0
    if direction == "short":
        return forward_return < 0
    return None


def _normalize_horizons(horizons: tuple[int, ...]) -> tuple[int, ...]:
    if not horizons:
        raise ResearchWorkbenchError("at least one horizon is required")
    values = tuple(sorted(set(horizons)))
    invalid = [horizon for horizon in values if horizon <= 0]
    if invalid:
        raise ResearchWorkbenchError(f"horizons must be positive integers: {invalid}")
    return values


def _default_r25_daily_path(*, start: date, end: date) -> Path:
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_trend_phase_validation"
    return data_dir() / "research" / PRODUCT_CODE / R25_OUTPUT_DIR / f"{stem}_daily.parquet"


def _output_paths(*, start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_trend_phase_events"
    return {
        "event_parquet": root / f"{stem}_events.parquet",
        "event_csv": root / f"{stem}_events.csv",
        "summary_parquet": root / f"{stem}_summary.parquet",
        "summary_csv": root / f"{stem}_summary.csv",
        "warning_csv": root / f"{stem}_warnings.csv",
        "manifest": root / f"{stem}_manifest.json",
    }


def _markdown_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_trend_phase_events"
    return root / f"{stem}.md"


def _maybe_float(value: object) -> float | None:
    if value is None:
        return None
    if pd.isna(value):
        return None
    return float(value)


def _numeric(value: object) -> float:
    numeric = _maybe_float(value)
    return 0.0 if numeric is None else numeric


def _fmt_number(value: object) -> str:
    numeric = _maybe_float(value)
    if numeric is None:
        return "NA"
    if abs(numeric - round(numeric)) < 1e-9:
        return f"{numeric:.0f}"
    return f"{numeric:.4f}"


def _fmt_percent(value: object) -> str:
    numeric = _maybe_float(value)
    if numeric is None:
        return "NA"
    return f"{numeric:.2%}"


def _default_run_id(*, start: date, end: date) -> str:
    return f"r26_trend_phase_events_{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
