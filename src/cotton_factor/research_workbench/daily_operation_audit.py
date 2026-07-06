"""R34 daily operation audit for the CF research workbench."""

from __future__ import annotations

import csv
import json
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, project_root
from cotton_factor.common.time import utc_now
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME

PRODUCT_CODE = "CF"
DAILY_OPERATION_AUDIT_VERSION = "R34_daily_operation_audit_v1"
WARNING_SEVERITY = "WARN"
INFO_SEVERITY = "INFO"
HUMAN_REVIEW_REQUIRED = (
    "daily_operation_audit_wording",
    "latest_signal_interpretation",
    "trend_phase_rules",
    "trend_quality_calibration",
    "contract_rule_assumptions",
)

WARNING_COLUMNS = [
    "run_id",
    "trade_date",
    "section",
    "severity",
    "warning_code",
    "warning_message",
    "human_review_required",
]


@dataclass(frozen=True)
class DailyOperationAuditWarningRecord:
    """Warning row for the R34 daily operation audit."""

    run_id: str
    trade_date: date
    section: str
    severity: str
    warning_code: str
    warning_message: str
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
            "human_review_required": ";".join(self.human_review_required),
        }


@dataclass(frozen=True)
class ResearchDailyOperationAuditResult:
    """Result of building the R34 daily operation audit."""

    product_code: str
    run_id: str
    trade_date: date
    core_latest_trade_date: date | None
    latest_signal_json_path: Path
    trend_board_json_path: Path
    core_quote_path: Path | None
    markdown_path: Path
    json_path: Path
    warning_csv_path: Path
    manifest_path: Path
    audit: dict[str, object]
    warning_records: tuple[DailyOperationAuditWarningRecord, ...]
    human_review_required: tuple[str, ...]

    @property
    def warning_count(self) -> int:
        """Return non-info warning count."""
        return sum(1 for warning in self.warning_records if warning.severity != INFO_SEVERITY)

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI summary."""
        market = _dict_value(self.audit, "latest_market_observation")
        trend = _dict_value(self.audit, "trend_phase_and_quality")
        system_status = _dict_value(self.audit, "system_status")
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "trade_date": self.trade_date.isoformat(),
            "core_latest_trade_date": (
                None
                if self.core_latest_trade_date is None
                else self.core_latest_trade_date.isoformat()
            ),
            "main_contract": market.get("main_contract"),
            "signal_direction": market.get("signal_direction"),
            "trend_phase_code": trend.get("phase_code"),
            "trend_phase_label": trend.get("phase_label"),
            "trend_quality_score": trend.get("quality_score"),
            "trend_quality_label": trend.get("quality_label"),
            "operation_status": system_status.get("operation_status"),
            "research_ready": system_status.get("research_ready"),
            "warning_count": self.warning_count,
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "warning_csv_path": str(self.warning_csv_path),
            "manifest_path": str(self.manifest_path),
            "latest_signal_json_path": str(self.latest_signal_json_path),
            "trend_board_json_path": str(self.trend_board_json_path),
            "core_quote_path": None if self.core_quote_path is None else str(self.core_quote_path),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_daily_operation_audit(
    *,
    latest_signal_json_path: Path,
    trend_board_json_path: Path,
    core_quote_path: Path | None = None,
    output_root: Path | None = None,
    run_id: str | None = None,
) -> ResearchDailyOperationAuditResult:
    """Build a Chinese daily operation audit from existing latest-day artifacts."""
    latest_signal = _load_json(latest_signal_json_path)
    trend_board = _load_json(trend_board_json_path)
    trade_date = _resolve_trade_date(latest_signal=latest_signal, trend_board=trend_board)
    audit_run_id = run_id or _default_run_id(trade_date)
    quote_path = core_quote_path or data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    core_latest = _core_latest_trade_date(quote_path) if quote_path.exists() else None

    # R34 只做日更后的汇总审计，不重新计算研究信号，也不读取 R32 日级 forward_return 标签。
    audit = _build_audit(
        latest_signal=latest_signal,
        trend_board=trend_board,
        trade_date=trade_date,
        core_latest_trade_date=core_latest,
        core_quote_path=quote_path if quote_path.exists() else None,
    )
    warnings = tuple(
        _build_warnings(
            run_id=audit_run_id,
            trade_date=trade_date,
            latest_signal=latest_signal,
            trend_board=trend_board,
            core_latest_trade_date=core_latest,
        )
    )
    paths = _output_paths(trade_date=trade_date, output_root=output_root)
    result = ResearchDailyOperationAuditResult(
        product_code=PRODUCT_CODE,
        run_id=audit_run_id,
        trade_date=trade_date,
        core_latest_trade_date=core_latest,
        latest_signal_json_path=latest_signal_json_path,
        trend_board_json_path=trend_board_json_path,
        core_quote_path=quote_path if quote_path.exists() else None,
        markdown_path=paths["markdown"],
        json_path=paths["json"],
        warning_csv_path=paths["warning_csv"],
        manifest_path=paths["manifest"],
        audit=audit,
        warning_records=warnings,
        human_review_required=_human_review_required(warnings),
    )
    _write_markdown(result=result)
    _write_json(result=result)
    _write_warning_csv(warnings=warnings, csv_path=result.warning_csv_path)
    _write_manifest(result=result)
    return result


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ResearchWorkbenchError(f"required R34 input JSON not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ResearchWorkbenchError(f"R34 input JSON must be an object: {path}")
    return payload


def _resolve_trade_date(
    *,
    latest_signal: dict[str, Any],
    trend_board: dict[str, Any],
) -> date:
    signal_date = _parse_date(
        str(latest_signal.get("trade_date") or latest_signal.get("data_asof"))
    )
    board_date = _parse_date(str(trend_board.get("trade_date")))
    if signal_date != board_date:
        raise ResearchWorkbenchError(
            "latest signal brief and trend continuity board trade_date mismatch: "
            f"{signal_date.isoformat()} != {board_date.isoformat()}"
        )
    return signal_date


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ResearchWorkbenchError(f"invalid R34 trade date: {value}") from exc


def _core_latest_trade_date(path: Path) -> date:
    frame = pd.read_parquet(path, columns=["trade_date"])
    if frame.empty:
        raise ResearchWorkbenchError(f"core quote table is empty: {path}")
    values = pd.to_datetime(frame["trade_date"]).dt.date
    return max(values)


def _build_audit(
    *,
    latest_signal: dict[str, Any],
    trend_board: dict[str, Any],
    trade_date: date,
    core_latest_trade_date: date | None,
    core_quote_path: Path | None,
) -> dict[str, object]:
    latest_summary = _dict_value(latest_signal, "summary")
    factor_signals = _dict_value(latest_summary, "factor_signals")
    term_structure = _dict_value(latest_summary, "term_structure")
    trend_context = _dict_value(trend_board, "trend_quality_calibration_context")
    rows = trend_board.get("rows")
    latest_board_row = rows[-1] if isinstance(rows, list) and rows else {}
    if not isinstance(latest_board_row, dict):
        latest_board_row = {}

    watch_items = latest_summary.get("watch_items")
    if not isinstance(watch_items, list):
        watch_items = []

    return {
        "data_and_artifact_status": {
            "trade_date": trade_date.isoformat(),
            "core_latest_trade_date": (
                None if core_latest_trade_date is None else core_latest_trade_date.isoformat()
            ),
            "core_quote_path": None if core_quote_path is None else str(core_quote_path),
            "latest_signal_json_path": str(latest_signal.get("json_path")),
            "trend_board_json_path": str(trend_board.get("json_path")),
            "latest_signal_warning_count": latest_signal.get("warning_count", 0),
            "trend_board_warning_count": trend_board.get("warning_count", 0),
        },
        "latest_market_observation": {
            "main_contract": latest_signal.get("main_contract"),
            "signal_direction": latest_signal.get("signal_direction"),
            "factor_states": factor_signals.get("states"),
            "multi_factor": factor_signals.get("multi_factor"),
            "main_returns": factor_signals.get("main_returns"),
            "term_structure": {
                "near_contract": term_structure.get("near_contract"),
                "far_contract": term_structure.get("far_contract"),
                "main_minus_near": term_structure.get("main_minus_near"),
                "far_minus_main": term_structure.get("far_minus_main"),
                "carry_annualized": term_structure.get("carry_annualized"),
                "curve_slope": term_structure.get("curve_slope"),
            },
        },
        "trend_phase_and_quality": {
            "phase_code": trend_board.get("latest_phase_code"),
            "phase_label": trend_board.get("latest_phase_label"),
            "observation_marker": trend_board.get("latest_observation_marker"),
            "transition_code": trend_board.get("latest_transition_code"),
            "quality_score": trend_board.get("latest_trend_quality_score"),
            "quality_label": trend_board.get("latest_trend_quality_label"),
            "quality_reason": latest_board_row.get("trend_quality_reason"),
            "board_row_count": trend_board.get("row_count"),
        },
        "historical_calibration_context": {
            "context_status": trend_context.get("context_status", "NOT_PROVIDED"),
            "alignment_status": trend_context.get("alignment_status"),
            "latest_score_context_label": trend_context.get("latest_score_context_label"),
            "latest_score_percentile": trend_context.get("latest_score_percentile"),
            "interpretation_cn": trend_context.get("interpretation_cn"),
            "bucket_summary": trend_context.get("bucket_summary"),
        },
        "system_status": {
            "operation_status": "RUNNABLE_WITH_WARNINGS",
            "research_ready": True,
            "trading_instruction": False,
            "no_future_return_labels": True,
            "contains_forward_return_validation": False,
            "boundary_cn": "本审计摘要只用于日更核对和研究观察，不构成交易指令。",
        },
        "tomorrow_watch_list": watch_items,
        "research_boundary": {
            "未包含未来收益标签": True,
            "未完成 forward-return 验证": True,
            "不构成交易指令": True,
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        },
    }


def _build_warnings(
    *,
    run_id: str,
    trade_date: date,
    latest_signal: dict[str, Any],
    trend_board: dict[str, Any],
    core_latest_trade_date: date | None,
) -> list[DailyOperationAuditWarningRecord]:
    warnings: list[DailyOperationAuditWarningRecord] = []
    if core_latest_trade_date is None:
        warnings.append(
            _warning(
                run_id=run_id,
                trade_date=trade_date,
                section="data_status",
                severity=WARNING_SEVERITY,
                code="CORE_LATEST_DATE_NOT_CHECKED",
                message="未读取到 core 最新交易日，日更新鲜度需要人工复核。",
                human_review=("data_freshness",),
            )
        )
    elif core_latest_trade_date != trade_date:
        warnings.append(
            _warning(
                run_id=run_id,
                trade_date=trade_date,
                section="data_status",
                severity=WARNING_SEVERITY,
                code="CORE_LATEST_DATE_MISMATCH",
                message=(
                    "core 最新交易日与 R34 审计日期不一致："
                    f"{core_latest_trade_date.isoformat()} != {trade_date.isoformat()}。"
                ),
                human_review=("data_freshness",),
            )
        )
    signal_warning_count = _int_value(latest_signal.get("warning_count"))
    board_warning_count = _int_value(trend_board.get("warning_count"))
    if signal_warning_count > 0 or board_warning_count > 0:
        warnings.append(
            _warning(
                run_id=run_id,
                trade_date=trade_date,
                section="source_artifacts",
                severity=WARNING_SEVERITY,
                code="SOURCE_ARTIFACT_HAS_WARNINGS",
                message=(
                    "上游 R23/R29 产物存在 warning："
                    f"latest={signal_warning_count}, trend_board={board_warning_count}。"
                ),
                human_review=("source_warning_review",),
            )
        )
    calibration = _dict_value(trend_board, "trend_quality_calibration_context")
    if calibration.get("context_status") != "PROVIDED":
        warnings.append(
            _warning(
                run_id=run_id,
                trade_date=trade_date,
                section="calibration_context",
                severity=WARNING_SEVERITY,
                code="CALIBRATION_CONTEXT_NOT_PROVIDED",
                message="趋势质量历史校准上下文未接入，本日趋势质量只能作启发式观察。",
                human_review=("trend_quality_calibration",),
            )
        )
    elif calibration.get("alignment_status") not in {"MATCHED", "MATCHED_WITH_BUCKET"}:
        warnings.append(
            _warning(
                run_id=run_id,
                trade_date=trade_date,
                section="calibration_context",
                severity=WARNING_SEVERITY,
                code="CALIBRATION_CONTEXT_ALIGNMENT_REVIEW",
                message="趋势质量校准上下文与最新观察未完全匹配，需要人工复核。",
                human_review=("trend_quality_calibration",),
            )
        )
    warnings.append(
        _warning(
            run_id=run_id,
            trade_date=trade_date,
            section="research_boundary",
            severity=INFO_SEVERITY,
            code="DAILY_OPERATION_AUDIT_RESEARCH_ONLY",
            message="R34 未包含未来收益标签、未完成 forward-return 验证、不构成交易指令。",
            human_review=HUMAN_REVIEW_REQUIRED,
        )
    )
    return warnings


def _warning(
    *,
    run_id: str,
    trade_date: date,
    section: str,
    severity: str,
    code: str,
    message: str,
    human_review: tuple[str, ...],
) -> DailyOperationAuditWarningRecord:
    return DailyOperationAuditWarningRecord(
        run_id=run_id,
        trade_date=trade_date,
        section=section,
        severity=severity,
        warning_code=code,
        warning_message=message,
        human_review_required=human_review,
    )


def _write_markdown(*, result: ResearchDailyOperationAuditResult) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    data_status = _dict_value(result.audit, "data_and_artifact_status")
    market = _dict_value(result.audit, "latest_market_observation")
    trend = _dict_value(result.audit, "trend_phase_and_quality")
    calibration = _dict_value(result.audit, "historical_calibration_context")
    system_status = _dict_value(result.audit, "system_status")
    watch_items = result.audit.get("tomorrow_watch_list")
    if not isinstance(watch_items, list):
        watch_items = []

    lines = [
        f"# CF 日更运行审计摘要（{result.trade_date.isoformat()}）",
        "",
        "## 数据与产物状态",
        f"- core 最新交易日：{data_status.get('core_latest_trade_date')}",
        f"- latest signal brief：{result.latest_signal_json_path}",
        f"- trend continuity board：{result.trend_board_json_path}",
        "- 上游 warning 数："
        f"R23={data_status.get('latest_signal_warning_count')}；"
        f"R29/R33={data_status.get('trend_board_warning_count')}",
        "",
        "## 最新市场观察",
        f"- 主力合约：{market.get('main_contract')}",
        f"- 多因子方向：{market.get('signal_direction')}",
        f"- 因子状态：{_json_inline(market.get('factor_states'))}",
        f"- 主力收益变化：{_json_inline(market.get('main_returns'))}",
        f"- 期限结构：{_json_inline(market.get('term_structure'))}",
        "",
        "## 趋势阶段与质量",
        f"- 当前阶段：{trend.get('phase_code')} / {trend.get('phase_label')}",
        f"- 观察标记：{trend.get('observation_marker')}",
        f"- 趋势质量：{trend.get('quality_score')} / {trend.get('quality_label')}",
        f"- 质量解释：{trend.get('quality_reason')}",
        "",
        "## 历史校准上下文",
        f"- 接入状态：{calibration.get('context_status')}",
        f"- 匹配状态：{calibration.get('alignment_status')}",
        f"- 历史位置：{calibration.get('latest_score_context_label')}",
        f"- 校准解释：{calibration.get('interpretation_cn')}",
        "",
        "## 系统运行状态",
        f"- 运行状态：{system_status.get('operation_status')}",
        f"- 研究可用：{system_status.get('research_ready')}",
        "- 交易指令：否",
        "",
        "## 明日观察清单",
    ]
    if watch_items:
        lines.extend(f"- {item}" for item in watch_items)
    else:
        lines.append("- 暂无自动观察项，需人工复核最新盘口与期限结构。")
    lines.extend(
        [
            "",
            "## 研究边界与人工复核",
            "- 未包含未来收益标签。",
            "- 未完成 forward-return 验证。",
            "- 不构成交易指令。",
            "- 人工复核项：" + "、".join(result.human_review_required),
        ]
    )
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_json(*, result: ResearchDailyOperationAuditResult) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **result.to_summary(),
        "report_type": "daily_operation_audit",
        "rule_version": DAILY_OPERATION_AUDIT_VERSION,
        "no_future_return_labels": True,
        "contains_forward_return_validation": False,
        "audit": result.audit,
        "warnings": [warning.to_csv_row() for warning in result.warning_records],
    }
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_warning_csv(
    *,
    warnings: tuple[DailyOperationAuditWarningRecord, ...],
    csv_path: Path,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows([warning.to_csv_row() for warning in warnings])


def _write_manifest(*, result: ResearchDailyOperationAuditResult) -> None:
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": result.run_id,
        "product_code": result.product_code,
        "report_type": "daily_operation_audit",
        "rule_version": DAILY_OPERATION_AUDIT_VERSION,
        "data_asof": result.trade_date.isoformat(),
        "generated_at": utc_now().isoformat(),
        "no_lookahead": True,
        "contains_forward_return_validation": False,
        "core_latest_trade_date": (
            None
            if result.core_latest_trade_date is None
            else result.core_latest_trade_date.isoformat()
        ),
        "latest_signal_json_path": str(result.latest_signal_json_path),
        "trend_board_json_path": str(result.trend_board_json_path),
        "core_quote_path": None if result.core_quote_path is None else str(result.core_quote_path),
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
        "markdown": output_dir / "daily_operation_audit.md",
        "json": output_dir / "daily_operation_audit.json",
        "warning_csv": output_dir / "daily_operation_audit_warnings.csv",
        "manifest": output_dir / "daily_operation_audit_manifest.json",
    }


def _human_review_required(
    warnings: tuple[DailyOperationAuditWarningRecord, ...],
) -> tuple[str, ...]:
    values: list[str] = list(HUMAN_REVIEW_REQUIRED)
    for warning in warnings:
        values.extend(warning.human_review_required)
    return tuple(dict.fromkeys(values))


def _dict_value(payload: dict[str, Any] | dict[str, object], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _int_value(value: object) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _json_inline(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _default_run_id(trade_date: date) -> str:
    suffix = uuid.uuid4().hex[:8]
    return f"r34_daily_operation_audit_{trade_date:%Y%m%d}_{suffix}"
