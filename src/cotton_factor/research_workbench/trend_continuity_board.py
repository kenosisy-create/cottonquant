"""R29 latest CF trend continuity observation board."""

from __future__ import annotations

import csv
import json
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, project_root
from cotton_factor.common.time import utc_now
from cotton_factor.research_workbench import latest_signal_brief as r23
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME

PRODUCT_CODE = "CF"
UNIVERSE = "CF_MAIN"
SIGNAL_OBJECT_ID = "CF.C1"
TREND_CONTINUITY_RULE_VERSION = "R29_trend_continuity_board_v2_r31_quality"
TREND_QUALITY_RULE_VERSION = "R31_trend_quality_score_v1"
TREND_QUALITY_CALIBRATION_CONTEXT_VERSION = "R33_trend_quality_calibration_context_v1"
DEFAULT_LOOKBACK_TRADING_DAYS = 20
WARNING_SEVERITY = "WARN"
INFO_SEVERITY = "INFO"
HUMAN_REVIEW_REQUIRED = (
    "trend_phase_rules",
    "factor_thresholds",
    "trend_continuity_wording",
    "trend_quality_scoring",
    "trend_quality_calibration",
    "main_contract_roll_reason",
    "contract_rule_assumptions",
)

WARNING_COLUMNS = [
    "run_id",
    "trade_date",
    "section",
    "severity",
    "warning_code",
    "warning_message",
    "affected_count",
    "human_review_required",
]


@dataclass(frozen=True)
class TrendContinuityWarningRecord:
    """Warning row for the R29 trend continuity board."""

    run_id: str
    trade_date: date
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
            "trade_date": self.trade_date.isoformat(),
            "section": self.section,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "affected_count": str(self.affected_count),
            "human_review_required": ";".join(self.human_review_required),
        }


@dataclass(frozen=True)
class ResearchTrendContinuityBoardResult:
    """Result of building the R29 latest trend continuity board."""

    product_code: str
    run_id: str
    trade_date: date
    lookback_trading_days: int
    row_count: int
    latest_main_contract: str
    latest_phase_code: str
    latest_phase_label: str
    latest_transition_code: str | None
    latest_observation_marker: str
    latest_trend_quality_score: int
    latest_trend_quality_label: str
    warning_records: tuple[TrendContinuityWarningRecord, ...]
    board_csv_path: Path
    markdown_path: Path
    json_path: Path
    warning_csv_path: Path
    manifest_path: Path
    core_quote_path: Path
    trend_rule_candidate_path: Path | None
    trend_quality_calibration_manifest_path: Path | None
    trend_quality_calibration_context: dict[str, object]
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
            "trade_date": self.trade_date.isoformat(),
            "lookback_trading_days": self.lookback_trading_days,
            "row_count": self.row_count,
            "latest_main_contract": self.latest_main_contract,
            "latest_phase_code": self.latest_phase_code,
            "latest_phase_label": self.latest_phase_label,
            "latest_transition_code": self.latest_transition_code,
            "latest_observation_marker": self.latest_observation_marker,
            "latest_trend_quality_score": self.latest_trend_quality_score,
            "latest_trend_quality_label": self.latest_trend_quality_label,
            "warning_count": self.warning_count,
            "board_csv_path": str(self.board_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "warning_csv_path": str(self.warning_csv_path),
            "manifest_path": str(self.manifest_path),
            "core_quote_path": str(self.core_quote_path),
            "trend_rule_candidate_path": (
                None
                if self.trend_rule_candidate_path is None
                else str(self.trend_rule_candidate_path)
            ),
            "trend_quality_calibration_manifest_path": (
                None
                if self.trend_quality_calibration_manifest_path is None
                else str(self.trend_quality_calibration_manifest_path)
            ),
            "trend_quality_calibration_context": self.trend_quality_calibration_context,
            "human_review_required": list(self.human_review_required),
        }


