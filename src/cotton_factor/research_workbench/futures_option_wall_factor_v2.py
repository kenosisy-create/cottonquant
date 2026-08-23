"""R93O CF期权墙因子v2与统一增量证据研究。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.research_workbench.state_upgrade_common import (
    artifact_manifest,
    fmt_number,
    fmt_percent,
    latest_matching_path,
    load_table,
    normalize_trade_date,
    utc_timestamp_id,
    write_frame,
    write_json,
    write_warning_csv,
)

PRODUCT_CODE = "CF"
RULE_VERSION = "V5.1_R93O_option_wall_factor_v2_v1"
DEFAULT_HORIZONS = (1, 3, 5)
DEFAULT_MIN_SAMPLE_SIZE = 30
DEFAULT_FDR_LEVEL = 0.10
DEFAULT_DEAD_ZONE_BPS = 10

# 以下阈值在真实结果运行前固定，不从后验收益中搜索。
WALL_DISTANCE_THRESHOLD_BPS = 50.0
WALL_SHIFT_THRESHOLD_BPS = 50.0
OI_Z_THRESHOLD = 0.5
OI_Z_WINDOW = 60
OI_Z_MIN_PERIODS = 20
RV_WINDOW = 20
RANK_WINDOW = 252
RANK_MIN_PERIODS = 20
CHANGE_LAGS = (1, 3, 5)
EXPIRY_BUCKETS = ("DTE_0_5", "DTE_6_15", "DTE_16_30", "DTE_GT_30")
INFO = "INFO"
WARN = "WARN"

HUMAN_REVIEW_REQUIRED = (
    "option_open_interest_long_short_ownership_unknown",
    "option_wall_is_not_automatic_support_or_resistance",
    "wall_factor_direction_proxy_interpretation",
    "option_iv_and_realized_volatility_proxy_interpretation",
    "pcr_change_direction_proxy_interpretation",
    "option_market_stage_boundaries",
    "fdr_and_leave_one_year_out_interpretation",
)

RESEARCH_BOUNDARY = {
    "features_use_t_or_earlier": True,
    "forward_returns_are_historical_posterior_labels": True,
    "t_plus_one_execution": True,
    "r93n_is_frozen_input_baseline": True,
    "option_open_interest_ownership_is_unknown": True,
    "high_oi_strike_is_not_automatic_support_or_resistance": True,
    "dealer_gamma_is_not_inferred": True,
    "option_iv_and_greek_are_research_proxies": True,
    "post_hoc_threshold_search": False,
    "automatic_direction_reversal": False,
    "enters_signal_matrix": False,
    "enters_composite_score": False,
    "changes_strategy_direction_or_sizing": False,
    "promotion_eligible": False,
    "trading_instruction": "not_a_trading_instruction",
}

FEATURE_REQUIRED_COLUMNS = {
    "observation_id",
    "trade_date",
    "main_contract",
    "underlying_settle",
    "dynamic_call_wall_strike",
    "dynamic_put_wall_strike",
    "dynamic_call_wall_distance",
    "dynamic_put_wall_distance",
    "dynamic_call_wall_open_interest_change",
    "dynamic_put_wall_open_interest_change",
    "local_call_open_interest",
    "local_put_open_interest",
    "pcr_oi",
    "atm_iv_rank",
    "futures_direction_5d",
    "option_market_stage",
    "expiry_bucket",
    "feature_uses_t_or_earlier",
    "contains_posterior_outcome",
}

LABEL_REQUIRED_COLUMNS = {
    "observation_id",
    "trade_date",
    "main_contract",
    "calendar_year",
    "option_market_stage",
    "expiry_bucket",
    "horizon",
    "execution_date",
    "exit_date",
    "forward_return",
    "long_mfe",
    "long_mae",
    "short_mfe",
    "short_mae",
    "futures_direction",
    "futures_directional_return",
    "futures_hit",
    "r48_option_direction",
    "r48_directional_return",
    "r48_hit",
    "dynamic_option_direction",
    "dynamic_directional_return",
    "dynamic_hit",
    "forward_label_available",
    "t_plus_one_execution",
    "label_uses_post_t_prices",
    "forward_returns_are_historical_posterior_labels",
}

FORBIDDEN_FEATURE_COLUMNS = {
    "forward_return",
    "execution_date",
    "exit_date",
    "future_return",
    "fwd_ret",
    "mfe",
    "mae",
    "candidate_hit",
}


@dataclass(frozen=True)
class CandidateSpec:
    """预注册候选定义；comparison_mode决定增量检验的参照样本。"""

    candidate_id: str
    family: str
    value_column: str
    comparison_mode: str
    threshold: float
    interpretation: str
    expiry_bucket: str | None = None


@dataclass(frozen=True)
class FuturesOptionWallFactorV2WarningRecord:
    """R93O告警与人工复核记录。"""

    run_id: str
    section: str
    severity: str
    warning_code: str
    warning_message: str
    affected_count: int
    human_review_required: str = ""

    def to_summary(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "section": self.section,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "affected_count": self.affected_count,
            "human_review_required": self.human_review_required,
        }


@dataclass(frozen=True)
class ResearchFuturesOptionWallFactorV2Result:
    """R93O研究包路径与核心裁决摘要。"""

    run_id: str
    start: date
    end: date
    status: str
    feature_row_count: int
    candidate_signal_row_count: int
    posterior_label_row_count: int
    model_comparison_row_count: int
    candidate_evidence_row_count: int
    oos_row_count: int
    candidate_count: int
    keep_count: int
    watch_count: int
    reject_count: int
    latest_main_contract: str
    latest_active_candidates: tuple[str, ...]
    feature_parquet_path: Path
    feature_csv_path: Path
    candidate_signal_parquet_path: Path
    candidate_signal_csv_path: Path
    posterior_label_parquet_path: Path
    posterior_label_csv_path: Path
    model_comparison_parquet_path: Path
    model_comparison_csv_path: Path
    candidate_evidence_parquet_path: Path
    candidate_evidence_csv_path: Path
    oos_parquet_path: Path
    oos_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    dynamic_wall_feature_path: Path
    dynamic_wall_label_path: Path
    option_factor_path: Path | None
    warning_records: tuple[FuturesOptionWallFactorV2WarningRecord, ...]

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
            "feature_row_count": self.feature_row_count,
            "candidate_signal_row_count": self.candidate_signal_row_count,
            "posterior_label_row_count": self.posterior_label_row_count,
            "model_comparison_row_count": self.model_comparison_row_count,
            "candidate_evidence_row_count": self.candidate_evidence_row_count,
            "oos_row_count": self.oos_row_count,
            "candidate_count": self.candidate_count,
            "keep_count": self.keep_count,
            "watch_count": self.watch_count,
            "reject_count": self.reject_count,
            "latest_main_contract": self.latest_main_contract,
            "latest_active_candidates": list(self.latest_active_candidates),
            "warning_count": self.warning_count,
            "warnings": [item.to_summary() for item in self.warning_records],
            "feature_parquet_path": str(self.feature_parquet_path),
            "candidate_signal_parquet_path": str(self.candidate_signal_parquet_path),
            "posterior_label_parquet_path": str(self.posterior_label_parquet_path),
            "model_comparison_parquet_path": str(self.model_comparison_parquet_path),
            "candidate_evidence_parquet_path": str(
                self.candidate_evidence_parquet_path
            ),
            "oos_parquet_path": str(self.oos_parquet_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "dynamic_wall_feature_path": str(self.dynamic_wall_feature_path),
            "dynamic_wall_label_path": str(self.dynamic_wall_label_path),
            "option_factor_path": (
                None if self.option_factor_path is None else str(self.option_factor_path)
            ),
            "features_use_t_or_earlier": True,
            "historical_returns_are_posterior_labels": True,
            "enters_composite_score": False,
            "promotion_eligible": False,
            "trading_instruction": "not_a_trading_instruction",
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        }


def build_cf_futures_option_wall_factor_v2_research(
    *,
    dynamic_wall_feature_path: Path | None = None,
    dynamic_wall_label_path: Path | None = None,
    option_factor_path: Path | None = None,
    start: date | None = None,
    end: date | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    fdr_level: float = DEFAULT_FDR_LEVEL,
    dead_zone_bps: int = DEFAULT_DEAD_ZONE_BPS,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchFuturesOptionWallFactorV2Result:
    """构建R93O预注册特征、统一基线、FDR和留一年证据。"""
    normalized_horizons = _validate_parameters(
        horizons=horizons,
        min_sample_size=min_sample_size,
        fdr_level=fdr_level,
        dead_zone_bps=dead_zone_bps,
    )
    feature_path = dynamic_wall_feature_path or latest_matching_path(
        data_dir() / "research" / PRODUCT_CODE / "futures_option_dynamic_wall",
        "CF_*_futures_option_dynamic_wall_feature_daily.parquet",
        label="R93N dynamic-wall feature",
    )
    label_path = dynamic_wall_label_path or _matching_r93n_label_path(feature_path)
    factor_path = option_factor_path or _optional_latest_path(
        data_dir() / "research" / PRODUCT_CODE / "option_factors",
        "CF_*_option_factor_proxy_daily.parquet",
    )

    source_features = _load_r93n_features(feature_path)
    source_labels = _load_r93n_labels(label_path)
    effective_start = max(
        start or min(source_features["trade_date"]),
        min(source_features["trade_date"]),
    )
    effective_end = min(
        end or max(source_features["trade_date"]),
        max(source_features["trade_date"]),
    )
    source_features = source_features.loc[
        source_features["trade_date"].between(effective_start, effective_end)
    ].copy()
    source_labels = source_labels.loc[
        source_labels["trade_date"].between(effective_start, effective_end)
        & source_labels["horizon"].isin(normalized_horizons)
    ].copy()
    if source_features.empty or source_labels.empty:
        raise ResearchWorkbenchError("R93O日期过滤后没有可用的R93N特征或标签")
    _validate_source_alignment(source_features, source_labels)

    active_run_id = run_id or utc_timestamp_id("r93o_wall_factor_v2", effective_end)
    option_factors = _load_option_factors(factor_path)
    features = _build_v2_features(
        source_features=source_features,
        option_factors=option_factors,
        run_id=active_run_id,
    )
    candidate_specs = _candidate_specs()
    candidate_signals = _build_candidate_signals(
        features=features,
        candidate_specs=candidate_specs,
        run_id=active_run_id,
    )
    posterior_labels = _build_candidate_posterior_labels(
        source_labels=source_labels,
        candidate_signals=candidate_signals,
        dead_zone_bps=dead_zone_bps,
        run_id=active_run_id,
    )
    model_comparison = _build_model_comparison(
        source_labels=source_labels,
        min_sample_size=min_sample_size,
        run_id=active_run_id,
    )
    candidate_evidence = _build_candidate_evidence(
        posterior_labels=posterior_labels,
        min_sample_size=min_sample_size,
        fdr_level=fdr_level,
        run_id=active_run_id,
    )
    oos = _build_leave_one_year_out(
        posterior_labels=posterior_labels,
        min_sample_size=min_sample_size,
        run_id=active_run_id,
    )
    candidate_evidence = _apply_final_decisions(
        candidate_evidence=candidate_evidence,
        oos=oos,
        min_sample_size=min_sample_size,
        fdr_level=fdr_level,
    )
    warnings = _warning_records(
        run_id=active_run_id,
        features=features,
        posterior_labels=posterior_labels,
        candidate_evidence=candidate_evidence,
        oos=oos,
        option_factor_path=factor_path,
        option_factors=option_factors,
    )
    paths = _paths(
        start=min(features["trade_date"]),
        end=max(features["trade_date"]),
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    _write_outputs(
        paths=paths,
        features=features,
        candidate_signals=candidate_signals,
        posterior_labels=posterior_labels,
        model_comparison=model_comparison,
        candidate_evidence=candidate_evidence,
        oos=oos,
        warnings=warnings,
    )

    latest = features.sort_values("trade_date").iloc[-1]
    latest_signals = candidate_signals.loc[
        candidate_signals["trade_date"].eq(latest["trade_date"])
        & candidate_signals["signal_direction"].isin(["long", "short"])
    ]
    mature_decisions = candidate_evidence.loc[
        candidate_evidence["option_market_stage"].eq("MATURE_ACTIVE")
    ]
    keep_count = int(mature_decisions["decision"].eq("KEEP").sum())
    watch_count = int(mature_decisions["decision"].eq("WATCH").sum())
    reject_count = int(mature_decisions["decision"].eq("REJECT").sum())
    result = ResearchFuturesOptionWallFactorV2Result(
        run_id=active_run_id,
        start=min(features["trade_date"]),
        end=max(features["trade_date"]),
        status="READY_WITH_WARNINGS" if any(w.severity == WARN for w in warnings) else "READY",
        feature_row_count=len(features),
        candidate_signal_row_count=len(candidate_signals),
        posterior_label_row_count=len(posterior_labels),
        model_comparison_row_count=len(model_comparison),
        candidate_evidence_row_count=len(candidate_evidence),
        oos_row_count=len(oos),
        candidate_count=len(candidate_specs),
        keep_count=keep_count,
        watch_count=watch_count,
        reject_count=reject_count,
        latest_main_contract=str(latest["main_contract"]),
        latest_active_candidates=tuple(latest_signals["candidate_id"].astype(str)),
        feature_parquet_path=paths["feature_parquet"],
        feature_csv_path=paths["feature_csv"],
        candidate_signal_parquet_path=paths["signal_parquet"],
        candidate_signal_csv_path=paths["signal_csv"],
        posterior_label_parquet_path=paths["label_parquet"],
        posterior_label_csv_path=paths["label_csv"],
        model_comparison_parquet_path=paths["model_parquet"],
        model_comparison_csv_path=paths["model_csv"],
        candidate_evidence_parquet_path=paths["evidence_parquet"],
        candidate_evidence_csv_path=paths["evidence_csv"],
        oos_parquet_path=paths["oos_parquet"],
        oos_csv_path=paths["oos_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
        dynamic_wall_feature_path=feature_path,
        dynamic_wall_label_path=label_path,
        option_factor_path=factor_path,
        warning_records=tuple(warnings),
    )
    _write_markdown(
        result=result,
        latest=latest.to_dict(),
        latest_signals=latest_signals,
        model_comparison=model_comparison,
        candidate_evidence=candidate_evidence,
        oos=oos,
        candidate_specs=candidate_specs,
    )
    write_json(
        result.json_path,
        {
            "report_type": "cf_futures_option_wall_factor_v2_research",
            "rule_version": RULE_VERSION,
            "summary": result.to_summary(),
            "latest_state": latest.to_dict(),
            "latest_candidate_signals": latest_signals.to_dict("records"),
            "pre_registered_parameters": _pre_registered_parameters(),
            "candidate_registry": [spec.__dict__ for spec in candidate_specs],
            "research_boundary": RESEARCH_BOUNDARY,
        },
    )
    manifest = artifact_manifest(
        run_id=active_run_id,
        report_type="cf_futures_option_wall_factor_v2_research",
        rule_version=RULE_VERSION,
        data_asof=result.end,
        input_paths={
            "dynamic_wall_feature_path": feature_path,
            "dynamic_wall_label_path": label_path,
            "option_factor_path": factor_path,
        },
        output_paths={
            "feature_parquet_path": result.feature_parquet_path,
            "candidate_signal_parquet_path": result.candidate_signal_parquet_path,
            "posterior_label_parquet_path": result.posterior_label_parquet_path,
            "model_comparison_parquet_path": result.model_comparison_parquet_path,
            "candidate_evidence_parquet_path": result.candidate_evidence_parquet_path,
            "oos_parquet_path": result.oos_parquet_path,
            "warning_csv_path": result.warning_csv_path,
            "markdown_path": result.markdown_path,
            "json_path": result.json_path,
        },
        human_review_required=HUMAN_REVIEW_REQUIRED,
        research_boundary=RESEARCH_BOUNDARY,
    )
    manifest["pre_registered_parameters"] = _pre_registered_parameters()
    manifest["candidate_registry"] = [spec.__dict__ for spec in candidate_specs]
    manifest["row_counts"] = {
        "feature": len(features),
        "candidate_signal": len(candidate_signals),
        "posterior_label": len(posterior_labels),
        "model_comparison": len(model_comparison),
        "candidate_evidence": len(candidate_evidence),
        "leave_one_year_out": len(oos),
    }
    write_json(result.manifest_path, manifest)
    return result


def _validate_parameters(
    *,
    horizons: tuple[int, ...],
    min_sample_size: int,
    fdr_level: float,
    dead_zone_bps: int,
) -> tuple[int, ...]:
    normalized = tuple(sorted(set(int(value) for value in horizons)))
    if not normalized or any(value not in DEFAULT_HORIZONS for value in normalized):
        raise ResearchWorkbenchError("R93O horizons只允许1,3,5")
    if min_sample_size <= 0:
        raise ResearchWorkbenchError("R93O min_sample_size必须为正数")
    if not 0 < fdr_level < 1:
        raise ResearchWorkbenchError("R93O fdr_level必须位于0和1之间")
    if dead_zone_bps < 0:
        raise ResearchWorkbenchError("R93O dead_zone_bps不能为负数")
    return normalized


def _matching_r93n_label_path(feature_path: Path) -> Path:
    expected = feature_path.with_name(
        feature_path.name.replace("_feature_daily.parquet", "_lifecycle_label_daily.parquet")
    )
    if expected.exists():
        return expected
    return latest_matching_path(
        feature_path.parent,
        "CF_*_futures_option_dynamic_wall_lifecycle_label_daily.parquet",
        label="R93N dynamic-wall posterior label",
    )


def _optional_latest_path(directory: Path, pattern: str) -> Path | None:
    if not directory.exists():
        return None
    candidates = list(directory.glob(pattern))
    if not candidates:
        return None
    return latest_matching_path(directory, pattern, label=pattern)


def _load_r93n_features(path: Path) -> pd.DataFrame:
    frame = load_table(path, required=FEATURE_REQUIRED_COLUMNS, label="R93O R93N feature")
    overlap = sorted(FORBIDDEN_FEATURE_COLUMNS & set(frame.columns))
    if overlap:
        raise ResearchWorkbenchError(f"R93O T日特征表包含后验字段: {overlap}")
    frame = normalize_trade_date(frame)
    if frame["observation_id"].duplicated().any():
        raise ResearchWorkbenchError("R93O R93N feature observation_id存在重复")
    if not frame["feature_uses_t_or_earlier"].fillna(False).astype(bool).all():
        raise ResearchWorkbenchError("R93O R93N feature存在非T日可观察字段")
    if frame["contains_posterior_outcome"].fillna(True).astype(bool).any():
        raise ResearchWorkbenchError("R93O R93N feature混入历史后验结果")
    return frame.sort_values("trade_date").reset_index(drop=True)


def _load_r93n_labels(path: Path) -> pd.DataFrame:
    frame = load_table(path, required=LABEL_REQUIRED_COLUMNS, label="R93O R93N label")
    frame = normalize_trade_date(frame)
    frame["execution_date"] = pd.to_datetime(frame["execution_date"], errors="coerce").dt.date
    frame["exit_date"] = pd.to_datetime(frame["exit_date"], errors="coerce").dt.date
    frame["horizon"] = pd.to_numeric(frame["horizon"], errors="coerce")
    available = frame["forward_label_available"].fillna(False).astype(bool)
    if not frame.loc[available, "t_plus_one_execution"].fillna(False).astype(bool).all():
        raise ResearchWorkbenchError("R93O R93N label违反T+1执行约束")
    if not frame.loc[available, "label_uses_post_t_prices"].fillna(False).astype(bool).all():
        raise ResearchWorkbenchError("R93O R93N label缺少后验价格边界标记")
    if not frame.loc[
        available, "forward_returns_are_historical_posterior_labels"
    ].fillna(False).astype(bool).all():
        raise ResearchWorkbenchError("R93O forward return未标记为历史后验标签")
    invalid_execution = frame.loc[available & frame["execution_date"].notna()].query(
        "execution_date <= trade_date"
    )
    if not invalid_execution.empty:
        raise ResearchWorkbenchError("R93O execution_date必须晚于trade_date")
    invalid_exit = frame.loc[
        available & frame["execution_date"].notna() & frame["exit_date"].notna()
    ].query("exit_date < execution_date")
    if not invalid_exit.empty:
        raise ResearchWorkbenchError("R93O exit_date不能早于execution_date")
    return frame.sort_values(["trade_date", "horizon"]).reset_index(drop=True)


def _load_option_factors(path: Path | None) -> pd.DataFrame | None:
    if path is None:
        return None
    frame = load_table(
        path,
        required={"trade_date", "underlying_contract", "atm_iv_proxy"},
        label="R93O R48 option factor",
    )
    frame = normalize_trade_date(frame)
    frame["underlying_contract"] = frame["underlying_contract"].astype(str)
    return frame[
        ["trade_date", "underlying_contract", "atm_iv_proxy"]
    ].drop_duplicates(["trade_date", "underlying_contract"], keep="last")


def _validate_source_alignment(features: pd.DataFrame, labels: pd.DataFrame) -> None:
    feature_ids = set(features["observation_id"].astype(str))
    label_ids = set(labels["observation_id"].astype(str))
    if not label_ids.issubset(feature_ids):
        missing = sorted(label_ids - feature_ids)[:5]
        raise ResearchWorkbenchError(f"R93O标签找不到对应T日特征: {missing}")
    if max(labels["trade_date"]) != max(features["trade_date"]):
        raise ResearchWorkbenchError("R93O R93N feature和label的data_asof不一致")


def _build_v2_features(
    *,
    source_features: pd.DataFrame,
    option_factors: pd.DataFrame | None,
    run_id: str,
) -> pd.DataFrame:
    working = source_features.copy().sort_values(["main_contract", "trade_date"])
    numeric_columns = (
        "underlying_settle",
        "dynamic_call_wall_strike",
        "dynamic_put_wall_strike",
        "dynamic_call_wall_distance",
        "dynamic_put_wall_distance",
        "dynamic_call_wall_open_interest_change",
        "dynamic_put_wall_open_interest_change",
        "local_call_open_interest",
        "local_put_open_interest",
        "pcr_oi",
        "atm_iv_rank",
    )
    for column in numeric_columns:
        working[column] = pd.to_numeric(working[column], errors="coerce")
    if option_factors is not None:
        factors = option_factors.rename(columns={"underlying_contract": "main_contract"})
        working = working.merge(
            factors,
            on=["trade_date", "main_contract"],
            how="left",
            validate="one_to_one",
        )
    else:
        working["atm_iv_proxy"] = math.nan

    # 墙距使用标的结算价标准化；正值表示上方空间大于下方空间。
    working["call_wall_distance_bps"] = working["dynamic_call_wall_distance"] * 10000.0
    working["put_wall_distance_bps"] = working["dynamic_put_wall_distance"] * 10000.0
    working["upside_wall_room_bps"] = working["call_wall_distance_bps"].clip(lower=0)
    working["downside_wall_room_bps"] = (-working["put_wall_distance_bps"]).clip(lower=0)
    working["wall_distance_balance_bps"] = (
        working["upside_wall_room_bps"] - working["downside_wall_room_bps"]
    )

    # OI变化只做滚动标准化，不能由公开OI反推出买卖方或做市商Gamma。
    grouped = working.groupby("main_contract", sort=False, group_keys=False)
    for side in ("call", "put"):
        column = f"dynamic_{side}_wall_open_interest_change"
        rolling_mean = grouped[column].transform(
            lambda values: values.rolling(
                OI_Z_WINDOW, min_periods=OI_Z_MIN_PERIODS
            ).mean()
        )
        rolling_std = grouped[column].transform(
            lambda values: values.rolling(
                OI_Z_WINDOW, min_periods=OI_Z_MIN_PERIODS
            ).std(ddof=0)
        )
        working[f"{side}_wall_oi_change_z"] = (
            (working[column] - rolling_mean) / rolling_std.replace(0, math.nan)
        )
    working["wall_oi_change_z_balance"] = (
        working["call_wall_oi_change_z"] - working["put_wall_oi_change_z"]
    )

    for lag in CHANGE_LAGS:
        call_prior = grouped["dynamic_call_wall_strike"].shift(lag)
        put_prior = grouped["dynamic_put_wall_strike"].shift(lag)
        working[f"wall_migration_{lag}d_bps"] = (
            (
                (working["dynamic_call_wall_strike"] - call_prior)
                + (working["dynamic_put_wall_strike"] - put_prior)
            )
            / (2.0 * working["underlying_settle"])
            * 10000.0
        )
        call_local_prior = grouped["local_call_open_interest"].shift(lag)
        put_local_prior = grouped["local_put_open_interest"].shift(lag)
        call_growth = _safe_growth(working["local_call_open_interest"], call_local_prior)
        put_growth = _safe_growth(working["local_put_open_interest"], put_local_prior)
        working[f"call_local_oi_growth_{lag}d"] = call_growth
        working[f"put_local_oi_growth_{lag}d"] = put_growth
        working[f"build_unwind_asymmetry_{lag}d"] = call_growth - put_growth
        pcr_prior = grouped["pcr_oi"].shift(lag)
        working[f"pcr_oi_change_{lag}d"] = working["pcr_oi"] - pcr_prior
        # 低PCR通常对应Call侧占优，因此负PCR变化记为偏多方向分值。
        working[f"pcr_direction_score_{lag}d"] = -working[f"pcr_oi_change_{lag}d"]

    settle_return = grouped["underlying_settle"].pct_change(fill_method=None)
    working["settle_return_1d_same_contract"] = settle_return
    # RV、IV分位和3日重定价必须沿交易日排序，不能沿合约代码排序。
    chronological_index = working.sort_values("trade_date").index
    chronological_return = working.loc[
        chronological_index, "settle_return_1d_same_contract"
    ]
    chronological_rv = (
        chronological_return.rolling(RV_WINDOW, min_periods=RV_WINDOW).std(ddof=0)
        * math.sqrt(252.0)
    )
    working["realized_volatility_20d"] = chronological_rv.reindex(working.index)
    iv_source = pd.to_numeric(
        working.loc[chronological_index, "atm_iv_proxy"], errors="coerce"
    )
    if iv_source.notna().sum() < RANK_MIN_PERIODS:
        iv_rank = pd.to_numeric(
            working.loc[chronological_index, "atm_iv_rank"], errors="coerce"
        )
    else:
        iv_rank = _trailing_rank(iv_source, RANK_WINDOW, RANK_MIN_PERIODS)
    rv_rank = _trailing_rank(
        chronological_rv, RANK_WINDOW, RANK_MIN_PERIODS
    )
    chronological_spread = iv_rank - rv_rank
    chronological_repricing = chronological_spread - chronological_spread.shift(3)
    working["iv_rank_main_252"] = iv_rank.reindex(working.index)
    working["rv_rank_main_252"] = rv_rank.reindex(working.index)
    working["iv_rv_rank_spread"] = chronological_spread.reindex(working.index)
    working["iv_rv_repricing_change_3d"] = chronological_repricing.reindex(working.index)

    working["r93o_feature_rule_version"] = RULE_VERSION
    working["r93o_feature_uses_t_or_earlier"] = True
    working["r93o_contains_posterior_outcome"] = False
    working["enters_signal_matrix"] = False
    working["enters_composite_score"] = False
    working["promotion_eligible"] = False
    working["trading_instruction"] = "not_a_trading_instruction"
    working["run_id"] = run_id
    return working.sort_values("trade_date").reset_index(drop=True)


def _safe_growth(current: pd.Series, prior: pd.Series) -> pd.Series:
    denominator = pd.to_numeric(prior, errors="coerce")
    numerator = pd.to_numeric(current, errors="coerce") - denominator
    result = numerator / denominator.where(denominator.gt(0))
    return result.replace([np.inf, -np.inf], math.nan)


def _trailing_rank(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").tolist()
    ranks: list[float] = []
    for index, current in enumerate(values):
        if current is None or pd.isna(current):
            ranks.append(math.nan)
            continue
        history = [
            float(value)
            for value in values[max(0, index - window + 1) : index + 1]
            if value is not None and pd.notna(value)
        ]
        ranks.append(
            math.nan
            if len(history) < min_periods
            else sum(value <= float(current) for value in history) / len(history)
        )
    return pd.Series(ranks, index=series.index, dtype="float64")


def _candidate_specs() -> tuple[CandidateSpec, ...]:
    specs = [
        CandidateSpec(
            "WALL_DISTANCE_BALANCE",
            "WALL_DISTANCE",
            "wall_distance_balance_bps",
            "DIRECTIONAL_PAIR",
            WALL_DISTANCE_THRESHOLD_BPS,
            "上方动态Call墙空间减下方动态Put墙空间；仅为几何结构proxy。",
        ),
        CandidateSpec(
            "WALL_OI_CHANGE_Z_BALANCE",
            "WALL_OI_CHANGE",
            "wall_oi_change_z_balance",
            "DIRECTIONAL_PAIR",
            OI_Z_THRESHOLD,
            "Call墙OI标准化变化减Put墙OI标准化变化；不推断买卖方。",
        ),
    ]
    for lag in CHANGE_LAGS:
        specs.extend(
            [
                CandidateSpec(
                    f"WALL_MIGRATION_{lag}D",
                    "WALL_MIGRATION",
                    f"wall_migration_{lag}d_bps",
                    "DIRECTIONAL_PAIR",
                    WALL_SHIFT_THRESHOLD_BPS,
                    f"Call/Put动态墙{lag}日平均迁移方向。",
                ),
                CandidateSpec(
                    f"BUILD_UNWIND_ASYMMETRY_{lag}D",
                    "BUILD_UNWIND_ASYMMETRY",
                    f"build_unwind_asymmetry_{lag}d",
                    "DIRECTIONAL_PAIR",
                    0.0,
                    f"Call相对Put局部OI的{lag}日建仓撤仓不对称。",
                ),
                CandidateSpec(
                    f"PCR_OI_CHANGE_{lag}D",
                    "PCR_CHANGE",
                    f"pcr_direction_score_{lag}d",
                    "DIRECTIONAL_PAIR",
                    0.0,
                    f"PCR OI的{lag}日变化方向；下降记为Call侧相对占优。",
                ),
            ]
        )
    specs.append(
        CandidateSpec(
            "IV_RV_REPRICING_CONFIRM_3D",
            "IV_RV_REPRICING",
            "iv_rv_repricing_change_3d",
            "FUTURES_SELECTION",
            0.0,
            "IV分位相对RV分位3日上升时保留期货方向，仅检验风险重定价门控。",
        )
    )
    for bucket in EXPIRY_BUCKETS:
        specs.append(
            CandidateSpec(
                f"EXPIRY_{bucket}",
                "EXPIRY_BUCKET",
                "expiry_bucket",
                "FUTURES_SELECTION",
                0.0,
                f"仅在{bucket}到期桶保留期货方向，用于固定分层而非方向推断。",
                expiry_bucket=bucket,
            )
        )
    return tuple(specs)


def _build_candidate_signals(
    *,
    features: pd.DataFrame,
    candidate_specs: tuple[CandidateSpec, ...],
    run_id: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for feature in features.itertuples(index=False):
        futures_direction = _normalize_direction(feature.futures_direction_5d)
        for spec in candidate_specs:
            raw_value = getattr(feature, spec.value_column, None)
            if spec.expiry_bucket is not None:
                available = str(feature.expiry_bucket) != "UNKNOWN_DTE"
                active = available and str(feature.expiry_bucket) == spec.expiry_bucket
                direction = futures_direction if active else "neutral"
                value: object = str(feature.expiry_bucket)
            elif spec.comparison_mode == "FUTURES_SELECTION":
                number = _number_or_none(raw_value)
                available = number is not None
                active = available and number > spec.threshold
                direction = futures_direction if active else "neutral"
                value = number
            else:
                number = _number_or_none(raw_value)
                available = number is not None
                direction = _direction_from_value(number, spec.threshold)
                active = direction in {"long", "short"}
                value = number
            rows.append(
                {
                    "run_id": run_id,
                    "observation_id": str(feature.observation_id),
                    "trade_date": feature.trade_date,
                    "main_contract": str(feature.main_contract),
                    "option_market_stage": str(feature.option_market_stage),
                    "expiry_bucket": str(feature.expiry_bucket),
                    "candidate_id": spec.candidate_id,
                    "candidate_family": spec.family,
                    "comparison_mode": spec.comparison_mode,
                    # 统一存成文本，避免到期桶类别与数值特征混在同一Parquet列中。
                    "feature_value": "" if value is None else str(value),
                    "pre_registered_threshold": spec.threshold,
                    "signal_available": available,
                    "signal_active": active,
                    "signal_direction": direction,
                    "futures_direction_at_t": futures_direction,
                    "feature_uses_t_or_earlier": True,
                    "contains_posterior_outcome": False,
                    "enters_signal_matrix": False,
                    "enters_composite_score": False,
                    "promotion_eligible": False,
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
    return pd.DataFrame(rows)


def _direction_from_value(value: float | None, threshold: float) -> str:
    if value is None:
        return "neutral"
    if value > threshold:
        return "long"
    if value < -threshold:
        return "short"
    return "neutral"


def _build_candidate_posterior_labels(
    *,
    source_labels: pd.DataFrame,
    candidate_signals: pd.DataFrame,
    dead_zone_bps: int,
    run_id: str,
) -> pd.DataFrame:
    merged = candidate_signals.merge(
        source_labels,
        on=[
            "observation_id",
            "trade_date",
            "main_contract",
            "option_market_stage",
            "expiry_bucket",
        ],
        how="inner",
        validate="many_to_many",
        suffixes=("", "_label"),
    )
    dead_zone = dead_zone_bps / 10000.0
    forward = pd.to_numeric(merged["forward_return"], errors="coerce")
    signs = merged["signal_direction"].map({"long": 1.0, "short": -1.0})
    merged["candidate_directional_return"] = forward * signs
    merged["candidate_outcome"] = merged["candidate_directional_return"].map(
        lambda value: _directional_outcome(value, dead_zone)
    )
    merged["candidate_hit"] = merged["candidate_directional_return"].map(
        lambda value: None if pd.isna(value) else bool(float(value) > dead_zone)
    )
    merged["candidate_mfe"] = np.where(
        merged["signal_direction"].eq("long"),
        merged["long_mfe"],
        np.where(merged["signal_direction"].eq("short"), merged["short_mfe"], math.nan),
    )
    merged["candidate_mae"] = np.where(
        merged["signal_direction"].eq("long"),
        merged["long_mae"],
        np.where(merged["signal_direction"].eq("short"), merged["short_mae"], math.nan),
    )
    merged["run_id"] = run_id
    merged["forward_returns_are_historical_posterior_labels"] = True
    merged["promotion_eligible"] = False
    merged["trading_instruction"] = "not_a_trading_instruction"
    columns = [
        "run_id",
        "observation_id",
        "trade_date",
        "main_contract",
        "calendar_year",
        "option_market_stage",
        "expiry_bucket",
        "candidate_id",
        "candidate_family",
        "comparison_mode",
        "feature_value",
        "pre_registered_threshold",
        "signal_available",
        "signal_active",
        "signal_direction",
        "horizon",
        "execution_date",
        "exit_date",
        "forward_return",
        "candidate_directional_return",
        "candidate_outcome",
        "candidate_hit",
        "candidate_mfe",
        "candidate_mae",
        "futures_direction",
        "futures_directional_return",
        "futures_hit",
        "r48_option_direction",
        "r48_directional_return",
        "r48_hit",
        "dynamic_option_direction",
        "dynamic_directional_return",
        "dynamic_hit",
        "forward_label_available",
        "t_plus_one_execution",
        "label_uses_post_t_prices",
        "forward_returns_are_historical_posterior_labels",
        "promotion_eligible",
        "trading_instruction",
    ]
    return merged[columns].sort_values(
        ["trade_date", "candidate_id", "horizon"]
    ).reset_index(drop=True)


def _build_model_comparison(
    *,
    source_labels: pd.DataFrame,
    min_sample_size: int,
    run_id: str,
) -> pd.DataFrame:
    available = source_labels.loc[
        source_labels["forward_label_available"].fillna(False).astype(bool)
    ].copy()
    rows: list[dict[str, object]] = []
    model_columns = {
        "FUTURES_ONLY": ("futures_directional_return", "futures_hit", "futures_direction"),
        "R48_OPTION_FACTOR": ("r48_directional_return", "r48_hit", "r48_option_direction"),
        "R93N_DYNAMIC_WALL": (
            "dynamic_directional_return",
            "dynamic_hit",
            "dynamic_option_direction",
        ),
    }
    for stage in ("ALL", "EARLY_THIN", "EXPANSION", "MATURE_ACTIVE"):
        stage_rows = available if stage == "ALL" else available.loc[
            available["option_market_stage"].eq(stage)
        ]
        for horizon, horizon_rows in stage_rows.groupby("horizon", sort=True):
            for model_id, (return_column, hit_column, direction_column) in model_columns.items():
                metrics = _model_metrics(
                    horizon_rows,
                    return_column=return_column,
                    hit_column=hit_column,
                    direction_column=direction_column,
                    min_sample_size=min_sample_size,
                )
                rows.append(
                    {
                        "run_id": run_id,
                        "model_id": model_id,
                        "option_market_stage": stage,
                        "horizon": int(horizon),
                        **metrics,
                        "promotion_eligible": False,
                        "trading_instruction": "not_a_trading_instruction",
                    }
                )
    return pd.DataFrame(rows)


def _model_metrics(
    frame: pd.DataFrame,
    *,
    return_column: str,
    hit_column: str,
    direction_column: str,
    min_sample_size: int,
) -> dict[str, object]:
    returns = pd.to_numeric(frame[return_column], errors="coerce").dropna()
    directions = frame[direction_column].map(_normalize_direction)
    hits = frame.loc[directions.isin(["long", "short"]), hit_column].dropna()
    return {
        "available_label_count": len(frame),
        "direction_sample_count": len(returns),
        "hit_rate": _bool_mean(hits),
        "mean_directional_return": _mean_or_nan(returns),
        "median_directional_return": _median_or_nan(returns),
        "evidence_level": _sample_evidence(len(returns), min_sample_size),
    }


def _build_candidate_evidence(
    *,
    posterior_labels: pd.DataFrame,
    min_sample_size: int,
    fdr_level: float,
    run_id: str,
) -> pd.DataFrame:
    available = posterior_labels.loc[
        posterior_labels["forward_label_available"].fillna(False).astype(bool)
    ].copy()
    rows: list[dict[str, object]] = []
    for stage in ("ALL", "EARLY_THIN", "EXPANSION", "MATURE_ACTIVE"):
        stage_rows = available if stage == "ALL" else available.loc[
            available["option_market_stage"].eq(stage)
        ]
        grouped = stage_rows.groupby(
            ["candidate_id", "candidate_family", "comparison_mode", "horizon"],
            sort=True,
        )
        for (candidate_id, family, mode, horizon), group in grouped:
            metrics = _candidate_metrics(group, comparison_mode=str(mode))
            annual = _annual_stability(group, comparison_mode=str(mode))
            p_value = _candidate_incremental_p_value(group, comparison_mode=str(mode))
            rows.append(
                {
                    "run_id": run_id,
                    "candidate_id": str(candidate_id),
                    "candidate_family": str(family),
                    "comparison_mode": str(mode),
                    "option_market_stage": stage,
                    "horizon": int(horizon),
                    **metrics,
                    **annual,
                    "incremental_p_value": p_value,
                    "fdr_q_value": math.nan,
                    "oos_test_years": 0,
                    "oos_positive_years": 0,
                    "oos_non_partial_positive": False,
                    "decision": "REJECT",
                    "decision_reason": "PENDING_OOS",
                    "promotion_eligible": False,
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
    summary = pd.DataFrame(rows)
    tested = summary["incremental_p_value"].notna()
    if tested.any():
        summary.loc[tested, "fdr_q_value"] = _benjamini_hochberg(
            summary.loc[tested, "incremental_p_value"].astype(float).tolist()
        )
    summary["pre_oos_status"] = summary.apply(
        lambda row: _pre_oos_status(
            row=row,
            min_sample_size=min_sample_size,
            fdr_level=fdr_level,
        ),
        axis=1,
    )
    return summary


def _candidate_metrics(group: pd.DataFrame, *, comparison_mode: str) -> dict[str, object]:
    active = group.loc[group["signal_direction"].isin(["long", "short"])].copy()
    inactive = group.loc[~group["signal_direction"].isin(["long", "short"])].copy()
    candidate_returns = pd.to_numeric(
        active["candidate_directional_return"], errors="coerce"
    ).dropna()
    candidate_hit = _bool_mean(active["candidate_hit"])
    futures_active = pd.to_numeric(
        active["futures_directional_return"], errors="coerce"
    ).dropna()
    futures_inactive = pd.to_numeric(
        inactive["futures_directional_return"], errors="coerce"
    ).dropna()
    futures_all = pd.to_numeric(group["futures_directional_return"], errors="coerce").dropna()
    r48_active = pd.to_numeric(active["r48_directional_return"], errors="coerce").dropna()
    dynamic_active = pd.to_numeric(
        active["dynamic_directional_return"], errors="coerce"
    ).dropna()
    candidate_mean = _mean_or_none(candidate_returns)
    futures_active_mean = _mean_or_none(futures_active)
    futures_inactive_mean = _mean_or_none(futures_inactive)
    futures_all_mean = _mean_or_none(futures_all)
    r48_mean = _mean_or_none(r48_active)
    dynamic_mean = _mean_or_none(dynamic_active)
    primary_delta = (
        _difference(candidate_mean, futures_active_mean)
        if comparison_mode == "DIRECTIONAL_PAIR"
        else _difference(futures_active_mean, futures_inactive_mean)
    )
    return {
        "available_label_count": len(group),
        "candidate_sample_count": len(candidate_returns),
        "inactive_futures_sample_count": len(futures_inactive),
        "candidate_hit_rate": candidate_hit,
        "candidate_mean_directional_return": _nan_if_none(candidate_mean),
        "candidate_median_directional_return": _median_or_nan(candidate_returns),
        "candidate_mean_mfe": _mean_or_nan(
            pd.to_numeric(active["candidate_mfe"], errors="coerce").dropna()
        ),
        "candidate_mean_mae": _mean_or_nan(
            pd.to_numeric(active["candidate_mae"], errors="coerce").dropna()
        ),
        "futures_active_hit_rate": _bool_mean(active["futures_hit"]),
        "futures_active_sample_count": len(futures_active),
        "futures_active_mean_directional_return": _nan_if_none(futures_active_mean),
        "futures_inactive_hit_rate": _bool_mean(inactive["futures_hit"]),
        "futures_inactive_direction_sample_count": len(futures_inactive),
        "futures_inactive_mean_directional_return": _nan_if_none(futures_inactive_mean),
        "futures_all_mean_directional_return": _nan_if_none(futures_all_mean),
        "r48_active_hit_rate": _bool_mean(active["r48_hit"]),
        "r48_active_sample_count": len(r48_active),
        "r48_active_mean_directional_return": _nan_if_none(r48_mean),
        "r93n_active_hit_rate": _bool_mean(active["dynamic_hit"]),
        "r93n_active_sample_count": len(dynamic_active),
        "r93n_active_mean_directional_return": _nan_if_none(dynamic_mean),
        "candidate_minus_futures_active_mean_return": _nan_if_none(
            _difference(candidate_mean, futures_active_mean)
        ),
        "candidate_minus_r48_active_mean_return": _nan_if_none(
            _difference(candidate_mean, r48_mean)
        ),
        "candidate_minus_r93n_active_mean_return": _nan_if_none(
            _difference(candidate_mean, dynamic_mean)
        ),
        "selection_minus_futures_inactive_mean_return": _nan_if_none(
            _difference(futures_active_mean, futures_inactive_mean)
        ),
        "selection_minus_futures_all_mean_return": _nan_if_none(
            _difference(futures_active_mean, futures_all_mean)
        ),
        "primary_incremental_mean_return": _nan_if_none(primary_delta),
    }


def _annual_stability(group: pd.DataFrame, *, comparison_mode: str) -> dict[str, object]:
    deltas: list[float] = []
    for _year, year_rows in group.groupby("calendar_year", sort=True):
        metrics = _candidate_metrics(year_rows, comparison_mode=comparison_mode)
        delta = _number_or_none(metrics["primary_incremental_mean_return"])
        if delta is not None:
            deltas.append(delta)
    positive = sum(value > 0 for value in deltas)
    return {
        "annual_comparable_years": len(deltas),
        "annual_positive_years": positive,
        "annual_direction_consistency": math.nan if not deltas else positive / len(deltas),
    }


def _candidate_incremental_p_value(group: pd.DataFrame, *, comparison_mode: str) -> float:
    active = group.loc[group["signal_direction"].isin(["long", "short"])].copy()
    if comparison_mode == "DIRECTIONAL_PAIR":
        comparable = active.loc[active["candidate_hit"].notna() & active["futures_hit"].notna()]
        if comparable.empty:
            return math.nan
        candidate_hit = comparable["candidate_hit"].astype(bool)
        futures_hit = comparable["futures_hit"].astype(bool)
        candidate_only = int((candidate_hit & ~futures_hit).sum())
        futures_only = int((~candidate_hit & futures_hit).sum())
        return _exact_binomial_two_sided(candidate_only, candidate_only + futures_only)
    inactive = group.loc[~group["signal_direction"].isin(["long", "short"])].copy()
    active_hits = active["futures_hit"].dropna().astype(bool)
    inactive_hits = inactive["futures_hit"].dropna().astype(bool)
    if active_hits.empty or inactive_hits.empty:
        return math.nan
    return _fisher_exact_two_sided(
        int(active_hits.sum()),
        int((~active_hits).sum()),
        int(inactive_hits.sum()),
        int((~inactive_hits).sum()),
    )


def _pre_oos_status(*, row: pd.Series, min_sample_size: int, fdr_level: float) -> str:
    sample_count = int(row["candidate_sample_count"])
    primary_delta = _number_or_none(row["primary_incremental_mean_return"])
    candidate_mean = _number_or_none(row["candidate_mean_directional_return"])
    q_value = _number_or_none(row["fdr_q_value"])
    if sample_count < min_sample_size or primary_delta is None or primary_delta <= 0:
        return "REJECT"
    if candidate_mean is None or candidate_mean <= 0:
        return "REJECT"
    if q_value is not None and q_value <= fdr_level:
        return "KEEP_CANDIDATE"
    return "WATCH"


def _build_leave_one_year_out(
    *,
    posterior_labels: pd.DataFrame,
    min_sample_size: int,
    run_id: str,
) -> pd.DataFrame:
    mature = posterior_labels.loc[
        posterior_labels["forward_label_available"].fillna(False).astype(bool)
        & posterior_labels["option_market_stage"].eq("MATURE_ACTIVE")
    ].copy()
    years = sorted(set(int(value) for value in mature["calendar_year"]))
    rows: list[dict[str, object]] = []
    if len(years) < 2:
        return pd.DataFrame()
    for (candidate_id, family, mode, horizon), candidate_rows in mature.groupby(
        ["candidate_id", "candidate_family", "comparison_mode", "horizon"], sort=True
    ):
        for test_year in years:
            train = candidate_rows.loc[candidate_rows["calendar_year"].ne(test_year)]
            test = candidate_rows.loc[candidate_rows["calendar_year"].eq(test_year)]
            train_metrics = _candidate_metrics(train, comparison_mode=str(mode))
            test_metrics = _candidate_metrics(test, comparison_mode=str(mode))
            train_delta = _number_or_none(train_metrics["primary_incremental_mean_return"])
            selected = (
                int(train_metrics["candidate_sample_count"]) >= min_sample_size
                and train_delta is not None
                and train_delta > 0
            )
            test_delta = _number_or_none(test_metrics["primary_incremental_mean_return"])
            test_count = int(test_metrics["candidate_sample_count"])
            if not selected:
                status = "NOT_SELECTED_IN_TRAIN"
            elif test_count < max(5, min_sample_size // 3):
                status = "TEST_SMALL_SAMPLE"
            elif test_delta is not None and test_delta > 0:
                status = "OOS_POSITIVE"
            else:
                status = "OOS_NO_INCREMENT"
            rows.append(
                {
                    "run_id": run_id,
                    "candidate_id": str(candidate_id),
                    "candidate_family": str(family),
                    "comparison_mode": str(mode),
                    "horizon": int(horizon),
                    "test_year": test_year,
                    "train_years": ";".join(str(year) for year in years if year != test_year),
                    "train_sample_count": int(train_metrics["candidate_sample_count"]),
                    "train_primary_incremental_mean_return": train_delta,
                    "selected_in_train": selected,
                    "test_sample_count": test_count,
                    "test_candidate_hit_rate": test_metrics["candidate_hit_rate"],
                    "test_candidate_mean_directional_return": test_metrics[
                        "candidate_mean_directional_return"
                    ],
                    "test_primary_incremental_mean_return": test_delta,
                    "oos_status": status,
                    "test_year_is_partial": test_year == max(years),
                    "promotion_eligible": False,
                    "trading_instruction": "not_a_trading_instruction",
                }
            )
    return pd.DataFrame(rows)


def _apply_final_decisions(
    *,
    candidate_evidence: pd.DataFrame,
    oos: pd.DataFrame,
    min_sample_size: int,
    fdr_level: float,
) -> pd.DataFrame:
    working = candidate_evidence.copy()
    if oos.empty:
        oos_counts: dict[tuple[str, int], tuple[int, int, bool]] = {}
    else:
        oos_counts = {}
        for (candidate_id, horizon), group in oos.groupby(["candidate_id", "horizon"]):
            valid = group.loc[
                group["oos_status"].isin(["OOS_POSITIVE", "OOS_NO_INCREMENT"])
            ]
            positive = valid.loc[valid["oos_status"].eq("OOS_POSITIVE")]
            non_partial_positive = bool(
                (~positive["test_year_is_partial"].fillna(True).astype(bool)).any()
            )
            oos_counts[(str(candidate_id), int(horizon))] = (
                len(valid),
                len(positive),
                non_partial_positive,
            )
    decisions: list[str] = []
    reasons: list[str] = []
    test_years_values: list[int] = []
    positive_years_values: list[int] = []
    non_partial_values: list[bool] = []
    for row in working.itertuples(index=False):
        test_years, positive_years, non_partial = oos_counts.get(
            (str(row.candidate_id), int(row.horizon)), (0, 0, False)
        )
        test_years_values.append(test_years)
        positive_years_values.append(positive_years)
        non_partial_values.append(non_partial)
        sample_count = int(row.candidate_sample_count)
        primary_delta = _number_or_none(row.primary_incremental_mean_return)
        candidate_mean = _number_or_none(row.candidate_mean_directional_return)
        q_value = _number_or_none(row.fdr_q_value)
        annual_years = int(row.annual_comparable_years)
        annual_consistency = _number_or_none(row.annual_direction_consistency)
        if sample_count < min_sample_size:
            decision, reason = "REJECT", "SMALL_SAMPLE"
        elif (
            primary_delta is None
            or primary_delta <= 0
            or candidate_mean is None
            or candidate_mean <= 0
        ):
            decision, reason = "REJECT", "NO_POSITIVE_PRIMARY_INCREMENT"
        elif str(row.option_market_stage) != "MATURE_ACTIVE":
            decision, reason = "WATCH", "NON_MATURE_DIAGNOSTIC_ONLY"
        elif (
            q_value is not None
            and q_value <= fdr_level
            and annual_years >= 2
            and annual_consistency is not None
            and annual_consistency >= 2 / 3
            and test_years >= 2
            and positive_years >= 2
            and non_partial
            and _beats_secondary_references(row, min_sample_size=min_sample_size)
        ):
            decision, reason = "KEEP", "FDR_ANNUAL_OOS_AND_REFERENCE_GATES_PASS"
        else:
            decision, reason = "WATCH", "POSITIVE_BUT_GATE_INCOMPLETE"
        decisions.append(decision)
        reasons.append(reason)
    working["oos_test_years"] = test_years_values
    working["oos_positive_years"] = positive_years_values
    working["oos_non_partial_positive"] = non_partial_values
    working["decision"] = decisions
    working["decision_reason"] = reasons
    return working.sort_values(
        ["option_market_stage", "decision", "horizon", "candidate_id"]
    ).reset_index(drop=True)


def _beats_secondary_references(row: object, *, min_sample_size: int) -> bool:
    if str(getattr(row, "comparison_mode")) == "FUTURES_SELECTION":
        return True
    for sample_field, delta_field in (
        ("r48_active_sample_count", "candidate_minus_r48_active_mean_return"),
        ("r93n_active_sample_count", "candidate_minus_r93n_active_mean_return"),
    ):
        if int(getattr(row, sample_field)) < min_sample_size:
            return False
        field = delta_field
        value = _number_or_none(getattr(row, field))
        if value is None or value <= 0:
            return False
    return True


def _warning_records(
    *,
    run_id: str,
    features: pd.DataFrame,
    posterior_labels: pd.DataFrame,
    candidate_evidence: pd.DataFrame,
    oos: pd.DataFrame,
    option_factor_path: Path | None,
    option_factors: pd.DataFrame | None,
) -> list[FuturesOptionWallFactorV2WarningRecord]:
    unavailable_labels = int(
        (~posterior_labels["forward_label_available"].fillna(False).astype(bool)).sum()
    )
    small_rows = int(candidate_evidence["decision_reason"].eq("SMALL_SAMPLE").sum())
    keep_rows = int(
        candidate_evidence.loc[
            candidate_evidence["option_market_stage"].eq("MATURE_ACTIVE"), "decision"
        ].eq("KEEP").sum()
    )
    missing_iv = int(features["iv_rv_repricing_change_3d"].isna().sum())
    feature_asof = max(features["trade_date"])
    factor_asof = (
        None
        if option_factors is None or option_factors.empty
        else max(option_factors["trade_date"])
    )
    factor_behind = factor_asof is not None and factor_asof < feature_asof
    return [
        FuturesOptionWallFactorV2WarningRecord(
            run_id=run_id,
            section="input",
            severity=WARN if option_factors is None or factor_behind else INFO,
            warning_code=(
                "R48_OPTION_FACTOR_NOT_CONNECTED"
                if option_factors is None
                else (
                    "R48_OPTION_FACTOR_ASOF_BEHIND"
                    if factor_behind
                    else "R48_OPTION_FACTOR_CONNECTED"
                )
            ),
            warning_message=(
                "未接入R48 atm_iv_proxy，IV-RV仅使用R93N现有IV rank回退。"
                if option_factors is None
                else (
                    f"R48期权因子截至{factor_asof}，落后R93O特征截至{feature_asof}。"
                    if factor_behind
                    else f"R48期权因子已接入：{option_factor_path}"
                )
            ),
            affected_count=(
                len(features)
                if option_factors is None
                else int(features["trade_date"].gt(factor_asof).sum())
                if factor_behind
                else 0
            ),
            human_review_required="option_iv_and_realized_volatility_proxy_interpretation",
        ),
        FuturesOptionWallFactorV2WarningRecord(
            run_id=run_id,
            section="feature",
            severity=WARN if missing_iv == len(features) else INFO,
            warning_code="IV_RV_REPRICING_FEATURE_MISSING",
            warning_message="滚动窗口不足或IV缺失的日期不能生成IV-RV重定价特征。",
            affected_count=missing_iv,
            human_review_required="option_iv_and_realized_volatility_proxy_interpretation",
        ),
        FuturesOptionWallFactorV2WarningRecord(
            run_id=run_id,
            section="posterior_label",
            severity=INFO,
            warning_code="LATEST_FORWARD_LABEL_PENDING",
            warning_message="最新日期没有完整未来窗口属于正常状态；后验标签不会回写T日特征。",
            affected_count=unavailable_labels,
        ),
        FuturesOptionWallFactorV2WarningRecord(
            run_id=run_id,
            section="sample_size",
            severity=WARN if small_rows else INFO,
            warning_code="R93O_SMALL_SAMPLE_CANDIDATE",
            warning_message="部分候选或到期桶样本不足，裁决已降级为REJECT。",
            affected_count=small_rows,
            human_review_required="fdr_and_leave_one_year_out_interpretation",
        ),
        FuturesOptionWallFactorV2WarningRecord(
            run_id=run_id,
            section="decision",
            severity=WARN if keep_rows == 0 else INFO,
            warning_code=(
                "NO_R93O_KEEP_CANDIDATE"
                if keep_rows == 0
                else "R93O_KEEP_CANDIDATE_EXISTS"
            ),
            warning_message=(
                "成熟活跃期没有候选同时通过FDR、年度一致性、留一年和参考模型门槛。"
                if keep_rows == 0
                else "至少一个成熟活跃期候选通过预注册证据门槛；仍不得自动晋级主模型。"
            ),
            affected_count=keep_rows,
            human_review_required="fdr_and_leave_one_year_out_interpretation",
        ),
        FuturesOptionWallFactorV2WarningRecord(
            run_id=run_id,
            section="oos",
            severity=WARN if oos.empty else INFO,
            warning_code="R93O_OOS_NOT_AVAILABLE" if oos.empty else "R93O_OOS_AVAILABLE",
            warning_message=(
                "成熟活跃期留一年验证结果已单独保存。"
                if not oos.empty
                else "成熟期年份不足，不能进行留一年验证。"
            ),
            affected_count=len(oos),
            human_review_required="fdr_and_leave_one_year_out_interpretation",
        ),
        FuturesOptionWallFactorV2WarningRecord(
            run_id=run_id,
            section="research_boundary",
            severity=INFO,
            warning_code="OPTION_OI_OWNERSHIP_UNKNOWN",
            warning_message=(
                "公开期权OI不能识别买卖方，高OI墙不能自动解释为支撑、阻力或dealer gamma。"
            ),
            affected_count=len(features),
            human_review_required="option_open_interest_long_short_ownership_unknown",
        ),
    ]


def _paths(
    *,
    start: date,
    end: date,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    stem = f"CF_{start.isoformat()}_{end.isoformat()}_futures_option_wall_factor_v2"
    data_root = output_dir or (
        data_dir() / "research" / PRODUCT_CODE / "futures_option_wall_factor_v2"
    )
    report_root = report_output_dir or reports_dir() / "research" / "futures_option_wall_factor_v2"
    return {
        "feature_parquet": data_root / f"{stem}_feature_daily.parquet",
        "feature_csv": data_root / f"{stem}_feature_daily.csv",
        "signal_parquet": data_root / f"{stem}_candidate_signal_daily.parquet",
        "signal_csv": data_root / f"{stem}_candidate_signal_daily.csv",
        "label_parquet": data_root / f"{stem}_posterior_label.parquet",
        "label_csv": data_root / f"{stem}_posterior_label.csv",
        "model_parquet": data_root / f"{stem}_model_comparison.parquet",
        "model_csv": data_root / f"{stem}_model_comparison.csv",
        "evidence_parquet": data_root / f"{stem}_candidate_evidence.parquet",
        "evidence_csv": data_root / f"{stem}_candidate_evidence.csv",
        "oos_parquet": data_root / f"{stem}_leave_one_year_out.parquet",
        "oos_csv": data_root / f"{stem}_leave_one_year_out.csv",
        "warning_csv": data_root / f"{stem}_warnings.csv",
        "markdown": report_root / f"{stem}.md",
        "json": report_root / f"{stem}.json",
        "manifest": report_root / f"{stem}_manifest.json",
    }


def _write_outputs(
    *,
    paths: dict[str, Path],
    features: pd.DataFrame,
    candidate_signals: pd.DataFrame,
    posterior_labels: pd.DataFrame,
    model_comparison: pd.DataFrame,
    candidate_evidence: pd.DataFrame,
    oos: pd.DataFrame,
    warnings: list[FuturesOptionWallFactorV2WarningRecord],
) -> None:
    write_frame(features, paths["feature_parquet"], paths["feature_csv"])
    write_frame(candidate_signals, paths["signal_parquet"], paths["signal_csv"])
    write_frame(posterior_labels, paths["label_parquet"], paths["label_csv"])
    write_frame(model_comparison, paths["model_parquet"], paths["model_csv"])
    write_frame(candidate_evidence, paths["evidence_parquet"], paths["evidence_csv"])
    write_frame(oos, paths["oos_parquet"], paths["oos_csv"])
    write_warning_csv(paths["warning_csv"], [item.to_summary() for item in warnings])


def _write_markdown(
    *,
    result: ResearchFuturesOptionWallFactorV2Result,
    latest: dict[str, object],
    latest_signals: pd.DataFrame,
    model_comparison: pd.DataFrame,
    candidate_evidence: pd.DataFrame,
    oos: pd.DataFrame,
    candidate_specs: tuple[CandidateSpec, ...],
) -> None:
    lines = [
        "# CF期权墙因子v2研究 R93O",
        "",
        "## 数据状态",
        "",
        f"- 样本区间：`{result.start}` 至 `{result.end}`。",
        (
            f"- R93N T日特征：`{result.feature_row_count}` 行；"
            f"预注册候选：`{result.candidate_count}` 个。"
        ),
        (
            f"- 候选信号：`{result.candidate_signal_row_count}` 行；"
            f"历史后验标签：`{result.posterior_label_row_count}` 行。"
        ),
        (
            f"- 当前主力：`{result.latest_main_contract}`；"
            f"最新活跃候选：`{', '.join(result.latest_active_candidates) or '无'}`。"
        ),
        "- 本研究只读取R93N冻结特征和物理分离的T+1标签，不重新解析交易所raw/core。",
        "",
        "## 预注册定义",
        "",
        "| 候选 | 特征族 | 比较方式 | 固定阈值 | 解释 |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for spec in candidate_specs:
        lines.append(
            f"| {spec.candidate_id} | {spec.family} | {spec.comparison_mode} | "
            f"{fmt_number(spec.threshold, 3)} | {spec.interpretation} |"
        )
    lines.extend(
        [
            "",
            "## 统一模型基线",
            "",
            "| 市场阶段 | 周期 | 模型 | 样本 | 命中率 | 平均方向收益 | 证据等级 |",
            "| --- | ---: | --- | ---: | ---: | ---: | --- |",
        ]
    )
    model_focus = model_comparison.loc[
        model_comparison["option_market_stage"].isin(["ALL", "MATURE_ACTIVE"])
    ]
    for row in model_focus.itertuples(index=False):
        lines.append(
            f"| {row.option_market_stage} | {row.horizon}D | {row.model_id} | "
            f"{row.direction_sample_count} | {fmt_percent(row.hit_rate)} | "
            f"{fmt_percent(row.mean_directional_return)} | {row.evidence_level} |"
        )
    lines.extend(
        [
            "",
            "## 成熟活跃期候选裁决",
            "",
            "| 候选 | 周期 | 样本 | 候选命中 | 候选均值 | 主增量 | "
            "FDR q | 年度一致性 | OOS正年份 | 裁决 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    mature = candidate_evidence.loc[
        candidate_evidence["option_market_stage"].eq("MATURE_ACTIVE")
    ].sort_values(
        ["decision", "primary_incremental_mean_return", "candidate_sample_count"],
        ascending=[True, False, False],
    )
    for row in mature.itertuples(index=False):
        lines.append(
            f"| {row.candidate_id} | {row.horizon}D | {row.candidate_sample_count} | "
            f"{fmt_percent(row.candidate_hit_rate)} | "
            f"{fmt_percent(row.candidate_mean_directional_return)} | "
            f"{fmt_percent(row.primary_incremental_mean_return)} | "
            f"{fmt_number(row.fdr_q_value, 4)} | "
            f"{fmt_percent(row.annual_direction_consistency)} | "
            f"{row.oos_positive_years}/{row.oos_test_years} | {row.decision} |"
        )
    lines.extend(["", "## 留一年验证", ""])
    if oos.empty:
        lines.append("- 成熟活跃期年份不足，当前不能形成留一年验证。")
    else:
        lines.extend(
            [
                "| 候选 | 周期 | 测试年 | 训练样本 | 测试样本 | 测试主增量 | 状态 |",
                "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        selected = oos.loc[oos["selected_in_train"].astype(bool)].sort_values(
            ["oos_status", "test_primary_incremental_mean_return"],
            ascending=[True, False],
        )
        for row in selected.head(40).itertuples(index=False):
            lines.append(
                f"| {row.candidate_id} | {row.horizon}D | {row.test_year} | "
                f"{row.train_sample_count} | {row.test_sample_count} | "
                f"{fmt_percent(row.test_primary_incremental_mean_return)} | {row.oos_status} |"
            )
    lines.extend(
        [
            "",
            "## 当前样本映射",
            "",
            (
                f"- 日期：`{latest.get('trade_date')}`；"
                f"合约：`{latest.get('main_contract')}`；"
                f"市场阶段：`{latest.get('option_market_stage')}`。"
            ),
            (
                f"- 动态Call/Put墙距："
                f"`{fmt_number(latest.get('call_wall_distance_bps'), 1)}` / "
                f"`{fmt_number(latest.get('put_wall_distance_bps'), 1)}` bps。"
            ),
            (
                f"- 墙OI标准化差：`{fmt_number(latest.get('wall_oi_change_z_balance'), 3)}`；"
                f"IV-RV 3日重定价："
                f"`{fmt_number(latest.get('iv_rv_repricing_change_3d'), 3)}`。"
            ),
        ]
    )
    if latest_signals.empty:
        lines.append("- 最新日没有候选形成明确long/short方向。")
    else:
        for row in latest_signals.itertuples(index=False):
            lines.append(
                f"- `{row.candidate_id}`：`{row.signal_direction}`，特征值 `{row.feature_value}`。"
            )
    lines.extend(
        [
            "",
            "## 研究裁决",
            "",
            (
                f"- 成熟活跃期：`KEEP={result.keep_count}`、"
                f"`WATCH={result.watch_count}`、`REJECT={result.reject_count}`。"
            ),
            (
                "- KEEP只表示候选通过本轮预注册历史证据门槛，"
                "仍不得自动写回signal_matrix、composite_score、方向或仓位。"
            ),
            "- WATCH表示存在正向迹象但FDR、年度一致性、留一年或参考模型门槛未全部通过。",
            "- REJECT表示当前定义没有正向增量或样本不足，不进行反向做空解释。",
            "",
            "## 研究边界",
            "",
            "- 所有forward return仅为历史后验验证标签，按T+1执行口径构造，不参与T日特征生成。",
            "- 期权IV/Greek仍是研究proxy；公开OI不能识别买卖方，也不能推断dealer gamma。",
            "- 高OI行权价不自动等于支撑或阻力；方向约定只是待证伪的预注册proxy。",
            "- 本研究不自动反转期货方向，不修改主模型，不构成交易指令。",
            "",
            "## HUMAN_REVIEW_REQUIRED",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in HUMAN_REVIEW_REQUIRED)
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _pre_registered_parameters() -> dict[str, object]:
    return {
        "horizons": list(DEFAULT_HORIZONS),
        "wall_distance_threshold_bps": WALL_DISTANCE_THRESHOLD_BPS,
        "wall_shift_threshold_bps": WALL_SHIFT_THRESHOLD_BPS,
        "oi_z_threshold": OI_Z_THRESHOLD,
        "oi_z_window": OI_Z_WINDOW,
        "oi_z_min_periods": OI_Z_MIN_PERIODS,
        "rv_window": RV_WINDOW,
        "rank_window": RANK_WINDOW,
        "rank_min_periods": RANK_MIN_PERIODS,
        "change_lags": list(CHANGE_LAGS),
        "expiry_buckets": list(EXPIRY_BUCKETS),
        "post_hoc_threshold_search": False,
    }


def _normalize_direction(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in {"long", "bullish", "偏多", "多"}:
        return "long"
    if text in {"short", "bearish", "偏空", "空"}:
        return "short"
    return "neutral"


def _directional_outcome(value: object, dead_zone: float) -> str:
    number = _number_or_none(value)
    if number is None:
        return "NO_DIRECTION"
    if number > dead_zone:
        return "FOLLOW_THROUGH"
    if number < -dead_zone:
        return "FAILED"
    return "UNRESOLVED"


def _sample_evidence(sample_count: int, min_sample_size: int) -> str:
    if sample_count >= max(100, min_sample_size * 3):
        return "READY"
    if sample_count >= min_sample_size:
        return "WATCH"
    return "WEAK_OR_SMALL_SAMPLE"


def _exact_binomial_two_sided(successes: int, sample_count: int) -> float:
    if sample_count <= 0:
        return math.nan
    successes = max(0, min(successes, sample_count))
    observed = math.comb(sample_count, successes) * (0.5**sample_count)
    probability = 0.0
    for value in range(sample_count + 1):
        candidate = math.comb(sample_count, value) * (0.5**sample_count)
        if candidate <= observed + 1e-15:
            probability += candidate
    return min(1.0, probability)


def _fisher_exact_two_sided(a: int, b: int, c: int, d: int) -> float:
    row_one = a + b
    row_two = c + d
    success_total = a + c
    total = row_one + row_two
    if total <= 0 or row_one <= 0 or row_two <= 0:
        return math.nan
    lower = max(0, row_one - (total - success_total))
    upper = min(row_one, success_total)

    def probability(value: int) -> float:
        log_p = (
            math.lgamma(success_total + 1)
            - math.lgamma(value + 1)
            - math.lgamma(success_total - value + 1)
            + math.lgamma(total - success_total + 1)
            - math.lgamma(row_one - value + 1)
            - math.lgamma(total - success_total - row_one + value + 1)
            - (
                math.lgamma(total + 1)
                - math.lgamma(row_one + 1)
                - math.lgamma(total - row_one + 1)
            )
        )
        return math.exp(log_p)

    observed = probability(a)
    return min(
        1.0,
        sum(
            probability(value)
            for value in range(lower, upper + 1)
            if probability(value) <= observed + 1e-15
        ),
    )


def _benjamini_hochberg(p_values: list[float]) -> list[float]:
    if not p_values:
        return []
    order = sorted(range(len(p_values)), key=p_values.__getitem__)
    adjusted = [1.0] * len(p_values)
    running = 1.0
    count = len(p_values)
    for rank_index in range(count - 1, -1, -1):
        index = order[rank_index]
        rank = rank_index + 1
        running = min(running, p_values[index] * count / rank)
        adjusted[index] = min(1.0, running)
    return adjusted


def _number_or_none(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _nan_if_none(value: float | None) -> float:
    return math.nan if value is None else value


def _difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _mean_or_none(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return None if numeric.empty else float(numeric.mean())


def _mean_or_nan(values: pd.Series) -> float:
    value = _mean_or_none(values)
    return math.nan if value is None else value


def _median_or_nan(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return math.nan if numeric.empty else float(numeric.median())


def _bool_mean(values: pd.Series) -> float:
    available = values.dropna()
    return math.nan if available.empty else float(available.astype(bool).mean())
