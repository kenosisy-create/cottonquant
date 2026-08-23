"""R93G cotton-year and policy-reference research sidecar for CF."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, project_root, reports_dir
from cotton_factor.common.time import utc_now
from cotton_factor.strategy.io import latest_strategy_input_paths

PRODUCT_CODE = "CF"
RULE_VERSION = "V5.1_R93G_cotton_year_policy_v1"
DEFAULT_HORIZONS = (5, 20, 60)
IFIND_SPOT_EXTENSION_ID = "S002885871"
IFIND_SPOT_EXTENSION_NAME = "现货价:棉花(3128B级)"
RESEARCH_BOUNDARY = (
    "18600元/吨只作为政策研究参考线，不是期货支撑位、现货保底价或公允价值；"
    "本模块不修改composite_score，不构成交易指令。"
)
HUMAN_REVIEW_REQUIRED = (
    "target_price_official_effective_period_and_quality_basis",
    "ccindex_3128b_policy_price_comparability",
    "mapped_futures_contract_vs_policy_reference",
    "fundamental_source_unit_and_frequency",
    "policy_supply_event_volume_and_effective_date",
)


@dataclass(frozen=True)
class PolicyReferenceConfig:
    """Validated subset of the inspectable R93G YAML contract."""

    version: str
    target_price: float
    target_unit: str
    source_status: str
    official_effective_period_verified: bool
    source_note: str
    cotton_year_start_month: int
    cotton_year_start_day: int
    spot_indicator_id: str
    spot_indicator_name: str
    excluded_price_objects: tuple[str, ...]


@dataclass(frozen=True)
class CottonYearPolicyWarningRecord:
    """One explicit R93G warning or boundary record."""

    severity: str
    warning_code: str
    message: str
    human_review_required: tuple[str, ...] = ()

    def to_summary(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "warning_code": self.warning_code,
            "message": self.message,
            "human_review_required": list(self.human_review_required),
        }


@dataclass(frozen=True)
class ResearchCottonYearPolicyResult:
    """R93G artifacts and latest observable policy-reference state."""

    run_id: str
    status: str
    start: date
    end: date
    spot_data_asof: date
    target_price: float
    latest_contract: str
    latest_futures_settle: float
    latest_futures_gap: float
    latest_futures_gap_pct: float
    latest_spot_observation_date: date
    latest_spot_price: float
    latest_spot_source_name: str
    latest_spot_source_indicator_id: str
    latest_spot_staleness_days: int
    latest_spot_usable: bool
    daily_path: Path
    cotton_year_summary_path: Path
    historical_validation_path: Path
    validation_summary_path: Path
    fundamental_summary_path: Path
    warning_csv_path: Path
    json_path: Path
    manifest_path: Path
    markdown_path: Path
    warning_records: tuple[CottonYearPolicyWarningRecord, ...]

    @property
    def warning_count(self) -> int:
        return sum(row.severity in {"WARN", "ERROR"} for row in self.warning_records)

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI-safe payload."""
        return {
            "run_id": self.run_id,
            "status": self.status,
            "product_code": PRODUCT_CODE,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "spot_data_asof": self.spot_data_asof.isoformat(),
            "target_price": self.target_price,
            "latest_contract": self.latest_contract,
            "latest_futures_settle": self.latest_futures_settle,
            "latest_futures_gap": self.latest_futures_gap,
            "latest_futures_gap_pct": self.latest_futures_gap_pct,
            "latest_spot_observation_date": self.latest_spot_observation_date.isoformat(),
            "latest_spot_price": self.latest_spot_price,
            "latest_spot_source_name": self.latest_spot_source_name,
            "latest_spot_source_indicator_id": self.latest_spot_source_indicator_id,
            "latest_spot_staleness_days": self.latest_spot_staleness_days,
            "latest_spot_usable": self.latest_spot_usable,
            "daily_path": str(self.daily_path),
            "cotton_year_summary_path": str(self.cotton_year_summary_path),
            "historical_validation_path": str(self.historical_validation_path),
            "validation_summary_path": str(self.validation_summary_path),
            "fundamental_summary_path": str(self.fundamental_summary_path),
            "warning_csv_path": str(self.warning_csv_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "markdown_path": str(self.markdown_path),
            "warning_count": self.warning_count,
            "warnings": [row.to_summary() for row in self.warning_records],
            "fundamental_signal_status": "not_connected",
        }


def build_cf_cotton_year_policy_research(
    *,
    continuous_price_path: Path | None = None,
    spot_price_path: Path | None = None,
    spot_extension_path: Path | None = None,
    fundamental_context_path: Path | None = None,
    policy_config_path: Path | None = None,
    input_dir: Path | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    max_spot_staleness_days: int = 7,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchCottonYearPolicyResult:
    """Build R93G current facts, posterior validation and Chinese report."""
    if max_spot_staleness_days < 0:
        raise ResearchWorkbenchError("max_spot_staleness_days must be >= 0")
    selected_horizons = tuple(sorted(set(horizons)))
    if not selected_horizons or any(value <= 0 for value in selected_horizons):
        raise ResearchWorkbenchError("R93G horizons must contain positive trading-day counts")

    continuous_path = continuous_price_path
    if continuous_path is None:
        continuous_path = latest_strategy_input_paths(input_dir)["continuous"]
    spot_path = spot_price_path or (
        data_dir()
        / "research"
        / PRODUCT_CODE
        / "fundamentals"
        / "CF_fundamental_spot_price_daily.parquet"
    )
    context_path = fundamental_context_path or (
        data_dir()
        / "research"
        / PRODUCT_CODE
        / "fundamental_context"
        / "CF_fundamental_context_daily.parquet"
    )
    config_path = policy_config_path or (
        project_root() / "configs" / "research" / "CF_policy_reference_v1.yaml"
    )
    config = load_policy_reference_config(config_path)
    continuous = _read_required_parquet(continuous_path, "continuous price")
    spot = _read_required_parquet(spot_path, "fundamental spot price")
    spot_bridge_statistics: dict[str, object] = {"active": False}
    if spot_extension_path is not None:
        spot_extension = _read_required_parquet(
            spot_extension_path,
            "iFinD spot extension",
        )
        primary_spot = spot
        spot = append_spot_extension(
            primary_spot=primary_spot,
            extension_spot=spot_extension,
            config=config,
        )
        spot_bridge_statistics = build_spot_bridge_statistics(
            primary_spot=primary_spot,
            extension_spot=spot_extension,
            config=config,
        )
    context = pd.read_parquet(context_path) if context_path.exists() else pd.DataFrame()

    daily = build_policy_reference_daily(
        continuous=continuous,
        spot=spot,
        config=config,
        max_spot_staleness_days=max_spot_staleness_days,
    )
    cotton_year_summary = build_cotton_year_summary(daily)
    historical_validation = build_policy_reference_historical_validation(
        daily=daily,
        horizons=selected_horizons,
    )
    validation_summary = build_policy_reference_validation_summary(historical_validation)
    fundamental_summary = build_cotton_year_fundamental_summary(
        context=context,
        config=config,
        start=pd.Timestamp(daily["trade_date"].min()),
        end=pd.Timestamp(daily["trade_date"].max()),
    )
    warning_records = _warning_records(
        daily=daily,
        fundamental_summary=fundamental_summary,
        context_path=context_path,
        config=config,
    )
    paths = _output_paths(
        start=pd.Timestamp(daily["trade_date"].min()).date(),
        end=pd.Timestamp(daily["trade_date"].max()).date(),
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    _write_parquet(paths["daily"], daily)
    _write_parquet(paths["cotton_year_summary"], cotton_year_summary)
    _write_parquet(paths["historical_validation"], historical_validation)
    _write_parquet(paths["validation_summary"], validation_summary)
    _write_parquet(paths["fundamental_summary"], fundamental_summary)

    latest = daily.iloc[-1]
    latest_spot = daily.loc[daily["spot_observation_date"].notna()].iloc[-1]
    active_run_id = run_id or _default_run_id()
    result = ResearchCottonYearPolicyResult(
        run_id=active_run_id,
        status="POLICY_REFERENCE_RESEARCH_READY_WITH_WARNINGS",
        start=pd.Timestamp(daily["trade_date"].min()).date(),
        end=pd.Timestamp(daily["trade_date"].max()).date(),
        spot_data_asof=pd.Timestamp(daily["spot_observation_date"].max()).date(),
        target_price=config.target_price,
        latest_contract=str(latest["mapped_contract"]),
        latest_futures_settle=float(latest["futures_settle"]),
        latest_futures_gap=float(latest["futures_gap_to_reference"]),
        latest_futures_gap_pct=float(latest["futures_gap_pct"]),
        latest_spot_observation_date=pd.Timestamp(
            latest_spot["spot_observation_date"]
        ).date(),
        latest_spot_price=float(latest_spot["spot_price_observed"]),
        latest_spot_source_name=str(latest_spot["spot_source_name"]),
        latest_spot_source_indicator_id=str(latest_spot["spot_source_indicator_id"]),
        latest_spot_staleness_days=int(latest_spot["spot_staleness_days"]),
        latest_spot_usable=bool(latest_spot["spot_usable"]),
        daily_path=paths["daily"],
        cotton_year_summary_path=paths["cotton_year_summary"],
        historical_validation_path=paths["historical_validation"],
        validation_summary_path=paths["validation_summary"],
        fundamental_summary_path=paths["fundamental_summary"],
        warning_csv_path=paths["warnings"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
        markdown_path=paths["markdown"],
        warning_records=tuple(warning_records),
    )
    _write_warnings(result)
    report_statistics = _report_statistics(daily=daily, validation=historical_validation)
    _write_json(
        result=result,
        config=config,
        horizons=selected_horizons,
        report_statistics=report_statistics,
        spot_bridge_statistics=spot_bridge_statistics,
    )
    _write_markdown(
        result=result,
        config=config,
        daily=daily,
        cotton_year_summary=cotton_year_summary,
        validation_summary=validation_summary,
        fundamental_summary=fundamental_summary,
        report_statistics=report_statistics,
        spot_bridge_statistics=spot_bridge_statistics,
    )
    input_paths = [continuous_path, spot_path, context_path, config_path]
    if spot_extension_path is not None:
        input_paths.append(spot_extension_path)
    _write_manifest(
        result=result,
        input_paths=tuple(input_paths),
        spot_bridge_statistics=spot_bridge_statistics,
    )
    return result


def load_policy_reference_config(path: Path) -> PolicyReferenceConfig:
    """Load and validate the explicit R93G policy-reference assumptions."""
    if not path.exists() or not path.is_file():
        raise ResearchWorkbenchError(f"policy reference config not found: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ResearchWorkbenchError("policy reference config must be a mapping")
    try:
        cotton_year = payload["cotton_year"]
        target = payload["target_price_reference"]
        spot = payload["spot_price_object"]
        verified = target["official_effective_period_verified"]
        exclusions = payload["excluded_price_objects"]
        if not isinstance(verified, bool):
            raise TypeError("official_effective_period_verified must be boolean")
        if not isinstance(exclusions, list):
            raise TypeError("excluded_price_objects must be a list")
        config = PolicyReferenceConfig(
            version=str(payload["version"]),
            target_price=float(target["value"]),
            target_unit=str(target["unit"]),
            source_status=str(target["source_status"]),
            official_effective_period_verified=verified,
            source_note=str(target["source_note"]),
            cotton_year_start_month=int(cotton_year["start_month"]),
            cotton_year_start_day=int(cotton_year["start_day"]),
            spot_indicator_id=str(spot["indicator_id"]),
            spot_indicator_name=str(spot["indicator_name"]),
            excluded_price_objects=tuple(str(value) for value in exclusions),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ResearchWorkbenchError(f"invalid policy reference config: {exc}") from exc
    if config.target_price <= 0:
        raise ResearchWorkbenchError("policy target-price reference must be positive")
    if not 1 <= config.cotton_year_start_month <= 12:
        raise ResearchWorkbenchError("cotton-year start month must be in 1..12")
    if not 1 <= config.cotton_year_start_day <= 31:
        raise ResearchWorkbenchError("cotton-year start day must be in 1..31")
    required_exclusions = {
        "additive_adjusted_continuous_price",
        "roll_neutral_return_index",
    }
    if not required_exclusions <= set(config.excluded_price_objects):
        raise ResearchWorkbenchError(
            "policy config must exclude adjusted continuous price and return index"
        )
    return config


def cotton_year_label(
    value: date | pd.Timestamp,
    *,
    start_month: int = 9,
    start_day: int = 1,
) -> str:
    """Map one observation to the September-August cotton marketing year."""
    current = pd.Timestamp(value)
    starts_this_year = (current.month, current.day) >= (start_month, start_day)
    start_year = current.year if starts_this_year else current.year - 1
    return f"{start_year}/{str(start_year + 1)[-2:]}"


def append_spot_extension(
    *,
    primary_spot: pd.DataFrame,
    extension_spot: pd.DataFrame,
    config: PolicyReferenceConfig,
) -> pd.DataFrame:
    """在不覆盖主现货历史的前提下接续 iFinD 3128B 观察。"""
    required = {
        "trade_date",
        "indicator_id",
        "indicator_name",
        "indicator_value",
        "unit",
        "source_name",
        "data_quality_flag",
        "human_review_required",
    }
    for label, frame in (("primary", primary_spot), ("extension", extension_spot)):
        missing = required - set(frame.columns)
        if missing:
            raise ResearchWorkbenchError(
                f"{label} spot series missing R93G columns: {sorted(missing)}"
            )

    primary = primary_spot.copy()
    primary_selected = primary.loc[
        primary["indicator_id"].eq(config.spot_indicator_id)
    ].copy()
    if primary_selected.empty:
        raise ResearchWorkbenchError(
            f"primary spot indicator not found: {config.spot_indicator_id}"
        )
    primary_selected["trade_date"] = pd.to_datetime(
        primary_selected["trade_date"]
    ).astype("datetime64[ns]")
    primary_last_date = primary_selected["trade_date"].max()

    extension = extension_spot.copy()
    observed_ids = set(extension["indicator_id"].dropna().astype(str))
    observed_names = set(extension["indicator_name"].dropna().astype(str))
    if observed_ids != {IFIND_SPOT_EXTENSION_ID}:
        raise ResearchWorkbenchError(
            "iFinD spot extension indicator mismatch: " f"{sorted(observed_ids)}"
        )
    if observed_names != {IFIND_SPOT_EXTENSION_NAME}:
        raise ResearchWorkbenchError(
            "iFinD spot extension name mismatch: " f"{sorted(observed_names)}"
        )
    extension["trade_date"] = pd.to_datetime(extension["trade_date"]).astype(
        "datetime64[ns]"
    )
    extension["indicator_value"] = pd.to_numeric(
        extension["indicator_value"], errors="coerce"
    )
    if extension["trade_date"].duplicated().any():
        raise ResearchWorkbenchError("iFinD spot extension contains duplicate dates")
    if extension["indicator_value"].isna().any() or extension[
        "indicator_value"
    ].le(0).any():
        raise ResearchWorkbenchError("iFinD spot extension price must be positive")

    # 主序列最后日期之前即使有缺口也不回填，避免供应商切换改写历史。
    forward_extension = extension.loc[
        extension["trade_date"].gt(primary_last_date)
    ].copy()
    primary["source_indicator_id"] = primary["indicator_id"].astype(str)
    primary["source_indicator_name"] = primary["indicator_name"].astype(str)
    primary["spot_bridge_status"] = "PRIMARY_HISTORY"
    if forward_extension.empty:
        return primary

    forward_extension["source_indicator_id"] = forward_extension["indicator_id"].astype(
        str
    )
    forward_extension["source_indicator_name"] = forward_extension[
        "indicator_name"
    ].astype(str)
    forward_extension["indicator_id"] = config.spot_indicator_id
    forward_extension["indicator_name"] = config.spot_indicator_name
    forward_extension["spot_bridge_status"] = "FORWARD_EXTENSION_AFTER_PRIMARY_END"
    return pd.concat([primary, forward_extension], ignore_index=True, sort=False)


def build_spot_bridge_statistics(
    *,
    primary_spot: pd.DataFrame,
    extension_spot: pd.DataFrame,
    config: PolicyReferenceConfig,
) -> dict[str, object]:
    """量化供应商重叠区间，验证接续关系但不推定口径完全一致。"""
    primary = primary_spot.loc[
        primary_spot["indicator_id"].eq(config.spot_indicator_id),
        ["trade_date", "indicator_value"],
    ].copy()
    extension = extension_spot.loc[
        extension_spot["indicator_id"].eq(IFIND_SPOT_EXTENSION_ID),
        ["trade_date", "indicator_value"],
    ].copy()
    primary["trade_date"] = pd.to_datetime(primary["trade_date"])
    extension["trade_date"] = pd.to_datetime(extension["trade_date"])
    primary["primary_price"] = pd.to_numeric(primary["indicator_value"], errors="coerce")
    extension["extension_price"] = pd.to_numeric(
        extension["indicator_value"], errors="coerce"
    )
    overlap = primary[["trade_date", "primary_price"]].merge(
        extension[["trade_date", "extension_price"]],
        on="trade_date",
        how="inner",
        validate="one_to_one",
    ).dropna()
    primary_end = primary["trade_date"].max()
    appended = extension.loc[extension["trade_date"].gt(primary_end)]
    correlation = (
        float(overlap["primary_price"].corr(overlap["extension_price"]))
        if len(overlap) >= 2
        else None
    )
    price_difference = overlap["extension_price"] - overlap["primary_price"]
    return {
        "active": True,
        "primary_indicator_id": config.spot_indicator_id,
        "extension_indicator_id": IFIND_SPOT_EXTENSION_ID,
        "primary_end": pd.Timestamp(primary_end).date().isoformat(),
        "extension_end": pd.Timestamp(extension["trade_date"].max()).date().isoformat(),
        "first_appended_date": (
            pd.Timestamp(appended["trade_date"].min()).date().isoformat()
            if not appended.empty
            else None
        ),
        "appended_observation_count": len(appended),
        "overlap_count": len(overlap),
        "overlap_start": (
            pd.Timestamp(overlap["trade_date"].min()).date().isoformat()
            if not overlap.empty
            else None
        ),
        "overlap_end": (
            pd.Timestamp(overlap["trade_date"].max()).date().isoformat()
            if not overlap.empty
            else None
        ),
        "overlap_correlation": correlation,
        "median_extension_minus_primary": (
            float(price_difference.median()) if not price_difference.empty else None
        ),
        "mean_extension_minus_primary": (
            float(price_difference.mean()) if not price_difference.empty else None
        ),
        "overlapping_history_overwritten": False,
        "comparability_status": "HUMAN_REVIEW_REQUIRED",
    }


def build_policy_reference_daily(
    *,
    continuous: pd.DataFrame,
    spot: pd.DataFrame,
    config: PolicyReferenceConfig,
    max_spot_staleness_days: int,
) -> pd.DataFrame:
    """Build a current-state table without any future labels."""
    required_continuous = {
        "trade_date",
        "product_code",
        "signal_object_id",
        "mapped_contract",
        "price_field",
        "raw_price",
        "input_snapshot_ids",
    }
    missing = required_continuous - set(continuous.columns)
    if missing:
        raise ResearchWorkbenchError(
            f"continuous price missing R93G columns: {sorted(missing)}"
        )
    selected = continuous.loc[
        continuous["product_code"].eq(PRODUCT_CODE)
        & continuous["signal_object_id"].eq("CF.C1")
        & continuous["price_field"].eq("settle")
    ].copy()
    if selected.empty:
        raise ResearchWorkbenchError("continuous price contains no CF.C1 settlement rows")
    selected["trade_date"] = pd.to_datetime(selected["trade_date"]).astype(
        "datetime64[ns]"
    )
    selected["raw_price"] = pd.to_numeric(selected["raw_price"], errors="coerce")
    if selected["trade_date"].duplicated().any():
        raise ResearchWorkbenchError("continuous price contains duplicate trade dates")
    if selected["raw_price"].isna().any() or selected["raw_price"].le(0).any():
        raise ResearchWorkbenchError("continuous raw settlement must be positive")
    selected = selected.sort_values("trade_date").reset_index(drop=True)

    required_spot = {
        "trade_date",
        "indicator_id",
        "indicator_name",
        "indicator_value",
        "unit",
        "source_name",
        "data_quality_flag",
        "human_review_required",
    }
    missing_spot = required_spot - set(spot.columns)
    if missing_spot:
        raise ResearchWorkbenchError(
            f"spot price observation missing R93G columns: {sorted(missing_spot)}"
        )
    spot_selected = spot.loc[spot["indicator_id"].eq(config.spot_indicator_id)].copy()
    if spot_selected.empty:
        raise ResearchWorkbenchError(
            f"spot indicator not found: {config.spot_indicator_id}"
        )
    names = set(spot_selected["indicator_name"].dropna().astype(str))
    if names != {config.spot_indicator_name}:
        raise ResearchWorkbenchError(
            "spot indicator id/name does not match policy-reference config"
        )
    spot_selected["trade_date"] = pd.to_datetime(spot_selected["trade_date"]).astype(
        "datetime64[ns]"
    )
    spot_selected["indicator_value"] = pd.to_numeric(
        spot_selected["indicator_value"], errors="coerce"
    )
    if spot_selected["trade_date"].duplicated().any():
        raise ResearchWorkbenchError("configured spot indicator contains duplicate dates")
    if spot_selected["indicator_value"].isna().any() or spot_selected[
        "indicator_value"
    ].le(0).any():
        raise ResearchWorkbenchError("configured spot price must be positive")
    if "source_indicator_id" not in spot_selected.columns:
        spot_selected["source_indicator_id"] = spot_selected["indicator_id"].astype(str)
    if "source_indicator_name" not in spot_selected.columns:
        spot_selected["source_indicator_name"] = spot_selected["indicator_name"].astype(str)
    if "spot_bridge_status" not in spot_selected.columns:
        spot_selected["spot_bridge_status"] = "PRIMARY_HISTORY"
    spot_selected = spot_selected.sort_values("trade_date").rename(
        columns={
            "trade_date": "spot_observation_date",
            "indicator_value": "spot_price_observed",
            "unit": "spot_unit",
            "source_name": "spot_source_name",
            "data_quality_flag": "spot_data_quality_flag",
            "human_review_required": "spot_human_review_required",
            "source_indicator_id": "spot_source_indicator_id",
            "source_indicator_name": "spot_source_indicator_name",
        }
    )
    spot_columns = [
        "spot_observation_date",
        "spot_price_observed",
        "spot_unit",
        "spot_source_name",
        "spot_data_quality_flag",
        "spot_human_review_required",
        "spot_source_indicator_id",
        "spot_source_indicator_name",
        "spot_bridge_status",
    ]
    # 现货只能向后匹配至期货观察日，禁止使用尚未公布的未来现货值。
    merged = pd.merge_asof(
        selected,
        spot_selected[spot_columns],
        left_on="trade_date",
        right_on="spot_observation_date",
        direction="backward",
        allow_exact_matches=True,
    )
    if merged["spot_observation_date"].notna().sum() == 0:
        raise ResearchWorkbenchError(
            "configured spot series has no observation at or before the futures history"
        )
    merged["spot_staleness_days"] = (
        merged["trade_date"] - merged["spot_observation_date"]
    ).dt.days
    merged["spot_usable"] = (
        merged["spot_observation_date"].notna()
        & merged["spot_staleness_days"].le(max_spot_staleness_days)
    )
    merged["cotton_year"] = merged["trade_date"].map(
        lambda value: cotton_year_label(
            value,
            start_month=config.cotton_year_start_month,
            start_day=config.cotton_year_start_day,
        )
    )
    # 参考线只用于计算可审计偏离，不在这里生成方向、支撑位或交易信号。
    merged["target_price_reference"] = config.target_price
    merged["target_price_unit"] = config.target_unit
    merged["target_price_source_status"] = config.source_status
    merged["futures_settle"] = merged["raw_price"]
    merged["futures_gap_to_reference"] = (
        merged["futures_settle"] - config.target_price
    )
    merged["futures_gap_pct"] = (
        merged["futures_gap_to_reference"] / config.target_price
    )
    merged["spot_gap_to_reference"] = merged["spot_price_observed"].where(
        merged["spot_usable"]
    ) - config.target_price
    merged["spot_gap_pct"] = merged["spot_gap_to_reference"] / config.target_price
    merged["mapped_basis_proxy"] = merged["spot_price_observed"].where(
        merged["spot_usable"]
    ) - merged["futures_settle"]
    merged["futures_reference_bucket"] = merged["futures_gap_pct"].map(
        _reference_bucket
    )
    merged["spot_reference_bucket"] = merged["spot_gap_pct"].map(_reference_bucket)
    merged.loc[~merged["spot_usable"], "spot_reference_bucket"] = "STALE_OR_MISSING"
    merged["relative_configuration"] = merged.apply(_relative_configuration, axis=1)
    merged["futures_price_object"] = "MAPPED_REAL_CONTRACT_SETTLEMENT"
    merged["spot_price_object"] = config.spot_indicator_id
    merged["policy_interpretation_status"] = "HUMAN_REVIEW_REQUIRED"
    merged["fundamental_signal_status"] = "not_connected"
    merged["contains_forward_label"] = False
    merged["rule_version"] = RULE_VERSION
    output_columns = [
        "trade_date",
        "product_code",
        "signal_object_id",
        "cotton_year",
        "mapped_contract",
        "futures_settle",
        "futures_gap_to_reference",
        "futures_gap_pct",
        "futures_reference_bucket",
        "spot_observation_date",
        "spot_price_observed",
        "spot_staleness_days",
        "spot_usable",
        "spot_gap_to_reference",
        "spot_gap_pct",
        "spot_reference_bucket",
        "mapped_basis_proxy",
        "relative_configuration",
        "target_price_reference",
        "target_price_unit",
        "target_price_source_status",
        "futures_price_object",
        "spot_price_object",
        "spot_unit",
        "spot_source_name",
        "spot_data_quality_flag",
        "spot_human_review_required",
        "spot_source_indicator_id",
        "spot_source_indicator_name",
        "spot_bridge_status",
        "policy_interpretation_status",
        "fundamental_signal_status",
        "contains_forward_label",
        "input_snapshot_ids",
        "rule_version",
    ]
    return merged[output_columns].reset_index(drop=True)


def build_cotton_year_summary(daily: pd.DataFrame) -> pd.DataFrame:
    """Summarize price-reference distance without forward labels."""
    rows: list[dict[str, object]] = []
    for cotton_year, frame in daily.groupby("cotton_year", sort=True):
        ordered = frame.sort_values("trade_date")
        spot_usable = ordered.loc[ordered["spot_usable"]].copy()
        rows.append(
            {
                "cotton_year": cotton_year,
                "date_start": ordered["trade_date"].min(),
                "date_end": ordered["trade_date"].max(),
                "trading_day_count": len(ordered),
                "contract_switch_count": int(
                    ordered["mapped_contract"].ne(ordered["mapped_contract"].shift()).sum()
                    - 1
                ),
                "futures_gap_mean": ordered["futures_gap_to_reference"].mean(),
                "futures_gap_median": ordered["futures_gap_to_reference"].median(),
                "futures_gap_min": ordered["futures_gap_to_reference"].min(),
                "futures_gap_max": ordered["futures_gap_to_reference"].max(),
                "futures_below_reference_rate": ordered["futures_gap_to_reference"].lt(
                    0
                ).mean(),
                "futures_reference_cross_count": _cross_count(
                    ordered["futures_gap_to_reference"]
                ),
                "spot_usable_day_count": len(spot_usable),
                "spot_gap_mean": _mean_or_none(spot_usable["spot_gap_to_reference"]),
                "spot_gap_median": _median_or_none(spot_usable["spot_gap_to_reference"]),
                "spot_below_reference_rate": _mean_or_none(
                    spot_usable["spot_gap_to_reference"].lt(0)
                ),
                "spot_reference_cross_count": _cross_count(
                    spot_usable["spot_gap_to_reference"]
                ),
                "mapped_basis_proxy_median": _median_or_none(
                    spot_usable["mapped_basis_proxy"]
                ),
                "contains_forward_label": False,
                "rule_version": RULE_VERSION,
            }
        )
    return pd.DataFrame(rows)


def build_policy_reference_historical_validation(
    *,
    daily: pd.DataFrame,
    horizons: tuple[int, ...],
) -> pd.DataFrame:
    """Build posterior labels in a table physically separate from current facts."""
    # 未来路径只在独立后验表中形成，当前状态表永远不回写这些字段。
    ordered = daily.sort_values("trade_date").reset_index(drop=True)
    rows: list[dict[str, object]] = []
    for index, current in ordered.iterrows():
        for horizon in horizons:
            future_index = index + horizon
            if future_index >= len(ordered):
                continue
            future = ordered.iloc[future_index]
            same_contract = current["mapped_contract"] == future["mapped_contract"]
            futures_current_gap = float(current["futures_gap_to_reference"])
            futures_future_gap = float(future["futures_gap_to_reference"])
            spot_comparable = bool(current["spot_usable"] and future["spot_usable"])
            spot_current_gap = (
                float(current["spot_gap_to_reference"]) if spot_comparable else None
            )
            spot_future_gap = (
                float(future["spot_gap_to_reference"]) if spot_comparable else None
            )
            rows.append(
                {
                    "signal_trade_date": current["trade_date"],
                    "label_trade_date": future["trade_date"],
                    "horizon_sessions": horizon,
                    "cotton_year": current["cotton_year"],
                    "target_price_reference": current["target_price_reference"],
                    "futures_reference_bucket": current["futures_reference_bucket"],
                    "futures_start_contract": current["mapped_contract"],
                    "futures_end_contract": future["mapped_contract"],
                    "futures_same_contract": same_contract,
                    "futures_start_gap": futures_current_gap,
                    "futures_end_gap": futures_future_gap if same_contract else None,
                    "futures_forward_return": (
                        float(future["futures_settle"])
                        / float(current["futures_settle"])
                        - 1.0
                        if same_contract
                        else None
                    ),
                    "futures_gap_converged": (
                        abs(futures_future_gap) < abs(futures_current_gap)
                        if same_contract
                        else None
                    ),
                    "futures_reference_crossed": (
                        _crossed_reference(futures_current_gap, futures_future_gap)
                        if same_contract
                        else None
                    ),
                    "spot_reference_bucket": current["spot_reference_bucket"],
                    "spot_comparable": spot_comparable,
                    "spot_start_gap": spot_current_gap,
                    "spot_end_gap": spot_future_gap,
                    "spot_forward_return": (
                        float(future["spot_price_observed"])
                        / float(current["spot_price_observed"])
                        - 1.0
                        if spot_comparable
                        else None
                    ),
                    "spot_gap_converged": (
                        abs(spot_future_gap) < abs(spot_current_gap)
                        if spot_comparable
                        and spot_current_gap is not None
                        and spot_future_gap is not None
                        else None
                    ),
                    "spot_reference_crossed": (
                        _crossed_reference(spot_current_gap, spot_future_gap)
                        if spot_comparable
                        and spot_current_gap is not None
                        and spot_future_gap is not None
                        else None
                    ),
                    "label_type": "HISTORICAL_POSTERIOR_ONLY",
                    "contains_forward_label": True,
                    "rule_version": RULE_VERSION,
                }
            )
    return pd.DataFrame(rows)


def build_policy_reference_validation_summary(validation: pd.DataFrame) -> pd.DataFrame:
    """Aggregate descriptive convergence evidence by object, horizon and bucket."""
    rows: list[dict[str, object]] = []
    object_contracts = (
        (
            "futures_same_contract",
            "futures_same_contract",
            "futures_reference_bucket",
            "futures_gap_converged",
            "futures_reference_crossed",
            "futures_forward_return",
        ),
        (
            "spot_ccindex_3128b",
            "spot_comparable",
            "spot_reference_bucket",
            "spot_gap_converged",
            "spot_reference_crossed",
            "spot_forward_return",
        ),
    )
    for object_name, comparable_col, bucket_col, convergence_col, cross_col, return_col in (
        object_contracts
    ):
        comparable = validation.loc[validation[comparable_col].eq(True)].copy()  # noqa: E712
        for (horizon, bucket), frame in comparable.groupby(
            ["horizon_sessions", bucket_col], sort=True
        ):
            convergence = frame[convergence_col].dropna().astype(bool)
            crossed = frame[cross_col].dropna().astype(bool)
            count = len(convergence)
            rate = float(convergence.mean()) if count else None
            lower, upper = _wilson_interval(sum(convergence), count)
            rows.append(
                {
                    "price_object": object_name,
                    "horizon_sessions": int(horizon),
                    "reference_bucket": bucket,
                    "sample_count": count,
                    "convergence_rate": rate,
                    "convergence_ci95_lower": lower,
                    "convergence_ci95_upper": upper,
                    "reference_cross_rate": (
                        float(crossed.mean()) if not crossed.empty else None
                    ),
                    "mean_forward_return": _mean_or_none(frame[return_col]),
                    "median_forward_return": _median_or_none(frame[return_col]),
                    "evidence_status": _evidence_status(count),
                    "label_type": "HISTORICAL_POSTERIOR_ONLY",
                    "rule_version": RULE_VERSION,
                }
            )
    columns = [
        "price_object",
        "horizon_sessions",
        "reference_bucket",
        "sample_count",
        "convergence_rate",
        "convergence_ci95_lower",
        "convergence_ci95_upper",
        "reference_cross_rate",
        "mean_forward_return",
        "median_forward_return",
        "evidence_status",
        "label_type",
        "rule_version",
    ]
    return pd.DataFrame(rows, columns=columns)


def build_cotton_year_fundamental_summary(
    *,
    context: pd.DataFrame,
    config: PolicyReferenceConfig,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """Keep each fundamental series separate while aligning it to cotton years."""
    columns = [
        "cotton_year",
        "dataset_type",
        "indicator_name",
        "metric_name",
        "unit",
        "date_start",
        "date_end",
        "observation_count",
        "first_value",
        "last_value",
        "change",
        "change_pct",
        "source_names",
        "human_review_required",
        "fundamental_signal_status",
        "rule_version",
    ]
    if context.empty:
        return pd.DataFrame(columns=columns)
    required = {
        "trade_date",
        "dataset_type",
        "indicator_name",
        "indicator_value",
        "unit",
        "source_name",
        "human_review_required",
    }
    missing = required - set(context.columns)
    if missing:
        raise ResearchWorkbenchError(
            f"fundamental context missing R93G columns: {sorted(missing)}"
        )
    selected = context.copy()
    selected["trade_date"] = pd.to_datetime(selected["trade_date"]).astype(
        "datetime64[ns]"
    )
    selected["indicator_value"] = pd.to_numeric(
        selected["indicator_value"], errors="coerce"
    )
    selected = selected.loc[
        selected["trade_date"].between(start, end)
        & selected["indicator_value"].notna()
    ].copy()
    if "metric_name" not in selected.columns:
        selected["metric_name"] = "not_applicable"
    else:
        selected["metric_name"] = selected["metric_name"].fillna("not_applicable")
    selected["cotton_year"] = selected["trade_date"].map(
        lambda value: cotton_year_label(
            value,
            start_month=config.cotton_year_start_month,
            start_day=config.cotton_year_start_day,
        )
    )
    # 每个基本面指标独立汇总，禁止把不同单位或频率拼成一个供给得分。
    rows: list[dict[str, object]] = []
    group_columns = ["cotton_year", "dataset_type", "indicator_name", "metric_name"]
    for keys, frame in selected.groupby(group_columns, sort=True, dropna=False):
        ordered = frame.sort_values("trade_date")
        first_value = float(ordered.iloc[0]["indicator_value"])
        last_value = float(ordered.iloc[-1]["indicator_value"])
        rows.append(
            {
                "cotton_year": keys[0],
                "dataset_type": keys[1],
                "indicator_name": keys[2],
                "metric_name": keys[3],
                "unit": _joined_values(ordered["unit"]),
                "date_start": ordered["trade_date"].min(),
                "date_end": ordered["trade_date"].max(),
                "observation_count": len(ordered),
                "first_value": first_value,
                "last_value": last_value,
                "change": last_value - first_value,
                "change_pct": (
                    last_value / first_value - 1.0 if first_value != 0 else None
                ),
                "source_names": _joined_values(ordered["source_name"]),
                "human_review_required": bool(
                    ordered["human_review_required"].astype(bool).any()
                ),
                "fundamental_signal_status": "not_connected",
                "rule_version": RULE_VERSION,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _reference_bucket(value: object) -> str:
    if value is None or pd.isna(value):
        return "MISSING"
    gap = float(value)
    if gap <= -0.20:
        return "BELOW_MORE_THAN_20PCT"
    if gap <= -0.10:
        return "BELOW_10_TO_20PCT"
    if gap <= -0.05:
        return "BELOW_5_TO_10PCT"
    if gap < 0:
        return "BELOW_WITHIN_5PCT"
    if gap <= 0.05:
        return "ABOVE_WITHIN_5PCT"
    if gap <= 0.10:
        return "ABOVE_5_TO_10PCT"
    if gap <= 0.20:
        return "ABOVE_10_TO_20PCT"
    return "ABOVE_MORE_THAN_20PCT"


def _relative_configuration(row: pd.Series) -> str:
    if not bool(row["spot_usable"]):
        return "SPOT_STALE_OR_MISSING"
    futures_above = float(row["futures_gap_to_reference"]) >= 0
    spot_above = float(row["spot_gap_to_reference"]) >= 0
    if futures_above and spot_above:
        return "BOTH_ABOVE_REFERENCE"
    if not futures_above and not spot_above:
        return "BOTH_BELOW_REFERENCE"
    if spot_above:
        return "SPOT_ABOVE_FUTURES_BELOW"
    return "FUTURES_ABOVE_SPOT_BELOW"


def _crossed_reference(start_gap: float, end_gap: float) -> bool:
    return (start_gap < 0 <= end_gap) or (start_gap > 0 >= end_gap)


def _cross_count(values: pd.Series) -> int:
    signs = values.dropna().map(lambda value: 1 if value > 0 else -1 if value < 0 else 0)
    signs = signs.loc[signs.ne(0)]
    if signs.empty:
        return 0
    return int(signs.ne(signs.shift()).sum() - 1)


def _wilson_interval(successes: int, count: int) -> tuple[float | None, float | None]:
    if count <= 0:
        return None, None
    z = 1.959963984540054
    proportion = successes / count
    denominator = 1.0 + z**2 / count
    centre = (proportion + z**2 / (2 * count)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1 - proportion) / count + z**2 / (4 * count**2))
        / denominator
    )
    return centre - margin, centre + margin


def _evidence_status(count: int) -> str:
    if count >= 100:
        return "DESCRIPTIVE_SUFFICIENT_SAMPLE"
    if count >= 30:
        return "WATCH"
    return "SMALL_SAMPLE"


def _warning_records(
    *,
    daily: pd.DataFrame,
    fundamental_summary: pd.DataFrame,
    context_path: Path,
    config: PolicyReferenceConfig,
) -> list[CottonYearPolicyWarningRecord]:
    warnings = [
        CottonYearPolicyWarningRecord(
            severity="WARN",
            warning_code="POLICY_EFFECTIVE_PERIOD_NOT_VERIFIED",
            message=(
                "18600元/吨按研究参考线使用；官方有效期、标准级和补贴结算口径尚未在本模块复核。"
            ),
            human_review_required=(
                "target_price_official_effective_period_and_quality_basis",
            ),
        ),
        CottonYearPolicyWarningRecord(
            severity="WARN",
            warning_code="POLICY_SUPPLY_EVENT_NOT_CONNECTED",
            message=(
                "轮入轮出、配额、补贴结算和新棉产量等政策供给事件尚未形成统一时点表，"
                "本版不计算政策供给得分。"
            ),
            human_review_required=(
                "policy_supply_event_volume_and_effective_date",
            ),
        ),
        CottonYearPolicyWarningRecord(
            severity="INFO",
            warning_code="REFERENCE_IS_NOT_PRICE_FLOOR",
            message=RESEARCH_BOUNDARY,
        ),
    ]
    if config.official_effective_period_verified:
        warnings = [
            row
            for row in warnings
            if row.warning_code != "POLICY_EFFECTIVE_PERIOD_NOT_VERIFIED"
        ]
    extension_rows = daily.loc[
        daily["spot_bridge_status"].eq("FORWARD_EXTENSION_AFTER_PRIMARY_END")
    ]
    if not extension_rows.empty:
        switch_date = pd.Timestamp(extension_rows["spot_observation_date"].min()).date()
        warnings.append(
            CottonYearPolicyWarningRecord(
                severity="WARN",
                warning_code="IFIND_SPOT_FORWARD_EXTENSION_ACTIVE",
                message=(
                    f"原CCIndex主序列结束后，自{switch_date}起使用iFinD 3128B现货向后接续；"
                    "重叠历史未覆盖，供应商口径与单位仍需人工复核。"
                ),
                human_review_required=(
                    "ccindex_3128b_policy_price_comparability",
                    "fundamental_source_unit_and_frequency",
                ),
            )
        )
    latest = daily.iloc[-1]
    if not bool(latest["spot_usable"]):
        warnings.append(
            CottonYearPolicyWarningRecord(
                severity="WARN",
                warning_code="LATEST_SPOT_PRICE_STALE",
                message=(
                    f"期货最新日为{pd.Timestamp(latest['trade_date']).date()}，"
                    f"最近现货观察为{pd.Timestamp(latest['spot_observation_date']).date()}，"
                    f"滞后{int(latest['spot_staleness_days'])}个自然日；不得作为最新现货判断。"
                ),
                human_review_required=("ccindex_3128b_policy_price_comparability",),
            )
        )
    if not context_path.exists() or fundamental_summary.empty:
        warnings.append(
            CottonYearPolicyWarningRecord(
                severity="WARN",
                warning_code="FUNDAMENTAL_CONTEXT_NOT_AVAILABLE",
                message="未发现可用基本面解释层，棉花年度供需观察汇总为空。",
                human_review_required=("fundamental_source_unit_and_frequency",),
            )
        )
    return warnings


def _report_statistics(
    *,
    daily: pd.DataFrame,
    validation: pd.DataFrame,
) -> dict[str, object]:
    usable_spot = daily.loc[daily["spot_usable"]]
    futures_same = validation.loc[validation["futures_same_contract"].eq(True)]  # noqa: E712
    spot_comparable = validation.loc[validation["spot_comparable"].eq(True)]  # noqa: E712
    return {
        "daily_row_count": len(daily),
        "futures_below_reference_rate": float(
            daily["futures_gap_to_reference"].lt(0).mean()
        ),
        "spot_usable_day_count": len(usable_spot),
        "spot_below_reference_rate": (
            float(usable_spot["spot_gap_to_reference"].lt(0).mean())
            if not usable_spot.empty
            else None
        ),
        "futures_same_contract_validation_count": len(futures_same),
        "spot_validation_count": len(spot_comparable),
    }


def _output_paths(
    *,
    start: date,
    end: date,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / "cotton_year_policy"
    report_root = report_output_dir or (
        reports_dir() / "research" / "cotton_year_policy"
    )
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return {
        "daily": root / f"{stem}_policy_reference_daily.parquet",
        "cotton_year_summary": root / f"{stem}_cotton_year_summary.parquet",
        "historical_validation": root
        / f"{stem}_policy_reference_historical_validation.parquet",
        "validation_summary": root / f"{stem}_policy_reference_validation_summary.parquet",
        "fundamental_summary": root / f"{stem}_cotton_year_fundamental_summary.parquet",
        "warnings": root / f"{stem}_cotton_year_policy_warnings.csv",
        "json": report_root / f"{stem}_cotton_year_policy_research.json",
        "manifest": root / f"{stem}_cotton_year_policy_manifest.json",
        "markdown": report_root / f"{stem}_cotton_year_policy_research.md",
    }


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def _write_warnings(result: ResearchCottonYearPolicyResult) -> None:
    result.warning_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with result.warning_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "run_id",
                "severity",
                "warning_code",
                "message",
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
                    "human_review_required": ";".join(row.human_review_required),
                }
            )


def _write_json(
    *,
    result: ResearchCottonYearPolicyResult,
    config: PolicyReferenceConfig,
    horizons: tuple[int, ...],
    report_statistics: dict[str, object],
    spot_bridge_statistics: dict[str, object],
) -> None:
    payload = {
        "report_type": "cotton_year_policy_reference_research",
        "rule_version": RULE_VERSION,
        "summary": result.to_summary(),
        "policy_reference_config": {
            "version": config.version,
            "target_price": config.target_price,
            "target_unit": config.target_unit,
            "source_status": config.source_status,
            "official_effective_period_verified": (
                config.official_effective_period_verified
            ),
            "source_note": config.source_note,
            "excluded_price_objects": list(config.excluded_price_objects),
        },
        "historical_validation_horizons": list(horizons),
        "historical_validation_uses_overlapping_daily_observations": True,
        "report_statistics": report_statistics,
        "spot_bridge_statistics": spot_bridge_statistics,
        "current_state_contains_forward_labels": False,
        "historical_validation_is_posterior_only": True,
        "fundamental_signal_status": "not_connected",
        "research_boundary": RESEARCH_BOUNDARY,
        "human_review_required": list(HUMAN_REVIEW_REQUIRED),
    }
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_markdown(
    *,
    result: ResearchCottonYearPolicyResult,
    config: PolicyReferenceConfig,
    daily: pd.DataFrame,
    cotton_year_summary: pd.DataFrame,
    validation_summary: pd.DataFrame,
    fundamental_summary: pd.DataFrame,
    report_statistics: dict[str, object],
    spot_bridge_statistics: dict[str, object],
) -> None:
    latest = daily.iloc[-1]
    lines = [
        "# CF R93G 棉花年度与政策参考线研究",
        "",
        "## 先说结论",
        "",
        "- `18,600元/吨`不能当作郑棉期货支撑位或公允价值；它在本报告中只是一条政策研究参考线。",
        "- 能与该参考线做价格偏离观察的是CCIndex 3128B现货和真实主力合约结算价，"
        "原CCIndex结束后可用iFinD 3128B现货向后接续；现货与期货仍存在地域、质量、"
        "交割月份和政策结算差异。",
        "- 加法调整连续价是信号对象，无换月跳空指数是收益指数；二者均不参与价格水平比较。",
        "- 历史收敛率只描述偏离后的路径，不证明政策线对市场价格存在因果吸引力。",
        "",
        "## 数据状态",
        "",
        f"- 期货区间：`{result.start}` 至 `{result.end}`",
        f"- 现货数据截至：`{result.spot_data_asof}`",
        f"- 最新现货来源：`{result.latest_spot_source_name}` / "
        f"`{result.latest_spot_source_indicator_id}`；来源切换保留在日表中。",
        f"- 棉花年度起点：每年 `{config.cotton_year_start_month:02d}-"
        f"{config.cotton_year_start_day:02d}`",
        f"- 政策参考线：`{config.target_price:,.0f}元/吨`，状态：`{config.source_status}`",
        "",
        "## 最新可观察状态",
        "",
        f"- 最新期货：`{result.end}` / `{result.latest_contract}` / "
        f"`{result.latest_futures_settle:,.0f}元/吨`。",
        f"- 相对参考线：`{result.latest_futures_gap:,.0f}元/吨` "
        f"(`{result.latest_futures_gap_pct:.2%}`)。",
        f"- 最近现货：`{result.latest_spot_observation_date}` / "
        f"`{result.latest_spot_price:,.0f}元/吨` / `{result.latest_spot_source_name}`，"
        "相对参考线 "
        f"`{result.latest_spot_price - result.target_price:,.0f}元/吨`。",
        f"- 现货相对期货最新日滞后：`{int(latest['spot_staleness_days'])}`个自然日，"
        f"可用状态：`{bool(latest['spot_usable'])}`。",
        "",
        "## 全历史偏离事实",
        "",
        f"- 真实映射期货低于参考线的交易日占比："
        f"`{_fmt_pct(report_statistics['futures_below_reference_rate'])}`。",
        f"- 可用3128B现货低于参考线的交易日占比："
        f"`{_fmt_pct(report_statistics['spot_below_reference_rate'])}`。",
        "- 参考线以下出现大量有效样本，本身已经否定“18,600等于市场硬底”的解释。",
        "",
        "## 分棉花年度观察",
        "",
        (
            "| 棉花年度 | 交易日 | 期货低于参考线 | 期货中位偏离 | "
            "现货可用日 | 现货低于参考线 | 基差代理中位数 |"
        ),
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for _, row in cotton_year_summary.iterrows():
        lines.append(
            f"| {row['cotton_year']} | {int(row['trading_day_count'])} | "
            f"{_fmt_pct(row['futures_below_reference_rate'])} | "
            f"{_fmt_money(row['futures_gap_median'])} | "
            f"{int(row['spot_usable_day_count'])} | "
            f"{_fmt_pct(row['spot_below_reference_rate'])} | "
            f"{_fmt_money(row['mapped_basis_proxy_median'])} |"
        )
    if bool(spot_bridge_statistics.get("active")):
        lines.extend(
            [
                "",
                "## 现货来源桥接验证",
                "",
                f"- 重叠区间：`{spot_bridge_statistics['overlap_start']}` 至 "
                f"`{spot_bridge_statistics['overlap_end']}`，"
                f"`{spot_bridge_statistics['overlap_count']}`个共同观察。",
                f"- 重叠相关系数："
                f"`{_fmt_number(spot_bridge_statistics['overlap_correlation'], 4)}`。",
                f"- iFinD减原CCIndex的中位价差："
                f"`{_fmt_money(spot_bridge_statistics['median_extension_minus_primary'])}`元/吨。",
                f"- 实际接续起点：`{spot_bridge_statistics['first_appended_date']}`；"
                "原主序列最后日期之前的数据一律不回填或覆盖。",
                "- 高相关性只支持序列接续的研究可用性，不证明供应商定义、采样时点和"
                "质量口径完全相同。",
            ]
        )
    lines.extend(
        [
            "",
            "## 历史收敛验证",
            "",
            "下表仅展示样本数不少于30的历史后验分组。收敛表示未来绝对偏离缩小，"
            "不等于可交易收益，也不代表政策因果。",
            "每日观察存在周期重叠，样本数不是独立事件数；Wilson区间只用于描述比例不确定性，"
            "不能替代独立事件或样本外检验。",
            "",
            "| 价格对象 | 周期 | 偏离区间 | 样本数 | 收敛率 | 95%区间 | 跨越参考线 |",
            "| --- | ---: | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    displayed = validation_summary.loc[validation_summary["sample_count"].ge(30)].copy()
    for _, row in displayed.iterrows():
        lines.append(
            f"| {row['price_object']} | {int(row['horizon_sessions'])}D | "
            f"{row['reference_bucket']} | {int(row['sample_count'])} | "
            f"{_fmt_pct(row['convergence_rate'])} | "
            f"{_fmt_pct(row['convergence_ci95_lower'])} - "
            f"{_fmt_pct(row['convergence_ci95_upper'])} | "
            f"{_fmt_pct(row['reference_cross_rate'])} |"
        )
    if displayed.empty:
        lines.append("| 无合格分组 | 无 | 无 | 0 | 不可用 | 不可用 | 不可用 |")
    lines.extend(
        [
            "",
            "## 政策供给与基本面边界",
            "",
            f"- 已按棉花年度整理 `{len(fundamental_summary)}` 条独立指标汇总，"
            "不跨指标混合单位。",
            "- 仓单、库存、进口和纺织链仍为人工复核观察，状态保持 `not_connected`。",
            "- 轮入轮出挂牌量、成交量、质量、提货速度、进口配额和补贴结算尚未统一成"
            "带生效时点的政策事件表，因此本版不构造政策供给评分。",
            "- 独立的 `reserve_cotton2026/` 项目没有被本模块读取或并入主仓库。",
            "",
            "## 警告与人审项",
            "",
        ]
    )
    lines.extend(
        f"- `{row.warning_code}`：{row.message}" for row in result.warning_records
    )
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            f"> {RESEARCH_BOUNDARY}",
            "",
            "当前状态表不包含forward label；未来路径只保存在独立历史后验表。",
        ]
    )
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_manifest(
    *,
    result: ResearchCottonYearPolicyResult,
    input_paths: tuple[Path, ...],
    spot_bridge_statistics: dict[str, object],
) -> None:
    existing_inputs = tuple(path for path in input_paths if path.exists())
    artifacts = (
        result.daily_path,
        result.cotton_year_summary_path,
        result.historical_validation_path,
        result.validation_summary_path,
        result.fundamental_summary_path,
        result.warning_csv_path,
        result.json_path,
        result.markdown_path,
    )
    payload = {
        "report_type": "cotton_year_policy_reference_research",
        "rule_version": RULE_VERSION,
        "generated_at": utc_now().isoformat(),
        "summary": result.to_summary(),
        "input_sha256": {str(path): _sha256(path) for path in existing_inputs},
        "artifact_sha256": {str(path): _sha256(path) for path in artifacts},
        "current_state_contains_forward_labels": False,
        "historical_validation_is_posterior_only": True,
        "historical_validation_uses_overlapping_daily_observations": True,
        "spot_bridge_statistics": spot_bridge_statistics,
        "fundamental_signal_status": "not_connected",
        "research_boundary": RESEARCH_BOUNDARY,
        "human_review_required": list(HUMAN_REVIEW_REQUIRED),
    }
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    result.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_required_parquet(path: Path, label: str) -> pd.DataFrame:
    if not path.exists() or not path.is_file():
        raise ResearchWorkbenchError(f"{label} parquet not found: {path}")
    frame = pd.read_parquet(path)
    if frame.empty:
        raise ResearchWorkbenchError(f"{label} parquet contains no rows: {path}")
    return frame


def _mean_or_none(values: pd.Series) -> float | None:
    cleaned = pd.to_numeric(values, errors="coerce").dropna()
    return float(cleaned.mean()) if not cleaned.empty else None


def _median_or_none(values: pd.Series) -> float | None:
    cleaned = pd.to_numeric(values, errors="coerce").dropna()
    return float(cleaned.median()) if not cleaned.empty else None


def _joined_values(values: pd.Series) -> str:
    return ";".join(sorted(set(values.dropna().astype(str))))


def _fmt_pct(value: object) -> str:
    if value is None or pd.isna(value):
        return "不可用"
    return f"{float(value):.2%}"


def _fmt_money(value: object) -> str:
    if value is None or pd.isna(value):
        return "不可用"
    return f"{float(value):,.0f}"


def _fmt_number(value: object, decimals: int) -> str:
    if value is None or pd.isna(value):
        return "不可用"
    return f"{float(value):.{decimals}f}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_run_id() -> str:
    return f"cf_r93g_cotton_year_policy_{uuid.uuid4().hex[:8]}"
