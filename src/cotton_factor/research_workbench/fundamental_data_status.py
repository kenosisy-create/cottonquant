"""R93J CF基本面数据可用性与新鲜度状态表。"""

from __future__ import annotations

import csv
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.common.time import utc_now
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME
from cotton_factor.research_workbench.ifind_edb_context import COTTON_EDB, FX_SWAP_TENORS

PRODUCT_CODE = "CF"
RULE_VERSION = "V5.1_R93J_fundamental_data_status_v1"

# 按数据真实发布节奏判断新鲜度，避免把月频进口或事件数据伪装成日频数据。
FRESHNESS_LIMITS = {
    "D": (3, 7),
    "W": (10, 21),
    "M": (45, 75),
}

BASE_TABLE_SPECS = (
    {
        "dataset_type": "basis",
        "filename": "CF_fundamental_basis_daily.parquet",
        "indicator_column": "basis_indicator_name",
        "fallback_name": "基差",
        "value_column": "basis",
        "frequency": "D",
    },
    {
        "dataset_type": "spot_price",
        "filename": "CF_fundamental_spot_price_daily.parquet",
        "indicator_column": "indicator_name",
        "fallback_name": "棉花现货价格",
        "value_column": "indicator_value",
        "frequency": "D",
    },
    {
        "dataset_type": "warehouse_receipt",
        "filename": "CF_fundamental_warehouse_receipt_daily.parquet",
        "indicator_column": "indicator_name",
        "fallback_name": "仓单数量:一号棉",
        "value_column": "warehouse_receipt",
        "frequency": "D",
    },
    {
        "dataset_type": "inventory",
        "filename": "CF_fundamental_inventory_daily.parquet",
        "indicator_column": "indicator_name",
        "fallback_name": "棉花库存",
        "value_column": "inventory_value",
        "frequency": "M",
    },
    {
        "dataset_type": "import",
        "filename": "CF_fundamental_import_daily.parquet",
        "indicator_column": "indicator_name",
        "fallback_name": "棉花进口",
        "value_column": "import_value",
        "frequency": "M",
    },
    {
        "dataset_type": "textile_chain",
        "filename": "CF_fundamental_textile_chain_daily.parquet",
        "indicator_column": "indicator_name",
        "fallback_name": "纺织链",
        "value_column": "indicator_value",
        "frequency": "W",
        "metric_column": "metric_name",
    },
)

MISSING_CONTRACTS = (
    {
        "dataset_type": "textile_chain",
        "indicator_name": "纺织订单",
        "frequency": "W",
        "recommended_source": "iFinD或TTEB；需先确认唯一指标口径和ID",
        "next_action": "通过SuperCommand确认指标ID、单位和历史是否连续",
    },
    {
        "dataset_type": "textile_chain",
        "indicator_name": "棉纱利润",
        "frequency": "W",
        "recommended_source": "iFinD或TTEB；需确认棉价、纱价和加工费口径",
        "next_action": "先固定利润公式和成本口径，再接入原始序列",
    },
    {
        "dataset_type": "macro",
        "indicator_name": "USD/CNY即期汇率",
        "frequency": "D",
        "recommended_source": "iFinD EDB或CFETS官方数据",
        "next_action": "确认即期汇率指标ID；不得使用掉期曲线替代",
    },
    {
        "dataset_type": "global_market",
        "indicator_name": "ICE棉花连续价格",
        "frequency": "D",
        "recommended_source": "iFinD历史行情或ICE授权数据",
        "next_action": "确认合约代码、币种、单位和连续价格调整规则",
    },
    {
        "dataset_type": "warehouse_detail",
        "indicator_name": "仓单质量与仓库明细",
        "frequency": "D",
        "recommended_source": "郑商所官方仓单日报",
        "next_action": "建立仓库、等级、有效预报、注册和注销字段契约",
    },
)

