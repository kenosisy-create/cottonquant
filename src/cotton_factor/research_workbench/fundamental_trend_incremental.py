"""R93K 基本面发布时间对齐与趋势事件增量研究。"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME

PRODUCT_CODE = "CF"
RULE_VERSION = "V5.1_R93K_fundamental_trend_incremental_v2"
DEFAULT_HORIZONS = (5, 20)
DEFAULT_CHANGE_PERIODS = 4
DEFAULT_MIN_SAMPLE_SIZE = 20
DEFAULT_FDR_LEVEL = 0.10
DEFAULT_PROXY_LAGS = (0, 5, 10)
INFO = "INFO"
WARN = "WARN"
RESEARCH_BOUNDARY = (
    "基本面特征只使用事件日及以前已知记录；趋势收益仅作为历史后验标签。"
    "RELEASE_DATE_EXACT与OBSERVATION_DATE_PROXY物理分组，代理证据不得晋级策略，"
    "本模块不修改composite_score，不构成交易指令。"
)
EVENT_COLUMNS = {
    "event_id",
    "event_date",
    "direction",
    "direction_episode_id",
    "horizon",
    "directional_return",
    "label_available",
    "outcome",
    "historical_posterior_label",
}
WARNING_COLUMNS = (
    "run_id",
    "severity",
    "warning_code",
    "warning_message",
    "affected_count",
    "human_review_required",
)

# 只使用经济含义清晰且不重复的代表序列，避免同一底层数据重复计票。
BASE_SERIES_SPECS = (
    {
        "dataset_type": "spot_price",
        "filename": "CF_fundamental_spot_price_daily.parquet",
        "indicator_name": "中国棉花价格指数:3128B",
        "value_column": "indicator_value",
        "frequency": "D",
        "expected_effect": "DEMAND_OR_TIGHTNESS_POSITIVE",
    },
    {
        "dataset_type": "basis",
        "filename": "CF_fundamental_basis_daily.parquet",
        "indicator_column": "basis_indicator_name",
        "indicator_name": "基差",
        "value_column": "basis",
        "frequency": "D",
        "expected_effect": "DEMAND_OR_TIGHTNESS_POSITIVE",
    },
    {
        "dataset_type": "warehouse_receipt",
        "filename": "CF_fundamental_warehouse_receipt_daily.parquet",
        "indicator_name": "仓单数量:一号棉",
        "value_column": "warehouse_receipt",
        "frequency": "D",
        "expected_effect": "SUPPLY_PRESSURE_POSITIVE",
    },
    {
        "dataset_type": "inventory",
        "filename": "CF_fundamental_inventory_daily.parquet",
        "indicator_name": "中国:商业库存量:棉花",
        "value_column": "inventory_value",
        "frequency": "M",
        "expected_effect": "SUPPLY_PRESSURE_POSITIVE",
    },
    {
        "dataset_type": "inventory",
        "filename": "CF_fundamental_inventory_daily.parquet",
        "indicator_name": "中国:工业库存量:棉花",
        "value_column": "inventory_value",
        "frequency": "M",
        "expected_effect": "DEMAND_OR_TIGHTNESS_POSITIVE",
    },
    {
        "dataset_type": "import",
        "filename": "CF_fundamental_import_daily.parquet",
        "indicator_name": "棉花:进口数量:当月值",
        "value_column": "import_value",
        "frequency": "M",
        "expected_effect": "SUPPLY_PRESSURE_POSITIVE",
    },
    {
        "dataset_type": "textile_chain",
        "filename": "CF_fundamental_textile_chain_daily.parquet",
        "indicator_name": "纯棉纱厂负荷",
        "metric_name": "周均",
        "value_column": "indicator_value",
        "frequency": "W",
        "expected_effect": "DEMAND_OR_TIGHTNESS_POSITIVE",
    },
    {
        "dataset_type": "textile_chain",
        "filename": "CF_fundamental_textile_chain_daily.parquet",
        "indicator_name": "全棉坯布负荷",
        "metric_name": "周均",
        "value_column": "indicator_value",
        "frequency": "W",
        "expected_effect": "DEMAND_OR_TIGHTNESS_POSITIVE",
    },
    {
        "dataset_type": "textile_chain",
        "filename": "CF_fundamental_textile_chain_daily.parquet",
        "indicator_name": "纺企棉纱库存",
        "metric_name": "周均",
        "value_column": "indicator_value",
        "frequency": "W",
        "expected_effect": "SUPPLY_PRESSURE_POSITIVE",
    },
    {
        "dataset_type": "textile_chain",
        "filename": "CF_fundamental_textile_chain_daily.parquet",
        "indicator_name": "全棉坯布库存",
        "metric_name": "周均",
        "value_column": "indicator_value",
        "frequency": "W",
        "expected_effect": "SUPPLY_PRESSURE_POSITIVE",
    },
)


@dataclass(frozen=True)
class FundamentalTrendIncrementalWarningRecord:
    """R93K警告与研究边界。"""

    run_id: str
    severity: str
    warning_code: str
    warning_message: str
    affected_count: int
    human_review_required: tuple[str, ...] = ()

    def to_summary(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "affected_count": self.affected_count,
            "human_review_required": list(self.human_review_required),
        }


@dataclass(frozen=True)
class FundamentalTrendIncrementalResult:
    """R93K研究产物与摘要。"""

    run_id: str
    start: date
    end: date
    status: str
    event_row_count: int
    independent_episode_count: int
    feature_row_count: int
    exact_feature_count: int
    proxy_feature_count: int
    exact_event_feature_count: int
    proxy_event_feature_count: int
    positive_candidate_count: int
    negative_filter_count: int
    knowledge_calendar_path: Path
    event_feature_path: Path
    summary_path: Path
    sensitivity_path: Path
    warning_csv_path: Path
    json_path: Path
    markdown_path: Path
    manifest_path: Path
    warning_records: tuple[FundamentalTrendIncrementalWarningRecord, ...]

    @property
    def warning_count(self) -> int:
        return sum(item.severity == WARN for item in self.warning_records)

    def to_summary(self) -> dict[str, object]:
        return {
            "product_code": PRODUCT_CODE,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "status": self.status,
            "event_row_count": self.event_row_count,
            "independent_episode_count": self.independent_episode_count,
            "feature_row_count": self.feature_row_count,
            "exact_feature_count": self.exact_feature_count,
            "proxy_feature_count": self.proxy_feature_count,
            "exact_event_feature_count": self.exact_event_feature_count,
            "proxy_event_feature_count": self.proxy_event_feature_count,
            "positive_candidate_count": self.positive_candidate_count,
            "negative_filter_count": self.negative_filter_count,
            "warning_count": self.warning_count,
            "warnings": [item.to_summary() for item in self.warning_records],
            "knowledge_calendar_path": str(self.knowledge_calendar_path),
            "event_feature_path": str(self.event_feature_path),
            "summary_path": str(self.summary_path),
            "sensitivity_path": str(self.sensitivity_path),
            "warning_csv_path": str(self.warning_csv_path),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "manifest_path": str(self.manifest_path),
            "historical_returns_are_posterior_labels": True,
            "fundamental_signal_status": "not_connected",
            "research_boundary": RESEARCH_BOUNDARY,
        }


def build_cf_fundamental_trend_incremental_research(
    *,
    breakout_event_path: Path | None = None,
    core_quote_path: Path | None = None,
    fundamental_dir: Path | None = None,
    ifind_cotton_context_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    change_periods: int = DEFAULT_CHANGE_PERIODS,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    fdr_level: float = DEFAULT_FDR_LEVEL,
    proxy_lags: tuple[int, ...] = DEFAULT_PROXY_LAGS,
) -> FundamentalTrendIncrementalResult:
    """构建发布时间感知的基本面趋势事件增量证据。"""
    normalized_horizons = _positive_values(horizons, "horizons")
    normalized_proxy_lags = _non_negative_values(proxy_lags, "proxy_lags")
    _validate_parameters(
        change_periods=change_periods,
        min_sample_size=min_sample_size,
        fdr_level=fdr_level,
    )
    event_path = breakout_event_path or _latest_breakout_event_path()
    quote_path = core_quote_path or data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    selected_fundamental_dir = (
        fundamental_dir or data_dir() / "research" / PRODUCT_CODE / "fundamentals"
    )
    ifind_path = ifind_cotton_context_path or _latest_ifind_cotton_context_path()
    events = _load_events(event_path, normalized_horizons)
    trading_dates = _load_trading_dates(quote_path)
    active_run_id = run_id or _default_run_id()
    calendar, input_paths, source_warnings = _build_knowledge_calendar(
        fundamental_dir=selected_fundamental_dir,
        ifind_cotton_context_path=ifind_path,
        proxy_lags=normalized_proxy_lags,
        change_periods=change_periods,
        run_id=active_run_id,
        trading_dates=trading_dates,
    )
    event_features = _align_events(events=events, calendar=calendar, run_id=active_run_id)
    summary = _build_summary(
        event_features,
        min_sample_size=min_sample_size,
        fdr_level=fdr_level,
    )
    sensitivity = _build_sensitivity(event_features, min_sample_size=min_sample_size)
    warnings = tuple(
        source_warnings
        + _warning_records(
            run_id=active_run_id,
            event_features=event_features,
            summary=summary,
            min_sample_size=min_sample_size,
        )
    )
    positive_count = int(summary["incremental_status"].eq("POSITIVE_CANDIDATE").sum())
    negative_count = int(summary["incremental_status"].eq("NEGATIVE_FILTER").sum())
    paths = _output_paths(
        start=events["event_date"].min(),
        end=events["event_date"].max(),
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    result = FundamentalTrendIncrementalResult(
        run_id=active_run_id,
        start=events["event_date"].min(),
        end=events["event_date"].max(),
        status=(
            "FUNDAMENTAL_TREND_INCREMENTAL_READY_WITH_WARNINGS"
            if any(item.severity == WARN for item in warnings)
            else "FUNDAMENTAL_TREND_INCREMENTAL_READY"
        ),
        event_row_count=len(events),
        independent_episode_count=int(events["direction_episode_id"].nunique()),
        feature_row_count=len(event_features),
        exact_feature_count=int(
            calendar["knowledge_quality"].eq("RELEASE_DATE_EXACT").sum()
        ),
        proxy_feature_count=int(
            calendar["knowledge_quality"].eq("OBSERVATION_DATE_PROXY").sum()
        ),
        exact_event_feature_count=int(
            event_features["knowledge_quality"].eq("RELEASE_DATE_EXACT").sum()
        ),
        proxy_event_feature_count=int(
            event_features["knowledge_quality"].eq("OBSERVATION_DATE_PROXY").sum()
        ),
        positive_candidate_count=positive_count,
        negative_filter_count=negative_count,
        knowledge_calendar_path=paths["calendar"],
        event_feature_path=paths["events"],
        summary_path=paths["summary"],
        sensitivity_path=paths["sensitivity"],
        warning_csv_path=paths["warnings"],
        json_path=paths["json"],
        markdown_path=paths["markdown"],
        manifest_path=paths["manifest"],
        warning_records=warnings,
    )
    _write_outputs(
        result=result,
        calendar=calendar,
        event_features=event_features,
        summary=summary,
        sensitivity=sensitivity,
        input_paths=[event_path, quote_path, *input_paths],
        parameters={
            "horizons": list(normalized_horizons),
            "change_periods": change_periods,
            "min_sample_size": min_sample_size,
            "fdr_level": fdr_level,
            "proxy_lags": list(normalized_proxy_lags),
        },
    )
    return result


def _build_knowledge_calendar(
    *,
    fundamental_dir: Path,
    ifind_cotton_context_path: Path,
    proxy_lags: tuple[int, ...],
    change_periods: int,
    run_id: str,
    trading_dates: pd.DatetimeIndex,
) -> tuple[
    pd.DataFrame,
    list[Path],
    list[FundamentalTrendIncrementalWarningRecord],
]:
    frames: list[pd.DataFrame] = []
    input_paths: list[Path] = []
    warnings: list[FundamentalTrendIncrementalWarningRecord] = []
    for spec in BASE_SERIES_SPECS:
        path = fundamental_dir / str(spec["filename"])
        if not path.exists():
            warnings.append(
                FundamentalTrendIncrementalWarningRecord(
                    run_id=run_id,
                    severity=WARN,
                    warning_code="R93K_BASE_SERIES_MISSING",
                    warning_message=f"基本面代表序列不存在：{path}",
                    affected_count=1,
                    human_review_required=("fundamental_source_coverage",),
                )
            )
            continue
        raw = pd.read_parquet(path)
        series, duplicate_count = _normalize_base_series(
            raw,
            spec=spec,
            change_periods=change_periods,
            proxy_lags=proxy_lags,
            trading_dates=trading_dates,
        )
        if duplicate_count:
            warnings.append(
                FundamentalTrendIncrementalWarningRecord(
                    run_id=run_id,
                    severity=INFO,
                    warning_code="R93K_IDENTICAL_DUPLICATES_COLLAPSED",
                    warning_message=(
                        f"{spec['indicator_name']}存在完全同值的重复观察，"
                        "仅在R93K研究副本中折叠。"
                    ),
                    affected_count=duplicate_count,
                    human_review_required=("upstream_fundamental_duplicate_cleanup",),
                )
            )
        stitched_ids = tuple(
            sorted(value for value in series["indicator_id"].astype(str).unique() if value)
        )
        if len(stitched_ids) > 1:
            warnings.append(
                FundamentalTrendIncrementalWarningRecord(
                    run_id=run_id,
                    severity=INFO,
                    warning_code="R93K_CANONICAL_SERIES_STITCHED",
                    warning_message=(
                        f"{spec['indicator_name']}按规范指标名拼接来源ID："
                        f"{';'.join(stitched_ids)}。事件特征只保留当期实际来源ID。"
                    ),
                    affected_count=len(stitched_ids),
                    human_review_required=("fundamental_series_transition",),
                )
            )
        frames.append(series)
        input_paths.append(path)

    if ifind_cotton_context_path.exists():
        ifind_raw = pd.read_parquet(ifind_cotton_context_path)
        ifind = _normalize_ifind_exact(
            ifind_raw,
            change_periods=change_periods,
            trading_dates=trading_dates,
        )
        frames.append(ifind)
        input_paths.append(ifind_cotton_context_path)
        policy_count = int(ifind_raw["dataset_type"].astype(str).eq("policy").sum())
        if policy_count:
            warnings.append(
                FundamentalTrendIncrementalWarningRecord(
                    run_id=run_id,
                    severity=INFO,
                    warning_code="R93K_POLICY_CONTEXT_NOT_DIRECTIONALIZED",
                    warning_message=(
                        "储备棉事件保留在R93H上下文；因政策冲击方向尚未预登记，"
                        "本轮不转换为趋势支持票。"
                    ),
                    affected_count=policy_count,
                    human_review_required=("policy_event_direction_semantics",),
                )
            )
    else:
        warnings.append(
            FundamentalTrendIncrementalWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="R93K_IFIND_EXACT_SERIES_MISSING",
                warning_message=f"iFinD严格发布日期数据不存在：{ifind_cotton_context_path}",
                affected_count=1,
                human_review_required=("ifind_edb_refresh",),
            )
        )
    if not frames:
        raise ResearchWorkbenchError("R93K没有可用的基本面代表序列")
    calendar = pd.concat(frames, ignore_index=True)
    calendar["run_id"] = run_id
    calendar["rule_version"] = RULE_VERSION
    calendar["fundamental_signal_status"] = "not_connected"
    calendar["state_uses_known_date_or_earlier"] = True
    return (
        calendar.sort_values(
            ["knowledge_date", "knowledge_quality", "indicator_name", "proxy_lag_sessions"]
        ).reset_index(drop=True),
        input_paths,
        warnings,
    )


def _normalize_base_series(
    frame: pd.DataFrame,
    *,
    spec: dict[str, object],
    change_periods: int,
    proxy_lags: tuple[int, ...],
    trading_dates: pd.DatetimeIndex,
) -> tuple[pd.DataFrame, int]:
    indicator_column = str(spec.get("indicator_column", "indicator_name"))
    required = {"trade_date", indicator_column, str(spec["value_column"])}
    missing = required - set(frame.columns)
    if missing:
        raise ResearchWorkbenchError(
            f"R93K {spec['indicator_name']}缺少字段: {sorted(missing)}"
        )
    selected = frame.loc[
        frame[indicator_column].astype(str).eq(str(spec["indicator_name"]))
    ].copy()
    metric_name = spec.get("metric_name")
    if metric_name is not None:
        if "metric_name" not in selected.columns:
            raise ResearchWorkbenchError(f"R93K {spec['indicator_name']}缺少metric_name")
        selected = selected.loc[selected["metric_name"].astype(str).eq(str(metric_name))]
    if selected.empty:
        raise ResearchWorkbenchError(f"R93K找不到代表序列: {spec['indicator_name']}")
    selected["observation_date"] = pd.to_datetime(
        selected["trade_date"], errors="coerce"
    ).dt.normalize()
    selected["indicator_value"] = pd.to_numeric(
        selected[str(spec["value_column"])], errors="coerce"
    )
    if selected[["observation_date", "indicator_value"]].isna().any().any():
        raise ResearchWorkbenchError(f"R93K代表序列存在无效日期或数值: {spec['indicator_name']}")
    duplicate_mask = selected.duplicated(["observation_date"], keep=False)
    duplicate_count = int(selected.duplicated(["observation_date"], keep="first").sum())
    if duplicate_mask.any():
        conflicting = selected.loc[duplicate_mask].groupby("observation_date")[
            "indicator_value"
        ].nunique()
        if conflicting.gt(1).any():
            raise ResearchWorkbenchError(
                f"R93K代表序列同日存在冲突值: {spec['indicator_name']}"
            )
        selected = selected.drop_duplicates(["observation_date"], keep="last")
    selected = selected.sort_values("observation_date")
    selected["change_value"] = selected["indicator_value"].diff(change_periods)
    selected["change_direction"] = selected["change_value"].map(_change_direction)
    selected["fundamental_price_vote"] = selected["change_value"].map(
        lambda value: _price_vote(value, str(spec["expected_effect"]))
    )
    selected["indicator_id"] = _series_or_blank(selected, "indicator_id")
    selected["source_name"] = _series_or_blank(selected, "source_name")
    selected["frequency"] = str(spec["frequency"])
    selected["dataset_type"] = str(spec["dataset_type"])
    selected["indicator_name"] = str(spec["indicator_name"])
    selected["expected_effect"] = str(spec["expected_effect"])
    selected["knowledge_quality"] = "OBSERVATION_DATE_PROXY"
    selected["release_time_status"] = "UNKNOWN_HISTORICAL_RELEASE_TIME"
    selected["source_lane"] = "fundamental_history"
    selected["source_release_time"] = pd.NaT
    outputs: list[pd.DataFrame] = []
    for lag in proxy_lags:
        copy = selected.copy()
        copy["proxy_lag_sessions"] = lag
        copy["knowledge_date"] = copy["observation_date"].map(
            lambda value: _session_on_or_after(value, trading_dates, offset=lag)
        )
        copy = copy.loc[copy["knowledge_date"].notna()]
        outputs.append(copy)
    return pd.concat(outputs, ignore_index=True)[_calendar_columns()], duplicate_count


def _normalize_ifind_exact(
    frame: pd.DataFrame,
    *,
    change_periods: int,
    trading_dates: pd.DatetimeIndex,
) -> pd.DataFrame:
    required = {
        "trade_date",
        "dataset_type",
        "indicator_id",
        "indicator_name",
        "indicator_value",
        "rtime",
        "source_name",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ResearchWorkbenchError(f"R93K iFinD EDB缺少字段: {sorted(missing)}")
    selected = frame.loc[frame["dataset_type"].isin(["spot", "yarn"])].copy()
    selected["observation_date"] = pd.to_datetime(
        selected["trade_date"], errors="coerce"
    ).dt.normalize()
    release_time = pd.to_datetime(selected["rtime"], errors="coerce")
    selected["source_release_time"] = release_time
    selected["knowledge_date"] = release_time.map(
        lambda value: _effective_release_session(value, trading_dates)
    )
    selected["indicator_value"] = pd.to_numeric(selected["indicator_value"], errors="coerce")
    if selected[["observation_date", "knowledge_date", "indicator_value"]].isna().any().any():
        raise ResearchWorkbenchError("R93K iFinD EDB严格发布日期存在空值")
    if (selected["knowledge_date"] < selected["observation_date"]).any():
        raise ResearchWorkbenchError("R93K iFinD EDB knowledge_date早于observation_date")
    selected = selected.sort_values(["indicator_id", "observation_date"])
    selected["change_value"] = selected.groupby("indicator_id")["indicator_value"].diff(
        change_periods
    )
    selected["change_direction"] = selected["change_value"].map(_change_direction)
    selected["fundamental_price_vote"] = selected["change_value"].map(
        lambda value: _price_vote(value, "DEMAND_OR_TIGHTNESS_POSITIVE")
    )
    selected["frequency"] = "D"
    selected["expected_effect"] = "DEMAND_OR_TIGHTNESS_POSITIVE"
    selected["knowledge_quality"] = "RELEASE_DATE_EXACT"
    selected["release_time_status"] = "SOURCE_RTIME_EXACT"
    selected["source_lane"] = "ifind_edb_sidecar"
    selected["proxy_lag_sessions"] = 0
    return selected[_calendar_columns()].reset_index(drop=True)


def _calendar_columns() -> list[str]:
    return [
        "observation_date",
        "knowledge_date",
        "dataset_type",
        "indicator_name",
        "indicator_id",
        "indicator_value",
        "change_value",
        "change_direction",
        "fundamental_price_vote",
        "expected_effect",
        "frequency",
        "knowledge_quality",
        "release_time_status",
        "proxy_lag_sessions",
        "source_lane",
        "source_name",
        "source_release_time",
    ]


def _load_events(path: Path, horizons: tuple[int, ...]) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"R93K趋势事件表不存在: {path}")
    frame = pd.read_parquet(path)
    missing = EVENT_COLUMNS - set(frame.columns)
    if missing:
        raise ResearchWorkbenchError(f"R93K趋势事件表缺少字段: {sorted(missing)}")
    working = frame.loc[
        frame["label_available"].astype(bool) & frame["horizon"].isin(horizons)
    ].copy()
    if working.empty:
        raise ResearchWorkbenchError("R93K没有可用的历史趋势事件标签")
    if not working["historical_posterior_label"].eq(True).all():  # noqa: E712
        raise ResearchWorkbenchError("R93K要求显式历史后验标签")
    working["event_date"] = pd.to_datetime(working["event_date"], errors="coerce").dt.date
    if working["event_date"].isna().any():
        raise ResearchWorkbenchError("R93K趋势事件表存在无效event_date")
    working = working.sort_values(["event_date", "event_id"])
    # 每个趋势episode、每个周期只保留首次突破，避免伪增样本。
    return working.drop_duplicates(
        ["direction_episode_id", "horizon"], keep="first"
    ).reset_index(drop=True)


def _align_events(
    *,
    events: pd.DataFrame,
    calendar: pd.DataFrame,
    run_id: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    # 同一规范指标可能在来源口径切换后更换indicator_id，例如“纺企棉纱库存”
    # 接续为“纱线综合库存”。研究按规范指标拼接为一条序列，事件行仍保留实际来源ID。
    group_columns = [
        "knowledge_quality",
        "proxy_lag_sessions",
        "dataset_type",
        "indicator_name",
    ]
    for keys, series in calendar.groupby(group_columns, dropna=False, sort=True):
        quality, proxy_lag, dataset_type, indicator_name = keys
        available = series.loc[series["change_direction"].ne("UNAVAILABLE")].copy()
        if available.empty:
            continue
        available["knowledge_date"] = pd.to_datetime(available["knowledge_date"]).dt.date
        available = available.sort_values(["knowledge_date", "observation_date"])
        for event in events.itertuples(index=False):
            known = available.loc[available["knowledge_date"].le(event.event_date)]
            if known.empty:
                continue
            feature = known.iloc[-1]
            trend_sign = 1 if event.direction == "long" else -1
            vote = int(feature["fundamental_price_vote"])
            alignment = (
                "SUPPORTS_TREND"
                if vote != 0 and vote == trend_sign
                else "OPPOSES_TREND"
                if vote != 0 and vote == -trend_sign
                else "NEUTRAL"
            )
            rows.append(
                {
                    **event._asdict(),
                    "feature_name": "indicator_alignment",
                    "feature_value": alignment,
                    "indicator_id": str(feature["indicator_id"]),
                    "indicator_name": str(indicator_name),
                    "dataset_type": str(dataset_type),
                    "observation_date": feature["observation_date"],
                    "knowledge_date": feature["knowledge_date"],
                    "knowledge_lag_days": (
                        event.event_date - feature["knowledge_date"]
                    ).days,
                    "indicator_value": float(feature["indicator_value"]),
                    "change_value": float(feature["change_value"]),
                    "change_direction": str(feature["change_direction"]),
                    "fundamental_price_vote": vote,
                    "knowledge_quality": str(quality),
                    "release_time_status": str(feature["release_time_status"]),
                    "proxy_lag_sessions": int(proxy_lag),
                    "event_features_use_known_date_or_earlier": True,
                    "run_id": run_id,
                    "rule_version": RULE_VERSION,
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
    aligned = pd.DataFrame(rows)
    if aligned.empty:
        raise ResearchWorkbenchError("R93K没有任何可对齐的基本面事件特征")
    if (pd.to_datetime(aligned["knowledge_date"]).dt.date > aligned["event_date"]).any():
        raise ResearchWorkbenchError("R93K检测到knowledge_date晚于event_date")
    breadth = _build_breadth_rows(aligned, run_id=run_id)
    output = pd.concat([aligned, breadth], ignore_index=True).sort_values(
        ["event_date", "horizon", "knowledge_quality", "proxy_lag_sessions", "feature_name"]
    ).reset_index(drop=True)
    uniqueness = [
        "event_id",
        "horizon",
        "knowledge_quality",
        "proxy_lag_sessions",
        "feature_name",
        "dataset_type",
        "indicator_name",
    ]
    if output.duplicated(uniqueness).any():
        raise ResearchWorkbenchError("R93K事件特征存在重复的规范指标计票")
    return output


def _build_breadth_rows(frame: pd.DataFrame, *, run_id: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    group_columns = [
        "event_id",
        "direction_episode_id",
        "horizon",
        "knowledge_quality",
        "proxy_lag_sessions",
    ]
    indicators = frame.loc[frame["feature_name"].eq("indicator_alignment")]
    for _, group in indicators.groupby(group_columns, sort=True):
        first = group.iloc[0]
        support_count = int(group["feature_value"].eq("SUPPORTS_TREND").sum())
        oppose_count = int(group["feature_value"].eq("OPPOSES_TREND").sum())
        available_count = support_count + oppose_count
        if available_count == 0:
            breadth_value = "BREADTH_UNAVAILABLE"
        else:
            ratio = support_count / available_count
            breadth_value = (
                "BROAD_SUPPORT"
                if ratio >= 2 / 3
                else "BROAD_OPPOSITION"
                if ratio <= 1 / 3
                else "MIXED_BREADTH"
            )
        rows.append(
            {
                **{column: first[column] for column in EVENT_COLUMNS if column in first.index},
                "feature_name": "fundamental_breadth",
                "feature_value": breadth_value,
                "indicator_id": "BREADTH",
                "indicator_name": "基本面方向广度",
                "dataset_type": "composite_context",
                "observation_date": group["observation_date"].max(),
                "knowledge_date": group["knowledge_date"].max(),
                "knowledge_lag_days": int(group["knowledge_lag_days"].min()),
                "indicator_value": float(available_count),
                "change_value": float(support_count - oppose_count),
                "change_direction": breadth_value,
                "fundamental_price_vote": support_count - oppose_count,
                "knowledge_quality": first["knowledge_quality"],
                "release_time_status": "AGGREGATED_FROM_COMPONENTS",
                "proxy_lag_sessions": int(first["proxy_lag_sessions"]),
                "event_features_use_known_date_or_earlier": True,
                "run_id": run_id,
                "rule_version": RULE_VERSION,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    return pd.DataFrame(rows)


def _build_summary(
    frame: pd.DataFrame,
    *,
    min_sample_size: int,
    fdr_level: float,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    grouping = [
        "knowledge_quality",
        "proxy_lag_sessions",
        "feature_name",
        "indicator_name",
        "feature_value",
        "horizon",
    ]
    for keys, group in frame.groupby(grouping, dropna=False, sort=True):
        quality, proxy_lag, feature_name, indicator_name, feature_value, horizon = keys
        universe = frame.loc[
            frame["knowledge_quality"].eq(quality)
            & frame["proxy_lag_sessions"].eq(proxy_lag)
            & frame["feature_name"].eq(feature_name)
            & frame["indicator_name"].eq(indicator_name)
            & frame["horizon"].eq(horizon)
        ]
        comparison = universe.loc[universe["feature_value"].ne(feature_value)]
        metrics = _group_metrics(group)
        control = _group_metrics(comparison)
        exact_p = _fisher_exact_two_sided(
            group_successes=int(metrics["success_count"]),
            group_count=int(metrics["sample_count"]),
            comparison_successes=int(control["success_count"]),
            comparison_count=int(control["sample_count"]),
        )
        rows.append(
            {
                "knowledge_quality": quality,
                "proxy_lag_sessions": int(proxy_lag),
                "feature_name": feature_name,
                "indicator_name": indicator_name,
                "feature_value": feature_value,
                "horizon": int(horizon),
                **metrics,
                "comparison_sample_count": control["sample_count"],
                "comparison_success_count": control["success_count"],
                "comparison_hit_rate": control["hit_rate"],
                "comparison_mean_directional_return": control["mean_directional_return"],
                "delta_hit_rate": metrics["hit_rate"] - control["hit_rate"],
                "delta_mean_directional_return": (
                    metrics["mean_directional_return"]
                    - control["mean_directional_return"]
                ),
                "fisher_exact_p_value": exact_p,
                "fdr_q_value": math.nan,
                "incremental_status": "PENDING_FDR",
                "promotion_eligible": quality == "RELEASE_DATE_EXACT",
                "rule_version": RULE_VERSION,
            }
        )
    summary = pd.DataFrame(rows)
    tested_mask = summary["comparison_sample_count"].gt(0)
    family_columns = ["knowledge_quality", "proxy_lag_sessions", "horizon"]
    for _, family in summary.loc[tested_mask].groupby(family_columns, sort=True):
        summary.loc[family.index, "fdr_q_value"] = _benjamini_hochberg(
            family["fisher_exact_p_value"].astype(float).tolist()
        )
    for index, row in summary.iterrows():
        summary.at[index, "incremental_status"] = _incremental_status(
            row,
            min_sample_size=min_sample_size,
            fdr_level=fdr_level,
        )
    return summary.sort_values(grouping).reset_index(drop=True)


def _incremental_status(
    row: pd.Series,
    *,
    min_sample_size: int,
    fdr_level: float,
) -> str:
    quality = str(row["knowledge_quality"])
    if int(row["comparison_sample_count"]) <= 0:
        return (
            "PROXY_NO_COMPARISON"
            if quality != "RELEASE_DATE_EXACT"
            else "NO_COMPARISON"
        )
    enough = (
        int(row["sample_count"]) >= min_sample_size
        and int(row["comparison_sample_count"]) >= max(10, min_sample_size // 2)
    )
    positive = float(row["delta_hit_rate"]) > 0 and float(
        row["delta_mean_directional_return"]
    ) > 0
    negative = float(row["delta_hit_rate"]) < 0 and float(
        row["delta_mean_directional_return"]
    ) < 0
    significant = math.isfinite(float(row["fdr_q_value"])) and float(
        row["fdr_q_value"]
    ) <= fdr_level
    if quality != "RELEASE_DATE_EXACT":
        if enough and positive:
            return "PROXY_WATCH_POSITIVE"
        if enough and negative:
            return "PROXY_WATCH_NEGATIVE"
        return "PROXY_INCONCLUSIVE"
    if enough and significant and positive:
        return "POSITIVE_CANDIDATE"
    if enough and significant and negative:
        return "NEGATIVE_FILTER"
    if enough and positive:
        return "WATCH_POSITIVE"
    if enough and negative:
        return "WATCH_NEGATIVE"
    return "INCONCLUSIVE_OR_SMALL_SAMPLE"


def _build_sensitivity(frame: pd.DataFrame, *, min_sample_size: int) -> pd.DataFrame:
    proxy = frame.loc[
        frame["knowledge_quality"].eq("OBSERVATION_DATE_PROXY")
        & frame["feature_name"].eq("fundamental_breadth")
    ]
    rows: list[dict[str, object]] = []
    for (lag, horizon, value), group in proxy.groupby(
        ["proxy_lag_sessions", "horizon", "feature_value"], sort=True
    ):
        metrics = _group_metrics(group)
        rows.append(
            {
                "proxy_lag_sessions": int(lag),
                "horizon": int(horizon),
                "feature_value": value,
                **metrics,
                "sample_status": (
                    "SUFFICIENT" if int(metrics["sample_count"]) >= min_sample_size else "SMALL"
                ),
                "promotion_eligible": False,
                "rule_version": RULE_VERSION,
            }
        )
    return pd.DataFrame(rows)


def _group_metrics(group: pd.DataFrame) -> dict[str, float | int]:
    count = len(group)
    successes = int(group["outcome"].eq("FOLLOW_THROUGH").sum())
    hit_rate = successes / count if count else math.nan
    lower, upper = _wilson_interval(successes, count)
    return {
        "sample_count": count,
        "success_count": successes,
        "hit_rate": hit_rate,
        "hit_rate_ci_lower": lower,
        "hit_rate_ci_upper": upper,
        "mean_directional_return": (
            float(group["directional_return"].mean()) if count else math.nan
        ),
        "median_directional_return": (
            float(group["directional_return"].median()) if count else math.nan
        ),
    }


def _warning_records(
    *,
    run_id: str,
    event_features: pd.DataFrame,
    summary: pd.DataFrame,
    min_sample_size: int,
) -> list[FundamentalTrendIncrementalWarningRecord]:
    proxy_count = int(
        event_features["knowledge_quality"].eq("OBSERVATION_DATE_PROXY").sum()
    )
    exact_count = int(event_features["knowledge_quality"].eq("RELEASE_DATE_EXACT").sum())
    warnings = [
        FundamentalTrendIncrementalWarningRecord(
            run_id=run_id,
            severity=WARN,
            warning_code="R93K_PROXY_RELEASE_DATES_PRESENT",
            warning_message=(
                "长期基本面表缺少历史发布日期；OBSERVATION_DATE_PROXY仅作滞后敏感性，"
                "不得晋级策略。"
            ),
            affected_count=proxy_count,
            human_review_required=("historical_release_date_backfill",),
        ),
        FundamentalTrendIncrementalWarningRecord(
            run_id=run_id,
            severity=INFO,
            warning_code="R93K_EXACT_RELEASE_ROWS_PRESENT",
            warning_message="RELEASE_DATE_EXACT行使用来源rtime，并验证knowledge_date不晚于事件日。",
            affected_count=exact_count,
        ),
    ]
    small = int(summary["sample_count"].lt(min_sample_size).sum())
    if small:
        warnings.append(
            FundamentalTrendIncrementalWarningRecord(
                run_id=run_id,
                severity=WARN,
                warning_code="R93K_SMALL_SAMPLES_PRESENT",
                warning_message="部分基本面分组未达到最小独立episode样本门槛。",
                affected_count=small,
                human_review_required=("fundamental_incremental_sample_size",),
            )
        )
    warnings.append(
        FundamentalTrendIncrementalWarningRecord(
            run_id=run_id,
            severity=INFO,
            warning_code="R93K_POSTERIOR_LABEL_BOUNDARY",
            warning_message=(
                "趋势收益仅作为历史后验标签；基本面结果不进入composite_score或交易方向。"
            ),
            affected_count=len(event_features),
        )
    )
    return warnings


def _change_direction(value: object) -> str:
    if pd.isna(value):
        return "UNAVAILABLE"
    number = float(value)
    return "UP" if number > 0 else "DOWN" if number < 0 else "FLAT"


def _price_vote(value: object, expected_effect: str) -> int:
    if pd.isna(value) or float(value) == 0:
        return 0
    sign = 1 if float(value) > 0 else -1
    if expected_effect == "SUPPLY_PRESSURE_POSITIVE":
        sign *= -1
    return sign


def _series_or_blank(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype="object")
    return frame[column].fillna("").astype(str)


def _load_trading_dates(path: Path) -> pd.DatetimeIndex:
    if not path.exists():
        raise ResearchWorkbenchError(f"R93K CF core quote不存在: {path}")
    frame = pd.read_parquet(path, columns=["trade_date"])
    dates = pd.to_datetime(frame["trade_date"], errors="coerce").dropna().drop_duplicates()
    if dates.empty:
        raise ResearchWorkbenchError(f"R93K CF core quote没有有效交易日: {path}")
    return pd.DatetimeIndex(dates.sort_values().dt.normalize())


def _session_on_or_after(
    value: object,
    trading_dates: pd.DatetimeIndex,
    *,
    offset: int,
) -> pd.Timestamp:
    timestamp = pd.Timestamp(value).normalize()
    index = int(trading_dates.searchsorted(timestamp, side="left")) + offset
    return pd.NaT if index >= len(trading_dates) else trading_dates[index]


def _effective_release_session(
    value: object,
    trading_dates: pd.DatetimeIndex,
) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    release_date = timestamp.normalize()
    index = int(trading_dates.searchsorted(release_date, side="left"))
    if index >= len(trading_dates):
        return pd.NaT
    # 15:00之后发布的值不能用于当日结算后的研究状态，保守顺延至下一交易日。
    if trading_dates[index] == release_date and timestamp.hour >= 15:
        index += 1
    return pd.NaT if index >= len(trading_dates) else trading_dates[index]


def _positive_values(values: tuple[int, ...], label: str) -> tuple[int, ...]:
    normalized = tuple(sorted(set(int(value) for value in values)))
    if not normalized or any(value <= 0 for value in normalized):
        raise ResearchWorkbenchError(f"{label}必须包含正整数")
    return normalized


def _non_negative_values(values: tuple[int, ...], label: str) -> tuple[int, ...]:
    normalized = tuple(sorted(set(int(value) for value in values)))
    if not normalized or any(value < 0 for value in normalized):
        raise ResearchWorkbenchError(f"{label}必须包含非负整数")
    return normalized


def _validate_parameters(
    *,
    change_periods: int,
    min_sample_size: int,
    fdr_level: float,
) -> None:
    if change_periods < 1:
        raise ResearchWorkbenchError("change_periods必须为正整数")
    if min_sample_size < 1:
        raise ResearchWorkbenchError("min_sample_size必须为正整数")
    if not 0 < fdr_level <= 1:
        raise ResearchWorkbenchError("fdr_level必须位于(0,1]")


def _wilson_interval(successes: int, count: int) -> tuple[float, float]:
    if count <= 0:
        return math.nan, math.nan
    z = 1.959963984540054
    rate = successes / count
    denominator = 1 + z**2 / count
    centre = (rate + z**2 / (2 * count)) / denominator
    margin = (
        z
        * math.sqrt(rate * (1 - rate) / count + z**2 / (4 * count**2))
        / denominator
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _fisher_exact_two_sided(
    *,
    group_successes: int,
    group_count: int,
    comparison_successes: int,
    comparison_count: int,
) -> float:
    if group_count <= 0 or comparison_count <= 0:
        return 1.0
    total = group_count + comparison_count
    total_successes = group_successes + comparison_successes
    observed = _hypergeometric_probability(
        group_successes, group_count, total_successes, total
    )
    minimum = max(0, group_count - (total - total_successes))
    maximum = min(group_count, total_successes)
    probability = 0.0
    for successes in range(minimum, maximum + 1):
        candidate = _hypergeometric_probability(
            successes, group_count, total_successes, total
        )
        if candidate <= observed + 1e-12:
            probability += candidate
    return min(1.0, probability)


def _hypergeometric_probability(
    group_successes: int,
    group_count: int,
    total_successes: int,
    total_count: int,
) -> float:
    return (
        math.comb(total_successes, group_successes)
        * math.comb(total_count - total_successes, group_count - group_successes)
        / math.comb(total_count, group_count)
    )


def _benjamini_hochberg(p_values: list[float]) -> list[float]:
    if not p_values:
        return []
    order = sorted(range(len(p_values)), key=p_values.__getitem__)
    adjusted = [1.0] * len(p_values)
    running = 1.0
    count = len(p_values)
    for reverse_rank, index in enumerate(reversed(order), start=1):
        rank = count - reverse_rank + 1
        running = min(running, min(1.0, p_values[index] * count / rank))
        adjusted[index] = running
    return adjusted


def _latest_breakout_event_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "symmetric_trend"
    candidates = list(root.glob("*_symmetric_trend_breakout_event_horizon.parquet"))
    if not candidates:
        raise ResearchWorkbenchError(f"R93K找不到趋势事件表: {root}")
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name))


def _latest_ifind_cotton_context_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "ifind_edb"
    candidates = list(root.glob("*_ifind_cotton_context_daily.parquet"))
    if not candidates:
        return root / "MISSING_ifind_cotton_context_daily.parquet"
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name))


def _output_paths(
    *,
    start: date,
    end: date,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / "fundamental_trend_incremental"
    report_root = report_output_dir or reports_dir() / "research" / "fundamental_trend_incremental"
    stem = f"CF_{start}_{end}_fundamental_trend_incremental"
    return {
        "calendar": root / f"{stem}_knowledge_calendar.parquet",
        "events": root / f"{stem}_event_feature.parquet",
        "summary": root / f"{stem}_summary.parquet",
        "sensitivity": root / f"{stem}_proxy_lag_sensitivity.parquet",
        "warnings": root / f"{stem}_warnings.csv",
        "manifest": root / f"{stem}_manifest.json",
        "json": report_root / f"{stem}.json",
        "markdown": report_root / f"{stem}.md",
    }


def _write_outputs(
    *,
    result: FundamentalTrendIncrementalResult,
    calendar: pd.DataFrame,
    event_features: pd.DataFrame,
    summary: pd.DataFrame,
    sensitivity: pd.DataFrame,
    input_paths: list[Path],
    parameters: dict[str, object],
) -> None:
    for path, frame in (
        (result.knowledge_calendar_path, calendar),
        (result.event_feature_path, event_features),
        (result.summary_path, summary),
        (result.sensitivity_path, sensitivity),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
    _write_warnings(result)
    payload = {
        "report_type": "fundamental_trend_incremental",
        "rule_version": RULE_VERSION,
        "summary": result.to_summary(),
        "parameters": parameters,
        "historical_returns_are_posterior_labels": True,
        "fundamental_signal_status": "not_connected",
        "research_boundary": RESEARCH_BOUNDARY,
    }
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    _write_markdown(result=result, summary=summary, sensitivity=sensitivity)
    artifacts = (
        result.knowledge_calendar_path,
        result.event_feature_path,
        result.summary_path,
        result.sensitivity_path,
        result.warning_csv_path,
        result.json_path,
        result.markdown_path,
    )
    manifest = {
        "report_type": "fundamental_trend_incremental",
        "rule_version": RULE_VERSION,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "summary": result.to_summary(),
        "parameters": parameters,
        "input_sha256": {str(path): _sha256(path) for path in input_paths},
        "artifact_sha256": {str(path): _sha256(path) for path in artifacts},
        "historical_returns_are_posterior_labels": True,
        "fundamental_signal_status": "not_connected",
        "research_boundary": RESEARCH_BOUNDARY,
    }
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_warnings(result: FundamentalTrendIncrementalResult) -> None:
    result.warning_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with result.warning_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        for item in result.warning_records:
            writer.writerow(
                {
                    "run_id": item.run_id,
                    "severity": item.severity,
                    "warning_code": item.warning_code,
                    "warning_message": item.warning_message,
                    "affected_count": item.affected_count,
                    "human_review_required": ";".join(item.human_review_required),
                }
            )


def _write_markdown(
    *,
    result: FundamentalTrendIncrementalResult,
    summary: pd.DataFrame,
    sensitivity: pd.DataFrame,
) -> None:
    exact = summary.loc[summary["knowledge_quality"].eq("RELEASE_DATE_EXACT")]
    proxy = summary.loc[summary["knowledge_quality"].eq("OBSERVATION_DATE_PROXY")]
    lines = [
        "# CF R93K 基本面发布时间与趋势增量研究",
        "",
        "## 数据状态",
        "",
        f"- 趋势事件区间：`{result.start}` 至 `{result.end}`",
        f"- 首次突破事件-周期行：`{result.event_row_count}`",
        f"- 独立趋势episode：`{result.independent_episode_count}`",
        f"- 事件特征行：`{result.feature_row_count}`",
        f"- 严格发布日期日历行：`{result.exact_feature_count}`",
        f"- 观察日代理日历行：`{result.proxy_feature_count}`",
        f"- 严格发布日期事件特征行：`{result.exact_event_feature_count}`",
        f"- 观察日代理事件特征行：`{result.proxy_event_feature_count}`",
        "",
        "## 研究定义",
        "",
        "- 每个趋势episode、每个周期只保留首次突破。",
        "- 事件特征只允许使用 `knowledge_date <= event_date` 的记录。",
        "- `RELEASE_DATE_EXACT` 使用来源 `rtime`；`OBSERVATION_DATE_PROXY` 缺少历史发布日期。",
        "- 已确认的规范指标改名按类别与规范名拼接，事件行保留当期原始指标ID用于追溯。",
        "- 支持/反对趋势只表示基本面变化方向与趋势方向是否同向，不代表因果。",
        "- Fisher精确检验比较同指标同周期的当前分组与其余独立episode，并进行FDR校正。",
        "",
        "## 严格发布日期证据",
        "",
        _top_rows_markdown(exact),
        "",
        "## 观察日代理证据",
        "",
        "代理证据无论统计结果如何，均不具备自动晋级资格。",
        "",
        _top_rows_markdown(proxy),
        "",
        "## 代理发布日期滞后敏感性",
        "",
        "| 滞后交易日 | 周期 | 广度状态 | 样本 | 命中率 | 平均方向收益 |",
        "| ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    for row in sensitivity.itertuples(index=False):
        lines.append(
            f"| {row.proxy_lag_sessions} | {row.horizon}D | {row.feature_value} | "
            f"{row.sample_count} | {_pct(row.hit_rate)} | {_pct(row.mean_directional_return)} |"
        )
    lines.extend(
        [
            "",
            "## 结论边界",
            "",
            f"> {RESEARCH_BOUNDARY}",
            "",
            "- 现有严格发布日期数据主要来自2025年7月后的iFinD EDB，覆盖时间短，不能替代长期样本。",
            "- 长期库存、进口、仓单和纺织链只有观察期，没有历史发布日期；"
            "必须补齐发布日后才可做严格增量验证。",
            "- forward directional return只作为历史后验标签，不回流基本面特征。",
            "- 不生成fundamental_signal，不进入signal matrix或composite_score，不构成交易指令。",
            "",
            "## 人工复核项",
            "",
            "- `historical_release_date_backfill`",
            "- `fundamental_effect_direction_assumption`",
            "- `fundamental_incremental_sample_size`",
            "- `multiple_testing_interpretation`",
        ]
    )
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _top_rows_markdown(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "- 无可用证据。"
    ranked = frame.sort_values(
        ["promotion_eligible", "fdr_q_value", "sample_count"],
        ascending=[False, True, False],
        na_position="last",
    ).head(20)
    lines = [
        "| 指标 | 状态 | 代理滞后(交易日) | 周期 | 样本/对照 | 命中差 | 收益差 | q值 | 结论 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in ranked.itertuples(index=False):
        # 严格发布日期不使用代理滞后；显式写出差异，避免把0/5/10日敏感性误读为重复结果。
        proxy_lag = (
            str(int(row.proxy_lag_sessions))
            if row.knowledge_quality == "OBSERVATION_DATE_PROXY"
            else "不适用"
        )
        lines.append(
            f"| {row.indicator_name} | {row.feature_value} | {proxy_lag} | "
            f"{row.horizon}D | "
            f"{row.sample_count}/{row.comparison_sample_count} | {_pct(row.delta_hit_rate)} | "
            f"{_pct(row.delta_mean_directional_return)} | {_number(row.fdr_q_value)} | "
            f"{row.incremental_status} |"
        )
    return "\n".join(lines)


def _pct(value: object) -> str:
    number = float(value)
    return "-" if not math.isfinite(number) else f"{number:.2%}"


def _number(value: object) -> str:
    number = float(value)
    return "-" if not math.isfinite(number) else f"{number:.4f}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_run_id() -> str:
    return f"cf_r93k_fundamental_trend_{uuid.uuid4().hex[:8]}"
