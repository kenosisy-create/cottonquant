"""R23 latest signal-only CF research brief."""

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
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME
from cotton_factor.research_workbench.trend_phase import (
    SignalDirection,
    TrendPhaseResult,
    classify_cf_trend_phase,
)

PRODUCT_CODE = "CF"
EXCHANGE = "CZCE"
UNIVERSE = "CF_MAIN"
SIGNAL_OBJECT_ID = "CF.C1"
LATEST_SIGNAL_RULE_VERSION = "R23_latest_signal_only_brief_v1"
WARNING_SEVERITY = "WARN"
INFO_SEVERITY = "INFO"
DEFAULT_LOOKBACK_DAYS = 20
RETURN_HORIZONS = (1, 3, 5, 10, 20)
THRESHOLD_CANDIDATE_STATUSES = {"READY_CANDIDATE": 0, "WATCH_CANDIDATE": 1}
HUMAN_REVIEW_REQUIRED = (
    "latest_signal_interpretation",
    "factor_thresholds",
    "trend_phase_rules",
    "contract_rule_assumptions",
)
TREND_RULE_CANDIDATE_REQUIRED_COLUMNS = {
    "product_code",
    "transition_code",
    "candidate_status",
    "daily_brief_action",
    "selected_horizon",
    "event_count",
    "observation_count",
    "directional_hit_rate",
    "mean_forward_return",
    "rule_text_cn",
    "caveat_cn",
}

WARNING_COLUMNS = [
    "run_id",
    "trade_date",
    "section",
    "severity",
    "warning_code",
    "warning_message",
    "human_review_required",
    "input_snapshot_ids",
]


@dataclass(frozen=True)
class LatestSignalWarningRecord:
    """Warning row for the latest signal-only brief."""

    run_id: str
    trade_date: date
    section: str
    severity: str
    warning_code: str
    warning_message: str
    human_review_required: tuple[str, ...]
    input_snapshot_ids: tuple[str, ...]

    def to_csv_row(self) -> dict[str, str]:
        """Return a CSV-safe row."""
        return {
            "run_id": self.run_id,
            "trade_date": self.trade_date.isoformat(),
            "section": self.section,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "human_review_required": ";".join(self.human_review_required),
            "input_snapshot_ids": ";".join(self.input_snapshot_ids),
        }


@dataclass(frozen=True)
class LatestSignalBriefResult:
    """Result of building the R23 latest signal-only brief."""

    product_code: str
    run_id: str
    trade_date: date
    data_asof: date
    lookback_days: int
    main_contract: str
    signal_direction: SignalDirection
    trend_phase: TrendPhaseResult
    summary: dict[str, object]
    warning_records: tuple[LatestSignalWarningRecord, ...]
    markdown_path: Path
    json_path: Path
    warning_csv_path: Path
    manifest_path: Path
    core_quote_path: Path
    trend_rule_candidate_path: Path | None
    signal_matrix_path: Path | None
    signal_threshold_research_path: Path | None
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
            "data_asof": self.data_asof.isoformat(),
            "lookback_days": self.lookback_days,
            "main_contract": self.main_contract,
            "signal_direction": self.signal_direction,
            "trend_phase": self.trend_phase.to_summary(),
            "warning_count": self.warning_count,
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
            "signal_matrix_path": (
                None if self.signal_matrix_path is None else str(self.signal_matrix_path)
            ),
            "signal_threshold_research_path": (
                None
                if self.signal_threshold_research_path is None
                else str(self.signal_threshold_research_path)
            ),
            "trend_rule_context": self.summary.get("trend_rule_context"),
            "signal_matrix_context": self.summary.get("signal_matrix_context"),
            "signal_threshold_context": self.summary.get("signal_threshold_context"),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_latest_signal_brief(
    *,
    trade_date: date | None = None,
    core_quote_path: Path | None = None,
    output_root: Path | None = None,
    run_id: str | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    trend_rule_candidate_path: Path | None = None,
    signal_matrix_path: Path | None = None,
    signal_threshold_research_path: Path | None = None,
) -> LatestSignalBriefResult:
    """Build a latest-day CF signal-only brief without future-return labels."""
    if lookback_days <= 0:
        raise ResearchWorkbenchError("lookback_days must be positive")
    quote_path = core_quote_path or data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    quotes = _load_core_quotes(input_path=quote_path)
    active_date = _resolve_trade_date(quotes=quotes, trade_date=trade_date)
    # R23 只允许使用 T 日及以前的核心表，不能等待未来收益标签才生成观察报告。
    visible_quotes = quotes.loc[quotes["trade_date"] <= active_date].copy()
    latest_quotes = visible_quotes.loc[visible_quotes["trade_date"] == active_date].copy()
    if latest_quotes.empty:
        raise ResearchWorkbenchError(f"no {PRODUCT_CODE} core rows for {active_date.isoformat()}")

    brief_run_id = run_id or _default_run_id(active_date)
    # 主力合约按最新日持仓量优先、成交量次优排序，排序表会写入报告供人工复核。
    activity_rows = _activity_rows(visible_quotes=visible_quotes, active_date=active_date)
    main_row = activity_rows[0]
    main_contract = str(main_row["contract_code"])
    main_history = _main_contract_history(
        visible_quotes=visible_quotes,
        contract_code=main_contract,
        active_date=active_date,
    )
    main_metrics = _main_metrics(main_history=main_history)
    # 期限结构只读取最新日可观察合约，不依赖 forward return、回测或成本敏感性产物。
    term_structure = _term_structure(latest_quotes=latest_quotes, main_contract=main_contract)
    factor_signals = _factor_signals(
        main_metrics=main_metrics,
        term_structure=term_structure,
    )
    multi_factor = _multi_factor_summary(factor_signals)
    # R24 阶段判断是研究观察项，不升级为交易指令。
    trend_phase = classify_cf_trend_phase(
        signal_states=factor_signals,
        latest_settle=main_metrics["latest_settle"],
        ma20=main_metrics["ma20"],
        momentum_20=main_metrics["returns"].get("20"),
        latest_return=main_metrics["returns"].get("1"),
        oi_pressure=main_metrics["oi_pressure"],
    )
    previous_phase = _previous_trend_phase(
        visible_quotes=visible_quotes,
        active_date=active_date,
    )
    # R28 只读取 R27 已聚合候选表，用于日报解释；不读取未来收益明细或回测明细。
    trend_rule_candidates = (
        None
        if trend_rule_candidate_path is None
        else _load_trend_rule_candidates(input_path=trend_rule_candidate_path)
    )
    trend_rule_context = _trend_rule_context(
        trend_rule_candidate_path=trend_rule_candidate_path,
        candidates=trend_rule_candidates,
        previous_phase=previous_phase,
        current_phase=trend_phase,
    )
    # R38 只接入 R35 的 signal-only 矩阵快照；误传 R36 验证表时必须拒绝。
    signal_matrix_context = _signal_matrix_context(
        signal_matrix_path=signal_matrix_path,
        trade_date=active_date,
    )
    # R39 只读取 R37 聚合候选表，不允许 R36 逐日 forward_return 标签进入最新日报。
    signal_threshold_context = _signal_threshold_context(
        signal_threshold_research_path=signal_threshold_research_path,
        signal_matrix_context=signal_matrix_context,
    )
    snapshot_ids = _unique_values(latest_quotes["source_snapshot_id"].dropna().astype(str))
    summary = _build_summary(
        trade_date=active_date,
        core_quote_path=quote_path,
        latest_quotes=latest_quotes,
        activity_rows=activity_rows,
        main_metrics=main_metrics,
        term_structure=term_structure,
        factor_signals=factor_signals,
        multi_factor=multi_factor,
        trend_phase=trend_phase,
        trend_rule_context=trend_rule_context,
        signal_matrix_context=signal_matrix_context,
        signal_threshold_context=signal_threshold_context,
        snapshot_ids=tuple(snapshot_ids),
    )
    warnings = tuple(
        _build_warnings(
            run_id=brief_run_id,
            trade_date=active_date,
            main_metrics=main_metrics,
            term_structure=term_structure,
            factor_signals=factor_signals,
            trend_rule_context=trend_rule_context,
            signal_matrix_context=signal_matrix_context,
            signal_threshold_context=signal_threshold_context,
            snapshot_ids=tuple(snapshot_ids),
        )
    )

    paths = _output_paths(
        trade_date=active_date,
        output_root=output_root,
    )
    result = LatestSignalBriefResult(
        product_code=PRODUCT_CODE,
        run_id=brief_run_id,
        trade_date=active_date,
        data_asof=active_date,
        lookback_days=lookback_days,
        main_contract=main_contract,
        signal_direction=multi_factor["direction"],  # type: ignore[arg-type]
        trend_phase=trend_phase,
        summary=summary,
        warning_records=warnings,
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        warning_csv_path=paths["warning_csv"],
        manifest_path=paths["manifest"],
        core_quote_path=quote_path,
        trend_rule_candidate_path=trend_rule_candidate_path,
        signal_matrix_path=signal_matrix_path,
        signal_threshold_research_path=signal_threshold_research_path,
        human_review_required=_human_review_required(warnings),
    )
    _write_markdown(result=result)
    _write_json(result=result)
    _write_warning_csv(warnings=warnings, csv_path=result.warning_csv_path)
    _write_manifest(result=result)
    return result