SOURCE_RECOMMENDATIONS = {
    "basis": "确认现货价与郑商所真实合约结算价后由本地计算",
    "spot_price": "iFinD/中国棉花信息网，保留原指标ID和来源切换",
    "warehouse_receipt": "郑商所官方仓单日报为权威源，iFinD仅作交叉核对",
    "inventory": "iFinD/中国棉花信息网，保留统计期和发布日期",
    "import": "iFinD/海关月度数据，禁止向前展开为伪日频",
    "textile_chain": "TTEB或经确认的iFinD产业指标",
    "spot": "iFinD EDB研究侧车",
    "policy": "iFinD EDB事件序列，未公布期间不补零",
    "yarn": "iFinD EDB研究侧车",
    "fx_swap": "iFinD EDB掉期曲线；不能替代即期汇率",
}

STATUS_COLUMNS = (
    "product_code",
    "dataset_type",
    "indicator_name",
    "indicator_id",
    "frequency",
    "source_lane",
    "source_name",
    "date_start",
    "date_end",
    "row_count",
    "non_null_count",
    "duplicate_count",
    "lag_calendar_days",
    "data_status",
    "research_usability",
    "unit",
    "unit_status",
    "data_quality_flag",
    "human_review_required",
    "signal_status",
    "recommended_source",
    "next_action",
)


@dataclass(frozen=True)
class FundamentalDataStatusWarningRecord:
    """R93J警告或研究边界记录。"""

    severity: str
    warning_code: str
    message: str
    affected_count: int = 0
    human_review_required: tuple[str, ...] = ()

    def to_summary(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "warning_code": self.warning_code,
            "message": self.message,
            "affected_count": self.affected_count,
            "human_review_required": list(self.human_review_required),
        }


