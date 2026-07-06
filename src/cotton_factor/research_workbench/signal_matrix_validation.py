"""R36 rolling validation for the R35 CF signal matrix."""

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
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME
from cotton_factor.research_workbench.signal_matrix import SIGNAL_MATRIX_VERSION

PRODUCT_CODE = "CF"
SIGNAL_MATRIX_VALIDATION_VERSION = "R36_signal_matrix_rolling_validation_v1"
OUTPUT_DIR = "signal_matrix_validation"
WARNING_SEVERITY = "WARN"
INFO_SEVERITY = "INFO"
HUMAN_REVIEW_REQUIRED = (
    "rolling_window_definition",
    "forward_return_horizon_set",
    "main_contract_target_assumption",
    "signal_matrix_weighting",
    "factor_thresholds",
    "contract_rule_assumptions",
)

REQUIRED_MATRIX_COLUMNS = {
    "trade_date",
    "horizon",
    "main_contract",
    "direction",
    "trend_phase",
    "confidence",
    "confidence_score",
    "evidence_level",
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
class SignalMatrixValidationWarningRecord:
    """Warning row for R36 rolling validation."""

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
class ResearchSignalMatrixValidationResult:
    """Result of building R36 rolling validation artifacts."""

    product_code: str
    run_id: str
    start: date
    end: date
    windows: tuple[str, ...]
    daily_row_count: int
    window_summary_row_count: int
    phase_summary_row_count: int
    warning_records: tuple[SignalMatrixValidationWarningRecord, ...]
    daily_parquet_path: Path
    daily_csv_path: Path
    window_summary_parquet_path: Path
    window_summary_csv_path: Path
    phase_summary_parquet_path: Path
    phase_summary_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    signal_matrix_path: Path
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
            "windows": list(self.windows),
            "daily_row_count": self.daily_row_count,
            "window_summary_row_count": self.window_summary_row_count,
            "phase_summary_row_count": self.phase_summary_row_count,
            "warning_count": self.warning_count,
            "daily_parquet_path": str(self.daily_parquet_path),
            "daily_csv_path": str(self.daily_csv_path),
            "window_summary_parquet_path": str(self.window_summary_parquet_path),
            "window_summary_csv_path": str(self.window_summary_csv_path),
            "phase_summary_parquet_path": str(self.phase_summary_parquet_path),
            "phase_summary_csv_path": str(self.phase_summary_csv_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "signal_matrix_path": str(self.signal_matrix_path),
            "core_quote_path": str(self.core_quote_path),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_signal_matrix_validation(
    *,
    signal_matrix_path: Path,
    core_quote_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    windows: tuple[str, ...] | None = None,
) -> ResearchSignalMatrixValidationResult:
    """Validate the R35 matrix with T+1 forward returns in rolling windows."""
    matrix = _load_signal_matrix(signal_matrix_path)
    quote_path = core_quote_path or data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    quotes = r23._load_core_quotes(input_path=quote_path)
    start = min(matrix["trade_date"])
    end = max(matrix["trade_date"])
    window_specs = _resolve_windows(matrix=matrix, windows=windows)
    validation_run_id = run_id or _default_run_id(start=start, end=end)

    # R36 才允许生成 forward_return 验证标签；这些标签只用于后验验证，不反哺 R35/R38。
    daily_rows = _daily_validation_rows(
        matrix=matrix,
        quotes=quotes,
        windows=window_specs,
        run_id=validation_run_id,
    )
    window_summary_rows = _window_summary_rows(daily_rows=daily_rows)
    phase_summary_rows = _phase_summary_rows(daily_rows=daily_rows)
    warnings = _warning_records(run_id=validation_run_id, daily_rows=daily_rows)
    paths = _output_paths(start=start, end=end, output_dir=output_dir)
    markdown_path = _markdown_path(start=start, end=end, report_output_dir=report_output_dir)
    json_path = _json_path(start=start, end=end, report_output_dir=report_output_dir)
    result = ResearchSignalMatrixValidationResult(
        product_code=PRODUCT_CODE,
        run_id=validation_run_id,
        start=start,
        end=end,
        windows=tuple(item["window_id"] for item in window_specs),
        daily_row_count=len(daily_rows),
        window_summary_row_count=len(window_summary_rows),
        phase_summary_row_count=len(phase_summary_rows),
        warning_records=warnings,
        daily_parquet_path=paths["daily_parquet"],
        daily_csv_path=paths["daily_csv"],
        window_summary_parquet_path=paths["window_summary_parquet"],
        window_summary_csv_path=paths["window_summary_csv"],
        phase_summary_parquet_path=paths["phase_summary_parquet"],
        phase_summary_csv_path=paths["phase_summary_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=markdown_path,
        json_path=json_path,
        manifest_path=paths["manifest"],
        signal_matrix_path=signal_matrix_path,
        core_quote_path=quote_path,
        human_review_required=_human_review_required(warnings),
    )
    _write_table(
        rows=daily_rows,
        parquet_path=result.daily_parquet_path,
        csv_path=result.daily_csv_path,
    )
    _write_table(
        rows=window_summary_rows,
        parquet_path=result.window_summary_parquet_path,
        csv_path=result.window_summary_csv_path,
    )
    _write_table(
        rows=phase_summary_rows,
        parquet_path=result.phase_summary_parquet_path,
        csv_path=result.phase_summary_csv_path,
    )
    _write_warning_csv(warnings=warnings, csv_path=result.warning_csv_path)
    _write_markdown(
        result=result,
        window_summary_rows=window_summary_rows,
        phase_summary_rows=phase_summary_rows,
    )
    _write_json(
        result=result,
        window_summary_rows=window_summary_rows,
        phase_summary_rows=phase_summary_rows,
    )
    _write_manifest(result=result)
    return result


def _load_signal_matrix(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"signal matrix table not found: {path}")
    frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
    missing = sorted(REQUIRED_MATRIX_COLUMNS - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"signal matrix missing columns: {missing}")
    working = frame.copy()
    working["trade_date"] = pd.to_datetime(working["trade_date"]).dt.date
    working["horizon"] = pd.to_numeric(working["horizon"], errors="coerce").astype("Int64")
    working = working.dropna(subset=["trade_date", "horizon", "main_contract"])
    working["horizon"] = working["horizon"].astype(int)
    working = working.loc[working["horizon"] > 0].copy()
    if working.empty:
        raise ResearchWorkbenchError("signal matrix has no usable rows")
    return working.sort_values(["trade_date", "horizon"]).reset_index(drop=True)


def _resolve_windows(
    *,
    matrix: pd.DataFrame,
    windows: tuple[str, ...] | None,
) -> tuple[dict[str, object], ...]:
    if windows:
        return tuple(_parse_window_spec(item) for item in windows)
    years = sorted({value.year for value in matrix["trade_date"]})
    if len(years) == 1:
        year = years[0]
        return ({"window_id": str(year), "start": date(year, 1, 1), "end": date(year, 12, 31)},)
    return tuple(
        {
            "window_id": f"{left}-{right}",
            "start": date(left, 1, 1),
            "end": date(right, 12, 31),
        }
        for left, right in zip(years, years[1:], strict=False)
    )


def _parse_window_spec(value: str) -> dict[str, object]:
    cleaned = value.strip()
    if not cleaned:
        raise ResearchWorkbenchError("window spec must be non-empty")
    if "-" not in cleaned:
        year = int(cleaned)
        return {"window_id": cleaned, "start": date(year, 1, 1), "end": date(year, 12, 31)}
    left_raw, right_raw = cleaned.split("-", 1)
    left = int(left_raw)
    right = int(right_raw)
    if left > right:
        raise ResearchWorkbenchError(f"window start year must be <= end year: {cleaned}")
    return {"window_id": cleaned, "start": date(left, 1, 1), "end": date(right, 12, 31)}


def _daily_validation_rows(
    *,
    matrix: pd.DataFrame,
    quotes: pd.DataFrame,
    windows: tuple[dict[str, object], ...],
    run_id: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in matrix.to_dict(orient="records"):
        trade_date = item["trade_date"]
        assert isinstance(trade_date, date)
        window = _window_for_date(trade_date=trade_date, windows=windows)
        if window is None:
            continue
        horizon = int(item["horizon"])
        labels = _forward_label(
            quotes=quotes,
            trade_date=trade_date,
            contract_code=str(item["main_contract"]),
            horizon=horizon,
        )
        direction = str(item["direction"])
        forward_return = r23._float_or_none(labels["forward_return"])
        directional_hit = _directional_hit(direction=direction, forward_return=forward_return)
        value = dict(item)
        value.update(
            {
                "run_id": run_id,
                "window_id": window["window_id"],
                "window_start": window["start"],
                "window_end": window["end"],
                "forward_return": forward_return,
                "forward_label_available": labels["forward_label_available"],
                "execution_date": labels["execution_date"],
                "exit_date": labels["exit_date"],
                "directional_hit": directional_hit,
                "validation_rule_version": SIGNAL_MATRIX_VALIDATION_VERSION,
                "forward_returns_are_validation_labels": True,
            }
        )
        rows.append(_json_safe(value))
    return rows


def _window_for_date(
    *,
    trade_date: date,
    windows: tuple[dict[str, object], ...],
) -> dict[str, object] | None:
    for window in windows:
        start = window["start"]
        end = window["end"]
        assert isinstance(start, date)
        assert isinstance(end, date)
        if start <= trade_date <= end:
            return window
    return None


def _forward_label(
    *,
    quotes: pd.DataFrame,
    trade_date: date,
    contract_code: str,
    horizon: int,
) -> dict[str, object]:
    series = quotes.loc[quotes["contract_code"].astype(str) == contract_code].copy()
    series = series.sort_values("trade_date").reset_index(drop=True)
    matches = series.index[series["trade_date"] == trade_date].tolist()
    if not matches:
        return _empty_forward_label()
    signal_index = int(matches[0])
    entry_index = signal_index + 1
    exit_index = entry_index + horizon
    if entry_index >= len(series) or exit_index >= len(series):
        return _empty_forward_label()
    entry = series.iloc[entry_index]
    exit_row = series.iloc[exit_index]
    entry_price = r23._float_or_none(entry["settle"])
    exit_price = r23._float_or_none(exit_row["settle"])
    forward_return = (
        None
        if entry_price is None or exit_price is None or entry_price <= 0
        else exit_price / entry_price - 1
    )
    return {
        "forward_return": forward_return,
        "forward_label_available": forward_return is not None,
        "execution_date": entry["trade_date"].isoformat(),
        "exit_date": exit_row["trade_date"].isoformat(),
    }


def _empty_forward_label() -> dict[str, object]:
    return {
        "forward_return": None,
        "forward_label_available": False,
        "execution_date": None,
        "exit_date": None,
    }


def _directional_hit(*, direction: str, forward_return: float | None) -> bool | None:
    if forward_return is None or direction not in {"long", "short"}:
        return None
    if direction == "long":
        return forward_return > 0
    return forward_return < 0


def _window_summary_rows(*, daily_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    frame = pd.DataFrame(daily_rows)
    if frame.empty:
        return []
    rows: list[dict[str, object]] = []
    for key, group in frame.groupby(["window_id", "horizon"], sort=True, dropna=False):
        window_id, horizon = key
        rows.append(
            _summary_row(
                group=group,
                key_fields={"window_id": window_id, "horizon": horizon},
            )
        )
    return rows


def _phase_summary_rows(*, daily_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    frame = pd.DataFrame(daily_rows)
    if frame.empty:
        return []
    rows: list[dict[str, object]] = []
    for key, group in frame.groupby(["trend_phase", "horizon"], sort=True, dropna=False):
        trend_phase, horizon = key
        rows.append(
            _summary_row(group=group, key_fields={"trend_phase": trend_phase, "horizon": horizon})
        )
    return rows


def _summary_row(*, group: pd.DataFrame, key_fields: dict[str, object]) -> dict[str, object]:
    returns = pd.to_numeric(group["forward_return"], errors="coerce").dropna()
    hit_values = group["directional_hit"].dropna()
    long_count = int((group["direction"].astype(str) == "long").sum())
    short_count = int((group["direction"].astype(str) == "short").sum())
    row = {
        **key_fields,
        "signal_row_count": int(len(group)),
        "observation_count": int(len(returns)),
        "long_count": long_count,
        "short_count": short_count,
        "neutral_count": int((group["direction"].astype(str) == "neutral").sum()),
        "mean_forward_return": None,
        "median_forward_return": None,
        "positive_rate": None,
        "negative_rate": None,
        "directional_observation_count": int(len(hit_values)),
        "directional_hit_rate": None,
        "validation_rule_version": SIGNAL_MATRIX_VALIDATION_VERSION,
    }
    if len(returns):
        row["mean_forward_return"] = float(returns.mean())
        row["median_forward_return"] = float(returns.median())
        row["positive_rate"] = float((returns > 0).mean())
        row["negative_rate"] = float((returns < 0).mean())
    if len(hit_values):
        row["directional_hit_rate"] = float(hit_values.astype(bool).mean())
    return row


def _warning_records(
    *,
    run_id: str,
    daily_rows: list[dict[str, object]],
) -> tuple[SignalMatrixValidationWarningRecord, ...]:
    records = [
        _warning(
            run_id=run_id,
            section="research_boundary",
            severity=INFO_SEVERITY,
            warning_code="R36_FORWARD_RETURNS_ARE_VALIDATION_LABELS",
            warning_message="R36 forward_return 仅用于历史后验验证，不参与最新日信号生成。",
            affected_count=len(daily_rows),
            human_review_required=(),
        )
    ]
    missing_count = sum(not bool(row.get("forward_label_available")) for row in daily_rows)
    if missing_count:
        records.append(
            _warning(
                run_id=run_id,
                section="forward_returns",
                severity=WARNING_SEVERITY,
                warning_code="R36_FORWARD_LABEL_MISSING",
                warning_message="部分矩阵行缺少 T+1 后验收益标签，通常来自样本尾部或合约历史不足。",
                affected_count=missing_count,
                human_review_required=("forward_return_horizon_set",),
            )
        )
    if len(daily_rows) < 100:
        records.append(
            _warning(
                run_id=run_id,
                section="sample_size",
                severity=WARNING_SEVERITY,
                warning_code="R36_SMALL_VALIDATION_SAMPLE",
                warning_message="验证样本少于 100 行，窗口表现仅作为临时观察。",
                affected_count=len(daily_rows),
                human_review_required=("rolling_window_definition",),
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
) -> SignalMatrixValidationWarningRecord:
    return SignalMatrixValidationWarningRecord(
        run_id=run_id,
        section=section,
        severity=severity,
        warning_code=warning_code,
        warning_message=warning_message,
        affected_count=affected_count,
        human_review_required=human_review_required,
    )


def _write_table(*, rows: list[dict[str, object]], parquet_path: Path, csv_path: Path) -> None:
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False, encoding="utf-8")


def _write_warning_csv(
    *,
    warnings: tuple[SignalMatrixValidationWarningRecord, ...],
    csv_path: Path,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows([warning.to_csv_row() for warning in warnings])


def _write_markdown(
    *,
    result: ResearchSignalMatrixValidationResult,
    window_summary_rows: list[dict[str, object]],
    phase_summary_rows: list[dict[str, object]],
) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# CF 多周期信号矩阵滚动验证 - {result.start.isoformat()} 至 {result.end.isoformat()}",
        "",
        "## 一、数据状态",
        "",
        f"- Run ID：`{result.run_id}`",
        f"- 信号矩阵：`{result.signal_matrix_path}`",
        f"- 核心表：`{result.core_quote_path}`",
        f"- 滚动窗口：`{','.join(result.windows)}`",
        f"- 验证行数：`{result.daily_row_count}`",
        "- forward_return 是否仅为后验验证标签：`是`",
        "",
        "## 二、窗口表现",
        "",
        "| 窗口 | Horizon | 信号行 | 标签样本 | 平均后验收益 | 方向命中率 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in window_summary_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["window_id"]),
                    str(row["horizon"]),
                    str(row["signal_row_count"]),
                    str(row["observation_count"]),
                    r23._fmt_percent(row["mean_forward_return"]),
                    r23._fmt_percent(row["directional_hit_rate"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 三、阶段表现",
            "",
            "| 阶段 | Horizon | 信号行 | 标签样本 | 平均后验收益 | 方向命中率 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in phase_summary_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["trend_phase"]),
                    str(row["horizon"]),
                    str(row["signal_row_count"]),
                    str(row["observation_count"]),
                    r23._fmt_percent(row["mean_forward_return"]),
                    r23._fmt_percent(row["directional_hit_rate"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 四、研究边界",
            "",
            "- forward_return 只用于 R36 历史后验验证，不参与 R35/R38 当日信号。",
            "- 方向命中率只衡量矩阵方向与后验收益方向是否一致，不等同于交易收益。",
            "- T+1 执行、合约切换、临近交割和成本参数仍需人工复核。",
            "- 本报告不构成交易指令。",
            "",
            "## 五、人工复核项",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_json(
    *,
    result: ResearchSignalMatrixValidationResult,
    window_summary_rows: list[dict[str, object]],
    phase_summary_rows: list[dict[str, object]],
) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **result.to_summary(),
        "report_type": "signal_matrix_rolling_validation",
        "rule_version": SIGNAL_MATRIX_VALIDATION_VERSION,
        "source_signal_matrix_rule_version": SIGNAL_MATRIX_VERSION,
        "forward_returns_are_validation_labels": True,
        "window_summary_rows": window_summary_rows,
        "phase_summary_rows": phase_summary_rows,
        "warnings": [warning.to_csv_row() for warning in result.warning_records],
    }
    result.json_path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_manifest(*, result: ResearchSignalMatrixValidationResult) -> None:
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **result.to_summary(),
        "report_type": "signal_matrix_rolling_validation",
        "rule_version": SIGNAL_MATRIX_VALIDATION_VERSION,
        "source_signal_matrix_rule_version": SIGNAL_MATRIX_VERSION,
        "generated_at": utc_now().isoformat(),
        "forward_returns_are_validation_labels": True,
    }
    result.manifest_path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _output_paths(*, start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_signal_matrix_validation"
    return {
        "daily_parquet": root / f"{stem}_daily.parquet",
        "daily_csv": root / f"{stem}_daily.csv",
        "window_summary_parquet": root / f"{stem}_window_summary.parquet",
        "window_summary_csv": root / f"{stem}_window_summary.csv",
        "phase_summary_parquet": root / f"{stem}_phase_summary.parquet",
        "phase_summary_csv": root / f"{stem}_phase_summary.csv",
        "warning_csv": root / f"{stem}_warnings.csv",
        "manifest": root / f"{stem}_manifest.json",
    }


def _markdown_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_signal_matrix_validation"
    return root / f"{stem}.md"


def _json_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_signal_matrix_validation"
    return root / f"{stem}.json"


def _human_review_required(
    warnings: tuple[SignalMatrixValidationWarningRecord, ...],
) -> tuple[str, ...]:
    values = list(HUMAN_REVIEW_REQUIRED)
    values.extend(item for warning in warnings for item in warning.human_review_required)
    return tuple(r23._unique_values(values))


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
    if hasattr(value, "item"):
        return value.item()
    return value


def _is_scalar_missing(value: object) -> bool:
    if isinstance(value, (list, tuple, dict, str, Path, date)):
        return False
    return bool(pd.isna(value))


def _default_run_id(*, start: date, end: date) -> str:
    timestamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    suffix = uuid.uuid4().hex[:8]
    return (
        f"r36_signal_matrix_validation_{PRODUCT_CODE}_{start.isoformat()}_"
        f"{end.isoformat()}_{timestamp}_{suffix}"
    )