def _load_core_quotes(*, input_path: Path) -> pd.DataFrame:
    if not input_path.exists():
        raise ResearchWorkbenchError(f"core quote parquet not found: {input_path}")
    frame = pd.read_parquet(input_path)
    required = {
        "trade_date",
        "product_code",
        "contract_code",
        "settle",
        "volume",
        "open_interest",
        "source_snapshot_id",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"core quote table missing columns: {missing}")
    working = frame.copy()
    working["trade_date"] = pd.to_datetime(working["trade_date"]).dt.date
    working = working.loc[
        working["product_code"].astype(str).str.upper() == PRODUCT_CODE
    ].copy()
    if working.empty:
        raise ResearchWorkbenchError(f"core quote table has no {PRODUCT_CODE} rows")
    for column in ("settle", "volume", "open_interest"):
        working[column] = pd.to_numeric(working[column], errors="coerce")
    working = working.dropna(subset=["trade_date", "contract_code", "settle"])
    if working.empty:
        raise ResearchWorkbenchError(f"core quote table has no usable {PRODUCT_CODE} rows")
    return working.sort_values(["trade_date", "contract_code"]).reset_index(drop=True)


def _load_trend_rule_candidates(*, input_path: Path) -> pd.DataFrame:
    if not input_path.exists():
        raise ResearchWorkbenchError(f"trend rule candidate table not found: {input_path}")
    if input_path.suffix.lower() == ".csv":
        frame = pd.read_csv(input_path)
    else:
        frame = pd.read_parquet(input_path)
    missing = sorted(TREND_RULE_CANDIDATE_REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"trend rule candidate table missing columns: {missing}")
    working = frame.copy()
    working = working.loc[
        working["product_code"].astype(str).str.upper() == PRODUCT_CODE
    ].copy()
    if working.empty:
        raise ResearchWorkbenchError(f"trend rule candidate table has no {PRODUCT_CODE} rows")
    working["transition_code"] = working["transition_code"].astype(str)
    return working.reset_index(drop=True)


def _signal_matrix_context(
    *,
    signal_matrix_path: Path | None,
    trade_date: date,
) -> dict[str, object]:
    context: dict[str, object] = {
        "status": "NOT_PROVIDED",
        "signal_matrix_path": None if signal_matrix_path is None else str(signal_matrix_path),
        "trade_date": trade_date.isoformat(),
        "rows": [],
        "primary_horizon": None,
        "primary_direction": None,
        "primary_confidence": None,
        "research_boundary": "未接入 R35 多周期信号矩阵，本节不展示。",
    }
    if signal_matrix_path is None:
        return context
    if not signal_matrix_path.exists():
        raise ResearchWorkbenchError(f"signal matrix artifact not found: {signal_matrix_path}")
    if signal_matrix_path.suffix.lower() == ".json":
        payload = json.loads(signal_matrix_path.read_text(encoding="utf-8"))
        rows = payload.get("latest_rows")
        if not isinstance(rows, list):
            raise ResearchWorkbenchError("signal matrix JSON must contain latest_rows")
    else:
        frame = (
            pd.read_csv(signal_matrix_path)
            if signal_matrix_path.suffix.lower() == ".csv"
            else pd.read_parquet(signal_matrix_path)
        )
        if any(str(column).startswith("forward_return") for column in frame.columns):
            raise ResearchWorkbenchError(
                "signal matrix input for latest brief must not contain forward_return columns"
            )
        if "trade_date" not in frame.columns:
            raise ResearchWorkbenchError("signal matrix table missing trade_date column")
        working = frame.copy()
        working["trade_date"] = pd.to_datetime(working["trade_date"]).dt.date
        rows = working.loc[working["trade_date"] == trade_date].to_dict(orient="records")
    clean_rows = [_signal_matrix_row(row) for row in rows]
    if not clean_rows:
        raise ResearchWorkbenchError(
            f"signal matrix has no rows for {trade_date.isoformat()}: {signal_matrix_path}"
        )
    primary = _primary_signal_matrix_row(clean_rows)
    context.update(
        {
            "status": "PROVIDED",
            "rows": clean_rows,
            "primary_horizon": primary.get("horizon"),
            "primary_direction": primary.get("direction"),
            "primary_confidence": primary.get("confidence"),
            "research_boundary": "R35 矩阵只使用 T 日及以前可观察数据，不包含未来收益标签。",
        }
    )
    return context


def _signal_matrix_row(row: object) -> dict[str, object]:
    if not isinstance(row, dict):
        raise ResearchWorkbenchError("signal matrix row must be an object")
    forbidden = [key for key in row if str(key).startswith("forward_return")]
    if forbidden:
        raise ResearchWorkbenchError(
            f"signal matrix row for latest brief contains forbidden columns: {forbidden}"
        )
    required = {
        "horizon",
        "direction",
        "confidence_score",
        "confidence",
        "trend_phase",
        "evidence_level",
        "action_type",
        "warning_flags",
    }
    missing = sorted(required - set(row))
    if missing:
        raise ResearchWorkbenchError(f"signal matrix row missing columns: {missing}")
    return {
        "horizon": _int_or_none(row.get("horizon")),
        "direction": _none_if_missing(row.get("direction")),
        "confidence_score": _float_or_none(row.get("confidence_score")),
        "confidence": _none_if_missing(row.get("confidence")),
        "trend_phase": _none_if_missing(row.get("trend_phase")),
        "trend_phase_label": _none_if_missing(row.get("trend_phase_label")),
        "evidence_level": _none_if_missing(row.get("evidence_level")),
        "action_type": _none_if_missing(row.get("action_type")),
        "warning_flags": _none_if_missing(row.get("warning_flags")),
        "composite_score": _float_or_none(row.get("composite_score")),
        "option_signal": _none_if_missing(row.get("option_signal")),
        "option_signal_direction": _none_if_missing(row.get("option_signal_direction")),
        "option_factor_status": _none_if_missing(row.get("option_factor_status")),
        "option_atm_iv_rank": _float_or_none(row.get("option_atm_iv_rank")),
        "option_pcr_volume": _float_or_none(row.get("option_pcr_volume")),
        "option_pcr_oi": _float_or_none(row.get("option_pcr_oi")),
        "option_skew_proxy": _float_or_none(row.get("option_skew_proxy")),
    }


def _primary_signal_matrix_row(rows: list[dict[str, object]]) -> dict[str, object]:
    priority = {20: 0, 10: 1, 5: 2, 3: 3, 1: 4, 40: 5}
    return sorted(rows, key=lambda row: priority.get(int(row.get("horizon") or 999), 999))[0]


