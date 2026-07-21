"""R75 option structure change and confirmation-strength research for CF."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

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
OPTION_STRUCTURE_RESEARCH_VERSION = "R75_option_structure_research_v1"
DEFAULT_PRIMARY_HORIZON = 20
HUMAN_REVIEW_REQUIRED = (
    "option_proxy_model_interpretation",
    "pcr_direction_threshold",
    "skew_proxy_definition",
    "option_expiry_and_liquidity_weighting",
    "historical_forward_label_interpretation",
)
RESEARCH_BOUNDARY = {
    "option_iv_greek_is_proxy": True,
    "forward_returns_are_validation_labels": True,
    "latest_state_uses_future_data": False,
    "enters_composite_score": False,
    "trading_instruction": "not_a_trading_instruction",
}


@dataclass(frozen=True)
class ResearchOptionStructureResult:
    """R75 artifact paths and latest option structure state."""

    run_id: str
    start: date
    end: date
    row_count: int
    latest_underlying_contract: str
    latest_option_direction: str
    latest_confirmation_state: str
    latest_confirmation_strength: str
    warning_count: int
    daily_parquet_path: Path
    daily_csv_path: Path
    validation_parquet_path: Path
    validation_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    option_factor_path: Path
    signal_matrix_path: Path
    validation_daily_path: Path | None
    human_review_required: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        return {
            "product_code": PRODUCT_CODE,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "row_count": self.row_count,
            "latest_underlying_contract": self.latest_underlying_contract,
            "latest_option_direction": self.latest_option_direction,
            "latest_confirmation_state": self.latest_confirmation_state,
            "latest_confirmation_strength": self.latest_confirmation_strength,
            "warning_count": self.warning_count,
            "daily_parquet_path": str(self.daily_parquet_path),
            "validation_parquet_path": str(self.validation_parquet_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "option_factor_path": str(self.option_factor_path),
            "signal_matrix_path": str(self.signal_matrix_path),
            "validation_daily_path": (
                None if self.validation_daily_path is None else str(self.validation_daily_path)
            ),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_option_structure_research(
    *,
    option_factor_path: Path | None = None,
    signal_matrix_path: Path | None = None,
    validation_daily_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    primary_horizon: int = DEFAULT_PRIMARY_HORIZON,
) -> ResearchOptionStructureResult:
    """Build dynamic PCR/skew/IV structure states and posterior validation."""
    if primary_horizon <= 0:
        raise ResearchWorkbenchError("primary_horizon must be positive")
    factor_path = option_factor_path or _default_option_factor_path()
    matrix_path = signal_matrix_path or _default_signal_matrix_path()
    validation_path = validation_daily_path or _optional_validation_path()
    factors = load_table(
        factor_path,
        required={
            "trade_date",
            "underlying_contract",
            "atm_iv_proxy",
            "atm_iv_rank",
            "pcr_volume",
            "pcr_oi",
            "skew_proxy",
            "factor_status",
        },
        label="R48 option factor",
    )
    matrix = load_table(
        matrix_path,
        required={"trade_date", "horizon", "main_contract", "direction"},
        label="R35 signal matrix",
    )
    daily = _daily_rows(factors=factors, matrix=matrix, primary_horizon=primary_horizon)
    if daily.empty:
        raise ResearchWorkbenchError("R75 option structure has no rows")
    start = daily["trade_date"].min()
    end = daily["trade_date"].max()
    active_run_id = run_id or utc_timestamp_id("r75", end)
    daily.insert(0, "run_id", active_run_id)
    validation = _validation_rows(
        daily=daily,
        validation_path=validation_path,
        run_id=active_run_id,
    )
    warnings = _warning_rows(daily=daily, run_id=active_run_id, validation=validation)
    paths = _paths(start=start, end=end, output_dir=output_dir, report_dir=report_output_dir)
    write_frame(daily, paths["daily_parquet"], paths["daily_csv"])
    write_frame(validation, paths["validation_parquet"], paths["validation_csv"])
    write_warning_csv(paths["warning_csv"], warnings)
    latest = daily.iloc[-1].to_dict()
    result = ResearchOptionStructureResult(
        run_id=active_run_id,
        start=start,
        end=end,
        row_count=len(daily),
        latest_underlying_contract=str(latest["underlying_contract"]),
        latest_option_direction=str(latest["option_direction"]),
        latest_confirmation_state=str(latest["confirmation_state"]),
        latest_confirmation_strength=str(latest["confirmation_strength"]),
        warning_count=sum(1 for row in warnings if row["severity"] != "INFO"),
        daily_parquet_path=paths["daily_parquet"],
        daily_csv_path=paths["daily_csv"],
        validation_parquet_path=paths["validation_parquet"],
        validation_csv_path=paths["validation_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
        option_factor_path=factor_path,
        signal_matrix_path=matrix_path,
        validation_daily_path=validation_path,
        human_review_required=HUMAN_REVIEW_REQUIRED,
    )
    _write_markdown(result=result, latest=latest, validation=validation)
    write_json(
        result.json_path,
        {
            "report_type": "option_structure_research",
            "rule_version": OPTION_STRUCTURE_RESEARCH_VERSION,
            "summary": result.to_summary(),
            "latest_state": latest,
            "validation_rows": validation.to_dict(orient="records"),
            "warnings": warnings,
            "research_boundary": RESEARCH_BOUNDARY,
        },
    )
    write_json(
        result.manifest_path,
        artifact_manifest(
            run_id=active_run_id,
            report_type="option_structure_research",
            rule_version=OPTION_STRUCTURE_RESEARCH_VERSION,
            data_asof=end,
            input_paths={
                "option_factor_path": factor_path,
                "signal_matrix_path": matrix_path,
                "validation_daily_path": validation_path,
            },
            output_paths={
                "daily_parquet_path": result.daily_parquet_path,
                "validation_parquet_path": result.validation_parquet_path,
                "markdown_path": result.markdown_path,
                "json_path": result.json_path,
                "warning_csv_path": result.warning_csv_path,
            },
            human_review_required=HUMAN_REVIEW_REQUIRED,
            research_boundary=RESEARCH_BOUNDARY,
        ),
    )
    return result


def _daily_rows(
    *, factors: pd.DataFrame, matrix: pd.DataFrame, primary_horizon: int
) -> pd.DataFrame:
    option = normalize_trade_date(factors)
    for column in ("atm_iv_proxy", "atm_iv_rank", "pcr_volume", "pcr_oi", "skew_proxy"):
        option[column] = pd.to_numeric(option[column], errors="coerce")
    option = option.sort_values(["underlying_contract", "trade_date"])
    for column in ("atm_iv_proxy", "atm_iv_rank", "pcr_volume", "pcr_oi", "skew_proxy"):
        option[f"{column}_change_1d"] = option.groupby("underlying_contract")[column].diff()
    matrix_working = normalize_trade_date(matrix)
    matrix_working["horizon"] = pd.to_numeric(matrix_working["horizon"], errors="coerce")
    primary = matrix_working.loc[matrix_working["horizon"].eq(primary_horizon)].copy()
    primary = primary[
        ["trade_date", "main_contract", "direction"]
    ].rename(columns={"direction": "futures_direction"})
    daily = option.merge(
        primary,
        left_on=["trade_date", "underlying_contract"],
        right_on=["trade_date", "main_contract"],
        how="inner",
    )
    scores: list[float] = []
    directions: list[str] = []
    strengths: list[str] = []
    confirmations: list[str] = []
    repricing_states: list[str] = []
    for row in daily.itertuples(index=False):
        score = _option_score(row)
        direction = "long" if score >= 0.20 else "short" if score <= -0.20 else "neutral"
        strength = "high" if abs(score) >= 0.65 else "medium" if abs(score) >= 0.35 else "low"
        if direction == "neutral" or row.futures_direction not in {"long", "short"}:
            confirmation = "NEUTRAL_OR_OPTION_ONLY"
        elif direction == row.futures_direction:
            confirmation = f"CONFIRM_{direction.upper()}"
        else:
            confirmation = f"DIVERGE_FUTURES_{str(row.futures_direction).upper()}"
        if not pd.isna(row.atm_iv_rank) and row.atm_iv_rank >= 0.80:
            repricing = "HIGH_VOL_RISK_REPRICING"
        elif not pd.isna(row.atm_iv_rank) and row.atm_iv_rank <= 0.10:
            repricing = "LOW_VOL_UNPRICED"
        elif not pd.isna(row.atm_iv_proxy_change_1d) and row.atm_iv_proxy_change_1d > 0.003:
            repricing = "VOLATILITY_EXPANDING"
        else:
            repricing = "NORMAL_OR_STABLE"
        scores.append(score)
        directions.append(direction)
        strengths.append(strength)
        confirmations.append(confirmation)
        repricing_states.append(repricing)
    daily["option_direction_score"] = scores
    daily["option_direction"] = directions
    daily["confirmation_strength"] = strengths
    daily["confirmation_state"] = confirmations
    daily["volatility_repricing_state"] = repricing_states
    daily["rule_version"] = OPTION_STRUCTURE_RESEARCH_VERSION
    daily["option_iv_greek_is_proxy"] = True
    daily["enters_composite_score"] = False
    daily["trading_instruction"] = "not_a_trading_instruction"
    columns = [
        "trade_date",
        "underlying_contract",
        "futures_direction",
        "option_direction",
        "option_direction_score",
        "confirmation_state",
        "confirmation_strength",
        "volatility_repricing_state",
        "atm_iv_proxy",
        "atm_iv_proxy_change_1d",
        "atm_iv_rank",
        "atm_iv_rank_change_1d",
        "pcr_volume",
        "pcr_volume_change_1d",
        "pcr_oi",
        "pcr_oi_change_1d",
        "skew_proxy",
        "skew_proxy_change_1d",
        "factor_status",
    ]
    optional_columns = [
        name
        for name in ("eligible_option_count", "option_liquidity_score")
        if name in daily.columns
    ]
    columns.extend(optional_columns)
    columns.extend(
        [
            "rule_version",
            "option_iv_greek_is_proxy",
            "enters_composite_score",
            "trading_instruction",
        ]
    )
    return daily[columns].sort_values("trade_date").reset_index(drop=True)


def _option_score(row: object) -> float:
    # 水平分数描述当前结构，变化分数描述当日边际变化；二者分开后再合成。
    level_values = [
        _clip_score((1.0 - getattr(row, "pcr_volume")) / 0.40),
        _clip_score((1.0 - getattr(row, "pcr_oi")) / 0.40),
        _clip_score(-getattr(row, "skew_proxy") / 0.003),
    ]
    change_values = [
        _clip_score(-getattr(row, "pcr_volume_change_1d") / 0.30),
        _clip_score(-getattr(row, "pcr_oi_change_1d") / 0.20),
        _clip_score(-getattr(row, "skew_proxy_change_1d") / 0.002),
    ]
    level = _mean_available(level_values)
    change = _mean_available(change_values)
    if level is None and change is None:
        return 0.0
    if change is None:
        return float(level)
    if level is None:
        return float(change)
    return float(0.75 * level + 0.25 * change)


def _clip_score(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return max(-1.0, min(1.0, float(value)))


def _mean_available(values: list[float | None]) -> float | None:
    available = [value for value in values if value is not None]
    return None if not available else sum(available) / len(available)


def _validation_rows(
    *, daily: pd.DataFrame, validation_path: Path | None, run_id: str
) -> pd.DataFrame:
    columns = [
        "run_id",
        "confirmation_state",
        "confirmation_strength",
        "horizon",
        "sample_count",
        "directional_hit_rate",
        "mean_forward_return",
        "median_forward_return",
        "forward_returns_are_validation_labels",
        "trading_instruction",
    ]
    if validation_path is None:
        return pd.DataFrame(columns=columns)
    validation = load_table(
        validation_path,
        required={
            "trade_date",
            "horizon",
            "main_contract",
            "forward_return",
            "forward_label_available",
            "directional_hit",
        },
        label="R36 validation daily",
    )
    validation = normalize_trade_date(validation)
    joined = validation.merge(
        daily[
            [
                "trade_date",
                "underlying_contract",
                "confirmation_state",
                "confirmation_strength",
            ]
        ],
        left_on=["trade_date", "main_contract"],
        right_on=["trade_date", "underlying_contract"],
        how="inner",
    )
    joined = joined.loc[joined["forward_label_available"].fillna(False).astype(bool)].copy()
    joined["forward_return"] = pd.to_numeric(joined["forward_return"], errors="coerce")
    joined["directional_hit"] = pd.to_numeric(joined["directional_hit"], errors="coerce")
    rows: list[dict[str, object]] = []
    for keys, group in joined.groupby(
        ["confirmation_state", "confirmation_strength", "horizon"], dropna=False
    ):
        state, strength, horizon = keys
        rows.append(
            {
                "run_id": run_id,
                "confirmation_state": state,
                "confirmation_strength": strength,
                "horizon": int(horizon),
                "sample_count": len(group),
                "directional_hit_rate": group["directional_hit"].mean(),
                "mean_forward_return": group["forward_return"].mean(),
                "median_forward_return": group["forward_return"].median(),
                "forward_returns_are_validation_labels": True,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _warning_rows(
    *, daily: pd.DataFrame, run_id: str, validation: pd.DataFrame
) -> list[dict[str, object]]:
    low_vol = daily["volatility_repricing_state"].eq("LOW_VOL_UNPRICED")
    return [
        {
            "run_id": run_id,
            "section": "research_boundary",
            "severity": "INFO",
            "warning_code": "R75_OPTION_PROXY_RESEARCH_ONLY",
            "warning_message": "期权 IV、skew、PCR 为研究 proxy，不进入 composite_score。",
            "affected_count": len(daily),
            "human_review_required": "option_proxy_model_interpretation",
        },
        {
            "run_id": run_id,
            "section": "volatility_pricing",
            "severity": "WARN" if low_vol.any() else "INFO",
            "warning_code": "LOW_VOL_UNPRICED_STRUCTURE",
            "warning_message": "部分期权结构处于低隐波，方向确认不等同于突破定价。",
            "affected_count": int(low_vol.sum()),
            "human_review_required": "option_proxy_model_interpretation",
        },
        {
            "run_id": run_id,
            "section": "historical_validation",
            "severity": "WARN" if validation.empty else "INFO",
            "warning_code": "OPTION_STRUCTURE_VALIDATION_STATUS",
            "warning_message": "历史 forward return 只用于后验验证；空表表示未接入验证窗口。",
            "affected_count": 0 if validation.empty else len(validation),
            "human_review_required": "historical_forward_label_interpretation",
        },
    ]


def _default_option_factor_path() -> Path:
    return latest_matching_path(
        data_dir() / "research" / PRODUCT_CODE / "option_factors",
        "CF_*_option_factor_proxy_daily.parquet",
        label="R48 option factor",
    )


def _default_signal_matrix_path() -> Path:
    return latest_matching_path(
        data_dir() / "research" / PRODUCT_CODE / "signal_matrix",
        "CF_*_signal_matrix_daily.parquet",
        label="R35 signal matrix",
    )


def _optional_validation_path() -> Path | None:
    directory = data_dir() / "research" / PRODUCT_CODE / "signal_matrix_validation"
    candidates = list(directory.glob("CF_*_signal_matrix_validation_daily.parquet"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _paths(
    *, start: date, end: date, output_dir: Path | None, report_dir: Path | None
) -> dict[str, Path]:
    stem = f"CF_{start.isoformat()}_{end.isoformat()}_option_structure"
    data_root = output_dir or data_dir() / "research" / PRODUCT_CODE / "option_structure"
    report_root = report_dir or reports_dir() / "research" / "option_structure"
    return {
        "daily_parquet": data_root / f"{stem}_daily.parquet",
        "daily_csv": data_root / f"{stem}_daily.csv",
        "validation_parquet": data_root / f"{stem}_validation.parquet",
        "validation_csv": data_root / f"{stem}_validation.csv",
        "warning_csv": data_root / f"{stem}_warnings.csv",
        "manifest": data_root / f"{stem}_manifest.json",
        "markdown": report_root / f"{stem}.md",
        "json": report_root / f"{stem}.json",
    }


def _write_markdown(
    *, result: ResearchOptionStructureResult, latest: dict[str, object], validation: pd.DataFrame
) -> None:
    lines = [
        f"# CF 期权结构变化与确认强度 R75 - {result.end.isoformat()}",
        "",
        "## 最新结构",
        "",
        f"- 标的合约：`{latest['underlying_contract']}`",
        f"- 期货方向：`{latest['futures_direction']}`",
        f"- 期权方向：`{latest['option_direction']}`，连续分数 "
        f"`{fmt_number(latest['option_direction_score'], 4)}`",
        f"- 确认状态：`{latest['confirmation_state']}` / "
        f"`{latest['confirmation_strength']}`",
        f"- 波动定价：`{latest['volatility_repricing_state']}`",
        f"- PCR 成交 / 持仓：`{fmt_number(latest['pcr_volume'], 4)}` / "
        f"`{fmt_number(latest['pcr_oi'], 4)}`",
        f"- ATM IV rank：`{fmt_percent(latest['atm_iv_rank'])}`",
        f"- skew proxy：`{fmt_number(latest['skew_proxy'], 6)}`",
        "",
        "## 历史后验验证",
        "",
        "| 确认状态 | 强度 | 周期 | 样本 | 命中率 | 平均收益 |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    if validation.empty:
        lines.append("| 未接入验证窗口 | - | - | 0 | - | - |")
    else:
        sorted_rows = validation.sort_values(
            ["horizon", "sample_count"], ascending=[True, False]
        ).to_dict(orient="records")
        for row in sorted_rows[:30]:
            lines.append(
                f"| {row['confirmation_state']} | {row['confirmation_strength']} | "
                f"{row['horizon']}D | {row['sample_count']} | "
                f"{fmt_percent(row['directional_hit_rate'])} | "
                f"{fmt_percent(row['mean_forward_return'])} |"
            )
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "- PCR 水平、日变化、skew 和 IV 共同形成连续方向分数。",
            "- 低 IV 下的偏多确认不等于市场已为向上突破定价。",
            "- 美式期权 IV/Greek 尚为研究 proxy，不进入 `composite_score`。",
            "- forward return 仅为历史后验验证标签，不构成交易指令。",
            "",
        ]
    )
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text("\n".join(lines), encoding="utf-8")