@dataclass(frozen=True)
class ResearchFundamentalDataStatusResult:
    """R93J产物路径与数据状态摘要。"""

    run_id: str
    status: str
    as_of_date: date
    row_count: int
    status_counts: dict[str, int]
    fundamental_dir: Path
    ifind_manifest_path: Path | None
    status_parquet_path: Path
    status_csv_path: Path
    warning_csv_path: Path
    json_path: Path
    manifest_path: Path
    markdown_path: Path
    warning_records: tuple[FundamentalDataStatusWarningRecord, ...]

    @property
    def passed(self) -> bool:
        return self.status == "FUNDAMENTAL_DATA_STATUS_READY_WITH_GAPS"

    @property
    def warning_count(self) -> int:
        return sum(row.severity in {"WARN", "ERROR"} for row in self.warning_records)

    def to_summary(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "passed": self.passed,
            "product_code": PRODUCT_CODE,
            "as_of_date": self.as_of_date.isoformat(),
            "row_count": self.row_count,
            "status_counts": self.status_counts,
            "fundamental_dir": str(self.fundamental_dir),
            "ifind_manifest_path": (
                None if self.ifind_manifest_path is None else str(self.ifind_manifest_path)
            ),
            "status_parquet_path": str(self.status_parquet_path),
            "status_csv_path": str(self.status_csv_path),
            "warning_csv_path": str(self.warning_csv_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "markdown_path": str(self.markdown_path),
            "warning_count": self.warning_count,
            "warnings": [row.to_summary() for row in self.warning_records],
            "contains_forward_labels": False,
            "fundamental_signal_status": "not_connected",
        }


def build_cf_fundamental_data_status(
    *,
    as_of_date: date | None = None,
    core_quote_path: Path | None = None,
    fundamental_dir: Path | None = None,
    ifind_edb_manifest_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchFundamentalDataStatusResult:
    """汇总基本面历史表和iFinD侧车，生成频率感知的数据状态表。"""
    quote_path = core_quote_path or data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    selected_as_of = as_of_date or _latest_core_date(quote_path)
    selected_fundamental_dir = (
        fundamental_dir or data_dir() / "research" / PRODUCT_CODE / "fundamentals"
    )
    selected_ifind_manifest = ifind_edb_manifest_path or _latest_ifind_manifest()

    rows: list[dict[str, object]] = []
    input_paths: list[Path] = []
    source_warnings: list[FundamentalDataStatusWarningRecord] = []
    for spec in BASE_TABLE_SPECS:
        table_path = selected_fundamental_dir / str(spec["filename"])
        if table_path.exists():
            rows.extend(_base_table_rows(table_path, spec, selected_as_of, source_warnings))
            input_paths.append(table_path)
        else:
            rows.append(_missing_dataset_row(spec))

    if selected_ifind_manifest is not None:
        edb_rows, edb_inputs, edb_warnings = _ifind_rows(
            selected_ifind_manifest,
            selected_as_of,
        )
        rows.extend(edb_rows)
        input_paths.extend(edb_inputs)
        source_warnings.extend(edb_warnings)
    else:
        rows.extend(_missing_ifind_rows())

    rows.extend(_missing_contract_rows())
    status_table = pd.DataFrame(rows, columns=STATUS_COLUMNS)
    if status_table.empty:
        raise ResearchWorkbenchError("R93J没有可写出的基本面数据状态行")
    status_table = status_table.sort_values(
        ["data_status", "dataset_type", "indicator_name", "indicator_id"],
        kind="stable",
    ).reset_index(drop=True)

    status_counts = {
        str(key): int(value)
        for key, value in status_table["data_status"].value_counts().sort_index().items()
    }
    warnings = tuple(source_warnings + _summary_warnings(status_table))
    paths = _output_paths(output_dir=output_dir, report_output_dir=report_output_dir)
    _write_table(paths["status_parquet"], paths["status_csv"], status_table)
    result = ResearchFundamentalDataStatusResult(
        run_id=run_id or _default_run_id(),
        status="FUNDAMENTAL_DATA_STATUS_READY_WITH_GAPS",
        as_of_date=selected_as_of,
        row_count=len(status_table),
        status_counts=status_counts,
        fundamental_dir=selected_fundamental_dir,
        ifind_manifest_path=selected_ifind_manifest,
        status_parquet_path=paths["status_parquet"],
        status_csv_path=paths["status_csv"],
        warning_csv_path=paths["warnings"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
        markdown_path=paths["markdown"],
        warning_records=warnings,
    )
    _write_warnings(result)
    _write_json(result)
    _write_markdown(result, status_table)
    _write_manifest(result, input_paths)
    return result


def _base_table_rows(
    path: Path,
    spec: dict[str, object],
    as_of_date: date,
    warnings: list[FundamentalDataStatusWarningRecord],
) -> list[dict[str, object]]:
    frame = pd.read_parquet(path)
    required = {"trade_date", str(spec["value_column"])}
    missing = required - set(frame.columns)
    if missing:
        raise ResearchWorkbenchError(f"基本面表缺少字段 {sorted(missing)}: {path}")
    normalized = frame.copy()
    normalized["trade_date"] = pd.to_datetime(normalized["trade_date"], errors="coerce")
    if normalized["trade_date"].isna().any():
        raise ResearchWorkbenchError(f"基本面表存在无法解析的日期: {path}")
    normalized, future_count = _exclude_future_rows(normalized, as_of_date)
    if future_count:
        warnings.append(
            FundamentalDataStatusWarningRecord(
                severity="WARN",
                warning_code="R93J_FUTURE_ROWS_EXCLUDED",
                message=f"状态日之后的记录已从本次状态判断中排除：{path}",
                affected_count=future_count,
                human_review_required=("external_data_revision_timing",),
            )
        )
    if normalized.empty:
        return [_missing_dataset_row(spec)]

    indicator_column = str(spec["indicator_column"])
    if indicator_column in normalized.columns:
        normalized["_indicator_name"] = normalized[indicator_column].fillna("").astype(str)
    else:
        normalized["_indicator_name"] = str(spec["fallback_name"])
    normalized.loc[normalized["_indicator_name"].eq(""), "_indicator_name"] = str(
        spec["fallback_name"]
    )
    metric_column = spec.get("metric_column")
    if metric_column and str(metric_column) in normalized.columns:
        metric = normalized[str(metric_column)].fillna("").astype(str)
        normalized["_indicator_name"] = normalized["_indicator_name"] + metric.map(
            lambda value: f":{value}" if value else ""
        )

    output: list[dict[str, object]] = []
    for indicator_name, group in normalized.groupby("_indicator_name", sort=True):
        output.append(
            _coverage_row(
                group=group,
                dataset_type=str(spec["dataset_type"]),
                indicator_name=str(indicator_name),
                value_column=str(spec["value_column"]),
                frequency=str(spec["frequency"]),
                source_lane="fundamental_history",
                as_of_date=as_of_date,
                recommended_source=SOURCE_RECOMMENDATIONS[str(spec["dataset_type"])],
            )
        )
    return output


def _ifind_rows(
    manifest_path: Path,
    as_of_date: date,
) -> tuple[
    list[dict[str, object]],
    list[Path],
    list[FundamentalDataStatusWarningRecord],
]:
    if not manifest_path.exists():
        raise ResearchWorkbenchError(f"iFinD EDB manifest不存在: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary = payload.get("summary", {})
    cotton_path = _manifest_artifact_path(summary, "cotton_context_path", manifest_path)
    fx_path = _manifest_artifact_path(summary, "fx_swap_curve_path", manifest_path)
    cotton = pd.read_parquet(cotton_path)
    fx_swap = pd.read_parquet(fx_path)
    rows: list[dict[str, object]] = []
    warnings: list[FundamentalDataStatusWarningRecord] = []

    rows.extend(
        _group_ifind_table(
            cotton,
            as_of_date=as_of_date,
            value_column="indicator_value",
            name_column="indicator_name",
            dataset_column="dataset_type",
            warnings=warnings,
            source_label="iFinD棉花EDB",
        )
    )
    fx = fx_swap.copy()
    fx["dataset_type"] = "fx_swap"
    rows.extend(
        _group_ifind_table(
            fx,
            as_of_date=as_of_date,
            value_column="swap_value",
            name_column="index_name",
            dataset_column="dataset_type",
            warnings=warnings,
            source_label="iFinD掉期曲线EDB",
        )
    )
    return rows, [manifest_path, cotton_path, fx_path], warnings


def _group_ifind_table(
    frame: pd.DataFrame,
    *,
    as_of_date: date,
    value_column: str,
    name_column: str,
    dataset_column: str,
    warnings: list[FundamentalDataStatusWarningRecord],
    source_label: str,
) -> list[dict[str, object]]:
    required = {"trade_date", "indicator_id", value_column, name_column, dataset_column}
    missing = required - set(frame.columns)
    if missing:
        raise ResearchWorkbenchError(f"{source_label}缺少字段: {sorted(missing)}")
    normalized = frame.copy()
    normalized["trade_date"] = pd.to_datetime(normalized["trade_date"], errors="coerce")
    if normalized["trade_date"].isna().any():
        raise ResearchWorkbenchError(f"{source_label}存在无法解析的日期")
    normalized, future_count = _exclude_future_rows(normalized, as_of_date)
    if future_count:
        warnings.append(
            FundamentalDataStatusWarningRecord(
                severity="WARN",
                warning_code="R93J_IFIND_FUTURE_ROWS_EXCLUDED",
                message=f"{source_label}中状态日之后的记录已排除。",
                affected_count=future_count,
                human_review_required=("ifind_revision_timing",),
            )
        )
    output: list[dict[str, object]] = []
    for (_, indicator_id), group in normalized.groupby(
        [dataset_column, "indicator_id"], sort=True
    ):
        dataset_type = str(group[dataset_column].iloc[0])
        frequency = "EVENT" if dataset_type == "policy" else "D"
        output.append(
            _coverage_row(
                group=group,
                dataset_type=dataset_type,
                indicator_name=str(group[name_column].iloc[0]),
                value_column=value_column,
                frequency=frequency,
                source_lane="ifind_edb_sidecar",
                as_of_date=as_of_date,
                indicator_id=str(indicator_id),
                recommended_source=SOURCE_RECOMMENDATIONS[dataset_type],
            )
        )
    return output


def _coverage_row(
    *,
    group: pd.DataFrame,
    dataset_type: str,
    indicator_name: str,
    value_column: str,
    frequency: str,
    source_lane: str,
    as_of_date: date,
    recommended_source: str,
    indicator_id: str | None = None,
) -> dict[str, object]:
    dates = pd.to_datetime(group["trade_date"])
    date_start = dates.min().date()
    date_end = dates.max().date()
    lag = max((as_of_date - date_end).days, 0)
    data_status, research_usability = _freshness_status(frequency, lag)
    observed_indicator_id = indicator_id or _joined_values(group, "indicator_id")
    source_name = _joined_values(group, "source_name") or "未记录"
    unit = _joined_values(group, "unit")
    unit_status = _joined_values(group, "unit_status") or (
        "CONFIRMED_IN_SOURCE" if unit else "REVIEW_REQUIRED"
    )
    quality = _joined_values(group, "data_quality_flag") or "REVIEW_REQUIRED"
    human_review = _any_truthy(group, "human_review_required")
    return {
        "product_code": PRODUCT_CODE,
        "dataset_type": dataset_type,
        "indicator_name": indicator_name,
        "indicator_id": observed_indicator_id,
        "frequency": frequency,
        "source_lane": source_lane,
        "source_name": source_name,
        "date_start": date_start,
        "date_end": date_end,
        "row_count": len(group),
        "non_null_count": int(pd.to_numeric(group[value_column], errors="coerce").notna().sum()),
        "duplicate_count": int(group.duplicated(["trade_date"]).sum()),
        "lag_calendar_days": lag,
        "data_status": data_status,
        "research_usability": research_usability,
        "unit": unit,
        "unit_status": unit_status,
        "data_quality_flag": quality,
        "human_review_required": human_review,
        "signal_status": "not_connected",
        "recommended_source": recommended_source,
        "next_action": _next_action(data_status, frequency),
    }


def _freshness_status(frequency: str, lag_days: int) -> tuple[str, str]:
    if frequency == "EVENT":
        return "EVENT_DRIVEN", "EVENT_CONTEXT_ONLY"
    current_limit, lagging_limit = FRESHNESS_LIMITS.get(frequency, (7, 14))
    if lag_days <= current_limit:
        return "CURRENT", "CURRENT_CONTEXT"
    if lag_days <= lagging_limit:
        return "LAGGING", "USABLE_WITH_LAG_WARNING"
    return "STALE", "HISTORICAL_ONLY"


def _next_action(data_status: str, frequency: str) -> str:
    if data_status == "CURRENT":
        return "按原频率增量更新并保留来源快照"
    if data_status == "LAGGING":
        return "检查最新发布日、接口额度和修订时间"
    if data_status == "STALE":
        return "补取最新数据；更新前只允许用于历史解释"
    if frequency == "EVENT":
        return "仅在事件发布时追加，未发布期间不得补零"
    return "建立数据契约后接入"


def _missing_dataset_row(spec: dict[str, object]) -> dict[str, object]:
    return _empty_status_row(
        dataset_type=str(spec["dataset_type"]),
        indicator_name=f"数据集:{spec['fallback_name']}",
        frequency=str(spec["frequency"]),
        source_lane="fundamental_history",
        recommended_source=SOURCE_RECOMMENDATIONS[str(spec["dataset_type"])],
        next_action=f"补充或重建 {spec['filename']}",
    )


def _missing_ifind_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for indicator_id, (dataset_type, name, _) in COTTON_EDB.items():
        rows.append(
            _empty_status_row(
                dataset_type=dataset_type,
                indicator_name=name,
                indicator_id=indicator_id,
                frequency="EVENT" if dataset_type == "policy" else "D",
                source_lane="ifind_edb_sidecar",
                recommended_source=SOURCE_RECOMMENDATIONS[dataset_type],
                next_action="补充完整R93H iFinD EDB来源包",
            )
        )
    for indicator_id, tenor in FX_SWAP_TENORS.items():
        rows.append(
            _empty_status_row(
                dataset_type="fx_swap",
                indicator_name=f"USD/CNY外汇掉期曲线:{tenor}",
                indicator_id=indicator_id,
                frequency="D",
                source_lane="ifind_edb_sidecar",
                recommended_source=SOURCE_RECOMMENDATIONS["fx_swap"],
                next_action="补充完整R93H iFinD EDB来源包",
            )
        )
    return rows


def _missing_contract_rows() -> list[dict[str, object]]:
    return [
        _empty_status_row(
            dataset_type=str(item["dataset_type"]),
            indicator_name=str(item["indicator_name"]),
            frequency=str(item["frequency"]),
            source_lane="missing_contract",
            recommended_source=str(item["recommended_source"]),
            next_action=str(item["next_action"]),
        )
        for item in MISSING_CONTRACTS
    ]


def _empty_status_row(
    *,
    dataset_type: str,
    indicator_name: str,
    frequency: str,
    source_lane: str,
    recommended_source: str,
    next_action: str,
    indicator_id: str = "",
) -> dict[str, object]:
    return {
        "product_code": PRODUCT_CODE,
        "dataset_type": dataset_type,
        "indicator_name": indicator_name,
        "indicator_id": indicator_id,
        "frequency": frequency,
        "source_lane": source_lane,
        "source_name": "未接入",
        "date_start": None,
        "date_end": None,
        "row_count": 0,
        "non_null_count": 0,
        "duplicate_count": 0,
        "lag_calendar_days": None,
        "data_status": "MISSING",
        "research_usability": "NOT_AVAILABLE",
        "unit": "",
        "unit_status": "NOT_CONNECTED",
        "data_quality_flag": "MISSING",
        "human_review_required": True,
        "signal_status": "not_connected",
        "recommended_source": recommended_source,
        "next_action": next_action,
    }


def _summary_warnings(frame: pd.DataFrame) -> list[FundamentalDataStatusWarningRecord]:
    warnings: list[FundamentalDataStatusWarningRecord] = []
    for data_status, severity, code, message in (
        ("MISSING", "WARN", "R93J_MISSING_DATA_CONTRACTS", "仍有基本面指标尚未接入。"),
        ("STALE", "WARN", "R93J_STALE_DATA_PRESENT", "部分基本面指标已超过频率新鲜度上限。"),
        ("LAGGING", "INFO", "R93J_LAGGING_DATA_PRESENT", "部分基本面指标存在可解释的发布滞后。"),
    ):
        count = int(frame["data_status"].eq(data_status).sum())
        if count:
            warnings.append(
                FundamentalDataStatusWarningRecord(
                    severity=severity,
                    warning_code=code,
                    message=message,
                    affected_count=count,
                    human_review_required=("fundamental_data_freshness",),
                )
            )
    duplicate_count = int(pd.to_numeric(frame["duplicate_count"]).sum())
    if duplicate_count:
        warnings.append(
            FundamentalDataStatusWarningRecord(
                severity="WARN",
                warning_code="R93J_DUPLICATE_OBSERVATIONS_PRESENT",
                message="部分指标同一观察日存在重复记录，不能直接进入统计模型。",
                affected_count=duplicate_count,
                human_review_required=("fundamental_duplicate_interpretation",),
            )
        )
    warnings.append(
        FundamentalDataStatusWarningRecord(
            severity="INFO",
            warning_code="R93J_SIGNAL_NOT_CONNECTED",
            message="本状态表只管理覆盖和新鲜度，不生成基本面方向，不进入composite_score。",
            affected_count=len(frame),
        )
    )
    return warnings


def _latest_core_date(path: Path) -> date:
    if not path.exists():
        raise ResearchWorkbenchError(f"CF core quote不存在，无法确定状态日: {path}")
    frame = pd.read_parquet(path, columns=["trade_date"])
    dates = pd.to_datetime(frame["trade_date"], errors="coerce")
    if not dates.notna().any():
        raise ResearchWorkbenchError(f"CF core quote没有有效trade_date: {path}")
    return dates.max().date()


def _latest_ifind_manifest() -> Path | None:
    root = data_dir() / "research" / PRODUCT_CODE / "ifind_edb"
    candidates: list[tuple[date, str, Path]] = []
    for path in root.glob("*_ifind_edb_manifest.json") if root.exists() else ():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            data_end = date.fromisoformat(str(payload.get("summary", {}).get("data_end")))
            generated_at = str(payload.get("generated_at", ""))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        candidates.append((data_end, generated_at, path))
    return max(candidates, default=(date.min, "", None))[2]


def _manifest_artifact_path(summary: dict[str, Any], key: str, manifest_path: Path) -> Path:
    raw = summary.get(key)
    if not raw:
        raise ResearchWorkbenchError(f"iFinD EDB manifest缺少summary.{key}: {manifest_path}")
    path = Path(str(raw))
    if not path.is_absolute():
        path = manifest_path.parents[4] / path
    if not path.exists():
        raise ResearchWorkbenchError(f"iFinD EDB产物不存在: {path}")
    return path


def _exclude_future_rows(frame: pd.DataFrame, as_of_date: date) -> tuple[pd.DataFrame, int]:
    future = frame["trade_date"].dt.date > as_of_date
    return frame.loc[~future].copy(), int(future.sum())


def _joined_values(frame: pd.DataFrame, column: str) -> str:
    if column not in frame.columns:
        return ""
    values = sorted(
        {
            str(value).strip()
            for value in frame[column].dropna().tolist()
            if str(value).strip()
        }
    )
    return " / ".join(values)


def _any_truthy(frame: pd.DataFrame, column: str) -> bool:
    if column not in frame.columns:
        return True
    return any(
        value is True or str(value).strip().lower() in {"true", "1", "yes"}
        for value in frame[column].tolist()
    )


def _output_paths(
    *,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / "fundamental_data_status"
    report_root = report_output_dir or reports_dir() / "research" / "fundamental_data_status"
    return {
        "status_parquet": root / "CF_fundamental_data_status.parquet",
        "status_csv": root / "CF_fundamental_data_status.csv",
        "warnings": root / "CF_fundamental_data_status_warnings.csv",
        "manifest": root / "CF_fundamental_data_status_manifest.json",
        "json": report_root / "CF_fundamental_data_status.json",
        "markdown": report_root / "CF_fundamental_data_status.md",
    }


def _write_table(parquet_path: Path, csv_path: Path, frame: pd.DataFrame) -> None:
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False, encoding="utf-8")


def _write_warnings(result: ResearchFundamentalDataStatusResult) -> None:
    result.warning_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with result.warning_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "run_id",
                "severity",
                "warning_code",
                "message",
                "affected_count",
                "human_review_required",
            ),
        )
        writer.writeheader()
        for row in result.warning_records:
            writer.writerow(
                {
                    "run_id": result.run_id,
                    "severity": row.severity,
                    "warning_code": row.warning_code,
                    "message": row.message,
                    "affected_count": row.affected_count,
                    "human_review_required": ";".join(row.human_review_required),
                }
            )


def _write_json(result: ResearchFundamentalDataStatusResult) -> None:
    payload = {
        "report_type": "fundamental_data_status",
        "rule_version": RULE_VERSION,
        "summary": result.to_summary(),
        "freshness_limits_calendar_days": FRESHNESS_LIMITS,
        "contains_forward_labels": False,
        "fundamental_signal_status": "not_connected",
    }
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _write_markdown(
    result: ResearchFundamentalDataStatusResult,
    frame: pd.DataFrame,
) -> None:
    lines = [
        "# CF R93J 基本面数据状态表",
        "",
        "## 数据状态",
        "",
        f"- 状态日：`{result.as_of_date}`",
        f"- 指标/缺口行数：`{result.row_count}`",
        f"- 状态分布：`{json.dumps(result.status_counts, ensure_ascii=False, sort_keys=True)}`",
        "- 基本面方向状态：`not_connected`",
        "- 是否包含未来收益标签：`否`",
        "",
        "## 新鲜度口径",
        "",
        "- 日频：3个日历日内为CURRENT，4-7日为LAGGING，超过7日为STALE。",
        "- 周频：10个日历日内为CURRENT，11-21日为LAGGING，超过21日为STALE。",
        "- 月频：45个日历日内为CURRENT，46-75日为LAGGING，超过75日为STALE。",
        "- 事件型：有记录即标记EVENT_DRIVEN；未公布期间不补零，也不以沉默天数判定断更。",
        "",
        "## 数据源概览",
        "",
        "| 数据层 | 指标数 | 最新观察 | CURRENT | LAGGING | STALE | EVENT | MISSING |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for source_lane, group in frame.groupby("source_lane", sort=True):
        observed_dates = pd.to_datetime(group["date_end"], errors="coerce")
        latest = observed_dates.max()
        latest_text = "-" if pd.isna(latest) else latest.date().isoformat()
        counts = group["data_status"].value_counts()
        lines.append(
            f"| {source_lane} | {len(group)} | {latest_text} | "
            f"{int(counts.get('CURRENT', 0))} | {int(counts.get('LAGGING', 0))} | "
            f"{int(counts.get('STALE', 0))} | {int(counts.get('EVENT_DRIVEN', 0))} | "
            f"{int(counts.get('MISSING', 0))} |"
        )

    attention = frame.loc[frame["data_status"].isin(["LAGGING", "STALE", "MISSING"])]
    lines.extend(
        [
            "",
            "## 待补与滞后项",
            "",
            "| 状态 | 类别 | 指标 | 最新观察 | 频率 | 建议来源 | 下一步 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in attention.itertuples(index=False):
        date_end = "-" if pd.isna(row.date_end) else str(row.date_end)
        lines.append(
            f"| {row.data_status} | {row.dataset_type} | {row.indicator_name} | "
            f"{date_end} | {row.frequency} | {row.recommended_source} | {row.next_action} |"
        )

    lines.extend(
        [
            "",
            "## 使用边界",
            "",
            "- CURRENT只表示数据覆盖及时，不代表指标具有方向预测能力。",
            "- LAGGING和STALE指标可以用于相应时点以前的历史解释，不得冒充最新事实。",
            "- 月频进口、库存保留原统计期；周频纺织链保留原观察日，均不向前填充为伪日频。",
            "- iFinD EDB继续作为研究侧车；掉期曲线不是即期汇率。",
            "- 本状态表不生成fundamental_signal，不进入signal matrix或composite_score。",
            "- 不含forward return，不构成交易指令。",
            "",
            "## 人工复核项",
            "",
            "- `fundamental_data_freshness`",
            "- `external_data_revision_timing`",
            "- `official_fundamental_field_interpretation`",
            "- `missing_indicator_id_and_unit`",
        ]
    )
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_manifest(
    result: ResearchFundamentalDataStatusResult,
    input_paths: list[Path],
) -> None:
    artifacts = (
        result.status_parquet_path,
        result.status_csv_path,
        result.warning_csv_path,
        result.json_path,
        result.markdown_path,
    )
    payload = {
        "report_type": "fundamental_data_status",
        "rule_version": RULE_VERSION,
        "generated_at": utc_now().isoformat(),
        "summary": result.to_summary(),
        "input_sha256": {str(path): _sha256(path) for path in input_paths},
        "artifact_sha256": {str(path): _sha256(path) for path in artifacts},
        "contains_forward_labels": False,
        "fundamental_signal_status": "not_connected",
    }
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    result.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_run_id() -> str:
    return f"cf_r93j_fundamental_status_{uuid.uuid4().hex[:8]}"