def _signal_threshold_context(
    *,
    signal_threshold_research_path: Path | None,
    signal_matrix_context: dict[str, object],
) -> dict[str, object]:
    context: dict[str, object] = {
        "status": "NOT_PROVIDED",
        "signal_threshold_research_path": (
            None if signal_threshold_research_path is None else str(signal_threshold_research_path)
        ),
        "primary_horizon": signal_matrix_context.get("primary_horizon"),
        "horizon_alignment_status": "NOT_EVALUATED",
        "matched_candidates": [],
        "alternate_candidates": [],
        "primary_candidate": None,
        "explanation_cn": "未接入 R37 阈值/权重研究候选，本节不展示。",
        "research_boundary": "R37 候选只用于历史解释和人工复核，不构成交易规则。",
    }
    if signal_threshold_research_path is None:
        return context
    if signal_matrix_context.get("status") != "PROVIDED":
        context["status"] = "MATRIX_NOT_PROVIDED"
        context["explanation_cn"] = (
            "已提供 R37 候选表，但未提供 R35 矩阵上下文，"
            "无法匹配当前 horizon。"
        )
        return context
    if not signal_threshold_research_path.exists():
        raise ResearchWorkbenchError(
            f"signal threshold research artifact not found: {signal_threshold_research_path}"
        )
    rows = _load_signal_threshold_rows(signal_threshold_research_path)
    primary_horizon = _int_or_none(signal_matrix_context.get("primary_horizon"))
    # R40：主周期候选仍然优先；其它周期只能作为参考，不能替代主周期确认。
    matched = _matched_threshold_candidates(rows=rows, primary_horizon=primary_horizon)
    alternate = _alternate_threshold_candidates(rows=rows, primary_horizon=primary_horizon)
    primary_candidate = matched[0] if matched else None
    context.update(
        {
            "status": "PROVIDED",
            "horizon_alignment_status": _threshold_horizon_alignment_status(
                primary_horizon=primary_horizon,
                matched_candidates=matched,
                alternate_candidates=alternate,
            ),
            "matched_candidates": matched,
            "alternate_candidates": alternate,
            "primary_candidate": primary_candidate,
            "explanation_cn": _threshold_explanation(
                primary_candidate=primary_candidate,
                alternate_candidates=alternate,
                primary_horizon=primary_horizon,
            ),
        }
    )
    return context


def _load_signal_threshold_rows(path: Path) -> list[dict[str, object]]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("weighting_rows")
        if not isinstance(rows, list):
            raise ResearchWorkbenchError("R37 JSON must contain weighting_rows")
    else:
        frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
        forbidden = [
            column
            for column in frame.columns
            if str(column).startswith("forward_return") or str(column) == "forward_return"
        ]
        if forbidden:
            raise ResearchWorkbenchError(
                f"R37 context must be aggregated; forbidden validation columns: {forbidden}"
            )
        required = {
            "scheme_id",
            "scheme_label_cn",
            "horizon",
            "coverage_rate",
            "observation_count",
            "mean_forward_return",
            "directional_hit_rate",
            "candidate_status",
        }
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ResearchWorkbenchError(f"R37 weighting table missing columns: {missing}")
        rows = frame.to_dict(orient="records")
    return [_signal_threshold_row(row) for row in rows]


def _signal_threshold_row(row: object) -> dict[str, object]:
    if not isinstance(row, dict):
        raise ResearchWorkbenchError("R37 weighting row must be an object")
    return {
        "scheme_id": _none_if_missing(row.get("scheme_id")),
        "scheme_label_cn": _none_if_missing(row.get("scheme_label_cn")),
        "horizon": _int_or_none(row.get("horizon")),
        "coverage_rate": _float_or_none(row.get("coverage_rate")),
        "observation_count": _int_or_none(row.get("observation_count")),
        "mean_forward_return": _float_or_none(row.get("mean_forward_return")),
        "directional_hit_rate": _float_or_none(row.get("directional_hit_rate")),
        "candidate_status": _none_if_missing(row.get("candidate_status")),
    }


def _matched_threshold_candidates(
    *,
    rows: list[dict[str, object]],
    primary_horizon: int | None,
) -> list[dict[str, object]]:
    if primary_horizon is None:
        return []
    matched = [
        row
        for row in rows
        if row.get("horizon") == primary_horizon
        and row.get("candidate_status") in THRESHOLD_CANDIDATE_STATUSES
    ]
    return _sort_threshold_candidates(rows=matched, primary_horizon=primary_horizon)[:5]


def _alternate_threshold_candidates(
    *,
    rows: list[dict[str, object]],
    primary_horizon: int | None,
) -> list[dict[str, object]]:
    if primary_horizon is None:
        return []
    alternate = [
        row
        for row in rows
        if row.get("horizon") != primary_horizon
        and row.get("candidate_status") in THRESHOLD_CANDIDATE_STATUSES
    ]
    return _sort_threshold_candidates(rows=alternate, primary_horizon=primary_horizon)[:5]


def _sort_threshold_candidates(
    *,
    rows: list[dict[str, object]],
    primary_horizon: int | None,
) -> list[dict[str, object]]:
    return sorted(
        rows,
        key=lambda row: (
            THRESHOLD_CANDIDATE_STATUSES[str(row["candidate_status"])],
            abs((_int_or_none(row.get("horizon")) or 999) - (primary_horizon or 999)),
            -(_float_or_none(row.get("directional_hit_rate")) or 0.0),
            -(_int_or_none(row.get("observation_count")) or 0),
            _int_or_none(row.get("horizon")) or 999,
        ),
    )


def _threshold_horizon_alignment_status(
    *,
    primary_horizon: int | None,
    matched_candidates: list[dict[str, object]],
    alternate_candidates: list[dict[str, object]],
) -> str:
    if primary_horizon is None:
        return "PRIMARY_HORIZON_UNKNOWN"
    if matched_candidates:
        return "PRIMARY_MATCHED"
    if alternate_candidates:
        return "ALTERNATE_ONLY"
    return "NO_READY_WATCH"


def _threshold_explanation(
    *,
    primary_candidate: dict[str, object] | None,
    alternate_candidates: list[dict[str, object]],
    primary_horizon: int | None,
) -> str:
    if primary_candidate is None:
        if alternate_candidates:
            nearest = alternate_candidates[0]
            return (
                f"R37 当前主观察 {primary_horizon}D horizon 暂无 READY/WATCH 候选；"
                f"其它周期存在 {len(alternate_candidates)} 个非主周期参考候选，"
                f"最近参考为 {nearest.get('scheme_label_cn')} 在 "
                f"{nearest.get('horizon')}D horizon 上的 {nearest.get('candidate_status')}。"
                "这些候选只能提示跨周期历史证据，不能替代主观察周期确认。"
            )
        return "R37 暂无与当前主观察 horizon 匹配的 READY/WATCH 候选，仅保留人工观察。"
    explanation = (
        f"R37 候选显示：{primary_candidate.get('scheme_label_cn')} 在 "
        f"{primary_candidate.get('horizon')}D horizon 上为 "
        f"{primary_candidate.get('candidate_status')}；"
        f"样本 {primary_candidate.get('observation_count')}，"
        f"方向命中率 {_fmt_percent(primary_candidate.get('directional_hit_rate'))}，"
        f"平均后验收益 {_fmt_percent(primary_candidate.get('mean_forward_return'))}。"
    )
    if alternate_candidates:
        explanation += (
            f"另有 {len(alternate_candidates)} 个非主周期参考候选，"
            "需人工复核周期一致性。"
        )
    return explanation


def _resolve_trade_date(*, quotes: pd.DataFrame, trade_date: date | None) -> date:
    dates = sorted(set(quotes["trade_date"]))
    if not dates:
        raise ResearchWorkbenchError("core quote table has no trade_date values")
    if trade_date is None:
        return dates[-1]
    if trade_date not in dates:
        raise ResearchWorkbenchError(f"no {PRODUCT_CODE} core rows for {trade_date.isoformat()}")
    return trade_date