def build_cf_trend_continuity_board(
    *,
    trade_date: date | None = None,
    core_quote_path: Path | None = None,
    output_root: Path | None = None,
    run_id: str | None = None,
    lookback_trading_days: int = DEFAULT_LOOKBACK_TRADING_DAYS,
    trend_rule_candidate_path: Path | None = None,
    trend_quality_calibration_manifest_path: Path | None = None,
) -> ResearchTrendContinuityBoardResult:
    """Build an R29 latest trend continuity board without future-return labels."""
    if lookback_trading_days <= 0:
        raise ResearchWorkbenchError("lookback_trading_days must be positive")
    quote_path = core_quote_path or data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    quotes = r23._load_core_quotes(input_path=quote_path)
    active_date = r23._resolve_trade_date(quotes=quotes, trade_date=trade_date)
    available_dates = sorted(value for value in set(quotes["trade_date"]) if value <= active_date)
    if not available_dates:
        raise ResearchWorkbenchError(f"no {PRODUCT_CODE} core rows up to {active_date.isoformat()}")
    board_dates = available_dates[-lookback_trading_days:]
    board_run_id = run_id or _default_run_id(active_date)
    # R29 只读取 R27 聚合候选表用于解释阶段切换，不读取 forward_return_* 明细。
    candidates = (
        None
        if trend_rule_candidate_path is None
        else r23._load_trend_rule_candidates(input_path=trend_rule_candidate_path)
    )
    rows = _board_rows(
        quotes=quotes,
        trade_dates=board_dates,
        run_id=board_run_id,
        candidates=candidates,
    )
    if not rows:
        raise ResearchWorkbenchError("trend continuity board has no rows")
    warnings = _warning_records(
        run_id=board_run_id,
        trade_date=active_date,
        rows=rows,
        requested_lookback=lookback_trading_days,
        available_lookback=len(board_dates),
        trend_rule_candidate_path=trend_rule_candidate_path,
        trend_quality_calibration_manifest_path=trend_quality_calibration_manifest_path,
    )
    paths = _output_paths(trade_date=active_date, output_root=output_root)
    latest = rows[-1]
    calibration_context = _trend_quality_calibration_context(
        latest=latest,
        active_date=active_date,
        manifest_path=trend_quality_calibration_manifest_path,
    )
    warnings = warnings + _trend_quality_calibration_warnings(
        run_id=board_run_id,
        trade_date=active_date,
        context=calibration_context,
    )
    result = ResearchTrendContinuityBoardResult(
        product_code=PRODUCT_CODE,
        run_id=board_run_id,
        trade_date=active_date,
        lookback_trading_days=lookback_trading_days,
        row_count=len(rows),
        latest_main_contract=str(latest["main_contract"]),
        latest_phase_code=str(latest["trend_phase_code"]),
        latest_phase_label=str(latest["trend_phase_label"]),
        latest_transition_code=_string_or_none(latest["transition_code"]),
        latest_observation_marker=str(latest["observation_marker"]),
        latest_trend_quality_score=int(latest["trend_quality_score"]),
        latest_trend_quality_label=str(latest["trend_quality_label"]),
        warning_records=warnings,
        board_csv_path=paths["board_csv"],
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        warning_csv_path=paths["warning_csv"],
        manifest_path=paths["manifest"],
        core_quote_path=quote_path,
        trend_rule_candidate_path=trend_rule_candidate_path,
        trend_quality_calibration_manifest_path=trend_quality_calibration_manifest_path,
        trend_quality_calibration_context=calibration_context,
        human_review_required=_human_review_required(warnings),
    )
    _write_board_csv(rows=rows, csv_path=result.board_csv_path)
    _write_markdown(result=result, rows=rows)
    _write_json(result=result, rows=rows)
    _write_warning_csv(warnings=warnings, csv_path=result.warning_csv_path)
    _write_manifest(result=result)
    return result


