"""R54 CF fundamental context and explanation layer."""

from __future__ import annotations

import csv
import json
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, project_root, reports_dir
from cotton_factor.common.time import utc_now
from cotton_factor.research_workbench import latest_signal_brief as r23
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME

PRODUCT_CODE = "CF"
FUNDAMENTAL_CONTEXT_VERSION = "R54_fundamental_context_v1"
OUTPUT_DIR = "fundamental_context"
DEFAULT_CHANGE_WINDOWS = (1, 4, 12)
PRICE_CONTEXT_WINDOW = 20
INFO_SEVERITY = "INFO"
WARN_SEVERITY = "WARN"
HUMAN_REVIEW_REQUIRED = (
    "fundamental_observation_interpretation",
    "textile_chain_field_interpretation",
    "basis_active_contract_interpretation",
    "warehouse_receipt_quantity_source",
    "inventory_source_and_unit",
    "import_period_and_unit",
    "fundamental_signal_rule_before_use",
)
WARNING_COLUMNS = (
    "severity",
    "warning_code",
    "message",
    "affected_count",
    "human_review_required",
)


@dataclass(frozen=True)
class FundamentalContextWarningRecord:
    """Warning row for R54 fundamental context."""

    severity: str
    warning_code: str
    message: str
    affected_count: int = 0
    human_review_required: tuple[str, ...] = ()

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable warning row."""
        return {
            "severity": self.severity,
            "warning_code": self.warning_code,
            "message": self.message,
            "affected_count": self.affected_count,
            "human_review_required": list(self.human_review_required),
        }

    def to_csv_row(self) -> dict[str, str]:
        """Return a CSV row."""
        return {
            "severity": self.severity,
            "warning_code": self.warning_code,
            "message": self.message,
            "affected_count": str(self.affected_count),
            "human_review_required": ";".join(self.human_review_required),
        }


@dataclass(frozen=True)
class ResearchFundamentalContextResult:
    """Result of building R54 fundamental context artifacts."""

    product_code: str
    run_id: str
    status: str
    data_asof: date | None
    context_row_count: int
    summary_row_count: int
    warning_records: tuple[FundamentalContextWarningRecord, ...]
    fundamental_observation_json_path: Path
    core_quote_path: Path
    context_parquet_path: Path
    context_csv_path: Path
    summary_parquet_path: Path
    summary_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    human_review_required: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """R54 passes when artifacts are written and inputs were inspectable."""
        return self.status in {
            "FUNDAMENTAL_CONTEXT_READY_WITH_WARNINGS",
            "NO_USABLE_FUNDAMENTAL_CONTEXT",
        }

    @property
    def warning_count(self) -> int:
        """Return non-info warning count."""
        return sum(1 for warning in self.warning_records if warning.severity != INFO_SEVERITY)

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI summary."""
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "status": self.status,
            "passed": self.passed,
            "data_asof": None if self.data_asof is None else self.data_asof.isoformat(),
            "context_row_count": self.context_row_count,
            "summary_row_count": self.summary_row_count,
            "warning_count": self.warning_count,
            "warnings": [warning.to_summary() for warning in self.warning_records],
            "fundamental_observation_json_path": str(
                self.fundamental_observation_json_path
            ),
            "core_quote_path": str(self.core_quote_path),
            "context_parquet_path": str(self.context_parquet_path),
            "context_csv_path": str(self.context_csv_path),
            "summary_parquet_path": str(self.summary_parquet_path),
            "summary_csv_path": str(self.summary_csv_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "fundamental_signal_status": "not_connected",
            "human_review_required": list(self.human_review_required),
        }