def _previous_trend_phase(
    *,
    visible_quotes: pd.DataFrame,
    active_date: date,
) -> TrendPhaseResult | None:
    previous_dates = sorted(
        trade_date for trade_date in set(visible_quotes["trade_date"]) if trade_date < active_date
    )
    if not previous_dates:
        return None
    return _classify_trend_phase_for_date(
        visible_quotes=visible_quotes,
        active_date=previous_dates[-1],
    )


def _classify_trend_phase_for_date(
    *,
    visible_quotes: pd.DataFrame,
    active_date: date,
) -> TrendPhaseResult:
    # 按单日可见数据重新识别当日主力，避免用最新主力反推前一交易日阶段。
    day_visible_quotes = visible_quotes.loc[visible_quotes["trade_date"] <= active_date].copy()
    latest_quotes = day_visible_quotes.loc[day_visible_quotes["trade_date"] == active_date].copy()
    activity_rows = _activity_rows(visible_quotes=day_visible_quotes, active_date=active_date)
    main_contract = str(activity_rows[0]["contract_code"])
    main_history = _main_contract_history(
        visible_quotes=day_visible_quotes,
        contract_code=main_contract,
        active_date=active_date,
    )
    main_metrics = _main_metrics(main_history=main_history)
    term_structure = _term_structure(latest_quotes=latest_quotes, main_contract=main_contract)
    factor_signals = _factor_signals(
        main_metrics=main_metrics,
        term_structure=term_structure,
    )
    return classify_cf_trend_phase(
        signal_states=factor_signals,
        latest_settle=main_metrics["latest_settle"],
        ma20=main_metrics["ma20"],
        momentum_20=main_metrics["returns"].get("20"),
        latest_return=main_metrics["returns"].get("1"),
        oi_pressure=main_metrics["oi_pressure"],
    )


def _activity_rows(*, visible_quotes: pd.DataFrame, active_date: date) -> list[dict[str, object]]:
    dates = sorted(set(visible_quotes["trade_date"]))
    try:
        prev_date = dates[dates.index(active_date) - 1]
    except (ValueError, IndexError):
        prev_date = None
    latest = visible_quotes.loc[visible_quotes["trade_date"] == active_date].copy()
    previous = (
        visible_quotes.loc[visible_quotes["trade_date"] == prev_date].copy()
        if prev_date is not None
        else pd.DataFrame(columns=visible_quotes.columns)
    )
    previous_by_contract = {
        row.contract_code: row
        for row in previous.itertuples(index=False)
    }
    records: list[dict[str, object]] = []
    latest = latest.sort_values(
        ["open_interest", "volume", "contract_code"],
        ascending=[False, False, True],
        na_position="last",
    )
    for rank, row in enumerate(latest.itertuples(index=False), start=1):
        prior = previous_by_contract.get(row.contract_code)
        prev_settle = _float_or_none(getattr(prior, "settle", None)) if prior else None
        prev_oi = _float_or_none(getattr(prior, "open_interest", None)) if prior else None
        settle = _float_or_none(row.settle)
        open_interest = _float_or_none(row.open_interest)
        settle_change = None if settle is None or prev_settle is None else settle - prev_settle
        settle_return = (
            None
            if settle is None or prev_settle is None or prev_settle <= 0
            else settle / prev_settle - 1
        )
        oi_change = (
            None
            if open_interest is None or prev_oi is None
            else open_interest - prev_oi
        )
        records.append(
            {
                "rank": rank,
                "contract_code": row.contract_code,
                "settle": settle,
                "prev_settle": prev_settle,
                "settle_change": settle_change,
                "settle_return": settle_return,
                "volume": _float_or_none(row.volume),
                "open_interest": open_interest,
                "prev_open_interest": prev_oi,
                "oi_change": oi_change,
                "source_snapshot_id": str(row.source_snapshot_id),
            }
        )
    if not records:
        raise ResearchWorkbenchError(f"no active contract rows for {active_date.isoformat()}")
    return records


def _main_contract_history(
    *,
    visible_quotes: pd.DataFrame,
    contract_code: str,
    active_date: date,
) -> pd.DataFrame:
    history = visible_quotes.loc[
        (visible_quotes["contract_code"].astype(str) == contract_code)
        & (visible_quotes["trade_date"] <= active_date)
    ].copy()
    if history.empty:
        raise ResearchWorkbenchError(f"main contract history not found: {contract_code}")
    return history.sort_values("trade_date").reset_index(drop=True)


def _main_metrics(*, main_history: pd.DataFrame) -> dict[str, object]:
    latest = main_history.iloc[-1]
    latest_settle = _float_or_none(latest["settle"])
    latest_oi = _float_or_none(latest["open_interest"])
    previous = main_history.iloc[-2] if len(main_history) >= 2 else None
    prev_oi = _float_or_none(previous["open_interest"]) if previous is not None else None
    oi_change = None if latest_oi is None or prev_oi is None else latest_oi - prev_oi
    oi_pressure = None if oi_change is None or prev_oi in {None, 0} else oi_change / prev_oi
    settles = pd.to_numeric(main_history["settle"], errors="coerce")
    ma20 = None
    if len(settles.dropna()) >= 20:
        ma20 = float(settles.rolling(20, min_periods=20).mean().iloc[-1])
    returns = _horizon_returns(main_history=main_history)
    return {
        "contract_code": str(latest["contract_code"]),
        "latest_settle": latest_settle,
        "latest_open_interest": latest_oi,
        "latest_volume": _float_or_none(latest["volume"]),
        "oi_change": oi_change,
        "oi_pressure": oi_pressure,
        "ma20": ma20,
        "returns": returns,
    }


def _horizon_returns(*, main_history: pd.DataFrame) -> dict[str, float | None]:
    returns: dict[str, float | None] = {}
    latest_settle = _float_or_none(main_history.iloc[-1]["settle"])
    for horizon in RETURN_HORIZONS:
        if len(main_history) <= horizon:
            returns[str(horizon)] = None
            continue
        prior_settle = _float_or_none(main_history.iloc[-1 - horizon]["settle"])
        returns[str(horizon)] = (
            None
            if latest_settle is None or prior_settle is None or prior_settle <= 0
            else latest_settle / prior_settle - 1
        )
    return returns


def _term_structure(*, latest_quotes: pd.DataFrame, main_contract: str) -> dict[str, object]:
    working = latest_quotes.copy()
    working["delivery_date"] = [
        _delivery_date(contract_code=str(row.contract_code), trade_date=row.trade_date)
        for row in working.itertuples(index=False)
    ]
    main_rows = working.loc[working["contract_code"].astype(str) == main_contract]
    if main_rows.empty:
        raise ResearchWorkbenchError(f"main contract missing from latest quotes: {main_contract}")
    main = main_rows.iloc[0]
    main_settle = _float_or_none(main["settle"])
    main_delivery = main["delivery_date"]
    near = working.loc[working["delivery_date"] < main_delivery].sort_values(
        "delivery_date",
        ascending=False,
    )
    far = working.loc[working["delivery_date"] > main_delivery].sort_values("delivery_date")
    near_row = near.iloc[0] if not near.empty else None
    far_row = far.iloc[0] if not far.empty else None
    far_settle = _float_or_none(far_row["settle"]) if far_row is not None else None
    curve_slope = (
        None
        if main_settle is None or far_settle is None or main_settle <= 0
        else far_settle / main_settle - 1
    )
    tenor_days = None
    carry_annualized = None
    if far_row is not None and curve_slope is not None:
        tenor_days = (far_row["delivery_date"] - main_delivery).days
        if tenor_days > 0:
            carry_annualized = curve_slope * 365 / tenor_days
    return {
        "main_contract": main_contract,
        "main_delivery_date": main_delivery.isoformat(),
        "near_contract": None if near_row is None else str(near_row["contract_code"]),
        "near_settle": None if near_row is None else _float_or_none(near_row["settle"]),
        "main_minus_near": _spread(main_settle, near_row),
        "far_contract": None if far_row is None else str(far_row["contract_code"]),
        "far_settle": far_settle,
        "far_minus_main": (
            None if far_settle is None or main_settle is None else far_settle - main_settle
        ),
        "curve_slope": curve_slope,
        "tenor_days": tenor_days,
        "carry_annualized": carry_annualized,
    }