def _board_rows(
    *,
    quotes: pd.DataFrame,
    trade_dates: list[date],
    run_id: str,
    candidates: pd.DataFrame | None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    previous_phase_code: str | None = None
    phase_run_length = 0
    for trade_date in trade_dates:
        row = _single_day_row(quotes=quotes, trade_date=trade_date, run_id=run_id)
        current_phase_code = str(row["trend_phase_code"])
        if previous_phase_code is None:
            transition_code = None
            phase_run_length = 1
        elif previous_phase_code == current_phase_code:
            transition_code = None
            phase_run_length += 1
        else:
            transition_code = f"{previous_phase_code}_TO_{current_phase_code}"
            phase_run_length = 1
        row["previous_phase_code"] = previous_phase_code
        row["transition_code"] = transition_code
        row["phase_run_length"] = phase_run_length
        row["observation_marker"] = _observation_marker(
            current_phase_code=current_phase_code,
            transition_code=transition_code,
        )
        row.update(_candidate_context(candidates=candidates, transition_code=transition_code))
        rows.append(row)
        previous_phase_code = current_phase_code
    _apply_trend_quality(rows=rows)
    return rows


def _apply_trend_quality(*, rows: list[dict[str, object]]) -> None:
    # R31 逐行评分只使用截至当日已经出现的观察行，避免用窗口后段信息反推历史质量。
    for index, row in enumerate(rows):
        quality = _trend_quality(row=row, history=rows[: index + 1])
        row.update(quality)


def _trend_quality(
    *,
    row: dict[str, object],
    history: list[dict[str, object]],
) -> dict[str, object]:
    score = 50
    reasons: list[str] = []
    phase_code = str(row["trend_phase_code"])
    phase_direction = str(row["trend_phase_direction"])
    multi_direction = str(row["multi_factor_direction"])
    phase_run_length = int(row["phase_run_length"])

    phase_delta = {
        "S0": -15,
        "S1": 10,
        "S2": 20,
        "S3": -8,
        "S4": -20,
    }.get(phase_code, -10)
    score += phase_delta
    reasons.append(f"阶段 {phase_code} 调整 {phase_delta:+d}")

    run_delta = _phase_run_delta(phase_code=phase_code, phase_run_length=phase_run_length)
    score += run_delta
    reasons.append(f"阶段持续 {phase_run_length} 日调整 {run_delta:+d}")

    direction_delta = _direction_alignment_delta(
        phase_direction=phase_direction,
        multi_direction=multi_direction,
    )
    score += direction_delta
    reasons.append(f"阶段方向与多因子方向调整 {direction_delta:+d}")

    oi_delta = _oi_quality_delta(
        phase_direction=phase_direction,
        oi_pressure=_float_or_none(row["main_oi_pressure"]),
    )
    score += oi_delta
    reasons.append(f"持仓压力调整 {oi_delta:+d}")

    structure_delta = _structure_quality_delta(
        multi_direction=multi_direction,
        carry_annualized=_float_or_none(row["carry_annualized"]),
        curve_slope=_float_or_none(row["curve_slope"]),
    )
    score += structure_delta
    reasons.append(f"期限结构调整 {structure_delta:+d}")

    oscillation_count = _recent_oscillation_count(history=history)
    oscillation_delta = _oscillation_delta(oscillation_count=oscillation_count)
    score += oscillation_delta
    reasons.append(f"近窗 S0/S3 往返 {oscillation_count} 次调整 {oscillation_delta:+d}")

    candidate_delta = _candidate_quality_delta(row.get("candidate_status"))
    score += candidate_delta
    reasons.append(f"R27 候选状态调整 {candidate_delta:+d}")

    bounded_score = max(0, min(100, score))
    return {
        "trend_quality_score": bounded_score,
        "trend_quality_label": _trend_quality_label(bounded_score),
        "trend_quality_reason": "；".join(reasons),
        "trend_quality_rule_version": TREND_QUALITY_RULE_VERSION,
    }


def _phase_run_delta(*, phase_code: str, phase_run_length: int) -> int:
    if phase_code in {"S1", "S2"}:
        return min(phase_run_length * 3, 15)
    if phase_code == "S3":
        return -min(max(phase_run_length - 1, 0) * 3, 12)
    if phase_code == "S0":
        return -min(phase_run_length, 8)
    if phase_code == "S4":
        return -min(phase_run_length * 4, 16)
    return 0


def _direction_alignment_delta(*, phase_direction: str, multi_direction: str) -> int:
    if phase_direction in {"long", "short"} and multi_direction == phase_direction:
        return 10
    if phase_direction in {"long", "short"} and multi_direction in {"long", "short"}:
        return -10
    if multi_direction == "neutral":
        return -3
    return 0


def _oi_quality_delta(*, phase_direction: str, oi_pressure: float | None) -> int:
    if oi_pressure is None:
        return 0
    if phase_direction == "long":
        return 8 if oi_pressure > 0 else -8 if oi_pressure < 0 else 0
    if phase_direction == "short":
        return 4 if oi_pressure > 0 else -4 if oi_pressure < 0 else 0
    return 0


def _structure_quality_delta(
    *,
    multi_direction: str,
    carry_annualized: float | None,
    curve_slope: float | None,
) -> int:
    if carry_annualized is None or curve_slope is None:
        return 0
    if carry_annualized > 0 and curve_slope > 0 and multi_direction == "long":
        return 6
    if carry_annualized < 0 and curve_slope < 0 and multi_direction == "short":
        return 6
    if carry_annualized * curve_slope < 0:
        return -4
    return 0


def _recent_oscillation_count(*, history: list[dict[str, object]]) -> int:
    recent = history[-10:]
    return sum(
        1
        for row in recent
        if row.get("transition_code") in {"S0_TO_S3", "S3_TO_S0"}
    )


def _oscillation_delta(*, oscillation_count: int) -> int:
    if oscillation_count >= 4:
        return -18
    if oscillation_count >= 2:
        return -10
    if oscillation_count == 1:
        return -4
    return 0


def _candidate_quality_delta(candidate_status: object) -> int:
    if candidate_status == "READY_CANDIDATE":
        return 8
    if candidate_status == "WATCH_CANDIDATE":
        return -3
    if candidate_status in {"INSUFFICIENT_SAMPLE", "NO_SAMPLE", "NOT_FOUND"}:
        return -5
    return 0


def _trend_quality_label(score: int) -> str:
    if score >= 75:
        return "强趋势质量"
    if score >= 60:
        return "趋势质量改善"
    if score >= 45:
        return "震荡观察"
    if score >= 30:
        return "趋势质量偏弱"
    return "趋势解释失效风险"


def _single_day_row(*, quotes: pd.DataFrame, trade_date: date, run_id: str) -> dict[str, object]:
    # 每一行都按当日可见核心表重新识别主力和因子，避免用最新主力回填历史。
    visible_quotes = quotes.loc[quotes["trade_date"] <= trade_date].copy()
    latest_quotes = visible_quotes.loc[visible_quotes["trade_date"] == trade_date].copy()
    activity_rows = r23._activity_rows(visible_quotes=visible_quotes, active_date=trade_date)
    main_contract = str(activity_rows[0]["contract_code"])
    main_history = r23._main_contract_history(
        visible_quotes=visible_quotes,
        contract_code=main_contract,
        active_date=trade_date,
    )
    main_metrics = r23._main_metrics(main_history=main_history)
    term_structure = r23._term_structure(latest_quotes=latest_quotes, main_contract=main_contract)
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
    snapshot_ids = r23._unique_values(latest_quotes["source_snapshot_id"].dropna().astype(str))
    return {
        "run_id": run_id,
        "product_code": PRODUCT_CODE,
        "universe": UNIVERSE,
        "signal_object_id": SIGNAL_OBJECT_ID,
        "trade_date": trade_date.isoformat(),
        "main_contract": main_contract,
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
        "source_snapshot_ids": ";".join(snapshot_ids),
        "continuity_rule_version": TREND_CONTINUITY_RULE_VERSION,
    }


def _candidate_context(
    *,
    candidates: pd.DataFrame | None,
    transition_code: str | None,
) -> dict[str, object]:
    if transition_code is None:
        return {
            "candidate_status": None,
            "daily_brief_action": None,
            "candidate_rule_text_cn": None,
            "candidate_caveat_cn": None,
        }
    if candidates is None:
        return {
            "candidate_status": "NOT_PROVIDED",
            "daily_brief_action": "NO_R27_CONTEXT",
            "candidate_rule_text_cn": None,
            "candidate_caveat_cn": None,
        }
    matched = candidates.loc[candidates["transition_code"].astype(str) == transition_code]
    if matched.empty:
        return {
            "candidate_status": "NOT_FOUND",
            "daily_brief_action": "WATCH_ONLY",
            "candidate_rule_text_cn": None,
            "candidate_caveat_cn": None,
        }
    row = matched.iloc[0]
    return {
        "candidate_status": str(row["candidate_status"]),
        "daily_brief_action": str(row["daily_brief_action"]),
        "candidate_rule_text_cn": _none_if_missing(row["rule_text_cn"]),
        "candidate_caveat_cn": _none_if_missing(row["caveat_cn"]),
    }


def _observation_marker(*, current_phase_code: str, transition_code: str | None) -> str:
    if transition_code in {"S0_TO_S1", "S1_TO_S2"}:
        return "趋势起点观察"
    if transition_code == "S0_TO_S3":
        return "震荡衰竭观察"
    if transition_code in {"S2_TO_S3"}:
        return "衰竭观察"
    if transition_code == "S3_TO_S0":
        return "衰竭降级未确认"
    if transition_code in {"S3_TO_S4", "S4_TO_S0"} or current_phase_code == "S4":
        return "终点/反向风险"
    if current_phase_code == "S1":
        return "起点观察"
    if current_phase_code == "S2":
        return "趋势延续"
    if current_phase_code == "S3":
        return "衰竭观察"
    return "未确认"


def _warning_records(
    *,
    run_id: str,
    trade_date: date,
    rows: list[dict[str, object]],
    requested_lookback: int,
    available_lookback: int,
    trend_rule_candidate_path: Path | None,
    trend_quality_calibration_manifest_path: Path | None,
) -> tuple[TrendContinuityWarningRecord, ...]:
    records = [
        _warning(
            run_id=run_id,
            trade_date=trade_date,
            section="research_boundary",
            severity=INFO_SEVERITY,
            warning_code="R29_NO_FORWARD_RETURN_LABELS",
            warning_message="R29 趋势连续性观察板未包含未来收益标签，未完成 forward-return 验证。",
            affected_count=len(rows),
            human_review_required=(),
        )
    ]
    if available_lookback < requested_lookback:
        records.append(
            _warning(
                run_id=run_id,
                trade_date=trade_date,
                section="data_status",
                severity=WARNING_SEVERITY,
                warning_code="R29_LOOKBACK_INCOMPLETE",
                warning_message="可用交易日少于请求的趋势连续性窗口。",
                affected_count=requested_lookback - available_lookback,
                human_review_required=("trend_continuity_wording",),
            )
        )
    if trend_rule_candidate_path is not None:
        records.append(
            _warning(
                run_id=run_id,
                trade_date=trade_date,
                section="trend_rule_context",
                severity=INFO_SEVERITY,
                warning_code="R29_R27_CANDIDATE_CONTEXT_ONLY",
                warning_message="R27 候选规则只作为阶段切换解释，不构成交易规则或交易指令。",
                affected_count=len(rows),
                human_review_required=("trend_rule_candidate_thresholds",),
            )
        )
    records.append(
        _warning(
            run_id=run_id,
            trade_date=trade_date,
            section="trend_quality",
            severity=INFO_SEVERITY,
            warning_code="R31_TREND_QUALITY_IS_HEURISTIC",
            warning_message="R31 趋势质量评分是研究解释启发式，不构成交易规则或交易指令。",
            affected_count=len(rows),
            human_review_required=("trend_quality_scoring",),
        )
    )
    if trend_quality_calibration_manifest_path is not None:
        records.append(
            _warning(
                run_id=run_id,
                trade_date=trade_date,
                section="trend_quality_calibration",
                severity=INFO_SEVERITY,
                warning_code="R33_TREND_QUALITY_CALIBRATION_AGGREGATED_ONLY",
                warning_message=(
                    "R33 只读取 R32 manifest 与分数段聚合校准表，"
                    "不读取逐日 forward-return 标签。"
                ),
                affected_count=len(rows),
                human_review_required=("trend_quality_calibration",),
            )
        )
    return tuple(records)


def _trend_quality_calibration_context(
    *,
    latest: dict[str, object],
    active_date: date,
    manifest_path: Path | None,
) -> dict[str, object]:
    if manifest_path is None:
        return {
            "context_status": "NOT_PROVIDED",
            "context_version": TREND_QUALITY_CALIBRATION_CONTEXT_VERSION,
            "interpretation_cn": "未接入 R32 趋势质量历史校准，本观察板仅展示 R31 当日启发式评分。",
            "research_boundary": "未读取 R32 校准产物，也未读取 forward-return 标签。",
        }
    if not manifest_path.exists():
        raise ResearchWorkbenchError(
            f"trend quality calibration manifest not found: {manifest_path}"
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("report_type") != "trend_quality_calibration":
        raise ResearchWorkbenchError(
            f"unsupported trend quality calibration manifest: {manifest_path}"
        )
    if manifest.get("forward_returns_are_validation_labels") is not True:
        raise ResearchWorkbenchError(
            "trend quality calibration manifest must mark forward returns as validation labels"
        )
    bucket_summary_path = Path(str(manifest.get("bucket_summary_parquet_path", "")))
    if not bucket_summary_path.exists():
        raise ResearchWorkbenchError(
            f"trend quality calibration bucket summary not found: {bucket_summary_path}"
        )
    bucket_summary = _load_calibration_bucket_summary(
        input_path=bucket_summary_path,
        score_bucket=str(manifest.get("latest_score_bucket")),
    )
    latest_score = int(latest["trend_quality_score"])
    manifest_score = _int_or_none(manifest.get("latest_trend_quality_score"))
    alignment_status = _calibration_alignment_status(
        active_date=active_date,
        latest=latest,
        manifest=manifest,
        latest_score=latest_score,
        manifest_score=manifest_score,
    )
    context = {
        "context_status": "PROVIDED",
        "context_version": TREND_QUALITY_CALIBRATION_CONTEXT_VERSION,
        "manifest_path": str(manifest_path),
        "bucket_summary_path": str(bucket_summary_path),
        "alignment_status": alignment_status,
        "calibration_start": manifest.get("start"),
        "calibration_end": manifest.get("end"),
        "calibration_daily_row_count": manifest.get("daily_row_count"),
        "latest_trade_date": manifest.get("latest_trade_date"),
        "latest_main_contract": manifest.get("latest_main_contract"),
        "latest_trend_quality_score": manifest_score,
        "latest_trend_quality_label": manifest.get("latest_trend_quality_label"),
        "latest_score_bucket": manifest.get("latest_score_bucket"),
        "latest_score_bucket_label": manifest.get("latest_score_bucket_label"),
        "latest_score_percentile": manifest.get("latest_score_percentile"),
        "latest_score_context_label": manifest.get("latest_score_context_label"),
        "current_board_trend_quality_score": latest_score,
        "current_board_trend_quality_label": latest.get("trend_quality_label"),
        "bucket_summary_rows": bucket_summary,
        "interpretation_cn": _calibration_interpretation(
            manifest=manifest,
            bucket_summary=bucket_summary,
            alignment_status=alignment_status,
        ),
        "research_boundary": (
            "R33 只读取 R32 manifest 和分数段聚合校准表；"
            "不读取逐日 forward-return 标签，不构成交易指令。"
        ),
    }
    return context


def _load_calibration_bucket_summary(
    *,
    input_path: Path,
    score_bucket: str,
) -> list[dict[str, object]]:
    frame = pd.read_parquet(input_path)
    required = {
        "score_bucket",
        "score_bucket_label",
        "horizon",
        "signal_day_count",
        "observation_count",
        "mean_forward_return",
        "directional_hit_rate",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"calibration bucket summary missing columns: {missing}")
    selected = frame.loc[frame["score_bucket"].astype(str) == score_bucket].copy()
    if selected.empty:
        selected = frame.copy()
    selected = selected.sort_values(["score_bucket", "horizon"])
    rows: list[dict[str, object]] = []
    for row in selected.to_dict(orient="records"):
        rows.append(
            {
                "score_bucket": str(row["score_bucket"]),
                "score_bucket_label": str(row["score_bucket_label"]),
                "horizon": _int_or_none(row["horizon"]),
                "signal_day_count": _int_or_none(row["signal_day_count"]),
                "observation_count": _int_or_none(row["observation_count"]),
                "mean_forward_return": _float_or_none(row["mean_forward_return"]),
                "directional_hit_rate": _float_or_none(row["directional_hit_rate"]),
            }
        )
    return rows


def _calibration_alignment_status(
    *,
    active_date: date,
    latest: dict[str, object],
    manifest: dict[str, object],
    latest_score: int,
    manifest_score: int | None,
) -> str:
    if manifest.get("latest_trade_date") != active_date.isoformat():
        return "STALE_DATE"
    if manifest.get("latest_main_contract") != latest.get("main_contract"):
        return "MAIN_CONTRACT_MISMATCH"
    if manifest_score != latest_score:
        return "SCORE_MISMATCH"
    return "MATCHED"


def _calibration_interpretation(
    *,
    manifest: dict[str, object],
    bucket_summary: list[dict[str, object]],
    alignment_status: str,
) -> str:
    score = manifest.get("latest_trend_quality_score")
    label = manifest.get("latest_trend_quality_label")
    bucket_label = manifest.get("latest_score_bucket_label")
    context_label = manifest.get("latest_score_context_label")
    percentile = _fmt_percent(manifest.get("latest_score_percentile"))
    h5 = _bucket_horizon(bucket_summary=bucket_summary, horizon=5)
    h10 = _bucket_horizon(bucket_summary=bucket_summary, horizon=10)
    evidence = []
    if h5 is not None:
        evidence.append(
            "h5均值 "
            f"{_fmt_percent(h5.get('mean_forward_return'))}、"
            f"方向命中率 {_fmt_percent(h5.get('directional_hit_rate'))}"
        )
    if h10 is not None:
        evidence.append(
            "h10均值 "
            f"{_fmt_percent(h10.get('mean_forward_return'))}、"
            f"方向命中率 {_fmt_percent(h10.get('directional_hit_rate'))}"
        )
    evidence_text = "；".join(evidence) if evidence else "当前分数段暂无足够聚合后验证据"
    stale_note = (
        ""
        if alignment_status == "MATCHED"
        else f"；校准状态为 {alignment_status}，需复核时效"
    )
    return (
        f"R32 校准显示当前质量 {score}/{label}，位于 {bucket_label}，"
        f"历史位置为 {context_label}（分位 {percentile}）；"
        f"该分数段聚合后验：{evidence_text}{stale_note}。"
    )


def _bucket_horizon(
    *,
    bucket_summary: list[dict[str, object]],
    horizon: int,
) -> dict[str, object] | None:
    for row in bucket_summary:
        if row.get("horizon") == horizon:
            return row
    return None


def _trend_quality_calibration_warnings(
    *,
    run_id: str,
    trade_date: date,
    context: dict[str, object],
) -> tuple[TrendContinuityWarningRecord, ...]:
    if context.get("context_status") != "PROVIDED":
        return tuple()
    records = [
        _warning(
            run_id=run_id,
            trade_date=trade_date,
            section="trend_quality_calibration",
            severity=INFO_SEVERITY,
            warning_code="R33_TREND_QUALITY_CALIBRATION_CONTEXT_ONLY",
            warning_message="R32 校准结论只作为趋势质量解释上下文，不构成交易规则或交易指令。",
            affected_count=len(context.get("bucket_summary_rows", [])),
            human_review_required=("trend_quality_calibration",),
        )
    ]
    if context.get("alignment_status") != "MATCHED":
        records.append(
            _warning(
                run_id=run_id,
                trade_date=trade_date,
                section="trend_quality_calibration",
                severity=WARNING_SEVERITY,
                warning_code="R33_TREND_QUALITY_CALIBRATION_ALIGNMENT_REVIEW",
                warning_message=(
                    "R32 校准 manifest 与当前观察板最新状态不完全一致，"
                    "需复核日期、主力或分数。"
                ),
                affected_count=1,
                human_review_required=("trend_quality_calibration", "trend_quality_scoring"),
            )
        )
    return tuple(records)


def _warning(
    *,
    run_id: str,
    trade_date: date,
    section: str,
    severity: str,
    warning_code: str,
    warning_message: str,
    affected_count: int,
    human_review_required: tuple[str, ...],
) -> TrendContinuityWarningRecord:
    return TrendContinuityWarningRecord(
        run_id=run_id,
        trade_date=trade_date,
        section=section,
        severity=severity,
        warning_code=warning_code,
        warning_message=warning_message,
        affected_count=affected_count,
        human_review_required=human_review_required,
    )


def _write_board_csv(*, rows: list[dict[str, object]], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ResearchWorkbenchError("cannot write empty trend continuity board")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown(
    *,
    result: ResearchTrendContinuityBoardResult,
    rows: list[dict[str, object]],
) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    latest = rows[-1]
    transitions = [row for row in rows if row.get("transition_code")]
    calibration = result.trend_quality_calibration_context
    lines = [
        f"# CF 趋势连续性观察板 - {result.trade_date.isoformat()}",
        "",
        "## 一、数据状态",
        "",
        "- 报告类型：`trend_continuity_board`",
        f"- 数据截至：`{result.trade_date.isoformat()}`",
        f"- 回看交易日：`{result.row_count}/{result.lookback_trading_days}`",
        f"- 核心表：`{result.core_quote_path}`",
        "- 是否包含未来收益标签：`否`",
        "- 是否完成 forward-return 验证：`否`",
        f"- 是否接入 R32 聚合校准：`{_yes_no(calibration.get('context_status') == 'PROVIDED')}`",
        "",
        "## 二、最新观察",
        "",
        f"- 主力合约：`{latest['main_contract']}`",
        f"- 当前阶段：`{latest['trend_phase_code']} {latest['trend_phase_label']}`",
        f"- 阶段持续天数：`{latest['phase_run_length']}`",
        f"- 阶段切换：`{latest['transition_code'] or '未发生阶段切换'}`",
        f"- 观察标记：`{latest['observation_marker']}`",
        f"- 趋势质量：`{latest['trend_quality_score']} / {latest['trend_quality_label']}`",
        f"- 质量说明：{latest['trend_quality_reason']}",
        f"- 多因子方向：`{_signal_cn(latest['multi_factor_direction'])}`",
        f"- 主力 OI pressure：`{_fmt_percent(latest['main_oi_pressure'])}`",
        f"- 曲线斜率 proxy：`{_fmt_percent(latest['curve_slope'])}`",
        f"- carry annualized proxy：`{_fmt_percent(latest['carry_annualized'])}`",
        "",
        "## 三、趋势质量历史校准",
        "",
    ]
    if calibration.get("context_status") == "PROVIDED":
        lines.extend(
            [
                f"- 校准窗口：`{calibration.get('calibration_start')}` 至 "
                f"`{calibration.get('calibration_end')}`，样本 "
                f"`{calibration.get('calibration_daily_row_count')}` 个交易日。",
                f"- 校准状态：`{calibration.get('alignment_status')}`",
                f"- 历史分位：`{_fmt_percent(calibration.get('latest_score_percentile'))}`，"
                f"历史位置：`{calibration.get('latest_score_context_label')}`",
                f"- 当前分数段：`{calibration.get('latest_score_bucket_label')}`",
                f"- 解读：{calibration.get('interpretation_cn')}",
                "",
                "| 分数段 | Horizon | 信号日 | 标签样本 | 平均后验收益 | 方向命中率 |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in calibration["bucket_summary_rows"]:  # type: ignore[index]
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row["score_bucket_label"]),
                        str(row["horizon"]),
                        str(row["signal_day_count"]),
                        str(row["observation_count"]),
                        _fmt_percent(row["mean_forward_return"]),
                        _fmt_percent(row["directional_hit_rate"]),
                    ]
                )
                + " |"
            )
        lines.append("")
    else:
        lines.extend(
            [
                f"- {calibration.get('interpretation_cn')}",
                f"- 研究边界：{calibration.get('research_boundary')}",
                "",
            ]
        )
    lines.extend(
        [
            "## 四、连续性表",
            "",
            (
                "| 日期 | 主力 | 结算价 | 1日收益 | OI pressure | carry | curve | "
                "多因子 | 阶段 | 切换 | 标记 | 质量 |"
            ),
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |",
        ]
    )
    for row in reversed(rows):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["trade_date"]),
                    str(row["main_contract"]),
                    _fmt_number(row["main_settle"]),
                    _fmt_percent(row["return_1d"]),
                    _fmt_percent(row["main_oi_pressure"]),
                    _fmt_percent(row["carry_annualized"]),
                    _fmt_percent(row["curve_slope"]),
                    _signal_cn(row["multi_factor_direction"]),
                    f"{row['trend_phase_code']} {row['trend_phase_label']}",
                    str(row["transition_code"] or ""),
                    str(row["observation_marker"]),
                    f"{row['trend_quality_score']} {row['trend_quality_label']}",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 五、阶段切换摘要",
            "",
        ]
    )
    if transitions:
        lines.extend(
            f"- {row['trade_date']}：`{row['transition_code']}`，"
            f"{row['observation_marker']}，R27 状态 `{row['candidate_status'] or 'NA'}`。"
            for row in transitions
        )
    else:
        lines.append("- 本窗口未发生趋势阶段切换。")
    lines.extend(
        [
            "",
            "## 六、研究边界",
            "",
            "- 本观察板只使用 T 日及以前核心行情。",
            "- 本观察板未包含未来收益标签。",
            "- 本观察板未完成 forward-return 验证。",
            "- R27 候选规则只用于解释阶段切换，不构成交易指令。",
            "- R31 趋势质量评分是研究解释启发式，不构成交易指令。",
            "- R32 校准上下文只读取 manifest 和分数段聚合校准表，不读取逐日 forward-return 标签。",
            "- 趋势阶段、因子阈值、主力切换和合约规则仍需人工复核。",
            "",
            "## 七、人工复核项",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_json(
    *,
    result: ResearchTrendContinuityBoardResult,
    rows: list[dict[str, object]],
) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **result.to_summary(),
        "report_type": "trend_continuity_board",
        "rule_version": TREND_CONTINUITY_RULE_VERSION,
        "trend_quality_rule_version": TREND_QUALITY_RULE_VERSION,
        "trend_quality_calibration_context_version": TREND_QUALITY_CALIBRATION_CONTEXT_VERSION,
        "no_future_return_labels": True,
        "forward_return_validation": "未完成 forward-return 验证",
        "contains_aggregated_trend_quality_calibration": (
            result.trend_quality_calibration_context.get("context_status") == "PROVIDED"
        ),
        "rows": rows,
        "warnings": [warning.to_csv_row() for warning in result.warning_records],
    }
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_warning_csv(
    *,
    warnings: tuple[TrendContinuityWarningRecord, ...],
    csv_path: Path,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows([warning.to_csv_row() for warning in warnings])


def _write_manifest(*, result: ResearchTrendContinuityBoardResult) -> None:
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": result.run_id,
        "product_code": result.product_code,
        "report_type": "trend_continuity_board",
        "rule_version": TREND_CONTINUITY_RULE_VERSION,
        "trend_quality_rule_version": TREND_QUALITY_RULE_VERSION,
        "trend_quality_calibration_context_version": TREND_QUALITY_CALIBRATION_CONTEXT_VERSION,
        "data_asof": result.trade_date.isoformat(),
        "generated_at": utc_now().isoformat(),
        "no_lookahead": True,
        "contains_forward_return_validation": False,
        "contains_aggregated_trend_quality_calibration": (
            result.trend_quality_calibration_context.get("context_status") == "PROVIDED"
        ),
        "core_quote_path": str(result.core_quote_path),
        "trend_rule_candidate_path": (
            None
            if result.trend_rule_candidate_path is None
                else str(result.trend_rule_candidate_path)
        ),
        "trend_quality_calibration_manifest_path": (
            None
            if result.trend_quality_calibration_manifest_path is None
            else str(result.trend_quality_calibration_manifest_path)
        ),
        "trend_quality_calibration_context": result.trend_quality_calibration_context,
        "board_csv_path": str(result.board_csv_path),
        "markdown_path": str(result.markdown_path),
        "json_path": str(result.json_path),
        "warning_csv_path": str(result.warning_csv_path),
        "human_review_required": list(result.human_review_required),
    }
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _output_paths(*, trade_date: date, output_root: Path | None) -> dict[str, Path]:
    root = output_root or project_root() / "runs" / "daily"
    output_dir = root / PRODUCT_CODE / trade_date.isoformat()
    return {
        "board_csv": output_dir / "trend_continuity_board.csv",
        "markdown": output_dir / "trend_continuity_board.md",
        "json": output_dir / "trend_continuity_board.json",
        "warning_csv": output_dir / "trend_continuity_board_warnings.csv",
        "manifest": output_dir / "trend_continuity_board_manifest.json",
    }


def _human_review_required(
    warnings: tuple[TrendContinuityWarningRecord, ...],
) -> tuple[str, ...]:
    values = list(HUMAN_REVIEW_REQUIRED)
    values.extend(item for warning in warnings for item in warning.human_review_required)
    return tuple(r23._unique_values(values))


def _fmt_number(value: object) -> str:
    return r23._fmt_number(value)


def _fmt_percent(value: object) -> str:
    return r23._fmt_percent(value)


def _float_or_none(value: object) -> float | None:
    return r23._float_or_none(value)


def _int_or_none(value: object) -> int | None:
    return r23._int_or_none(value)


def _signal_cn(value: object) -> str:
    return r23._signal_cn(value)


def _yes_no(value: bool) -> str:
    return "是" if value else "否"


def _none_if_missing(value: object) -> object | None:
    if value is None:
        return None
    if pd.isna(value):
        return None
    return value


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    if pd.isna(value):
        return None
    text = str(value)
    return text if text else None


def _default_run_id(trade_date: date) -> str:
    timestamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    suffix = uuid.uuid4().hex[:8]
    return f"r29_trend_continuity_{PRODUCT_CODE}_{trade_date.isoformat()}_{timestamp}_{suffix}"
