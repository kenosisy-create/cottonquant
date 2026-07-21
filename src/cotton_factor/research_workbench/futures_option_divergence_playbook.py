"""R71 futures-option divergence playbook for CF research review."""

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
from cotton_factor.research_workbench.futures_option_divergence import (
    FUTURES_OPTION_DIVERGENCE_VERSION,
)

PRODUCT_CODE = "CF"
FUTURES_OPTION_DIVERGENCE_PLAYBOOK_VERSION = (
    "R71_futures_option_divergence_playbook_v1"
)
OUTPUT_DIR = "futures_option_divergence_playbook"
DEFAULT_MIN_SAMPLE_SIZE = 30
DEFAULT_EDGE_THRESHOLD = 0.08
INFO_SEVERITY = "INFO"
WARN_SEVERITY = "WARN"
HUMAN_REVIEW_REQUIRED = (
    "futures_option_divergence_interpretation",
    "node_sample_size",
    "recent_stability_drift",
    "option_proxy_interpretation",
    "publish_wording",
)

REQUIRED_EVENT_COLUMNS = {
    "trade_date",
    "horizon",
    "main_contract",
    "futures_direction",
    "option_direction",
    "divergence_type",
    "option_signal",
    "trend_phase",
    "confidence",
    "winner_label",
    "forward_label_available",
}

REQUIRED_NODE_COLUMNS = {
    "divergence_type",
    "trend_phase",
    "confidence",
    "option_signal",
    "iv_rank_bucket",
    "skew_bucket",
    "pcr_bucket",
    "oi_signal",
    "sample_count",
    "futures_win_rate",
    "options_win_rate",
    "avg_futures_directional_forward_return",
    "average_resolution_horizon",
    "dominant_winner_label",
    "recent_stability",
    "evidence_level",
}

WARNING_COLUMNS = (
    "run_id",
    "section",
    "severity",
    "warning_code",
    "warning_message",
    "affected_count",
    "human_review_required",
)