def _factor_signals(
    *,
    main_metrics: dict[str, object],
    term_structure: dict[str, object],
) -> dict[str, SignalDirection]:
    returns = main_metrics["returns"]
    assert isinstance(returns, dict)
    latest_return = returns.get("1")
    oi_pressure = main_metrics["oi_pressure"]
    signals: dict[str, SignalDirection] = {
        "momentum": _direction(returns.get("20")),
        "carry": _direction(term_structure.get("carry_annualized")),
        "curve": _direction(term_structure.get("curve_slope")),
        "oi_pressure": _oi_direction(
            latest_return=_float_or_none(latest_return),
            oi_pressure=_float_or_none(oi_pressure),
        ),
    }
    return signals


def _multi_factor_summary(signals: dict[str, SignalDirection]) -> dict[str, object]:
    values = [state for state in signals.values() if state != "unknown"]
    score = sum(1 if state == "long" else -1 if state == "short" else 0 for state in values)
    direction: SignalDirection = "neutral"
    if score > 0:
        direction = "long"
    elif score < 0:
        direction = "short"
    confidence = "low"
    if values:
        ratio = abs(score) / len(values)
        if abs(score) >= 3 and ratio >= 0.75:
            confidence = "high"
        elif abs(score) >= 2 and ratio >= 0.5:
            confidence = "medium"
    return {
        "score": score,
        "available_signal_count": len(values),
        "direction": direction,
        "confidence": confidence,
    }


def _trend_rule_context(
    *,
    trend_rule_candidate_path: Path | None,
    candidates: pd.DataFrame | None,
    previous_phase: TrendPhaseResult | None,
    current_phase: TrendPhaseResult,
) -> dict[str, object]:
    previous_code = None if previous_phase is None else previous_phase.phase_code
    previous_label = None if previous_phase is None else previous_phase.phase_label
    transition_code = (
        None
        if previous_phase is None or previous_phase.phase_code == current_phase.phase_code
        else f"{previous_phase.phase_code}_TO_{current_phase.phase_code}"
    )
    context: dict[str, object] = {
        "candidate_path": None
        if trend_rule_candidate_path is None
        else str(trend_rule_candidate_path),
        "previous_phase_code": previous_code,
        "previous_phase_label": previous_label,
        "current_phase_code": current_phase.phase_code,
        "current_phase_label": current_phase.phase_label,
        "transition_code": transition_code,
        "candidate_status": None,
        "daily_brief_action": None,
        "selected_horizon": None,
        "event_count": None,
        "observation_count": None,
        "directional_hit_rate": None,
        "mean_forward_return": None,
        "rule_text_cn": None,
        "caveat_cn": None,
        "explanation_cn": None,
        "interpretation_level": "current_phase_only",
        "research_boundary": "R27 候选只用于解释，不构成交易指令",
    }
    if trend_rule_candidate_path is None:
        context["candidate_status"] = "NOT_PROVIDED"
        context["daily_brief_action"] = "NO_R27_CONTEXT"
        context["explanation_cn"] = "未接入 R27 候选规则表，本节仅展示 R24 当前阶段。"
        return context
    if previous_phase is None:
        context["candidate_status"] = "NO_PREVIOUS_PHASE"
        context["daily_brief_action"] = "WATCH_ONLY"
        context["explanation_cn"] = "缺少前一交易日阶段，不能形成阶段切换解释。"
        return context
    if transition_code is None:
        context["candidate_status"] = "NO_PHASE_CHANGE"
        context["daily_brief_action"] = "WATCH_ONLY"
        context["explanation_cn"] = "当前交易日较前一交易日未发生趋势阶段切换。"
        return context
    assert candidates is not None
    matched = candidates.loc[candidates["transition_code"].astype(str) == transition_code]
    if matched.empty:
        context["candidate_status"] = "NOT_FOUND"
        context["daily_brief_action"] = "WATCH_ONLY"
        context["explanation_cn"] = "R27 候选表中没有匹配该阶段切换的规则。"
        return context

    row = matched.iloc[0]
    status = str(row["candidate_status"])
    action = str(row["daily_brief_action"])
    rule_text = _none_if_missing(row["rule_text_cn"])
    caveat = _none_if_missing(row["caveat_cn"])
    context.update(
        {
            "candidate_status": status,
            "daily_brief_action": action,
            "selected_horizon": _int_or_none(row["selected_horizon"]),
            "event_count": _int_or_none(row["event_count"]),
            "observation_count": _int_or_none(row["observation_count"]),
            "directional_hit_rate": _float_or_none(row["directional_hit_rate"]),
            "mean_forward_return": _float_or_none(row["mean_forward_return"]),
            "rule_text_cn": rule_text,
            "caveat_cn": caveat,
            "candidate_rule_version": _none_if_missing(row.get("candidate_rule_version")),
        }
    )
    if status == "READY_CANDIDATE" and action == "ALLOW_DAILY_EXPLANATION_CANDIDATE":
        context["interpretation_level"] = "candidate_explanation"
        context["explanation_cn"] = f"历史候选解释：{rule_text} {caveat}"
    else:
        context["interpretation_level"] = "watch_only"
        context["explanation_cn"] = f"仅观察：{rule_text} {caveat}"
    return context


def _build_summary(
    *,
    trade_date: date,
    core_quote_path: Path,
    latest_quotes: pd.DataFrame,
    activity_rows: list[dict[str, object]],
    main_metrics: dict[str, object],
    term_structure: dict[str, object],
    factor_signals: dict[str, SignalDirection],
    multi_factor: dict[str, object],
    trend_phase: TrendPhaseResult,
    trend_rule_context: dict[str, object],
    signal_matrix_context: dict[str, object],
    signal_threshold_context: dict[str, object],
    snapshot_ids: tuple[str, ...],
) -> dict[str, object]:
    return {
        "report_type": "latest_signal_only",
        "rule_version": LATEST_SIGNAL_RULE_VERSION,
        "data_status": {
            "data_asof": trade_date.isoformat(),
            "core_quote_path": str(core_quote_path),
            "latest_row_count": int(len(latest_quotes)),
            "input_snapshot_ids": list(snapshot_ids),
            "contains_forward_return_validation": False,
        },
        "market_facts": {
            "main_contract": main_metrics["contract_code"],
            "main_settle": main_metrics["latest_settle"],
            "main_volume": main_metrics["latest_volume"],
            "main_open_interest": main_metrics["latest_open_interest"],
            "main_oi_change": main_metrics["oi_change"],
            "main_oi_pressure": main_metrics["oi_pressure"],
            "contract_activity": activity_rows,
        },
        "term_structure": term_structure,
        "factor_signals": {
            "states": factor_signals,
            "multi_factor": multi_factor,
            "main_returns": main_metrics["returns"],
            "ma20": main_metrics["ma20"],
        },
        "trend_phase": trend_phase.to_summary(),
        "trend_rule_context": trend_rule_context,
        "signal_matrix_context": signal_matrix_context,
        "signal_threshold_context": signal_threshold_context,
        "watch_items": _watch_items(
            factor_signals=factor_signals,
            multi_factor=multi_factor,
            trend_phase=trend_phase,
            main_metrics=main_metrics,
        ),
        "research_boundary": {
            "no_future_return_labels": True,
            "forward_return_validation": "未完成 forward-return 验证",
            "trading_instruction": "不构成交易指令",
        },
    }


