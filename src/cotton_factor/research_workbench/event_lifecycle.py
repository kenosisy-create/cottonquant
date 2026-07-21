"""R68 event lifecycle labels for CF trend phase research."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.common.time import utc_now

PRODUCT_CODE = "CF"
EVENT_LIFECYCLE_VERSION = "R68_event_lifecycle_labeling_v1"
OUTPUT_DIR = "event_lifecycle"
DEFAULT_HORIZON = 20
DEFAULT_MAX_HOLDING_DAYS = 20
DEFAULT_PROFIT_BARRIER = 0.03
DEFAULT_STOP_LOSS_BARRIER = 0.015
HUMAN_REVIEW_REQUIRED = (
    "event_lifecycle_labeling_rules",
    "triple_barrier_parameters",
    "phase_transition_definition",
    "mfe_mae_interpretation",
)


@dataclass(frozen=True)
class ResearchEventLifecycleResult:
    """Result of building R68 event lifecycle artifacts."""

    product_code: str
    run_id: str
    start: date
    end: date
    horizon: int
    episode_count: int
    transition_count: int
    trigger_diagnostic_count: int
    s1_episode_count: int
    s1_success_count: int
    s1_failure_count: int
    tbm_label_count: int
    warning_count: int
    episode_parquet_path: Path
    episode_csv_path: Path
    transition_parquet_path: Path
    transition_csv_path: Path
    trigger_diagnostic_parquet_path: Path
    trigger_diagnostic_csv_path: Path
    tbm_parquet_path: Path
    tbm_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    json_path: Path
    manifest_path: Path
    signal_matrix_path: Path
    human_review_required: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI summary."""
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "horizon": self.horizon,
            "episode_count": self.episode_count,
            "transition_count": self.transition_count,
            "trigger_diagnostic_count": self.trigger_diagnostic_count,
            "s1_episode_count": self.s1_episode_count,
            "s1_success_count": self.s1_success_count,
            "s1_failure_count": self.s1_failure_count,
            "tbm_label_count": self.tbm_label_count,
            "warning_count": self.warning_count,
            "episode_parquet_path": str(self.episode_parquet_path),
            "transition_parquet_path": str(self.transition_parquet_path),
            "trigger_diagnostic_parquet_path": str(self.trigger_diagnostic_parquet_path),
            "tbm_parquet_path": str(self.tbm_parquet_path),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "signal_matrix_path": str(self.signal_matrix_path),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_event_lifecycle_research(
    *,
    signal_matrix_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    horizon: int = DEFAULT_HORIZON,
    max_holding_days: int = DEFAULT_MAX_HOLDING_DAYS,
    profit_barrier: float = DEFAULT_PROFIT_BARRIER,
    stop_loss_barrier: float = DEFAULT_STOP_LOSS_BARRIER,
) -> ResearchEventLifecycleResult:
    """Build R68 episode, transition, MFE/MAE and simple TBM labels."""
    if horizon <= 0:
        raise ResearchWorkbenchError("horizon must be positive")
    if max_holding_days <= 0:
        raise ResearchWorkbenchError("max_holding_days must be positive")
    if profit_barrier <= 0 or stop_loss_barrier <= 0:
        raise ResearchWorkbenchError("profit_barrier and stop_loss_barrier must be positive")
    matrix_path = signal_matrix_path or _default_signal_matrix_path()
    matrix = _load_signal_matrix(matrix_path=matrix_path, horizon=horizon)
    if matrix.empty:
        raise ResearchWorkbenchError("R68 signal matrix slice is empty")
    lifecycle_run_id = run_id or _default_run_id(
        start=matrix["trade_date"].min(),
        end=matrix["trade_date"].max(),
    )
    # R68 只使用 R35 已生成的逐日研究矩阵，避免绕开现有 raw/core/research 边界。
    episodes = _episode_rows(matrix=matrix, run_id=lifecycle_run_id)
    transitions = _transition_rows(episodes=episodes, run_id=lifecycle_run_id)
    trigger_diagnostics = _trigger_diagnostic_rows(
        matrix=matrix,
        episodes=episodes,
        run_id=lifecycle_run_id,
    )
    tbm_labels = _tbm_label_rows(
        matrix=matrix,
        episodes=episodes,
        run_id=lifecycle_run_id,
        max_holding_days=max_holding_days,
        profit_barrier=profit_barrier,
        stop_loss_barrier=stop_loss_barrier,
    )
    warnings = _warning_rows(
        run_id=lifecycle_run_id,
        episodes=episodes,
        transitions=transitions,
        tbm_labels=tbm_labels,
    )
    paths = _output_paths(
        start=matrix["trade_date"].min(),
        end=matrix["trade_date"].max(),
        output_dir=output_dir,
    )
    markdown_path = _markdown_path(
        start=matrix["trade_date"].min(),
        end=matrix["trade_date"].max(),
        report_output_dir=report_output_dir,
    )
    json_path = _json_path(
        start=matrix["trade_date"].min(),
        end=matrix["trade_date"].max(),
        report_output_dir=report_output_dir,
    )
    _write_frame(pd.DataFrame(episodes), paths["episode_parquet"], paths["episode_csv"])
    _write_frame(pd.DataFrame(transitions), paths["transition_parquet"], paths["transition_csv"])
    _write_frame(
        pd.DataFrame(trigger_diagnostics),
        paths["trigger_diagnostic_parquet"],
        paths["trigger_diagnostic_csv"],
    )
    _write_frame(pd.DataFrame(tbm_labels), paths["tbm_parquet"], paths["tbm_csv"])
    _write_csv_frame(pd.DataFrame(warnings), paths["warning_csv"])
    result = ResearchEventLifecycleResult(
        product_code=PRODUCT_CODE,
        run_id=lifecycle_run_id,
        start=matrix["trade_date"].min(),
        end=matrix["trade_date"].max(),
        horizon=horizon,
        episode_count=len(episodes),
        transition_count=len(transitions),
        trigger_diagnostic_count=len(trigger_diagnostics),
        s1_episode_count=sum(1 for row in episodes if row["phase_code"] == "S1"),
        s1_success_count=sum(1 for row in episodes if row["s1_outcome"] == "success_to_s2"),
        s1_failure_count=sum(1 for row in episodes if row["s1_outcome"] == "failure_to_s0"),
        tbm_label_count=len(tbm_labels),
        warning_count=len([row for row in warnings if row["severity"] != "INFO"]),
        episode_parquet_path=paths["episode_parquet"],
        episode_csv_path=paths["episode_csv"],
        transition_parquet_path=paths["transition_parquet"],
        transition_csv_path=paths["transition_csv"],
        trigger_diagnostic_parquet_path=paths["trigger_diagnostic_parquet"],
        trigger_diagnostic_csv_path=paths["trigger_diagnostic_csv"],
        tbm_parquet_path=paths["tbm_parquet"],
        tbm_csv_path=paths["tbm_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=markdown_path,
        json_path=json_path,
        manifest_path=paths["manifest"],
        signal_matrix_path=matrix_path,
        human_review_required=HUMAN_REVIEW_REQUIRED,
    )
    _write_markdown(
        result=result,
        episodes=episodes,
        transitions=transitions,
        trigger_diagnostics=trigger_diagnostics,
        tbm_labels=tbm_labels,
        warnings=warnings,
        max_holding_days=max_holding_days,
        profit_barrier=profit_barrier,
        stop_loss_barrier=stop_loss_barrier,
    )
    _write_json(
        result=result,
        episodes=episodes,
        transitions=transitions,
        trigger_diagnostics=trigger_diagnostics,
        tbm_labels=tbm_labels,
        warnings=warnings,
        max_holding_days=max_holding_days,
        profit_barrier=profit_barrier,
        stop_loss_barrier=stop_loss_barrier,
    )
    _write_manifest(
        result=result,
        max_holding_days=max_holding_days,
        profit_barrier=profit_barrier,
        stop_loss_barrier=stop_loss_barrier,
    )
    return result


def _load_signal_matrix(*, matrix_path: Path, horizon: int) -> pd.DataFrame:
    if not matrix_path.exists():
        raise ResearchWorkbenchError(f"signal matrix not found: {matrix_path}")
    frame = (
        pd.read_csv(matrix_path)
        if matrix_path.suffix.lower() == ".csv"
        else pd.read_parquet(matrix_path)
    )
    required = {
        "trade_date",
        "horizon",
        "main_contract",
        "main_settle",
        "trend_phase",
        "trend_phase_label",
        "trend_phase_direction",
        "direction",
        "confidence",
        "transition_code",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"R68 signal matrix missing columns: {missing}")
    working = frame.copy()
    working["trade_date"] = pd.to_datetime(working["trade_date"], errors="coerce").dt.date
    working["horizon"] = pd.to_numeric(working["horizon"], errors="coerce")
    working["main_settle"] = pd.to_numeric(working["main_settle"], errors="coerce")
    working = working.loc[working["horizon"].eq(horizon)]
    working = working.dropna(subset=["trade_date", "main_settle", "trend_phase"])
    return working.sort_values("trade_date").reset_index(drop=True)


def _episode_rows(*, matrix: pd.DataFrame, run_id: str) -> list[dict[str, object]]:
    episodes: list[dict[str, object]] = []
    start_index = 0
    for index in range(1, len(matrix) + 1):
        phase_changed = index == len(matrix) or (
            str(matrix.iloc[index]["trend_phase"])
            != str(matrix.iloc[start_index]["trend_phase"])
        )
        if not phase_changed:
            continue
        end_index = index - 1
        episodes.append(
            _episode_row(
                matrix=matrix,
                run_id=run_id,
                episode_number=len(episodes) + 1,
                start_index=start_index,
                end_index=end_index,
                next_index=index if index < len(matrix) else None,
            )
        )
        start_index = index
    return episodes


def _episode_row(
    *,
    matrix: pd.DataFrame,
    run_id: str,
    episode_number: int,
    start_index: int,
    end_index: int,
    next_index: int | None,
) -> dict[str, object]:
    start = matrix.iloc[start_index]
    end = matrix.iloc[end_index]
    next_row = None if next_index is None else matrix.iloc[next_index]
    start_price = float(start["main_settle"])
    end_price = float(end["main_settle"])
    direction = _direction_for_episode(start)
    path = matrix.iloc[start_index : end_index + 1].copy()
    directional_returns = [
        _directional_return(
            start_price=start_price,
            price=float(row.main_settle),
            direction=direction,
        )
        for row in path.itertuples(index=False)
    ]
    next_phase = None if next_row is None else str(next_row["trend_phase"])
    next_date = None if next_row is None else next_row["trade_date"]
    phase_code = str(start["trend_phase"])
    s1_outcome = _s1_outcome(phase_code=phase_code, next_phase=next_phase)
    return {
        "run_id": run_id,
        "product_code": PRODUCT_CODE,
        "episode_id": f"{run_id}:EP{episode_number:04d}",
        "episode_number": episode_number,
        "phase_code": phase_code,
        "phase_label": str(start.get("trend_phase_label", "")),
        "phase_direction": str(start.get("trend_phase_direction", "")),
        "model_direction": str(start.get("direction", "")),
        "confidence": str(start.get("confidence", "")),
        "main_contract_start": str(start["main_contract"]),
        "main_contract_end": str(end["main_contract"]),
        "start_date": start["trade_date"],
        "end_date": end["trade_date"],
        "duration_trading_days": end_index - start_index + 1,
        "start_settle": start_price,
        "end_settle": end_price,
        "episode_return": end_price / start_price - 1.0,
        "directional_episode_return": _directional_return(
            start_price=start_price,
            price=end_price,
            direction=direction,
        ),
        "mfe": max(directional_returns),
        "mae": min(directional_returns),
        "next_phase": next_phase,
        "next_date": next_date,
        "transition_code": None if next_phase is None else f"{phase_code}_TO_{next_phase}",
        "s1_outcome": s1_outcome,
        "label_rule_version": EVENT_LIFECYCLE_VERSION,
        "trading_instruction": "not_a_trading_instruction",
    }


def _transition_rows(
    *,
    episodes: list[dict[str, object]],
    run_id: str,
) -> list[dict[str, object]]:
    transitions = [
        row
        for row in episodes
        if row.get("next_phase") is not None and row.get("transition_code") is not None
    ]
    from_counts: dict[str, int] = {}
    for row in transitions:
        phase = str(row["phase_code"])
        from_counts[phase] = from_counts.get(phase, 0) + 1
    rows: list[dict[str, object]] = []
    for (from_phase, to_phase), group in _group_rows(
        transitions,
        keys=("phase_code", "next_phase"),
    ).items():
        from_count = from_counts.get(str(from_phase), 0)
        count = len(group)
        rows.append(
            {
                "run_id": run_id,
                "product_code": PRODUCT_CODE,
                "from_phase": from_phase,
                "to_phase": to_phase,
                "transition_code": f"{from_phase}_TO_{to_phase}",
                "transition_count": count,
                "from_phase_transition_count": from_count,
                "transition_rate": None if from_count == 0 else count / from_count,
                "avg_duration_trading_days": _mean(
                    row["duration_trading_days"] for row in group
                ),
                "avg_mfe": _mean(row["mfe"] for row in group),
                "avg_mae": _mean(row["mae"] for row in group),
                "label_rule_version": EVENT_LIFECYCLE_VERSION,
            }
        )
    return sorted(rows, key=lambda row: (str(row["from_phase"]), str(row["to_phase"])))


def _trigger_diagnostic_rows(
    *,
    matrix: pd.DataFrame,
    episodes: list[dict[str, object]],
    run_id: str,
) -> list[dict[str, object]]:
    """统计 S1 转移触发日特征，用于解释 S1->S3 和 S1->S0 的差异。"""
    s1_closed = [
        row
        for row in episodes
        if row.get("phase_code") == "S1" and row.get("next_phase") is not None
    ]
    if not s1_closed:
        return []
    lookup = {row.trade_date: row._asdict() for row in matrix.itertuples(index=False)}
    closed_count = len(s1_closed)
    rows: list[dict[str, object]] = []
    for next_phase, group in _group_rows(s1_closed, keys=("next_phase",)).items():
        trigger_rows = [
            lookup[row["next_date"]]
            for row in group
            if row.get("next_date") in lookup
        ]
        rows.append(
            {
                "run_id": run_id,
                "product_code": PRODUCT_CODE,
                "from_phase": "S1",
                "to_phase": next_phase[0],
                "transition_code": f"S1_TO_{next_phase[0]}",
                "episode_count": len(group),
                "closed_s1_count": closed_count,
                "transition_rate": len(group) / closed_count,
                "trigger_price_short_rate": _state_rate(trigger_rows, "price_signal", "short"),
                "trigger_price_long_rate": _state_rate(trigger_rows, "price_signal", "long"),
                "trigger_momentum_short_rate": _state_rate(
                    trigger_rows,
                    "momentum_signal",
                    "short",
                ),
                "trigger_momentum_long_rate": _state_rate(
                    trigger_rows,
                    "momentum_signal",
                    "long",
                ),
                "trigger_oi_long_rate": _state_rate(trigger_rows, "oi_signal", "long"),
                "trigger_oi_neutral_rate": _state_rate(trigger_rows, "oi_signal", "neutral"),
                "trigger_oi_short_rate": _state_rate(trigger_rows, "oi_signal", "short"),
                "trigger_option_confirm_long_rate": _state_rate(
                    trigger_rows,
                    "option_signal",
                    "confirm_long",
                ),
                "trigger_option_divergence_rate": _option_divergence_rate(trigger_rows),
                "avg_trigger_trend_quality_score": _mean(
                    row.get("trend_quality_score") for row in trigger_rows
                ),
                "avg_trigger_composite_score": _mean(
                    row.get("composite_score") for row in trigger_rows
                ),
                "avg_trigger_confidence_score": _mean(
                    row.get("confidence_score") for row in trigger_rows
                ),
                "avg_trigger_return_1d": _mean(row.get("return_1d") for row in trigger_rows),
                "avg_trigger_return_3d": _mean(row.get("return_3d") for row in trigger_rows),
                "avg_trigger_return_5d": _mean(row.get("return_5d") for row in trigger_rows),
                "avg_trigger_return_10d": _mean(row.get("return_10d") for row in trigger_rows),
                "avg_trigger_return_20d": _mean(row.get("return_20d") for row in trigger_rows),
                "avg_trigger_oi_pressure": _mean(
                    row.get("main_oi_pressure") for row in trigger_rows
                ),
                "dominant_warning_flags": _dominant_warning_flags(trigger_rows),
                "trigger_condition_cn": _trigger_condition_text(str(next_phase[0])),
                "label_rule_version": EVENT_LIFECYCLE_VERSION,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    return sorted(rows, key=lambda row: str(row["to_phase"]))


def _tbm_label_rows(
    *,
    matrix: pd.DataFrame,
    episodes: list[dict[str, object]],
    run_id: str,
    max_holding_days: int,
    profit_barrier: float,
    stop_loss_barrier: float,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    date_to_index = {row.trade_date: index for index, row in enumerate(matrix.itertuples())}
    for episode in episodes:
        if episode["phase_code"] != "S1":
            continue
        start_date = episode["start_date"]
        start_index = date_to_index.get(start_date)
        if start_index is None:
            continue
        start_price = float(episode["start_settle"])
        direction = str(episode["phase_direction"] or episode["model_direction"])
        window = matrix.iloc[start_index : start_index + max_holding_days + 1]
        label, barrier_date, barrier_return, days_to_barrier = _first_barrier_hit(
            window=window,
            start_price=start_price,
            direction=direction,
            profit_barrier=profit_barrier,
            stop_loss_barrier=stop_loss_barrier,
        )
        rows.append(
            {
                "run_id": run_id,
                "product_code": PRODUCT_CODE,
                "episode_id": episode["episode_id"],
                "phase_code": episode["phase_code"],
                "start_date": start_date,
                "direction": direction,
                "max_holding_days": max_holding_days,
                "profit_barrier": profit_barrier,
                "stop_loss_barrier": stop_loss_barrier,
                "tbm_label": label,
                "barrier_date": barrier_date,
                "days_to_barrier": days_to_barrier,
                "barrier_return": barrier_return,
                "mfe_until_episode_end": episode["mfe"],
                "mae_until_episode_end": episode["mae"],
                "label_rule_version": EVENT_LIFECYCLE_VERSION,
                "trading_instruction": "not_a_trading_instruction",
            }
        )
    return rows


def _first_barrier_hit(
    *,
    window: pd.DataFrame,
    start_price: float,
    direction: str,
    profit_barrier: float,
    stop_loss_barrier: float,
) -> tuple[str, date | None, float | None, int | None]:
    if len(window) <= 1:
        return "insufficient_path", None, None, None
    last_date: date | None = None
    last_return: float | None = None
    for offset, row in enumerate(window.itertuples(index=False)):
        if offset == 0:
            continue
        ret = _directional_return(
            start_price=start_price,
            price=float(row.main_settle),
            direction=direction,
        )
        last_date = row.trade_date
        last_return = ret
        if ret >= profit_barrier:
            return "take_profit", row.trade_date, ret, offset
        if ret <= -stop_loss_barrier:
            return "stop_loss", row.trade_date, ret, offset
    return "time_expiry", last_date, last_return, len(window) - 1


def _warning_rows(
    *,
    run_id: str,
    episodes: list[dict[str, object]],
    transitions: list[dict[str, object]],
    tbm_labels: list[dict[str, object]],
) -> list[dict[str, object]]:
    warnings = [
        {
            "run_id": run_id,
            "section": "research_boundary",
            "severity": "INFO",
            "warning_code": "R68_EVENT_LABELS_RESEARCH_ONLY",
            "warning_message": "R68 事件生命周期标签只用于研究验证，不构成交易指令。",
            "affected_count": 0,
            "human_review_required": "",
        }
    ]
    s1_count = sum(1 for row in episodes if row["phase_code"] == "S1")
    if s1_count < 30:
        warnings.append(
            {
                "run_id": run_id,
                "section": "sample_size",
                "severity": "WARN",
                "warning_code": "R68_S1_SAMPLE_SIZE_LOW",
                "warning_message": "S1 episode 样本少于 30，不能输出强统计结论。",
                "affected_count": s1_count,
                "human_review_required": "event_lifecycle_labeling_rules",
            }
        )
    if not transitions:
        warnings.append(
            {
                "run_id": run_id,
                "section": "transition",
                "severity": "WARN",
                "warning_code": "R68_NO_TRANSITIONS",
                "warning_message": "没有可统计的状态转移。",
                "affected_count": 0,
                "human_review_required": "phase_transition_definition",
            }
        )
    if not tbm_labels:
        warnings.append(
            {
                "run_id": run_id,
                "section": "tbm",
                "severity": "WARN",
                "warning_code": "R68_NO_S1_TBM_LABELS",
                "warning_message": "没有可生成 TBM 标签的 S1 episode。",
                "affected_count": 0,
                "human_review_required": "triple_barrier_parameters",
            }
        )
    return warnings


def _write_markdown(
    *,
    result: ResearchEventLifecycleResult,
    episodes: list[dict[str, object]],
    transitions: list[dict[str, object]],
    trigger_diagnostics: list[dict[str, object]],
    tbm_labels: list[dict[str, object]],
    warnings: list[dict[str, object]],
    max_holding_days: int,
    profit_barrier: float,
    stop_loss_barrier: float,
) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    s1_rows = [row for row in episodes if row["phase_code"] == "S1"]
    success = [row for row in s1_rows if row["s1_outcome"] == "success_to_s2"]
    failure = [row for row in s1_rows if row["s1_outcome"] == "failure_to_s0"]
    lines = [
        f"# CF 事件生命周期研究 - {result.end.isoformat()}",
        "",
        "## 一、数据状态",
        "",
        "- 报告类型：`event_lifecycle_research`",
        f"- 规则版本：`{EVENT_LIFECYCLE_VERSION}`",
        f"- 数据区间：`{result.start.isoformat()}` 至 `{result.end.isoformat()}`",
        f"- 输入信号矩阵：`{result.signal_matrix_path}`",
        f"- 主观察 horizon：`{result.horizon}`D",
        "",
        "## 二、S1 生命周期摘要",
        "",
        f"- S1 episode 数：`{len(s1_rows)}`",
        f"- S1 -> S2 成功确认数：`{len(success)}`",
        f"- S1 -> S0 失败降级数：`{len(failure)}`",
        f"- S1 -> S2 转移概率：`{_fmt_percent(_safe_rate(len(success), len(s1_rows)))}`",
        f"- S1 -> S0 失败概率：`{_fmt_percent(_safe_rate(len(failure), len(s1_rows)))}`",
        (
            "- S1 平均存活交易日："
            f"`{_fmt_number(_mean(row['duration_trading_days'] for row in s1_rows))}`"
        ),
        f"- S1 平均 MFE：`{_fmt_percent(_mean(row['mfe'] for row in s1_rows))}`",
        f"- S1 平均 MAE：`{_fmt_percent(_mean(row['mae'] for row in s1_rows))}`",
        "",
        "## 三、状态转移矩阵",
        "",
        "| From | To | 次数 | 条件概率 | 平均存活日 | 平均 MFE | 平均 MAE |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in transitions:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["from_phase"]),
                    str(row["to_phase"]),
                    str(row["transition_count"]),
                    _fmt_percent(row.get("transition_rate")),
                    _fmt_number(row.get("avg_duration_trading_days")),
                    _fmt_percent(row.get("avg_mfe")),
                    _fmt_percent(row.get("avg_mae")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 四、S1 转移触发条件诊断",
            "",
            "| 转移 | 样本 | 概率 | 价格转空 | 动量转空 | 持仓转多 | 持仓中性 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in trigger_diagnostics:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["transition_code"]),
                    str(row["episode_count"]),
                    _fmt_percent(row.get("transition_rate")),
                    _fmt_percent(row.get("trigger_price_short_rate")),
                    _fmt_percent(row.get("trigger_momentum_short_rate")),
                    _fmt_percent(row.get("trigger_oi_long_rate")),
                    _fmt_percent(row.get("trigger_oi_neutral_rate")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "| 转移 | 期权确认多 | 趋势质量 | 置信分 | 1D收益 | 20D收益 | 触发解释 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in trigger_diagnostics:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["transition_code"]),
                    _fmt_percent(row.get("trigger_option_confirm_long_rate")),
                    _fmt_number(row.get("avg_trigger_trend_quality_score")),
                    _fmt_number(row.get("avg_trigger_confidence_score")),
                    _fmt_percent(row.get("avg_trigger_return_1d")),
                    _fmt_percent(row.get("avg_trigger_return_20d")),
                    str(row["trigger_condition_cn"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "### 触发条件初步判断",
            "",
            (
                "- `S1_TO_S3`：不是完全失败，而是结构多头残留下的动量/价格背离；"
                "常见特征是趋势质量和置信分下降，触发 `trend_exhaustion_watch`。"
            ),
            (
                "- `S1_TO_S0`：更接近信号失效；触发日价格和动量多数转空，"
                "置信分显著下降，持仓多为中性，系统降回未确认。"
            ),
        ]
    )
    lines.extend(
        [
            "",
            "## 五、简化 Triple Barrier 标签",
            "",
            f"- 最大持有交易日：`{max_holding_days}`",
            f"- 止盈边界：`{_fmt_percent(profit_barrier)}`",
            f"- 止损边界：`-{_fmt_percent(stop_loss_barrier)}`",
            "- 初版 TBM 只用于研究标签，不构成止盈止损规则。",
            "",
            "| TBM 标签 | 样本数 | 占比 | 平均触发日 | 平均触发收益 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in _tbm_summary_rows(tbm_labels):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["tbm_label"]),
                    str(row["count"]),
                    _fmt_percent(row["rate"]),
                    _fmt_number(row["avg_days_to_barrier"]),
                    _fmt_percent(row["avg_barrier_return"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 六、警示与研究边界",
            "",
        ]
    )
    for warning in warnings:
        lines.append(f"- `{warning['warning_code']}`：{warning['warning_message']}")
    lines.extend(
        [
            "- 固定 forward return 只保留为基准后验验证；R68 开始补充事件生命周期标签。",
            "- 当前 TBM 参数需要人工复核，不能直接进入交易规则。",
            "- 本报告不构成交易指令。",
            "",
        ]
    )
    result.markdown_path.write_text("\n".join(lines), encoding="utf-8")


def _write_json(
    *,
    result: ResearchEventLifecycleResult,
    episodes: list[dict[str, object]],
    transitions: list[dict[str, object]],
    trigger_diagnostics: list[dict[str, object]],
    tbm_labels: list[dict[str, object]],
    warnings: list[dict[str, object]],
    max_holding_days: int,
    profit_barrier: float,
    stop_loss_barrier: float,
) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "report_type": "event_lifecycle_research",
        "rule_version": EVENT_LIFECYCLE_VERSION,
        "generated_at": utc_now().isoformat(),
        "summary": result.to_summary(),
        "parameters": {
            "max_holding_days": max_holding_days,
            "profit_barrier": profit_barrier,
            "stop_loss_barrier": stop_loss_barrier,
        },
        "s1_summary": _s1_summary(episodes),
        "tbm_summary": _tbm_summary_rows(tbm_labels),
        "transition_rows": transitions,
        "trigger_diagnostic_rows": trigger_diagnostics,
        "warning_rows": warnings,
        "research_boundary": {
            "event_lifecycle_labels_are_research_only": True,
            "trading_instruction": "not_a_trading_instruction",
            "auto_reverse_allowed": False,
        },
    }
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _write_manifest(
    *,
    result: ResearchEventLifecycleResult,
    max_holding_days: int,
    profit_barrier: float,
    stop_loss_barrier: float,
) -> None:
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": result.run_id,
        "product_code": PRODUCT_CODE,
        "report_type": "event_lifecycle_research",
        "rule_version": EVENT_LIFECYCLE_VERSION,
        "generated_at": utc_now().isoformat(),
        "start": result.start.isoformat(),
        "end": result.end.isoformat(),
        "horizon": result.horizon,
        "signal_matrix_path": str(result.signal_matrix_path),
        "episode_parquet_path": str(result.episode_parquet_path),
        "transition_parquet_path": str(result.transition_parquet_path),
        "trigger_diagnostic_parquet_path": str(result.trigger_diagnostic_parquet_path),
        "tbm_parquet_path": str(result.tbm_parquet_path),
        "markdown_path": str(result.markdown_path),
        "json_path": str(result.json_path),
        "parameters": {
            "max_holding_days": max_holding_days,
            "profit_barrier": profit_barrier,
            "stop_loss_barrier": stop_loss_barrier,
        },
        "human_review_required": list(result.human_review_required),
    }
    result.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_frame(frame: pd.DataFrame, parquet_path: Path, csv_path: Path) -> None:
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False, encoding="utf-8")


def _write_csv_frame(frame: pd.DataFrame, csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(csv_path, index=False, encoding="utf-8")


def _s1_outcome(*, phase_code: str, next_phase: str | None) -> str:
    if phase_code != "S1":
        return "not_s1"
    if next_phase == "S2":
        return "success_to_s2"
    if next_phase == "S0":
        return "failure_to_s0"
    if next_phase is None:
        return "open_episode"
    return f"other_to_{next_phase.lower()}"


def _direction_for_episode(row: pd.Series) -> str:
    phase_direction = str(row.get("trend_phase_direction") or "")
    if phase_direction in {"long", "short"}:
        return phase_direction
    model_direction = str(row.get("direction") or "")
    if model_direction in {"long", "short"}:
        return model_direction
    return "long"


def _directional_return(*, start_price: float, price: float, direction: str) -> float:
    raw = price / start_price - 1.0
    return -raw if direction == "short" else raw


def _group_rows(
    rows: list[dict[str, object]],
    *,
    keys: tuple[str, ...],
) -> dict[tuple[object, ...], list[dict[str, object]]]:
    grouped: dict[tuple[object, ...], list[dict[str, object]]] = {}
    for row in rows:
        key = tuple(row[key_name] for key_name in keys)
        grouped.setdefault(key, []).append(row)
    return grouped


def _state_rate(rows: list[dict[str, object]], column: str, state: str) -> float | None:
    if not rows:
        return None
    return sum(1 for row in rows if str(row.get(column)) == state) / len(rows)


def _option_divergence_rate(rows: list[dict[str, object]]) -> float | None:
    if not rows:
        return None
    return (
        sum(1 for row in rows if str(row.get("option_signal", "")).startswith("diverge"))
        / len(rows)
    )


def _dominant_warning_flags(rows: list[dict[str, object]]) -> str:
    values = [str(row.get("warning_flags") or "") for row in rows]
    if not values:
        return ""
    counts = pd.Series(values).value_counts()
    return str(counts.index[0])


def _trigger_condition_text(to_phase: str) -> str:
    if to_phase == "S3":
        return (
            "结构信号仍有多头残留，但触发日趋势质量和置信分明显下降，"
            "常见于短期回落、持仓未确认或衰竭警示。"
        )
    if to_phase == "S0":
        return (
            "价格与动量大多转空，置信分降至低位，持仓多为中性；"
            "系统认为信号分歧，降回未确认。"
        )
    if to_phase == "S2":
        return (
            "价格、动量、期限结构和持仓压力形成同向确认，"
            "系统升级为趋势中。"
        )
    return "该转移属于少数路径，需要人工复核。"


def _s1_summary(episodes: list[dict[str, object]]) -> dict[str, object]:
    s1_rows = [row for row in episodes if row["phase_code"] == "S1"]
    success = [row for row in s1_rows if row["s1_outcome"] == "success_to_s2"]
    failure = [row for row in s1_rows if row["s1_outcome"] == "failure_to_s0"]
    return {
        "s1_episode_count": len(s1_rows),
        "success_to_s2_count": len(success),
        "failure_to_s0_count": len(failure),
        "success_to_s2_rate": _safe_rate(len(success), len(s1_rows)),
        "failure_to_s0_rate": _safe_rate(len(failure), len(s1_rows)),
        "avg_duration_trading_days": _mean(row["duration_trading_days"] for row in s1_rows),
        "avg_mfe": _mean(row["mfe"] for row in s1_rows),
        "avg_mae": _mean(row["mae"] for row in s1_rows),
    }


def _tbm_summary_rows(tbm_labels: list[dict[str, object]]) -> list[dict[str, object]]:
    if not tbm_labels:
        return []
    total = len(tbm_labels)
    rows: list[dict[str, object]] = []
    for label, group in _group_rows(tbm_labels, keys=("tbm_label",)).items():
        rows.append(
            {
                "tbm_label": label[0],
                "count": len(group),
                "rate": len(group) / total,
                "avg_days_to_barrier": _mean(row["days_to_barrier"] for row in group),
                "avg_barrier_return": _mean(row["barrier_return"] for row in group),
            }
        )
    return sorted(rows, key=lambda row: str(row["tbm_label"]))


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _mean(values: object) -> float | None:
    series = pd.Series(list(values), dtype="float64")
    series = series.dropna()
    if series.empty:
        return None
    return float(series.mean())


def _output_paths(*, start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_event_lifecycle"
    return {
        "episode_parquet": root / f"{stem}_episodes.parquet",
        "episode_csv": root / f"{stem}_episodes.csv",
        "transition_parquet": root / f"{stem}_transitions.parquet",
        "transition_csv": root / f"{stem}_transitions.csv",
        "trigger_diagnostic_parquet": root / f"{stem}_trigger_diagnostics.parquet",
        "trigger_diagnostic_csv": root / f"{stem}_trigger_diagnostics.csv",
        "tbm_parquet": root / f"{stem}_tbm_labels.parquet",
        "tbm_csv": root / f"{stem}_tbm_labels.csv",
        "warning_csv": root / f"{stem}_warnings.csv",
        "manifest": root / f"{stem}_manifest.json",
    }


def _markdown_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    return root / f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_event_lifecycle.md"


def _json_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    return root / f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_event_lifecycle.json"


def _default_signal_matrix_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "signal_matrix"
    candidates = sorted(root.glob(f"{PRODUCT_CODE}_*_signal_matrix_daily.parquet"))
    if not candidates:
        raise ResearchWorkbenchError(f"no signal matrix parquet found under {root}")
    return candidates[-1]


def _default_run_id(*, start: date, end: date) -> str:
    return (
        f"r68_event_lifecycle_{PRODUCT_CODE}_{start.isoformat()}_"
        f"{end.isoformat()}_{uuid.uuid4().hex[:8]}"
    )


def _fmt_percent(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2%}"


def _fmt_number(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2f}"
