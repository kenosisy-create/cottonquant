"""R37 threshold and weighting research for the CF signal matrix."""

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
from cotton_factor.research_workbench.signal_matrix_validation import (
    SIGNAL_MATRIX_VALIDATION_VERSION,
)

PRODUCT_CODE = "CF"
SIGNAL_THRESHOLD_RESEARCH_VERSION = "R37_signal_threshold_weight_research_v1"
OUTPUT_DIR = "signal_threshold_research"
WARNING_SEVERITY = "WARN"
INFO_SEVERITY = "INFO"
MIN_OBSERVATIONS_READY = 10
MIN_OBSERVATIONS_WATCH = 5
HUMAN_REVIEW_REQUIRED = (
    "factor_thresholds",
    "signal_matrix_weighting",
    "sample_size_requirement",
    "forward_return_horizon_set",
    "cost_model_parameters",
    "contract_rule_assumptions",
)

REQUIRED_VALIDATION_COLUMNS = {
    "trade_date",
    "horizon",
    "direction",
    "forward_return",
    "forward_label_available",
    "confidence_score",
    "trend_quality_score",
    "trend_phase",
}

FACTOR_COLUMNS = {
    "momentum_past_return": ("past_return", "当前 horizon 动量"),
    "momentum_20d": ("return_20d", "20日动量"),
    "carry": ("carry_annualized", "Carry 年化 proxy"),
    "curve": ("curve_slope", "远月曲线斜率"),
    "oi_pressure": ("main_oi_pressure", "主力持仓压力"),
    "confidence_score": ("confidence_score", "矩阵置信度"),
    "trend_quality_score": ("trend_quality_score", "趋势质量分"),
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
class SignalThresholdResearchWarningRecord:
    """Warning row for R37 threshold research."""

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
class ResearchSignalThresholdResult:
    """Result of building R37 threshold and weighting research artifacts."""

    product_code: str
    run_id: str
    start: date
    end: date
    threshold_row_count: int
    weighting_row_count: int
    warning_records: tuple[SignalThresholdResearchWarningRecord, ...]
    threshold_parquet_path: Path
    threshold_csv_path: Path
    weighting_parquet_path: Path
    weighting_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    validation_daily_path: Path
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
            "threshold_row_count": self.threshold_row_count,
            "weighting_row_count": self.weighting_row_count,
            "warning_count": self.warning_count,
            "threshold_parquet_path": str(self.threshold_parquet_path),
            "threshold_csv_path": str(self.threshold_csv_path),
            "weighting_parquet_path": str(self.weighting_parquet_path),
            "weighting_csv_path": str(self.weighting_csv_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "validation_daily_path": str(self.validation_daily_path),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_signal_threshold_research(
    *,
    validation_daily_path: Path,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchSignalThresholdResult:
    """Build R37 factor-threshold and weighting research from R36 validation rows."""
    validation = _load_validation_daily(validation_daily_path)
    start = min(validation["trade_date"])
    end = max(validation["trade_date"])
    threshold_run_id = run_id or _default_run_id(start=start, end=end)
    threshold_rows = _threshold_rows(validation=validation)
    weighting_rows = _weighting_rows(validation=validation)
    warnings = _warning_records(
        run_id=threshold_run_id,
        validation=validation,
        threshold_rows=threshold_rows,
        weighting_rows=weighting_rows,
    )
    paths = _output_paths(start=start, end=end, output_dir=output_dir)
    markdown_path = _markdown_path(start=start, end=end, report_output_dir=report_output_dir)
    json_path = _json_path(start=start, end=end, report_output_dir=report_output_dir)
    result = ResearchSignalThresholdResult(
        product_code=PRODUCT_CODE,
        run_id=threshold_run_id,
        start=start,
        end=end,
        threshold_row_count=len(threshold_rows),
        weighting_row_count=len(weighting_rows),
        warning_records=warnings,
        threshold_parquet_path=paths["threshold_parquet"],
        threshold_csv_path=paths["threshold_csv"],
        weighting_parquet_path=paths["weighting_parquet"],
        weighting_csv_path=paths["weighting_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=markdown_path,
        json_path=json_path,
        manifest_path=paths["manifest"],
        validation_daily_path=validation_daily_path,
        human_review_required=_human_review_required(warnings),
    )
    _write_table(
        rows=threshold_rows,
        parquet_path=result.threshold_parquet_path,
        csv_path=result.threshold_csv_path,
    )
    _write_table(
        rows=weighting_rows,
        parquet_path=result.weighting_parquet_path,
        csv_path=result.weighting_csv_path,
    )
    _write_warning_csv(warnings=warnings, csv_path=result.warning_csv_path)
    _write_markdown(result=result, threshold_rows=threshold_rows, weighting_rows=weighting_rows)
    _write_json(result=result, threshold_rows=threshold_rows, weighting_rows=weighting_rows)
    _write_manifest(result=result)
    return result


def _load_validation_daily(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"signal validation daily table not found: {path}")
    frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
    missing = sorted(REQUIRED_VALIDATION_COLUMNS - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"signal validation daily table missing columns: {missing}")
    working = frame.copy()
    working["trade_date"] = pd.to_datetime(working["trade_date"]).dt.date
    working["horizon"] = pd.to_numeric(working["horizon"], errors="coerce")
    working["forward_return"] = pd.to_numeric(working["forward_return"], errors="coerce")
    for column, _label in FACTOR_COLUMNS.values():
        if column in working.columns:
            working[column] = pd.to_numeric(working[column], errors="coerce")
    working = working.dropna(subset=["trade_date", "horizon"])
    working["horizon"] = working["horizon"].astype(int)
    if working.empty:
        raise ResearchWorkbenchError("signal validation daily table has no usable rows")
    return working.sort_values(["trade_date", "horizon"]).reset_index(drop=True)


def _threshold_rows(*, validation: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for horizon, horizon_group in validation.groupby("horizon", sort=True):
        available = horizon_group.loc[horizon_group["forward_label_available"].astype(bool)].copy()
        if available.empty:
            continue
        for factor_id, (column, label_cn) in FACTOR_COLUMNS.items():
            if column not in available.columns:
                continue
            values = available.dropna(subset=[column, "forward_return"]).copy()
            if values.empty:
                continue
            low, high = _quantile_bounds(values[column])
            middle_bucket = values.loc[(values[column] > low) & (values[column] <= high)]
            bucket_defs = (
                ("low", "低分位", None, low, values.loc[values[column] <= low]),
                ("middle", "中分位", low, high, middle_bucket),
                ("high", "高分位", high, None, values.loc[values[column] > high]),
            )
            for bucket_id, bucket_label, lower, upper, bucket in bucket_defs:
                rows.append(
                    _factor_bucket_row(
                        horizon=int(horizon),
                        factor_id=factor_id,
                        factor_label_cn=label_cn,
                        factor_column=column,
                        bucket_id=bucket_id,
                        bucket_label=bucket_label,
                        lower_bound=lower,
                        upper_bound=upper,
                        bucket=bucket,
                    )
                )
    return rows


def _quantile_bounds(values: pd.Series) -> tuple[float, float]:
    low = float(values.quantile(1 / 3))
    high = float(values.quantile(2 / 3))
    if low == high:
        low = float(values.min())
        high = float(values.max())
    return low, high


def _factor_bucket_row(
    *,
    horizon: int,
    factor_id: str,
    factor_label_cn: str,
    factor_column: str,
    bucket_id: str,
    bucket_label: str,
    lower_bound: float | None,
    upper_bound: float | None,
    bucket: pd.DataFrame,
) -> dict[str, object]:
    returns = pd.to_numeric(bucket["forward_return"], errors="coerce").dropna()
    hit_rate = _factor_direction_hit_rate(bucket=bucket, factor_column=factor_column)
    return {
        "factor_id": factor_id,
        "factor_label_cn": factor_label_cn,
        "factor_column": factor_column,
        "horizon": horizon,
        "bucket_id": bucket_id,
        "bucket_label": bucket_label,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "signal_row_count": int(len(bucket)),
        "observation_count": int(len(returns)),
        "factor_value_min": _series_stat(bucket[factor_column], "min"),
        "factor_value_median": _series_stat(bucket[factor_column], "median"),
        "factor_value_max": _series_stat(bucket[factor_column], "max"),
        "mean_forward_return": None if returns.empty else float(returns.mean()),
        "median_forward_return": None if returns.empty else float(returns.median()),
        "positive_rate": None if returns.empty else float((returns > 0).mean()),
        "negative_rate": None if returns.empty else float((returns < 0).mean()),
        "factor_direction_hit_rate": hit_rate,
        "candidate_status": _candidate_status(
            observation_count=int(len(returns)),
            hit_rate=hit_rate,
        ),
        "threshold_rule_version": SIGNAL_THRESHOLD_RESEARCH_VERSION,
    }


def _factor_direction_hit_rate(*, bucket: pd.DataFrame, factor_column: str) -> float | None:
    observation_count = 0
    hit_count = 0
    for row in bucket.to_dict(orient="records"):
        factor_value = r23._float_or_none(row.get(factor_column))
        forward_return = r23._float_or_none(row.get("forward_return"))
        if factor_value is None or forward_return is None or factor_value == 0:
            continue
        observation_count += 1
        if factor_value > 0 and forward_return > 0:
            hit_count += 1
        elif factor_value < 0 and forward_return < 0:
            hit_count += 1
    return None if observation_count == 0 else hit_count / observation_count


def _weighting_rows(*, validation: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for horizon, horizon_group in validation.groupby("horizon", sort=True):
        available = horizon_group.loc[horizon_group["forward_label_available"].astype(bool)].copy()
        if available.empty:
            continue
        schemes = (
            ("matrix_all", "矩阵全样本", available),
            ("confidence_ge_55", "置信度 >=55", available.loc[available["confidence_score"] >= 55]),
            ("confidence_ge_70", "置信度 >=70", available.loc[available["confidence_score"] >= 70]),
            (
                "trend_quality_ge_60",
                "趋势质量 >=60",
                available.loc[available["trend_quality_score"] >= 60],
            ),
            (
                "phase_s1_s2",
                "仅 S1/S2 阶段",
                available.loc[available["trend_phase"].isin(["S1", "S2"])],
            ),
            (
                "exclude_s3_s4",
                "排除 S3/S4 风险阶段",
                available.loc[~available["trend_phase"].isin(["S3", "S4"])],
            ),
        )
        for scheme_id, scheme_label, subset in schemes:
            rows.append(
                _scheme_row(
                    horizon=int(horizon),
                    scheme_id=scheme_id,
                    scheme_label_cn=scheme_label,
                    subset=subset,
                    total_count=len(available),
                )
            )
    return rows


def _scheme_row(
    *,
    horizon: int,
    scheme_id: str,
    scheme_label_cn: str,
    subset: pd.DataFrame,
    total_count: int,
) -> dict[str, object]:
    returns = pd.to_numeric(subset["forward_return"], errors="coerce").dropna()
    hit_rate = _matrix_direction_hit_rate(subset=subset)
    observation_count = int(len(returns))
    return {
        "scheme_id": scheme_id,
        "scheme_label_cn": scheme_label_cn,
        "horizon": horizon,
        "active_row_count": int(len(subset)),
        "total_row_count": int(total_count),
        "coverage_rate": None if total_count == 0 else len(subset) / total_count,
        "observation_count": observation_count,
        "mean_forward_return": None if returns.empty else float(returns.mean()),
        "median_forward_return": None if returns.empty else float(returns.median()),
        "directional_hit_rate": hit_rate,
        "candidate_status": _candidate_status(
            observation_count=observation_count,
            hit_rate=hit_rate,
        ),
        "threshold_rule_version": SIGNAL_THRESHOLD_RESEARCH_VERSION,
    }


def _matrix_direction_hit_rate(*, subset: pd.DataFrame) -> float | None:
    observation_count = 0
    hit_count = 0
    for row in subset.to_dict(orient="records"):
        direction = str(row.get("direction"))
        forward_return = r23._float_or_none(row.get("forward_return"))
        if direction not in {"long", "short"} or forward_return is None:
            continue
        observation_count += 1
        if direction == "long" and forward_return > 0:
            hit_count += 1
        elif direction == "short" and forward_return < 0:
            hit_count += 1
    return None if observation_count == 0 else hit_count / observation_count


def _candidate_status(*, observation_count: int, hit_rate: float | None) -> str:
    if observation_count < MIN_OBSERVATIONS_WATCH or hit_rate is None:
        return "INSUFFICIENT_EVIDENCE"
    if observation_count >= MIN_OBSERVATIONS_READY and hit_rate >= 0.60:
        return "READY_CANDIDATE"
    if hit_rate >= 0.55:
        return "WATCH_CANDIDATE"
    return "WEAK_OR_UNSTABLE"


def _warning_records(
    *,
    run_id: str,
    validation: pd.DataFrame,
    threshold_rows: list[dict[str, object]],
    weighting_rows: list[dict[str, object]],
) -> tuple[SignalThresholdResearchWarningRecord, ...]:
    records = [
        _warning(
            run_id=run_id,
            section="research_boundary",
            severity=INFO_SEVERITY,
            warning_code="R37_FORWARD_RETURNS_ARE_VALIDATION_LABELS",
            warning_message="R37 只读取 R36 后验验证行，阈值结论仍为研究候选。",
            affected_count=len(validation),
            human_review_required=(),
        )
    ]
    if len(validation) < 100:
        records.append(
            _warning(
                run_id=run_id,
                section="sample_size",
                severity=WARNING_SEVERITY,
                warning_code="R37_SMALL_RESEARCH_SAMPLE",
                warning_message="阈值研究样本少于 100 行，候选状态不能升级为稳定规则。",
                affected_count=len(validation),
                human_review_required=("sample_size_requirement",),
            )
        )
    ready_count = sum(row.get("candidate_status") == "READY_CANDIDATE" for row in weighting_rows)
    if ready_count == 0:
        records.append(
            _warning(
                run_id=run_id,
                section="weighting_candidates",
                severity=WARNING_SEVERITY,
                warning_code="R37_NO_READY_WEIGHTING_CANDIDATE",
                warning_message="当前过滤/权重方案没有达到 READY_CANDIDATE，后续只能作为观察。",
                affected_count=len(weighting_rows),
                human_review_required=("signal_matrix_weighting",),
            )
        )
    if not threshold_rows:
        records.append(
            _warning(
                run_id=run_id,
                section="threshold_candidates",
                severity=WARNING_SEVERITY,
                warning_code="R37_NO_THRESHOLD_ROWS",
                warning_message="未生成阈值分位表现，需检查 R36 验证输入。",
                affected_count=0,
                human_review_required=("factor_thresholds",),
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
) -> SignalThresholdResearchWarningRecord:
    return SignalThresholdResearchWarningRecord(
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
    warnings: tuple[SignalThresholdResearchWarningRecord, ...],
    csv_path: Path,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows([warning.to_csv_row() for warning in warnings])


def _write_markdown(
    *,
    result: ResearchSignalThresholdResult,
    threshold_rows: list[dict[str, object]],
    weighting_rows: list[dict[str, object]],
) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# CF 因子阈值与权重研究 - {result.start.isoformat()} 至 {result.end.isoformat()}",
        "",
        "## 一、数据状态",
        "",
        f"- Run ID：`{result.run_id}`",
        f"- R36 验证行：`{result.validation_daily_path}`",
        f"- 阈值行数：`{result.threshold_row_count}`",
        f"- 权重/过滤方案行数：`{result.weighting_row_count}`",
        "- forward_return 是否仅为后验验证标签：`是`",
        "",
        "## 二、权重与过滤方案候选",
        "",
        "| 方案 | Horizon | 覆盖率 | 样本 | 平均后验收益 | 方向命中率 | 状态 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in weighting_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["scheme_label_cn"]),
                    str(row["horizon"]),
                    r23._fmt_percent(row["coverage_rate"]),
                    str(row["observation_count"]),
                    r23._fmt_percent(row["mean_forward_return"]),
                    r23._fmt_percent(row["directional_hit_rate"]),
                    str(row["candidate_status"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 三、阈值分位候选（节选）",
            "",
            "| 因子 | Horizon | 分位 | 样本 | 平均后验收益 | 因子方向命中率 | 状态 |",
            "| --- | ---: | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in threshold_rows[:40]:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["factor_label_cn"]),
                    str(row["horizon"]),
                    str(row["bucket_label"]),
                    str(row["observation_count"]),
                    r23._fmt_percent(row["mean_forward_return"]),
                    r23._fmt_percent(row["factor_direction_hit_rate"]),
                    str(row["candidate_status"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 四、研究边界",
            "",
            "- R37 只形成阈值和权重候选，不固化交易规则。",
            "- READY_CANDIDATE 仍需成本、样本外和人工规则复核后才能进入日报解释。",
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
    result: ResearchSignalThresholdResult,
    threshold_rows: list[dict[str, object]],
    weighting_rows: list[dict[str, object]],
) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **result.to_summary(),
        "report_type": "signal_threshold_weight_research",
        "rule_version": SIGNAL_THRESHOLD_RESEARCH_VERSION,
        "source_validation_rule_version": SIGNAL_MATRIX_VALIDATION_VERSION,
        "forward_returns_are_validation_labels": True,
        "threshold_rows": threshold_rows,
        "weighting_rows": weighting_rows,
        "warnings": [warning.to_csv_row() for warning in result.warning_records],
    }
    result.json_path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_manifest(*, result: ResearchSignalThresholdResult) -> None:
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **result.to_summary(),
        "report_type": "signal_threshold_weight_research",
        "rule_version": SIGNAL_THRESHOLD_RESEARCH_VERSION,
        "source_validation_rule_version": SIGNAL_MATRIX_VALIDATION_VERSION,
        "generated_at": utc_now().isoformat(),
        "forward_returns_are_validation_labels": True,
        "produces_research_candidates_only": True,
    }
    result.manifest_path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _output_paths(*, start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_signal_threshold_research"
    return {
        "threshold_parquet": root / f"{stem}_thresholds.parquet",
        "threshold_csv": root / f"{stem}_thresholds.csv",
        "weighting_parquet": root / f"{stem}_weighting.parquet",
        "weighting_csv": root / f"{stem}_weighting.csv",
        "warning_csv": root / f"{stem}_warnings.csv",
        "manifest": root / f"{stem}_manifest.json",
    }


def _markdown_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_signal_threshold_research"
    return root / f"{stem}.md"


def _json_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_signal_threshold_research"
    return root / f"{stem}.json"


def _human_review_required(
    warnings: tuple[SignalThresholdResearchWarningRecord, ...],
) -> tuple[str, ...]:
    values = list(HUMAN_REVIEW_REQUIRED)
    values.extend(item for warning in warnings for item in warning.human_review_required)
    return tuple(r23._unique_values(values))


def _series_stat(values: pd.Series, method: str) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return None
    if method == "min":
        return float(numeric.min())
    if method == "median":
        return float(numeric.median())
    if method == "max":
        return float(numeric.max())
    raise ResearchWorkbenchError(f"unsupported series stat: {method}")


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
        f"r37_signal_threshold_research_{PRODUCT_CODE}_{start.isoformat()}_"
        f"{end.isoformat()}_{timestamp}_{suffix}"
    )