def _build_warnings(
    *,
    run_id: str,
    trade_date: date,
    main_metrics: dict[str, object],
    term_structure: dict[str, object],
    factor_signals: dict[str, SignalDirection],
    trend_rule_context: dict[str, object],
    signal_matrix_context: dict[str, object],
    signal_threshold_context: dict[str, object],
    snapshot_ids: tuple[str, ...],
) -> list[LatestSignalWarningRecord]:
    warnings = [
        _warning(
            run_id=run_id,
            trade_date=trade_date,
            section="research_boundary",
            severity=INFO_SEVERITY,
            warning_code="LATEST_SIGNAL_ONLY_NO_FORWARD_RETURN",
            warning_message="最新观察报告未包含未来收益标签，未完成 forward-return 验证。",
            human_review_required=(),
            input_snapshot_ids=snapshot_ids,
        ),
        _warning(
            run_id=run_id,
            trade_date=trade_date,
            section="interpretation",
            severity=WARNING_SEVERITY,
            warning_code="LATEST_SIGNAL_HUMAN_REVIEW_REQUIRED",
            warning_message="最新日信号、阈值和趋势阶段仍需人工复核。",
            human_review_required=HUMAN_REVIEW_REQUIRED,
            input_snapshot_ids=snapshot_ids,
        ),
    ]
    returns = main_metrics["returns"]
    assert isinstance(returns, dict)
    missing_horizons = [horizon for horizon, value in returns.items() if value is None]
    if missing_horizons:
        warnings.append(
            _warning(
                run_id=run_id,
                trade_date=trade_date,
                section="factor_signals",
                severity=WARNING_SEVERITY,
                warning_code="LATEST_SIGNAL_LOOKBACK_INCOMPLETE",
                warning_message=f"主力合约缺少回看窗口：{','.join(missing_horizons)}。",
                human_review_required=("factor_thresholds",),
                input_snapshot_ids=snapshot_ids,
            )
        )
    if term_structure.get("far_contract") is None:
        warnings.append(
            _warning(
                run_id=run_id,
                trade_date=trade_date,
                section="term_structure",
                severity=WARNING_SEVERITY,
                warning_code="LATEST_SIGNAL_FAR_LEG_MISSING",
                warning_message="最新日未找到主力之后的远月合约，curve/carry 信号不完整。",
                human_review_required=("contract_rule_assumptions",),
                input_snapshot_ids=snapshot_ids,
            )
        )
    unknown_signals = [name for name, state in factor_signals.items() if state == "unknown"]
    if unknown_signals:
        warnings.append(
            _warning(
                run_id=run_id,
                trade_date=trade_date,
                section="factor_signals",
                severity=WARNING_SEVERITY,
                warning_code="LATEST_SIGNAL_FACTOR_UNKNOWN",
                warning_message="存在无法判定的最新日信号：" + ",".join(unknown_signals),
                human_review_required=("factor_thresholds",),
                input_snapshot_ids=snapshot_ids,
            )
        )
    candidate_path = trend_rule_context.get("candidate_path")
    candidate_status = str(trend_rule_context.get("candidate_status"))
    if candidate_path is not None:
        warnings.append(
            _warning(
                run_id=run_id,
                trade_date=trade_date,
                section="trend_rule_context",
                severity=INFO_SEVERITY,
                warning_code="R28_TREND_RULE_CONTEXT_CANDIDATE_ONLY",
                warning_message="R28 只把 R27 候选规则用于日报解释，不构成交易规则或交易指令。",
                human_review_required=("trend_rule_candidate_thresholds", "daily_brief_wording"),
                input_snapshot_ids=snapshot_ids,
            )
        )
    if candidate_status in {"WATCH_CANDIDATE", "INSUFFICIENT_SAMPLE", "NO_SAMPLE", "NOT_FOUND"}:
        warnings.append(
            _warning(
                run_id=run_id,
                trade_date=trade_date,
                section="trend_rule_context",
                severity=WARNING_SEVERITY,
                warning_code="R28_TREND_RULE_CONTEXT_WATCH_ONLY",
                warning_message="当前阶段切换未达到可解释候选条件，仅能作为观察项。",
                human_review_required=("trend_rule_candidate_thresholds", "daily_brief_wording"),
                input_snapshot_ids=snapshot_ids,
            )
        )
    if signal_matrix_context.get("status") == "PROVIDED":
        warnings.append(
            _warning(
                run_id=run_id,
                trade_date=trade_date,
                section="signal_matrix_context",
                severity=INFO_SEVERITY,
                warning_code="R38_SIGNAL_MATRIX_CONTEXT_ONLY",
                warning_message="R38 只把 R35 多周期信号矩阵作为最新日报解释上下文。",
                human_review_required=("signal_matrix_weighting", "factor_thresholds"),
                input_snapshot_ids=snapshot_ids,
            )
        )
    if signal_threshold_context.get("status") == "PROVIDED":
        warnings.append(
            _warning(
                run_id=run_id,
                trade_date=trade_date,
                section="signal_threshold_context",
                severity=INFO_SEVERITY,
                warning_code="R39_THRESHOLD_CONTEXT_CANDIDATE_ONLY",
                warning_message="R39 只把 R37 阈值/权重候选作为日报解释，不构成交易规则。",
                human_review_required=("factor_thresholds", "signal_matrix_weighting"),
                input_snapshot_ids=snapshot_ids,
            )
        )
        if signal_threshold_context.get("horizon_alignment_status") == "ALTERNATE_ONLY":
            warnings.append(
                _warning(
                    run_id=run_id,
                    trade_date=trade_date,
                    section="signal_threshold_context",
                    severity=WARNING_SEVERITY,
                    warning_code="R40_THRESHOLD_ALTERNATE_HORIZON_REFERENCE",
                    warning_message=(
                        "R40 仅发现非主观察周期的阈值/权重候选，不能替代主周期确认。"
                    ),
                    human_review_required=("factor_thresholds", "signal_matrix_weighting"),
                    input_snapshot_ids=snapshot_ids,
                )
            )
    return warnings


def _warning(
    *,
    run_id: str,
    trade_date: date,
    section: str,
    severity: str,
    warning_code: str,
    warning_message: str,
    human_review_required: tuple[str, ...],
    input_snapshot_ids: tuple[str, ...],
) -> LatestSignalWarningRecord:
    return LatestSignalWarningRecord(
        run_id=run_id,
        trade_date=trade_date,
        section=section,
        severity=severity,
        warning_code=warning_code,
        warning_message=warning_message,
        human_review_required=human_review_required,
        input_snapshot_ids=input_snapshot_ids,
    )


def _trend_rule_markdown_lines(*, trend_rule_context: object) -> list[str]:
    context = trend_rule_context
    assert isinstance(context, dict)
    previous_code = context.get("previous_phase_code")
    previous_label = context.get("previous_phase_label")
    transition_code = context.get("transition_code")
    candidate_status = context.get("candidate_status")
    lines = [
        f"- 前一交易日阶段：`{_phase_text(previous_code, previous_label)}`",
        f"- 阶段切换：`{transition_code or '未发生阶段切换'}`",
    ]
    if candidate_status == "READY_CANDIDATE":
        lines.append(f"- {context.get('explanation_cn')}")
        lines.append(
            "- 聚合证据："
            f"样本 `{_fmt_optional_int(context.get('observation_count'))}`，"
            f"命中率 `{_fmt_percent(context.get('directional_hit_rate'))}`，"
            f"聚合收益均值 `{_fmt_percent(context.get('mean_forward_return'))}`，"
            f"参考 horizon `{_fmt_optional_int(context.get('selected_horizon'))}`。"
        )
    elif candidate_status == "NOT_PROVIDED":
        lines.append("- R27 候选规则：未接入候选规则表，本节仅展示 R24 当前阶段。")
    elif candidate_status == "NO_PREVIOUS_PHASE":
        lines.append("- R27 候选规则：缺少前一交易日阶段，暂不能形成阶段切换解释。")
    elif candidate_status == "NO_PHASE_CHANGE":
        lines.append("- R27 候选规则：阶段未切换，候选规则不适用于本交易日。")
    elif candidate_status == "NOT_FOUND":
        lines.append("- R27 候选规则：候选表中没有匹配该阶段切换的记录，仅作观察。")
    else:
        lines.append(f"- {context.get('explanation_cn')}")
    lines.append(f"- 研究边界：{context.get('research_boundary')}")
    return lines