@dataclass(frozen=True)
class FuturesOptionDivergencePlaybookWarningRecord:
    """Warning row for R71 playbook output."""

    run_id: str
    section: str
    severity: str
    warning_code: str
    warning_message: str
    affected_count: int
    human_review_required: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-safe warning summary."""
        return {
            "run_id": self.run_id,
            "section": self.section,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "affected_count": self.affected_count,
            "human_review_required": list(self.human_review_required),
        }

    def to_csv_row(self) -> dict[str, str]:
        """Return a CSV row."""
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
class ResearchFuturesOptionDivergencePlaybookResult:
    """Result of building the R71 futures-option divergence playbook."""

    product_code: str
    run_id: str
    start: date
    end: date
    node_count: int
    ready_node_count: int
    directional_node_count: int
    current_mapping_count: int
    warning_records: tuple[FuturesOptionDivergencePlaybookWarningRecord, ...]
    event_path: Path
    node_summary_path: Path
    latest_signal_json_path: Path | None
    node_table_parquet_path: Path
    node_table_csv_path: Path
    current_mapping_parquet_path: Path
    current_mapping_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    human_review_required: tuple[str, ...]

    @property
    def warning_count(self) -> int:
        """Return non-info warning count."""
        return sum(1 for warning in self.warning_records if warning.severity != INFO_SEVERITY)

    def to_summary(self) -> dict[str, object]:
        """Return compact CLI output."""
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "node_count": self.node_count,
            "ready_node_count": self.ready_node_count,
            "directional_node_count": self.directional_node_count,
            "current_mapping_count": self.current_mapping_count,
            "warning_count": self.warning_count,
            "warnings": [warning.to_summary() for warning in self.warning_records],
            "event_path": str(self.event_path),
            "node_summary_path": str(self.node_summary_path),
            "latest_signal_json_path": (
                None
                if self.latest_signal_json_path is None
                else str(self.latest_signal_json_path)
            ),
            "node_table_parquet_path": str(self.node_table_parquet_path),
            "current_mapping_parquet_path": str(self.current_mapping_parquet_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "forward_returns_are_validation_labels": True,
            "trading_instruction": "not_a_trading_instruction",
            "human_review_required": list(self.human_review_required),
        }


def build_cf_futures_option_divergence_playbook(
    *,
    event_path: Path | None = None,
    node_summary_path: Path | None = None,
    latest_signal_json_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
) -> ResearchFuturesOptionDivergencePlaybookResult:
    """Build the R71 human-readable playbook from R69 outputs."""
    if min_sample_size <= 0:
        raise ResearchWorkbenchError("min_sample_size must be positive")
    if edge_threshold < 0:
        raise ResearchWorkbenchError("edge_threshold must be non-negative")

    resolved_event_path = event_path or _default_event_path()
    resolved_node_path = node_summary_path or _default_node_summary_path()
    resolved_latest_path = latest_signal_json_path or _default_latest_signal_path()

    events = _load_table(resolved_event_path, required=REQUIRED_EVENT_COLUMNS)
    nodes = _load_table(resolved_node_path, required=REQUIRED_NODE_COLUMNS)
    latest = _load_latest_signal(resolved_latest_path) if resolved_latest_path else None

    start = min(events["trade_date"])
    end = max(events["trade_date"])
    playbook_run_id = run_id or _default_run_id(start=start, end=end)

    node_rows = _node_playbook_rows(
        nodes=nodes,
        run_id=playbook_run_id,
        min_sample_size=min_sample_size,
        edge_threshold=edge_threshold,
    )
    current_rows = _current_mapping_rows(
        latest=latest,
        node_rows=node_rows,
        run_id=playbook_run_id,
        evidence_end=end,
    )
    warnings = _warning_records(
        run_id=playbook_run_id,
        latest=latest,
        evidence_end=end,
        current_rows=current_rows,
    )

    paths = _output_paths(start=start, end=end, output_dir=output_dir)
    markdown_path = _markdown_path(start=start, end=end, report_output_dir=report_output_dir)
    json_path = _json_path(start=start, end=end, report_output_dir=report_output_dir)
    result = ResearchFuturesOptionDivergencePlaybookResult(
        product_code=PRODUCT_CODE,
        run_id=playbook_run_id,
        start=start,
        end=end,
        node_count=len(node_rows),
        ready_node_count=sum(1 for row in node_rows if row["evidence_level"] == "READY"),
        directional_node_count=sum(
            1 for row in node_rows if row["divergence_type"] == "directional_divergence"
        ),
        current_mapping_count=len(current_rows),
        warning_records=warnings,
        event_path=resolved_event_path,
        node_summary_path=resolved_node_path,
        latest_signal_json_path=resolved_latest_path,
        node_table_parquet_path=paths["node_parquet"],
        node_table_csv_path=paths["node_csv"],
        current_mapping_parquet_path=paths["current_parquet"],
        current_mapping_csv_path=paths["current_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=markdown_path,
        json_path=json_path,
        manifest_path=paths["manifest"],
        human_review_required=HUMAN_REVIEW_REQUIRED,
    )

    _write_frame(
        pd.DataFrame(node_rows),
        result.node_table_parquet_path,
        result.node_table_csv_path,
    )
    _write_frame(
        pd.DataFrame(current_rows),
        result.current_mapping_parquet_path,
        result.current_mapping_csv_path,
    )
    _write_warnings(result.warning_csv_path, warnings)
    _write_markdown(result=result, node_rows=node_rows, current_rows=current_rows)
    _write_json(result=result, node_rows=node_rows, current_rows=current_rows)
    _write_manifest(result=result, min_sample_size=min_sample_size, edge_threshold=edge_threshold)
    return result


def _load_table(path: Path, *, required: set[str]) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"R71 input table not found: {path}")
    frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"R71 input missing columns: {missing}")
    if "trade_date" in frame.columns:
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    return frame


def _load_latest_signal(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    if not path.exists():
        raise ResearchWorkbenchError(f"latest signal JSON not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("data_asof") is None:
        raise ResearchWorkbenchError("latest signal JSON missing data_asof")
    return payload


def _node_playbook_rows(
    *,
    nodes: pd.DataFrame,
    run_id: str,
    min_sample_size: int,
    edge_threshold: float,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    working = nodes.copy()
    working["sample_count"] = pd.to_numeric(working["sample_count"], errors="coerce").fillna(0)
    working = working.sort_values(
        ["divergence_type", "evidence_level", "sample_count"],
        ascending=[True, True, False],
    )
    for index, item in enumerate(working.to_dict(orient="records"), start=1):
        # R71 只解释 R69 已经计算好的节点，不重新贴胜负标签，避免改变研究口径。
        interpretation = _node_interpretation(
            item,
            min_sample_size=min_sample_size,
            edge_threshold=edge_threshold,
        )
        rows.append(
            {
                "run_id": run_id,
                "product_code": PRODUCT_CODE,
                "node_id": f"R71_NODE_{index:04d}",
                "divergence_type": str(item.get("divergence_type")),
                "trend_phase": str(item.get("trend_phase")),
                "confidence": str(item.get("confidence")),
                "option_signal": str(item.get("option_signal")),
                "iv_rank_bucket": str(item.get("iv_rank_bucket")),
                "skew_bucket": str(item.get("skew_bucket")),
                "pcr_bucket": str(item.get("pcr_bucket")),
                "oi_signal": str(item.get("oi_signal")),
                "sample_count": int(item.get("sample_count") or 0),
                "futures_win_rate": _float_or_none(item.get("futures_win_rate")),
                "options_win_rate": _float_or_none(item.get("options_win_rate")),
                "winner_edge": _winner_edge(item),
                "avg_futures_directional_forward_return": _float_or_none(
                    item.get("avg_futures_directional_forward_return")
                ),
                "average_resolution_horizon": _float_or_none(
                    item.get("average_resolution_horizon")
                ),
                "dominant_winner_label": str(item.get("dominant_winner_label")),
                "recent_stability": str(item.get("recent_stability")),
                "evidence_level": str(item.get("evidence_level")),
                "playbook_label": interpretation["playbook_label"],
                "playbook_label_cn": interpretation["playbook_label_cn"],
                "interpretation_cn": interpretation["interpretation_cn"],
                "review_focus_cn": interpretation["review_focus_cn"],
                "resolution_window_cn": _resolution_window_cn(
                    _float_or_none(item.get("average_resolution_horizon"))
                ),
                "forward_returns_are_validation_labels": True,
                "trading_instruction": "not_a_trading_instruction",
                "label_rule_version": FUTURES_OPTION_DIVERGENCE_PLAYBOOK_VERSION,
            }
        )
    if not rows:
        raise ResearchWorkbenchError("R71 found no node summary rows")
    return rows


def _node_interpretation(
    item: dict[str, object],
    *,
    min_sample_size: int,
    edge_threshold: float,
) -> dict[str, str]:
    divergence_type = str(item.get("divergence_type"))
    evidence_level = str(item.get("evidence_level"))
    recent_stability = str(item.get("recent_stability"))
    dominant = str(item.get("dominant_winner_label"))
    sample_count = int(item.get("sample_count") or 0)
    edge = _winner_edge(item)

    if sample_count < min_sample_size or evidence_level == "WEAK_OR_SMALL_SAMPLE":
        return {
            "playbook_label": "SMALL_SAMPLE_WATCH",
            "playbook_label_cn": "小样本观察",
            "interpretation_cn": "样本数不足，不能把胜率差异解释为稳定结构。",
            "review_focus_cn": "先复核样本来源、合约阶段和期权流动性，再决定是否继续观察。",
        }
    if divergence_type == "option_confirmation":
        label = (
            "OPTION_CONFIRMATION_READY"
            if evidence_level == "READY"
            else "OPTION_CONFIRMATION_WATCH"
        )
        return {
            "playbook_label": label,
            "playbook_label_cn": "期权同向确认" if evidence_level == "READY" else "同向确认观察",
            "interpretation_cn": "期权结构与期货方向同向，作为期货信号过滤器的对照组。",
            "review_focus_cn": "重点复核是否存在低波未定价、低流动性或临近到期扰动。",
        }
    if recent_stability == "DRIFT":
        return {
            "playbook_label": "RECENT_DRIFT_REVIEW",
            "playbook_label_cn": "近期漂移复核",
            "interpretation_cn": "长期样本与近期窗口存在漂移，不宜直接外推。",
            "review_focus_cn": "优先比较近期窗口与全样本差异，检查是否发生波动率 regime 切换。",
        }
    if dominant == "OPTIONS_WIN" and edge <= -edge_threshold:
        return {
            "playbook_label": "OPTIONS_SIDE_HISTORICALLY_VALIDATED",
            "playbook_label_cn": "期权方历史占优",
            "interpretation_cn": "历史上该结构更常由期权反向结构被后验价格验证。",
            "review_focus_cn": "复核 IV、PCR、skew 是否来自真实成交和持仓，而非低流动性噪音。",
        }
    if dominant == "FUTURES_WIN" and edge >= edge_threshold:
        return {
            "playbook_label": "FUTURES_SIDE_HISTORICALLY_VALIDATED",
            "playbook_label_cn": "期货方历史占优",
            "interpretation_cn": "历史上该结构更常由期货量价方向被后验价格验证。",
            "review_focus_cn": "复核期货持仓扩张、期限结构和趋势阶段是否仍然同向。",
        }
    return {
        "playbook_label": "MIXED_BATTLE_WATCH",
        "playbook_label_cn": "胜负混合观察",
        "interpretation_cn": "期货方与期权方胜率差异不足，当前只能作为矛盾观察节点。",
        "review_focus_cn": "等待下一交易日结构是否继续同向或快速解除背离。",
    }


def _current_mapping_rows(
    *,
    latest: dict[str, object] | None,
    node_rows: list[dict[str, object]],
    run_id: str,
    evidence_end: date,
) -> list[dict[str, object]]:
    if latest is None:
        return []
    context = latest.get("signal_matrix_context")
    rows = context.get("rows") if isinstance(context, dict) else []
    if not isinstance(rows, list):
        return []
    current_rows: list[dict[str, object]] = []
    data_asof = date.fromisoformat(str(latest["data_asof"])[:10])
    for item in rows:
        if not isinstance(item, dict):
            continue
        node_key = _latest_node_key(item)
        match = _best_node_match(node_key=node_key, node_rows=node_rows)
        current_rows.append(
            {
                "run_id": run_id,
                "product_code": PRODUCT_CODE,
                "data_asof": data_asof,
                "evidence_end": evidence_end,
                "horizon": int(item.get("horizon") or 0),
                "futures_direction": str(item.get("direction") or "unknown"),
                "option_direction": str(item.get("option_signal_direction") or "unknown"),
                "divergence_type": node_key["divergence_type"],
                "trend_phase": node_key["trend_phase"],
                "confidence": node_key["confidence"],
                "option_signal": node_key["option_signal"],
                "iv_rank_bucket": node_key["iv_rank_bucket"],
                "skew_bucket": node_key["skew_bucket"],
                "pcr_bucket": node_key["pcr_bucket"],
                "matched_node_id": None if match is None else match["node_id"],
                "matched_playbook_label": (
                    "NO_MATCHED_NODE" if match is None else match["playbook_label"]
                ),
                "matched_playbook_label_cn": (
                    "未匹配历史节点" if match is None else match["playbook_label_cn"]
                ),
                "matched_sample_count": 0 if match is None else match["sample_count"],
                "matched_futures_win_rate": None if match is None else match["futures_win_rate"],
                "matched_options_win_rate": None if match is None else match["options_win_rate"],
                "matched_average_resolution_horizon": (
                    None if match is None else match["average_resolution_horizon"]
                ),
                "current_mapping_boundary": (
                    "当前最新日只做结构映射，不进入 R69 胜负统计，"
                    "因为 forward_return 只能作为历史后验标签。"
                ),
                "forward_returns_are_validation_labels": True,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    return current_rows


def _latest_node_key(item: dict[str, object]) -> dict[str, str]:
    option_signal = str(item.get("option_signal") or "unknown")
    futures_direction = str(item.get("direction") or "unknown")
    option_direction = str(item.get("option_signal_direction") or "unknown")
    return {
        "divergence_type": _latest_divergence_type(
            option_signal=option_signal,
            futures_direction=futures_direction,
            option_direction=option_direction,
            iv_rank=_float_or_none(item.get("option_atm_iv_rank")),
        ),
        "trend_phase": str(item.get("trend_phase") or "unknown"),
        "confidence": str(item.get("confidence") or "unknown"),
        "option_signal": option_signal,
        "iv_rank_bucket": _iv_rank_bucket(_float_or_none(item.get("option_atm_iv_rank"))),
        "skew_bucket": _skew_bucket(_float_or_none(item.get("option_skew_proxy"))),
        "pcr_bucket": _pcr_bucket(
            _float_or_none(item.get("option_pcr_volume")),
            _float_or_none(item.get("option_pcr_oi")),
        ),
        "oi_signal": str(item.get("oi_signal") or "unknown"),
    }


def _latest_divergence_type(
    *,
    option_signal: str,
    futures_direction: str,
    option_direction: str,
    iv_rank: float | None,
) -> str:
    if option_signal == "volatility_risk":
        return "volatility_risk_override"
    if option_signal.startswith("diverge_") or (
        option_direction in {"long", "short"} and option_direction != futures_direction
    ):
        return "directional_divergence"
    if option_signal.startswith("confirm_"):
        return "option_confirmation"
    if option_signal in {"option_neutral", "option_watch"}:
        return "volatility_non_confirmation"
    if iv_rank is not None and iv_rank <= 0.10:
        return "volatility_non_confirmation"
    return "unknown"


def _best_node_match(
    *,
    node_key: dict[str, str],
    node_rows: list[dict[str, object]],
) -> dict[str, object] | None:
    candidates = []
    for row in node_rows:
        score = 0
        for key in (
            "divergence_type",
            "trend_phase",
            "confidence",
            "option_signal",
            "iv_rank_bucket",
            "skew_bucket",
            "pcr_bucket",
            "oi_signal",
        ):
            if str(row.get(key)) == node_key.get(key):
                score += 1
        if score >= 5 and str(row.get("divergence_type")) == node_key["divergence_type"]:
            candidates.append((score, int(row.get("sample_count") or 0), row))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True)[0][2]


def _warning_records(
    *,
    run_id: str,
    latest: dict[str, object] | None,
    evidence_end: date,
    current_rows: list[dict[str, object]],
) -> tuple[FuturesOptionDivergencePlaybookWarningRecord, ...]:
    records: list[FuturesOptionDivergencePlaybookWarningRecord] = [
        FuturesOptionDivergencePlaybookWarningRecord(
            run_id=run_id,
            section="research_boundary",
            severity=INFO_SEVERITY,
            warning_code="RESEARCH_ONLY_NOT_TRADING_INSTRUCTION",
            warning_message=(
                "R71 只解释 R69 背离节点，不修改 composite_score，"
                "不自动反转方向，也不构成交易指令。"
            ),
            affected_count=len(current_rows),
            human_review_required=("futures_option_divergence_interpretation",),
        )
    ]
    unmatched = sum(1 for row in current_rows if row["matched_node_id"] is None)
    if unmatched:
        records.append(
            FuturesOptionDivergencePlaybookWarningRecord(
                run_id=run_id,
                section="current_mapping",
                severity=WARN_SEVERITY,
                warning_code="CURRENT_STRUCTURE_WITHOUT_MATCHED_NODE",
                warning_message="部分最新结构没有匹配到足够相近的 R69 历史节点。",
                affected_count=unmatched,
                human_review_required=("node_sample_size", "option_proxy_interpretation"),
            )
        )
    if latest is not None:
        data_asof = date.fromisoformat(str(latest["data_asof"])[:10])
        if data_asof > evidence_end:
            records.append(
                FuturesOptionDivergencePlaybookWarningRecord(
                    run_id=run_id,
                    section="current_mapping",
                    severity=WARN_SEVERITY,
                    warning_code="CURRENT_SIGNAL_AFTER_EVIDENCE_END",
                    warning_message=(
                        "最新日只能做结构映射，不能进入 R69 胜负统计；"
                        "forward_return 仍需等待未来交易日形成后验标签。"
                    ),
                    affected_count=len(current_rows),
                    human_review_required=("forward_return_horizon_set",),
                )
            )
    return tuple(records)


def _winner_edge(item: dict[str, object]) -> float | None:
    futures = _float_or_none(item.get("futures_win_rate"))
    options = _float_or_none(item.get("options_win_rate"))
    if futures is None or options is None:
        return None
    return futures - options


def _resolution_window_cn(value: float | None) -> str:
    if value is None:
        return "暂无稳定解决周期"
    if value <= 3:
        return "短周期解决（约 1-3 个交易日）"
    if value <= 10:
        return "中短周期解决（约 4-10 个交易日）"
    if value <= 20:
        return "中周期解决（约 11-20 个交易日）"
    return "长周期解决（20 个交易日以上）"


def _float_or_none(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iv_rank_bucket(value: float | None) -> str:
    if value is None:
        return "iv_unknown"
    if value <= 0.10:
        return "iv_low_0_10"
    if value >= 0.80:
        return "iv_high_80_100"
    return "iv_normal"


def _skew_bucket(value: float | None) -> str:
    if value is None:
        return "skew_unknown"
    if value < -0.001:
        return "skew_put_discount_or_call_rich"
    if value > 0.001:
        return "skew_put_rich_or_call_discount"
    return "skew_neutral"


def _pcr_bucket(pcr_volume: float | None, pcr_oi: float | None) -> str:
    values = [value for value in (pcr_volume, pcr_oi) if value is not None]
    if not values:
        return "pcr_unknown"
    average = sum(values) / len(values)
    if average < 0.80:
        return "pcr_low"
    if average > 1.20:
        return "pcr_high"
    return "pcr_neutral"


def _write_frame(frame: pd.DataFrame, parquet_path: Path, csv_path: Path) -> None:
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False, encoding="utf-8-sig")


def _write_warnings(
    path: Path,
    warnings: tuple[FuturesOptionDivergencePlaybookWarningRecord, ...],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        for warning in warnings:
            writer.writerow(warning.to_csv_row())


def _write_markdown(
    *,
    result: ResearchFuturesOptionDivergencePlaybookResult,
    node_rows: list[dict[str, object]],
    current_rows: list[dict[str, object]],
) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    directional_ready = [
        row
        for row in node_rows
        if row["divergence_type"] == "directional_divergence"
        and row["evidence_level"] == "READY"
    ][:12]
    confirmation = [
        row for row in node_rows if row["divergence_type"] == "option_confirmation"
    ][:8]
    lines = [
        f"# CF 期货-期权背离节点解释表 R71（{result.start} 至 {result.end}）",
        "",
        "## 数据状态",
        f"- 输入 R69 事件表：`{result.event_path}`",
        f"- 输入 R69 节点表：`{result.node_summary_path}`",
        f"- 最新映射输入：`{result.latest_signal_json_path}`",
        f"- 节点总数：`{result.node_count}`",
        f"- READY 节点数：`{result.ready_node_count}`",
        f"- 方向背离节点数：`{result.directional_node_count}`",
        "",
        "## 解释口径",
        "- R71 不重新计算胜负标签，只解释 R69 已生成的历史后验证据。",
        "- `forward_return` 仅为历史后验验证标签，不参与最新日信号生成。",
        "- 节点解释用于人审结构性矛盾，不修改 `composite_score`，不自动反转方向。",
        "",
        "## 方向背离节点手册",
        "| 节点 | 阶段 | 期权信号 | 样本 | 期货胜率 | 期权胜率 | 平均解决 | 解释标签 |",
        "| --- | --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for row in directional_ready:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["node_id"]),
                    str(row["trend_phase"]),
                    str(row["option_signal"]),
                    str(row["sample_count"]),
                    _fmt_percent(row["futures_win_rate"]),
                    _fmt_percent(row["options_win_rate"]),
                    str(row["resolution_window_cn"]),
                    str(row["playbook_label_cn"]),
                ]
            )
            + " |"
        )
    if not directional_ready:
        lines.append("| - | - | - | 0 | - | - | - | 暂无 READY 方向背离节点 |")
    lines.extend(
        [
            "",
            "## 期权确认对照组",
            "| 节点 | 阶段 | 期权信号 | 样本 | 期货跟随率 | 平均方向收益 | 解释标签 |",
            "| --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in confirmation:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["node_id"]),
                    str(row["trend_phase"]),
                    str(row["option_signal"]),
                    str(row["sample_count"]),
                    _fmt_percent(row["futures_win_rate"]),
                    _fmt_percent(row["avg_futures_directional_forward_return"]),
                    str(row["playbook_label_cn"]),
                ]
            )
            + " |"
        )
    if not confirmation:
        lines.append("| - | - | - | 0 | - | - | 暂无对照组 |")
    lines.extend(
        [
            "",
            "## 当前样本映射",
            "| 日期 | 周期 | 结构 | 阶段 | 匹配节点 | 样本 | 解释标签 | 平均解决 |",
            "| --- | ---: | --- | --- | --- | ---: | --- | --- |",
        ]
    )
    for row in current_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["data_asof"]),
                    f"{row['horizon']}D",
                    str(row["divergence_type"]),
                    str(row["trend_phase"]),
                    str(row["matched_node_id"]),
                    str(row["matched_sample_count"]),
                    str(row["matched_playbook_label_cn"]),
                    _fmt_number(row["matched_average_resolution_horizon"]),
                ]
            )
            + " |"
        )
    if not current_rows:
        lines.append("| - | - | - | - | - | 0 | 未接入 latest signal | - |")
    lines.extend(
        [
            "",
            "## 研究边界",
            "- 本报告不构成交易指令。",
            "- R71 不修改 `composite_score`，不把期权直接写入期货主模型权重。",
            "- R71 不自动反转做空；背离只作为结构性矛盾的人审线索。",
            "- 期权 PCR、ATM IV rank、skew 均为研究 proxy，需保留人工复核。",
            "",
            "## 人工复核项",
        ]
    )
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_json(
    *,
    result: ResearchFuturesOptionDivergencePlaybookResult,
    node_rows: list[dict[str, object]],
    current_rows: list[dict[str, object]],
) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "report_type": "futures_option_divergence_playbook",
        "rule_version": FUTURES_OPTION_DIVERGENCE_PLAYBOOK_VERSION,
        "generated_at": utc_now().isoformat(),
        "summary": result.to_summary(),
        "node_rows": node_rows,
        "current_mapping_rows": current_rows,
        "research_boundary": {
            "forward_returns_are_validation_labels": True,
            "auto_reverse_allowed": False,
            "trading_instruction": "not_a_trading_instruction",
            "option_iv_greek_is_proxy": True,
            "source_rule_version": FUTURES_OPTION_DIVERGENCE_VERSION,
        },
    }
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def _write_manifest(
    *,
    result: ResearchFuturesOptionDivergencePlaybookResult,
    min_sample_size: int,
    edge_threshold: float,
) -> None:
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": result.run_id,
        "product_code": PRODUCT_CODE,
        "artifact_type": "futures_option_divergence_playbook",
        "version": FUTURES_OPTION_DIVERGENCE_PLAYBOOK_VERSION,
        "created_at": utc_now().isoformat(),
        "parameters": {
            "min_sample_size": min_sample_size,
            "edge_threshold": edge_threshold,
        },
        "inputs": {
            "event_path": str(result.event_path),
            "node_summary_path": str(result.node_summary_path),
            "latest_signal_json_path": (
                None
                if result.latest_signal_json_path is None
                else str(result.latest_signal_json_path)
            ),
        },
        "outputs": result.to_summary(),
        "human_review_required": list(result.human_review_required),
    }
    result.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _fmt_percent(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2%}"


def _fmt_number(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2f}"


def _default_event_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "futures_option_divergence"
    matches = sorted(root.glob("*_futures_option_divergence_divergence_event_daily.parquet"))
    if not matches:
        raise ResearchWorkbenchError("no R69 futures-option divergence event table found")
    return matches[-1]


def _default_node_summary_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "futures_option_divergence"
    matches = sorted(root.glob("*_futures_option_divergence_summary_by_node.parquet"))
    if not matches:
        raise ResearchWorkbenchError("no R69 futures-option divergence node summary found")
    return matches[-1]


def _default_latest_signal_path() -> Path | None:
    root = project_root() / "runs" / "daily" / PRODUCT_CODE
    if not root.exists():
        return None
    matches = sorted(root.glob("*/latest_signal_brief.json"))
    return matches[-1] if matches else None


def _output_paths(start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_futures_option_playbook"
    return {
        "node_parquet": root / f"{stem}_node_table.parquet",
        "node_csv": root / f"{stem}_node_table.csv",
        "current_parquet": root / f"{stem}_current_mapping.parquet",
        "current_csv": root / f"{stem}_current_mapping.csv",
        "warning_csv": root / f"{stem}_warnings.csv",
        "manifest": root / f"{stem}_manifest.json",
    }


def _markdown_path(start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    return root / f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_futures_option_playbook.md"


def _json_path(start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    return (
        root
        / f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_futures_option_playbook.json"
    )


def _default_run_id(start: date, end: date) -> str:
    return f"r71_futures_option_playbook_{PRODUCT_CODE}_{start}_{end}_{uuid.uuid4().hex[:8]}"