def build_cf_fundamental_context(
    *,
    fundamental_observation_json_path: Path | None = None,
    core_quote_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    change_windows: tuple[int, ...] = DEFAULT_CHANGE_WINDOWS,
) -> ResearchFundamentalContextResult:
    """Build R54 historical fundamental context without creating trading signals."""
    normalized_windows = _normalize_windows(change_windows)
    observation_path = (
        fundamental_observation_json_path or _default_fundamental_observation_json_path()
    )
    quote_path = core_quote_path or data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    observation_payload = _load_fundamental_observation(observation_path)
    market = _main_contract_market_context(quote_path)
    tables, table_warnings = _load_fundamental_tables(observation_payload, observation_path)
    observations = _normalize_observations(tables)
    context = _build_context_rows(
        observations=observations,
        market=market,
        change_windows=normalized_windows,
    )
    summary = _summary_rows(context)
    warnings = _warning_records(
        observation_payload=observation_payload,
        table_warnings=table_warnings,
        context=context,
    )
    data_asof = _max_date(context)
    status = (
        "FUNDAMENTAL_CONTEXT_READY_WITH_WARNINGS"
        if not context.empty
        else "NO_USABLE_FUNDAMENTAL_CONTEXT"
    )
    context_run_id = run_id or _default_run_id()
    paths = _output_paths(output_dir)
    result = ResearchFundamentalContextResult(
        product_code=PRODUCT_CODE,
        run_id=context_run_id,
        status=status,
        data_asof=data_asof,
        context_row_count=int(len(context)),
        summary_row_count=int(len(summary)),
        warning_records=tuple(warnings),
        fundamental_observation_json_path=observation_path,
        core_quote_path=quote_path,
        context_parquet_path=paths["context_parquet"],
        context_csv_path=paths["context_csv"],
        summary_parquet_path=paths["summary_parquet"],
        summary_csv_path=paths["summary_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=_markdown_path(report_output_dir),
        json_path=_json_path(report_output_dir),
        manifest_path=paths["manifest"],
        human_review_required=_human_review_required(warnings),
    )
    _write_outputs(
        result=result,
        context=context,
        summary=summary,
        observation_payload=observation_payload,
    )
    return result


def _load_fundamental_observation(path: Path) -> dict[str, object]:
    if not path.exists():
        raise ResearchWorkbenchError(f"fundamental observation JSON not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("report_type") != "fundamental_observation":
        raise ResearchWorkbenchError(
            "fundamental observation JSON must be fundamental_observation"
        )
    if payload.get("fundamental_signal_status") != "not_connected":
        raise ResearchWorkbenchError("fundamental observation must remain not_connected")
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise ResearchWorkbenchError("fundamental observation JSON missing summary object")
    return payload


def _load_fundamental_tables(
    payload: dict[str, object],
    observation_path: Path,
) -> tuple[dict[str, pd.DataFrame], list[FundamentalContextWarningRecord]]:
    summary = payload.get("summary")
    summary_dict = summary if isinstance(summary, dict) else {}
    table_specs = {
        "basis": "basis_path",
        "warehouse_receipt": "warehouse_receipt_path",
        "inventory": "inventory_path",
        "import": "import_path",
        "textile_chain": "textile_chain_path",
    }
    tables: dict[str, pd.DataFrame] = {}
    warnings: list[FundamentalContextWarningRecord] = []
    for dataset_type, key in table_specs.items():
        raw_path = summary_dict.get(key)
        if not raw_path:
            tables[dataset_type] = _empty_input_frame()
            warnings.append(
                FundamentalContextWarningRecord(
                    severity=WARN_SEVERITY,
                    warning_code=f"R54_{dataset_type.upper()}_PATH_MISSING",
                    message=f"R53 JSON 未提供 {dataset_type} 表路径。",
                    affected_count=1,
                    human_review_required=("fundamental_observation_interpretation",),
                )
            )
            continue
        table_path = _resolve_path(raw_path, base_path=observation_path)
        if not table_path.exists():
            tables[dataset_type] = _empty_input_frame()
            warnings.append(
                FundamentalContextWarningRecord(
                    severity=WARN_SEVERITY,
                    warning_code=f"R54_{dataset_type.upper()}_TABLE_MISSING",
                    message=f"未找到 {dataset_type} 表：{table_path}",
                    affected_count=1,
                    human_review_required=("fundamental_observation_interpretation",),
                )
            )
            continue
        tables[dataset_type] = _read_table(table_path)
    return tables, warnings


def _resolve_path(raw_path: object, *, base_path: Path) -> Path:
    value = Path(str(raw_path))
    if value.is_absolute():
        return value
    candidates = [
        project_root() / value,
        base_path.parent / value,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    return pd.read_parquet(path)


def _normalize_observations(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = [
        _normalize_basis(tables.get("basis", _empty_input_frame())),
        _normalize_warehouse_receipt(
            tables.get("warehouse_receipt", _empty_input_frame())
        ),
        _normalize_inventory(tables.get("inventory", _empty_input_frame())),
        _normalize_import(tables.get("import", _empty_input_frame())),
        _normalize_textile_chain(tables.get("textile_chain", _empty_input_frame())),
    ]
    usable = [frame for frame in frames if not frame.empty]
    if not usable:
        return _empty_context_input_frame()
    combined = pd.concat(usable, ignore_index=True)
    combined["trade_date"] = pd.to_datetime(combined["trade_date"], errors="coerce")
    combined = combined.dropna(subset=["trade_date", "indicator_value"])
    return combined.sort_values(
        ["dataset_type", "indicator_name", "metric_name", "trade_date"]
    ).reset_index(drop=True)


def _normalize_basis(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "basis" not in frame.columns:
        return _empty_context_input_frame()
    working = frame.copy()
    working["dataset_type"] = "basis"
    working["indicator_name"] = "basis:" + working.get("region", "unknown").astype(str)
    working["metric_name"] = "basis"
    working["indicator_value"] = pd.to_numeric(working["basis"], errors="coerce")
    working["source_name"] = working.get("source_name", "iFinD")
    working["source_file"] = working.get("source_file", "")
    working["unit"] = working.get("unit", "元/吨")
    working["data_quality_flag"] = working.get("data_quality_flag", "REVIEW_REQUIRED")
    working["remark"] = working.get("remark", "")
    return _select_context_input_columns(working)


def _normalize_warehouse_receipt(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "warehouse_receipt" not in frame.columns:
        return _empty_context_input_frame()
    working = frame.copy()
    working["dataset_type"] = "warehouse_receipt"
    working["metric_name"] = "warehouse_receipt"
    working["indicator_value"] = pd.to_numeric(
        working["warehouse_receipt"], errors="coerce"
    )
    return _select_context_input_columns(working)


def _normalize_inventory(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "inventory_value" not in frame.columns:
        return _empty_context_input_frame()
    working = frame.copy()
    working["dataset_type"] = "inventory"
    working["metric_name"] = "inventory"
    working["indicator_value"] = pd.to_numeric(working["inventory_value"], errors="coerce")
    return _select_context_input_columns(working)


def _normalize_import(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "import_value" not in frame.columns:
        return _empty_context_input_frame()
    working = frame.copy()
    working["dataset_type"] = "import"
    working["metric_name"] = "import"
    working["indicator_value"] = pd.to_numeric(working["import_value"], errors="coerce")
    return _select_context_input_columns(working)


def _normalize_textile_chain(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "indicator_value" not in frame.columns:
        return _empty_context_input_frame()
    working = frame.copy()
    working["dataset_type"] = "textile_chain"
    working["metric_name"] = working.get("metric_name", "value").astype(str)
    return _select_context_input_columns(working)


def _select_context_input_columns(frame: pd.DataFrame) -> pd.DataFrame:
    for column, default in {
        "product_code": PRODUCT_CODE,
        "indicator_name": "unknown",
        "metric_name": "value",
        "unit": "",
        "source_name": "",
        "source_file": "",
        "data_quality_flag": "REVIEW_REQUIRED",
        "human_review_required": True,
        "remark": "",
    }.items():
        if column not in frame.columns:
            frame[column] = default
    if "raw_indicator_name" not in frame.columns:
        frame["raw_indicator_name"] = frame["indicator_name"]
    return frame[
        [
            "trade_date",
            "product_code",
            "dataset_type",
            "indicator_name",
            "raw_indicator_name",
            "metric_name",
            "indicator_value",
            "unit",
            "source_name",
            "source_file",
            "data_quality_flag",
            "human_review_required",
            "remark",
        ]
    ].copy()


def _main_contract_market_context(core_quote_path: Path) -> pd.DataFrame:
    quotes = r23._load_core_quotes(input_path=core_quote_path)
    if quotes.empty:
        raise ResearchWorkbenchError(f"no {PRODUCT_CODE} core quote rows available")
    working = quotes.copy()
    working["_volume"] = pd.to_numeric(working["volume"], errors="coerce").fillna(0)
    working["_open_interest"] = pd.to_numeric(
        working["open_interest"], errors="coerce"
    ).fillna(0)
    working = working.sort_values(
        ["trade_date", "_open_interest", "_volume", "contract_code"],
        ascending=[True, False, False, True],
    )
    main = working.groupby("trade_date", as_index=False).head(1).copy()
    main = main.sort_values("trade_date").reset_index(drop=True)
    main["market_trade_date"] = pd.to_datetime(main["trade_date"])
    main["main_contract"] = main["contract_code"].astype(str)
    main["main_settle"] = pd.to_numeric(main["settle"], errors="coerce")
    # 价格上下文只使用当前观察日以前的主力序列，作为同向/背离解释，不是未来收益标签。
    main["main_settle_change_20d"] = main["main_settle"].pct_change(
        PRICE_CONTEXT_WINDOW
    )
    main["price_direction_20d"] = main["main_settle_change_20d"].map(_direction)
    return main[
        [
            "market_trade_date",
            "main_contract",
            "main_settle",
            "main_settle_change_20d",
            "price_direction_20d",
            "source_snapshot_id",
        ]
    ]


def _build_context_rows(
    *,
    observations: pd.DataFrame,
    market: pd.DataFrame,
    change_windows: tuple[int, ...],
) -> pd.DataFrame:
    if observations.empty:
        return _empty_context_frame(change_windows)
    enriched = _add_observation_changes(observations, change_windows)
    enriched["trade_date_ts"] = pd.to_datetime(enriched["trade_date"])
    market_sorted = market.sort_values("market_trade_date")
    enriched = pd.merge_asof(
        enriched.sort_values("trade_date_ts"),
        market_sorted,
        left_on="trade_date_ts",
        right_on="market_trade_date",
        direction="backward",
    )
    for window in change_windows:
        direction_col = f"direction_{window}_obs"
        relation_col = f"explanation_relation_{window}_vs_price20"
        label_col = f"context_label_{window}"
        enriched[label_col] = enriched.apply(
            lambda row, active_window=window: _context_label(row, active_window),
            axis=1,
        )
        enriched[relation_col] = enriched.apply(
            lambda row, active_direction_col=direction_col: _explanation_relation(
                row,
                direction_col=active_direction_col,
            ),
            axis=1,
        )
    enriched["interpretation_status"] = "HUMAN_REVIEW_REQUIRED"
    enriched["fundamental_signal_status"] = "not_connected"
    enriched = enriched.drop(columns=["trade_date_ts"], errors="ignore")
    return enriched.sort_values(
        ["trade_date", "dataset_type", "indicator_name", "metric_name"]
    ).reset_index(drop=True)


def _add_observation_changes(
    observations: pd.DataFrame,
    change_windows: tuple[int, ...],
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    group_columns = ["dataset_type", "indicator_name", "metric_name"]
    for _, group in observations.groupby(group_columns, dropna=False, sort=False):
        working = group.sort_values("trade_date").copy()
        values = pd.to_numeric(working["indicator_value"], errors="coerce")
        for window in change_windows:
            previous = values.shift(window)
            change = values - previous
            denominator = previous.abs().where(previous.abs() > 0)
            working[f"previous_value_{window}_obs"] = previous
            working[f"change_{window}_obs"] = change
            working[f"change_pct_{window}_obs"] = change / denominator
            working[f"direction_{window}_obs"] = change.map(_direction)
        frames.append(working)
    return pd.concat(frames, ignore_index=True) if frames else observations.copy()


def _summary_rows(context: pd.DataFrame) -> pd.DataFrame:
    if context.empty:
        return _empty_summary_frame()
    rows: list[dict[str, object]] = []
    group_columns = ["dataset_type", "indicator_name", "metric_name"]
    for key, group in context.groupby(group_columns, dropna=False, sort=True):
        dataset_type, indicator_name, metric_name = key
        ordered = group.sort_values("trade_date")
        latest = ordered.iloc[-1].to_dict()
        relation = ordered["explanation_relation_4_vs_price20"]
        aligned = int((relation == "aligned_trailing_context").sum())
        divergent = int((relation == "divergent_trailing_context").sum())
        comparable = aligned + divergent
        raw_indicator_names = tuple(
            sorted(str(value) for value in ordered["raw_indicator_name"].dropna().unique())
        )
        rows.append(
            {
                "dataset_type": dataset_type,
                "indicator_name": indicator_name,
                "raw_indicator_names": "；".join(raw_indicator_names),
                "metric_name": metric_name,
                "observation_count": int(len(ordered)),
                "date_start": pd.to_datetime(ordered["trade_date"]).min().date(),
                "date_end": pd.to_datetime(ordered["trade_date"]).max().date(),
                "latest_value": _float_or_none(latest.get("indicator_value")),
                "latest_unit": latest.get("unit"),
                "latest_change_1_obs": _float_or_none(latest.get("change_1_obs")),
                "latest_change_4_obs": _float_or_none(latest.get("change_4_obs")),
                "latest_direction_4_obs": latest.get("direction_4_obs"),
                "latest_context_label_4": latest.get("context_label_4"),
                "latest_main_contract": latest.get("main_contract"),
                "latest_price_direction_20d": latest.get("price_direction_20d"),
                "aligned_trailing_context_count": aligned,
                "divergent_trailing_context_count": divergent,
                "alignment_rate": None if comparable == 0 else aligned / comparable,
                "interpretation_status": "HUMAN_REVIEW_REQUIRED",
                "fundamental_signal_status": "not_connected",
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["dataset_type", "indicator_name", "metric_name"]
    ).reset_index(drop=True)


def _context_label(row: pd.Series, window: int) -> str:
    direction = str(row.get(f"direction_{window}_obs"))
    dataset_type = str(row.get("dataset_type"))
    indicator_name = str(row.get("indicator_name"))
    if direction in {"unknown", "flat"}:
        return "观察不足或变化不明显"
    if "负荷" in indicator_name or "开工" in indicator_name:
        return "下游负荷改善" if direction == "increase" else "下游负荷走弱"
    if dataset_type == "basis":
        return "基差扩大，现货相对偏强" if direction == "increase" else "基差收窄，现货相对走弱"
    if dataset_type == "warehouse_receipt":
        if direction == "increase":
            return "注册仓单增加，潜在交割供应压力上升"
        return "注册仓单下降，交割供应压力缓和"
    if dataset_type == "import":
        return (
            "进口观察值上升，统计期/单位需人工复核"
            if direction == "increase"
            else "进口观察值下降，统计期/单位需人工复核"
        )
    if dataset_type in {"inventory", "textile_chain"} and "库存" in indicator_name:
        return "库存/库存天数上升" if direction == "increase" else "库存/库存天数下降"
    return "基本面观察值上升" if direction == "increase" else "基本面观察值下降"


def _explanation_relation(row: pd.Series, *, direction_col: str) -> str:
    expected = _expected_price_direction(
        dataset_type=str(row.get("dataset_type")),
        indicator_name=str(row.get("indicator_name")),
        observation_direction=str(row.get(direction_col)),
    )
    price_direction = str(row.get("price_direction_20d"))
    if expected == "unknown" or price_direction == "unknown":
        return "insufficient_context"
    if price_direction == "flat":
        return "neutral_price_context"
    if expected == price_direction:
        return "aligned_trailing_context"
    return "divergent_trailing_context"


def _expected_price_direction(
    *,
    dataset_type: str,
    indicator_name: str,
    observation_direction: str,
) -> str:
    if observation_direction not in {"increase", "decrease"}:
        return "unknown"
    if "负荷" in indicator_name or "开工" in indicator_name or dataset_type == "basis":
        return "increase" if observation_direction == "increase" else "decrease"
    if dataset_type == "warehouse_receipt" or "库存" in indicator_name:
        return "decrease" if observation_direction == "increase" else "increase"
    if dataset_type == "import":
        return "decrease" if observation_direction == "increase" else "increase"
    return "unknown"


def _direction(value: object) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "unknown"
    if abs(numeric) <= 1e-12:
        return "flat"
    return "increase" if numeric > 0 else "decrease"


def _warning_records(
    *,
    observation_payload: dict[str, object],
    table_warnings: list[FundamentalContextWarningRecord],
    context: pd.DataFrame,
) -> list[FundamentalContextWarningRecord]:
    warnings = [
        FundamentalContextWarningRecord(
            severity=INFO_SEVERITY,
            warning_code="R54_FUNDAMENTAL_SIGNAL_NOT_CONNECTED",
            message=(
                "R54 基本面解释层不生成 fundamental_signal，"
                "不进入 signal matrix 或 composite_score。"
            ),
            affected_count=int(len(context)),
            human_review_required=("fundamental_signal_rule_before_use",),
        ),
        FundamentalContextWarningRecord(
            severity=INFO_SEVERITY,
            warning_code="R54_NO_FORWARD_RETURN_LABELS",
            message=(
                "R54 只使用基本面观察日及以前的变化和主力价格上下文，"
                "不输出 forward_return 后验标签。"
            ),
            affected_count=int(len(context)),
            human_review_required=(),
        ),
    ]
    warnings.extend(table_warnings)
    upstream_warnings = _upstream_warning_codes(observation_payload)
    if upstream_warnings:
        warnings.append(
            FundamentalContextWarningRecord(
                severity=WARN_SEVERITY,
                warning_code="R54_UPSTREAM_R53_WARNINGS_PRESENT",
                message="R53 基本面观察仍存在待复核项：" + "；".join(upstream_warnings),
                affected_count=len(upstream_warnings),
                human_review_required=("fundamental_observation_interpretation",),
            )
        )
    if context.empty:
        warnings.append(
            FundamentalContextWarningRecord(
                severity=WARN_SEVERITY,
                warning_code="R54_NO_USABLE_FUNDAMENTAL_CONTEXT",
                message="未生成可用基本面解释行。",
                affected_count=0,
                human_review_required=("fundamental_observation_interpretation",),
            )
        )
    else:
        comparable = context["explanation_relation_4_vs_price20"].isin(
            ["aligned_trailing_context", "divergent_trailing_context"]
        )
        warnings.append(
            FundamentalContextWarningRecord(
                severity=INFO_SEVERITY,
                warning_code="R54_TRAILING_RELATION_REQUIRES_REVIEW",
                message=(
                    "同向/背离只比较基本面自身变化与过去 20 个主力交易日价格方向，"
                    "是解释上下文，不是交易有效性验证。"
                ),
                affected_count=int(comparable.sum()),
                human_review_required=("fundamental_observation_interpretation",),
            )
        )
    return warnings


def _upstream_warning_codes(payload: dict[str, object]) -> list[str]:
    summary = payload.get("summary")
    summary_dict = summary if isinstance(summary, dict) else {}
    warnings = summary_dict.get("warnings")
    if not isinstance(warnings, list):
        return []
    codes: list[str] = []
    for warning in warnings:
        if not isinstance(warning, dict) or warning.get("severity") == "INFO":
            continue
        code = str(warning.get("warning_code"))
        if code and code not in codes:
            codes.append(code)
    return codes


def _write_outputs(
    *,
    result: ResearchFundamentalContextResult,
    context: pd.DataFrame,
    summary: pd.DataFrame,
    observation_payload: dict[str, object],
) -> None:
    result.context_parquet_path.parent.mkdir(parents=True, exist_ok=True)
    context.to_parquet(result.context_parquet_path, index=False)
    context.to_csv(result.context_csv_path, index=False, encoding="utf-8-sig")
    summary.to_parquet(result.summary_parquet_path, index=False)
    summary.to_csv(result.summary_csv_path, index=False, encoding="utf-8-sig")
    _write_warning_csv(result)
    _write_markdown(result=result, context=context, summary=summary)
    _write_json(
        result=result,
        context=context,
        summary=summary,
        observation_payload=observation_payload,
    )
    _write_manifest(result)


def _write_warning_csv(result: ResearchFundamentalContextResult) -> None:
    result.warning_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with result.warning_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows([warning.to_csv_row() for warning in result.warning_records])


def _write_markdown(
    *,
    result: ResearchFundamentalContextResult,
    context: pd.DataFrame,
    summary: pd.DataFrame,
) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    latest_rows = _latest_summary_rows(summary)
    relation_counts = (
        context["explanation_relation_4_vs_price20"].value_counts().to_dict()
        if not context.empty
        else {}
    )
    lines = [
        f"# CF 基本面解释层 R54 - {_date_text(result.data_asof)}",
        "",
        "## 数据状态",
        "",
        "- 报告类型：`fundamental_context`",
        f"- 状态：`{result.status}`",
        f"- Run ID：`{result.run_id}`",
        f"- 数据截至：`{_date_text(result.data_asof)}`",
        f"- 基本面输入：`{result.fundamental_observation_json_path}`",
        f"- 核心行情输入：`{result.core_quote_path}`",
        f"- 解释明细行数：`{result.context_row_count}`",
        f"- 汇总行数：`{result.summary_row_count}`",
        "- 基本面信号状态：`not_connected`",
        "- 本层只做历史解释上下文，不进入 signal matrix 或 composite_score。",
        "",
        "## 最新基本面解释摘要",
        "",
        (
            "| 数据集 | 指标 | 原始口径 | 口径 | 最新值 | 4期变化方向 | "
            "解释标签 | 主力 | 20日价格方向 | 同向率 |"
        ),
        "| --- | --- | --- | --- | ---: | --- | --- | --- | --- | ---: |",
    ]
    for row in latest_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("dataset_type")),
                    str(row.get("indicator_name")),
                    str(row.get("raw_indicator_names")),
                    str(row.get("metric_name")),
                    _fmt_number(row.get("latest_value")),
                    str(row.get("latest_direction_4_obs")),
                    str(row.get("latest_context_label_4")),
                    str(row.get("latest_main_contract")),
                    str(row.get("latest_price_direction_20d")),
                    _fmt_percent(row.get("alignment_rate")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 同向/背离历史观察",
            "",
            f"- 4期变化与过去 {PRICE_CONTEXT_WINDOW} 个主力交易日价格方向同向："
            f"`{relation_counts.get('aligned_trailing_context', 0)}` 行。",
            f"- 4期变化与过去 {PRICE_CONTEXT_WINDOW} 个主力交易日价格方向背离："
            f"`{relation_counts.get('divergent_trailing_context', 0)}` 行。",
            "- 上下文不足或价格中性："
            f"`{_insufficient_relation_count(relation_counts)}` 行。",
            "",
            "## 输出文件",
            "",
            f"- 解释明细：`{result.context_parquet_path}`",
            f"- 解释汇总：`{result.summary_parquet_path}`",
            f"- 告警表：`{result.warning_csv_path}`",
            "",
            "## 缺失与复核",
            "",
        ]
    )
    for warning in result.warning_records:
        if warning.severity == INFO_SEVERITY:
            continue
        lines.append(f"- `{warning.warning_code}`：{warning.message}")
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "- R54 不生成 `fundamental_signal`。",
            "- R54 不输出 forward_return 后验标签；历史收益验证仍由 R41/R42/R43 主线负责。",
            "- 库存、仓单、基差、纺织链口径均标记 `HUMAN_REVIEW_REQUIRED`。",
            "- 同向/背离只是解释当前价格结构的上下文，不构成交易指令。",
        ]
    )
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_json(
    *,
    result: ResearchFundamentalContextResult,
    context: pd.DataFrame,
    summary: pd.DataFrame,
    observation_payload: dict[str, object],
) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "report_type": "fundamental_context",
        "rule_version": FUNDAMENTAL_CONTEXT_VERSION,
        "generated_at": utc_now().isoformat(),
        "summary": result.to_summary(),
        "fundamental_signal_status": "not_connected",
        "contains_forward_return_labels": False,
        "r53_warning_codes": _upstream_warning_codes(observation_payload),
        "latest_summary_rows": _latest_summary_rows(summary),
        "context_preview_rows": context.tail(40).to_dict(orient="records"),
    }
    result.json_path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _write_manifest(result: ResearchFundamentalContextResult) -> None:
    manifest = {
        "report_type": "fundamental_context",
        "rule_version": FUNDAMENTAL_CONTEXT_VERSION,
        "generated_at": utc_now().isoformat(),
        **result.to_summary(),
        "contains_forward_return_labels": False,
    }
    result.manifest_path.write_text(
        json.dumps(_json_safe(manifest), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _latest_summary_rows(summary: pd.DataFrame) -> list[dict[str, object]]:
    if summary.empty:
        return []
    rows = summary.sort_values(["dataset_type", "indicator_name", "metric_name"]).to_dict(
        orient="records"
    )
    priority = {
        "basis": 0,
        "warehouse_receipt": 1,
        "textile_chain": 2,
        "inventory": 3,
        "import": 4,
    }
    rows.sort(key=lambda row: (priority.get(str(row.get("dataset_type")), 99), str(row)))
    return rows[:18]


def _insufficient_relation_count(relation_counts: dict[object, int]) -> int:
    return int(relation_counts.get("insufficient_context", 0)) + int(
        relation_counts.get("neutral_price_context", 0)
    )


def _output_paths(output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_fundamental_context"
    return {
        "context_parquet": root / f"{stem}_daily.parquet",
        "context_csv": root / f"{stem}_daily.csv",
        "summary_parquet": root / f"{stem}_summary.parquet",
        "summary_csv": root / f"{stem}_summary.csv",
        "warning_csv": root / f"{stem}_warnings.csv",
        "manifest": root / f"{stem}_manifest.json",
    }


def _markdown_path(report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    return root / f"{PRODUCT_CODE}_fundamental_context.md"


def _json_path(report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    return root / f"{PRODUCT_CODE}_fundamental_context.json"


def _default_fundamental_observation_json_path() -> Path:
    return (
        data_dir()
        / "research"
        / PRODUCT_CODE
        / "fundamentals"
        / f"{PRODUCT_CODE}_fundamental_observation.json"
    )


def _normalize_windows(windows: tuple[int, ...]) -> tuple[int, ...]:
    if not windows:
        raise ResearchWorkbenchError("at least one change window is required")
    values = tuple(sorted(set(windows)))
    invalid = [window for window in values if window <= 0]
    if invalid:
        raise ResearchWorkbenchError(f"change windows must be positive: {invalid}")
    return values


def _max_date(frame: pd.DataFrame) -> date | None:
    if frame.empty or "trade_date" not in frame.columns:
        return None
    return pd.to_datetime(frame["trade_date"], errors="coerce").max().date()


def _human_review_required(
    warnings: list[FundamentalContextWarningRecord],
) -> tuple[str, ...]:
    values = list(HUMAN_REVIEW_REQUIRED)
    values.extend(item for warning in warnings for item in warning.human_review_required)
    return tuple(r23._unique_values(values))


def _empty_input_frame() -> pd.DataFrame:
    return pd.DataFrame()


def _empty_context_input_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "trade_date",
            "product_code",
            "dataset_type",
            "indicator_name",
            "raw_indicator_name",
            "metric_name",
            "indicator_value",
            "unit",
            "source_name",
            "source_file",
            "data_quality_flag",
            "human_review_required",
            "remark",
        ]
    )


def _empty_context_frame(change_windows: tuple[int, ...]) -> pd.DataFrame:
    frame = _empty_context_input_frame()
    for window in change_windows:
        for column in (
            f"previous_value_{window}_obs",
            f"change_{window}_obs",
            f"change_pct_{window}_obs",
            f"direction_{window}_obs",
            f"context_label_{window}",
            f"explanation_relation_{window}_vs_price20",
        ):
            frame[column] = pd.Series(dtype="object")
    for column in (
        "market_trade_date",
        "main_contract",
        "main_settle",
        "main_settle_change_20d",
        "price_direction_20d",
        "source_snapshot_id",
        "interpretation_status",
        "fundamental_signal_status",
    ):
        frame[column] = pd.Series(dtype="object")
    return frame


def _empty_summary_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "dataset_type",
            "indicator_name",
            "raw_indicator_names",
            "metric_name",
            "observation_count",
            "date_start",
            "date_end",
            "latest_value",
            "latest_unit",
            "latest_change_1_obs",
            "latest_change_4_obs",
            "latest_direction_4_obs",
            "latest_context_label_4",
            "latest_main_contract",
            "latest_price_direction_20d",
            "aligned_trailing_context_count",
            "divergent_trailing_context_count",
            "alignment_rate",
            "interpretation_status",
            "fundamental_signal_status",
        ]
    )


def _float_or_none(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _fmt_number(value: object) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "-"
    return f"{numeric:.2f}"


def _fmt_percent(value: object) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "-"
    return f"{numeric:.2%}"


def _date_text(value: date | None) -> str:
    return "NA" if value is None else value.isoformat()


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if _is_scalar_missing(value):
        return None
    return value


def _is_scalar_missing(value: object) -> bool:
    if isinstance(value, (list, tuple, dict, str, Path, date, pd.Timestamp)):
        return False
    return bool(pd.isna(value))


def _default_run_id() -> str:
    return f"r54_fundamental_context_{PRODUCT_CODE}_{uuid.uuid4().hex[:8]}"