def _signal_matrix_markdown_lines(*, signal_matrix_context: dict[str, object]) -> list[str]:
    rows = signal_matrix_context.get("rows")
    assert isinstance(rows, list)
    lines = [
        "",
        "## 六、多周期信号矩阵",
        "",
        f"- 矩阵路径：`{signal_matrix_context.get('signal_matrix_path')}`",
        f"- 主观察 horizon：`{signal_matrix_context.get('primary_horizon')}`",
        f"- 主观察方向：`{_signal_cn(signal_matrix_context.get('primary_direction'))}`",
        f"- 主观察置信度：`{signal_matrix_context.get('primary_confidence')}`",
        "",
        "| Horizon | 方向 | 期权过滤 | 置信分 | 阶段 | 证据等级 | 操作类型 | 风险标签 |",
        "| ---: | --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for row in sorted(rows, key=lambda item: int(item.get("horizon") or 0)):
        assert isinstance(row, dict)
        phase = f"{row.get('trend_phase')} {row.get('trend_phase_label')}"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("horizon")),
                    _signal_cn(row.get("direction")),
                    str(row.get("option_signal") or "not_connected"),
                    _fmt_number(row.get("confidence_score")),
                    phase,
                    str(row.get("evidence_level")),
                    str(row.get("action_type")),
                    str(row.get("warning_flags")),
                ]
            )
            + " |"
        )
    lines.append(f"- 研究边界：{signal_matrix_context.get('research_boundary')}")
    return lines


def _signal_threshold_markdown_lines(
    *,
    signal_threshold_context: dict[str, object],
) -> list[str]:
    candidates = signal_threshold_context.get("matched_candidates")
    alternate_candidates = signal_threshold_context.get("alternate_candidates")
    assert isinstance(candidates, list)
    assert isinstance(alternate_candidates, list)
    lines = [
        "",
        "## 七、阈值与权重候选",
        "",
        f"- 候选路径：`{signal_threshold_context.get('signal_threshold_research_path')}`",
        f"- 主观察 horizon：`{signal_threshold_context.get('primary_horizon')}`",
        f"- 周期对齐状态：`{signal_threshold_context.get('horizon_alignment_status')}`",
        f"- 解释：{signal_threshold_context.get('explanation_cn')}",
        "",
        "### 主观察周期候选",
        "",
        "| 方案 | 状态 | 样本 | 覆盖率 | 平均后验收益 | 方向命中率 |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    if candidates:
        for row in candidates:
            assert isinstance(row, dict)
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row.get("scheme_label_cn")),
                        str(row.get("candidate_status")),
                        str(row.get("observation_count")),
                        _fmt_percent(row.get("coverage_rate")),
                        _fmt_percent(row.get("mean_forward_return")),
                        _fmt_percent(row.get("directional_hit_rate")),
                    ]
                )
                + " |"
            )
    else:
        lines.append("| 暂无匹配 READY/WATCH 候选 | - | 0 | - | - | - |")
    if alternate_candidates:
        lines.extend(
            [
                "",
                "### 非主周期参考候选",
                "",
                "- 下列候选与主观察 horizon 不一致，只能提示跨周期历史证据，不能替代主周期确认。",
                "",
                "| 周期 | 方案 | 状态 | 样本 | 覆盖率 | 平均后验收益 | 方向命中率 |",
                "| ---: | --- | --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in alternate_candidates:
            assert isinstance(row, dict)
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row.get("horizon")),
                        str(row.get("scheme_label_cn")),
                        str(row.get("candidate_status")),
                        str(row.get("observation_count")),
                        _fmt_percent(row.get("coverage_rate")),
                        _fmt_percent(row.get("mean_forward_return")),
                        _fmt_percent(row.get("directional_hit_rate")),
                    ]
                )
                + " |"
            )
    lines.append(f"- 研究边界：{signal_threshold_context.get('research_boundary')}")
    return lines


def _write_markdown(*, result: LatestSignalBriefResult) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    summary = result.summary
    data_status = summary["data_status"]  # type: ignore[index]
    market = summary["market_facts"]  # type: ignore[index]
    term = summary["term_structure"]  # type: ignore[index]
    factors = summary["factor_signals"]  # type: ignore[index]
    trend = summary["trend_phase"]  # type: ignore[index]
    trend_rule = summary["trend_rule_context"]  # type: ignore[index]
    signal_matrix = summary["signal_matrix_context"]  # type: ignore[index]
    signal_threshold = summary["signal_threshold_context"]  # type: ignore[index]
    lines = [
        f"# CF 最新交易日研究观察 - {result.trade_date.isoformat()}",
        "",
        "## 一、数据状态",
        "",
        "- 报告类型：`latest_signal_only`",
        f"- 数据截至：`{data_status['data_asof']}`",
        f"- Run ID：`{result.run_id}`",
        f"- 核心表：`{data_status['core_quote_path']}`",
        f"- 最新日行数：`{data_status['latest_row_count']}`",
        "- 是否包含未来收益标签：`否`",
        "- 是否完成 forward-return 验证：`否`",
        "",
        "## 二、市场事实",
        "",
        f"- 主力合约：`{market['main_contract']}`",
        f"- 主力结算价：`{_fmt_number(market['main_settle'])}`",
        f"- 主力成交量：`{_fmt_number(market['main_volume'])}`",
        f"- 主力持仓量：`{_fmt_number(market['main_open_interest'])}`",
        f"- 主力持仓变化：`{_fmt_number(market['main_oi_change'])}`",
        "",
        "| 排名 | 合约 | 结算价 | 单日变化 | 单日收益 | 成交量 | 持仓量 | 持仓变化 |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in market["contract_activity"]:  # type: ignore[index]
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["rank"]),
                    str(row["contract_code"]),
                    _fmt_number(row["settle"]),
                    _fmt_number(row["settle_change"]),
                    _fmt_percent(row["settle_return"]),
                    _fmt_number(row["volume"]),
                    _fmt_number(row["open_interest"]),
                    _fmt_number(row["oi_change"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 三、期限结构",
            "",
            f"- 近月合约：`{term['near_contract']}`",
            f"- 主力-近月价差：`{_fmt_number(term['main_minus_near'])}`",
            f"- 远月合约：`{term['far_contract']}`",
            f"- 远月-主力价差：`{_fmt_number(term['far_minus_main'])}`",
            f"- 曲线斜率 proxy：`{_fmt_percent(term['curve_slope'])}`",
            f"- carry annualized proxy：`{_fmt_percent(term['carry_annualized'])}`",
            "",
            "## 四、因子信号",
            "",
            "| 信号 | 状态 |",
            "| --- | --- |",
        ]
    )
    states = factors["states"]  # type: ignore[index]
    for name in ("momentum", "carry", "curve", "oi_pressure"):
        lines.append(f"| {name} | {_signal_cn(states[name])} |")
    multi = factors["multi_factor"]  # type: ignore[index]
    lines.extend(
        [
            "",
            f"- 多因子方向：`{_signal_cn(multi['direction'])}`",
            f"- 多因子分数：`{multi['score']}`",
            f"- 多因子置信度：`{multi['confidence']}`",
            "",
            "## 五、趋势阶段",
            "",
            f"- 阶段：`{trend['phase_code']} {trend['phase_label']}`",
            f"- 方向：`{_signal_cn(trend['direction'])}`",
            f"- 置信度：`{trend['confidence']}`",
            f"- 判断依据：{trend['reason']}",
        ]
    )
    lines.extend(_trend_rule_markdown_lines(trend_rule_context=trend_rule))
    if isinstance(signal_matrix, dict) and signal_matrix.get("status") == "PROVIDED":
        lines.extend(_signal_matrix_markdown_lines(signal_matrix_context=signal_matrix))
        if isinstance(signal_threshold, dict) and signal_threshold.get("status") == "PROVIDED":
            lines.extend(_signal_threshold_markdown_lines(signal_threshold_context=signal_threshold))
            watch_heading = "## 八、明日观察清单"
            boundary_heading = "## 九、研究边界"
            review_heading = "## 十、人工复核项"
        else:
            watch_heading = "## 七、明日观察清单"
            boundary_heading = "## 八、研究边界"
            review_heading = "## 九、人工复核项"
    else:
        watch_heading = "## 六、明日观察清单"
        boundary_heading = "## 七、研究边界"
        review_heading = "## 八、人工复核项"
    lines.extend(
        [
            "",
            watch_heading,
            "",
        ]
    )
    lines.extend(f"- {item}" for item in summary["watch_items"])  # type: ignore[index]
    lines.extend(
        [
            "",
            boundary_heading,
            "",
            "- 本报告未包含未来收益标签。",
            "- 本报告未完成 forward-return 验证。",
            "- 本报告不构成交易指令。",
            "- 最新日信号、因子阈值、趋势阶段和合约规则仍需人工复核。",
            "",
            review_heading,
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_json(*, result: LatestSignalBriefResult) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **result.to_summary(),
        "summary": result.summary,
        "warnings": [warning.to_csv_row() for warning in result.warning_records],
    }
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_warning_csv(
    *,
    warnings: tuple[LatestSignalWarningRecord, ...],
    csv_path: Path,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows([warning.to_csv_row() for warning in warnings])


def _write_manifest(*, result: LatestSignalBriefResult) -> None:
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": result.run_id,
        "product_code": result.product_code,
        "report_type": "latest_signal_only",
        "rule_version": LATEST_SIGNAL_RULE_VERSION,
        "data_asof": result.data_asof.isoformat(),
        "generated_at": utc_now().isoformat(),
        "no_lookahead": True,
        "contains_forward_return_validation": False,
        "core_quote_path": str(result.core_quote_path),
        "trend_rule_candidate_path": (
            None
            if result.trend_rule_candidate_path is None
            else str(result.trend_rule_candidate_path)
        ),
        "signal_matrix_path": (
            None if result.signal_matrix_path is None else str(result.signal_matrix_path)
        ),
        "signal_threshold_research_path": (
            None
            if result.signal_threshold_research_path is None
            else str(result.signal_threshold_research_path)
        ),
        "trend_rule_context": result.summary.get("trend_rule_context"),
        "signal_matrix_context": result.summary.get("signal_matrix_context"),
        "signal_threshold_context": result.summary.get("signal_threshold_context"),
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
        "markdown": output_dir / "latest_signal_brief.md",
        "json": output_dir / "latest_signal_brief.json",
        "warning_csv": output_dir / "latest_signal_brief_warnings.csv",
        "manifest": output_dir / "manifest.json",
    }


def _watch_items(
    *,
    factor_signals: dict[str, SignalDirection],
    multi_factor: dict[str, object],
    trend_phase: TrendPhaseResult,
    main_metrics: dict[str, object],
) -> list[str]:
    items: list[str] = []
    latest_return = _float_or_none(main_metrics["returns"].get("1"))  # type: ignore[union-attr]
    oi_pressure = _float_or_none(main_metrics["oi_pressure"])
    if (
        latest_return is not None
        and latest_return > 0
        and oi_pressure is not None
        and oi_pressure > 0
    ):
        items.append("观察上涨增仓能否继续延续，避免单日修复后回落。")
    if factor_signals.get("momentum") == "short" and multi_factor.get("direction") == "long":
        items.append("动量仍偏空但结构信号偏多，重点观察动量是否翻正。")
    if trend_phase.phase_code == "S1":
        items.append("当前处于起点观察，需继续确认价格、持仓与曲线结构是否共振。")
    elif trend_phase.phase_code == "S3":
        items.append("当前处于衰竭观察，重点检查价格与持仓是否背离。")
    elif trend_phase.phase_code == "S4":
        items.append("当前出现终点确认或反向风险，需降低对原方向信号的置信度。")
    if not items:
        items.append("信号尚未形成强共振，保持观察并等待更多交易日确认。")
    items.append("本报告不含未来收益验证，完整历史证据仍需查看 R20/R16/R18 产物。")
    return items


def _human_review_required(
    warnings: tuple[LatestSignalWarningRecord, ...],
) -> tuple[str, ...]:
    values = list(HUMAN_REVIEW_REQUIRED)
    values.extend(item for warning in warnings for item in warning.human_review_required)
    return tuple(_unique_values(values))


def _direction(value: object) -> SignalDirection:
    numeric = _float_or_none(value)
    if numeric is None:
        return "unknown"
    if numeric > 0:
        return "long"
    if numeric < 0:
        return "short"
    return "neutral"


def _oi_direction(
    *,
    latest_return: float | None,
    oi_pressure: float | None,
) -> SignalDirection:
    if latest_return is None or oi_pressure is None:
        return "unknown"
    if oi_pressure > 0 and latest_return > 0:
        return "long"
    if oi_pressure > 0 and latest_return < 0:
        return "short"
    if oi_pressure < 0:
        return "neutral"
    return "neutral"


def _spread(main_settle: float | None, row: object | None) -> float | None:
    if main_settle is None or row is None:
        return None
    settle = _float_or_none(row["settle"])
    return None if settle is None else main_settle - settle


def _delivery_date(*, contract_code: str, trade_date: date) -> date:
    suffix = contract_code.strip().upper().removeprefix(PRODUCT_CODE)
    if len(suffix) != 3 or not suffix.isdigit():
        raise ResearchWorkbenchError(f"unsupported CF contract code: {contract_code}")
    year_digit = int(suffix[0])
    month = int(suffix[1:])
    candidates = [
        year
        for year in range(trade_date.year - 1, trade_date.year + 3)
        if year % 10 == year_digit
    ]
    if not candidates:
        raise ResearchWorkbenchError(
            f"cannot infer delivery year for {contract_code} near {trade_date.year}"
        )
    year = min(candidates, key=lambda item: (abs(item - trade_date.year), item < trade_date.year))
    return date(year, month, 1)


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    if pd.isna(value):
        return None
    return float(value)


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    if pd.isna(value):
        return None
    return int(value)


def _none_if_missing(value: object) -> object | None:
    if value is None:
        return None
    if pd.isna(value):
        return None
    return value


def _fmt_number(value: object) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "NA"
    if abs(numeric - round(numeric)) < 1e-9:
        return f"{numeric:.0f}"
    return f"{numeric:.4f}"


def _fmt_percent(value: object) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "NA"
    return f"{numeric:.2%}"


def _fmt_optional_int(value: object) -> str:
    numeric = _int_or_none(value)
    return "NA" if numeric is None else str(numeric)


def _phase_text(phase_code: object, phase_label: object) -> str:
    if phase_code is None:
        return "NA"
    if phase_label is None:
        return str(phase_code)
    return f"{phase_code} {phase_label}"


def _signal_cn(value: object) -> str:
    return {
        "long": "偏多",
        "short": "偏空",
        "neutral": "中性",
        "unknown": "未知",
    }.get(str(value), str(value))


def _unique_values(values: object) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value)
        if text and text not in result:
            result.append(text)
    return result


def _default_run_id(trade_date: date) -> str:
    timestamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    suffix = uuid.uuid4().hex[:8]
    return f"r23_latest_signal_{PRODUCT_CODE}_{trade_date.isoformat()}_{timestamp}_{suffix}"
