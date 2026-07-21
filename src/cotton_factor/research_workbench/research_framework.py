"""R67 research evaluation framework guardrails for CF reports."""

from __future__ import annotations

from typing import Any

import pandas as pd

RESEARCH_FRAMEWORK_VERSION = "R67_research_evaluation_framework_v1"
OOS_REQUIRED_STATUS = "WATCH_ONLY_OOS_REQUIRED"
VALIDATED_STANCE_BLOCKED = "EVIDENCE_CONFLICT_BLOCKED"
VALIDATED_STANCE_WATCH = "WATCH_CONFIRMATION"
VALIDATED_STANCE_BIAS = "VALIDATED_BIAS_RESEARCH_ONLY"
VALIDATED_STANCE_RAW = "RAW_SIGNAL_ONLY"


def build_research_framework_context(
    *,
    latest: dict[str, object],
    decay: pd.DataFrame,
    stability: pd.DataFrame | None = None,
) -> dict[str, object]:
    """Build a conservative interpretation context for current signal evidence."""
    matrix = latest.get("signal_matrix_context")
    matrix_context = matrix if isinstance(matrix, dict) else {}
    rows = _latest_matrix_rows(latest)
    primary_horizon = _int_or_none(matrix_context.get("primary_horizon"))
    primary_direction = matrix_context.get("primary_direction")
    primary_strength = matrix_context.get("primary_confidence")
    high_strength_horizons = [
        _int_or_none(row.get("horizon"))
        for row in rows
        if row.get("direction") == primary_direction and row.get("confidence") == "high"
    ]
    high_strength_horizons = [horizon for horizon in high_strength_horizons if horizon is not None]
    primary_decay = _decay_row(decay, primary_horizon)
    reliability = _historical_reliability(primary_decay)
    conflicts = _evidence_conflicts(
        rows=rows,
        decay=decay,
        primary_horizon=primary_horizon,
        primary_strength=primary_strength,
        reliability=reliability,
    )
    threshold_context = _threshold_interpretation(latest, stability)
    option_context = _option_framework_context(rows)
    validated_stance = _validated_stance_context(
        raw_direction=primary_direction,
        primary_strength=primary_strength,
        reliability=reliability,
        conflicts=conflicts,
        threshold_context=threshold_context,
        option_context=option_context,
    )
    return {
        "rule_version": RESEARCH_FRAMEWORK_VERSION,
        "evaluation_principle": (
            "signal_strength 表示当前多因子同向强度；historical_reliability 表示"
            "历史后验验证可靠性，二者不能互相替代。"
        ),
        "current_signal_strength": {
            "primary_horizon": primary_horizon,
            "primary_direction": primary_direction,
            "primary_signal_strength": primary_strength,
            "high_strength_horizons": high_strength_horizons,
        },
        "historical_reliability": reliability,
        "evidence_conflicts": conflicts,
        "validated_stance": validated_stance,
        "threshold_interpretation": threshold_context,
        "option_framework_context": option_context,
        "event_labeling_gap": {
            "fixed_forward_return_role": "baseline_validation_only",
            "missing_event_lifecycle_labels": True,
            "required_next_research": [
                "S1_TO_S2_transition_probability",
                "S1_TO_S0_failure_probability",
                "S1_lifecycle_days",
                "MFE_MAE_distribution",
                "triple_barrier_labels",
            ],
            "interpretation_cn": (
                "固定 1D/3D/5D/10D/20D/40D forward return 只能作为基准验证；"
                "S1-S4 趋势阶段需要由 R68 事件生命周期标签进一步评价，"
                "在接入门控前仍需人工复核。"
            ),
        },
        "contrarian_scenario_cn": _contrarian_scenario_lines(
            reliability=reliability,
            conflicts=conflicts,
            option_context=option_context,
        ),
        "human_review_required": [
            "signal_strength_vs_historical_reliability",
            "oos_validation_before_threshold_upgrade",
            "event_lifecycle_labeling_required",
            "option_volatility_context_review",
        ],
    }


def research_framework_markdown_lines(context: dict[str, object]) -> list[str]:
    """Render R67 context as Chinese Markdown lines."""
    strength = _dict(context.get("current_signal_strength"))
    reliability = _dict(context.get("historical_reliability"))
    threshold = _dict(context.get("threshold_interpretation"))
    option = _dict(context.get("option_framework_context"))
    stance = _dict(context.get("validated_stance"))
    gap = _dict(context.get("event_labeling_gap"))
    conflicts = _list(context.get("evidence_conflicts"))
    contrarian = _list(context.get("contrarian_scenario_cn"))
    lines = [
        "## 研究评价框架修正（R67）",
        "",
        "- 核心口径：`signal_strength` 只表示当前多因子同向强度；"
        "`historical_reliability` 才表示历史后验验证可靠性。",
        "- 严禁把 high confidence 写成高预测胜率；若历史可靠性较弱，必须在结论区同步披露。",
        f"- 主观察周期：`{strength.get('primary_horizon')}`D；"
        f"当前方向：`{strength.get('primary_direction')}`；"
        f"当前信号强度：`{strength.get('primary_signal_strength')}`。",
        f"- 主周期历史可靠性：`{reliability.get('reliability_level')}`；"
        f"方向命中率：`{_fmt_percent(reliability.get('directional_hit_rate'))}`；"
        f"normal cost 后均值：`{_fmt_percent(reliability.get('mean_net_return_normal_cost'))}`；"
        f"稳定性：`{reliability.get('stability_status')}`。",
        f"- 验证后研究立场：`{stance.get('stance')}`；"
        f"原始模型方向：`{stance.get('raw_model_direction')}`。",
        f"- 立场解释：{stance.get('stance_reason_cn')}",
        "",
        "### 证据冲突",
        "",
    ]
    if conflicts:
        lines.extend(f"- {item}" for item in conflicts)
    else:
        lines.append("- 暂未检测到当前强信号与历史可靠性之间的明显冲突。")
    lines.extend(
        [
            "",
            "### 阈值候选解释降级",
            "",
            f"- 原始 READY/WATCH 候选数：`{threshold.get('raw_ready_watch_count', 0)}`。",
            f"- 发布解释状态：`{threshold.get('publish_status')}`。",
            "- 在没有样本外验证、滚动窗口稳定性和人工复核前，"
            "READY_CANDIDATE 只能写成观察候选，不能写成可执行规则。",
            "",
            "### 期权过滤解释",
            "",
            f"- 期权方向过滤：`{option.get('option_signal', 'not_connected')}`。",
            f"- 波动率状态：`{option.get('volatility_state', 'not_connected')}`。",
            f"- 解释：{option.get('interpretation_cn')}",
            "",
            "### 事件生命周期标签缺口",
            "",
            f"- {gap.get('interpretation_cn')}",
            "- 下一步必须将 R68 的 S1->S2 转移概率、S1 失败概率、MFE/MAE "
            "与 Triple Barrier 标签接入 validated_stance 门控。",
            "",
            "### 反面情景",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in contrarian)
    return lines


def display_threshold_status(raw_status: object) -> str:
    """Return conservative publication status for historical threshold candidates."""
    status = str(raw_status)
    if status in {"READY_CANDIDATE", "WATCH_CANDIDATE"}:
        return OOS_REQUIRED_STATUS
    return status


def validated_stance_label(context: dict[str, object]) -> str:
    """Return the validated stance label from an R67 context."""
    stance = _dict(context.get("validated_stance"))
    return str(stance.get("stance") or VALIDATED_STANCE_RAW)


def validated_stance_title_text(context: dict[str, object]) -> str:
    """Return conservative title wording for publish outputs."""
    stance = validated_stance_label(context)
    return {
        VALIDATED_STANCE_BLOCKED: "原始信号被证据冲突拦截",
        VALIDATED_STANCE_WATCH: "观察确认中",
        VALIDATED_STANCE_BIAS: "研究倾向待复核",
        VALIDATED_STANCE_RAW: "原始信号观察",
    }.get(stance, "研究观察")


def _historical_reliability(row: dict[str, object] | None) -> dict[str, object]:
    if row is None:
        return {
            "horizon": None,
            "directional_hit_rate": None,
            "mean_net_return_normal_cost": None,
            "stability_status": "MISSING",
            "reliability_level": "MISSING",
            "interpretation_cn": "缺少主周期历史后验验证，不能评价历史可靠性。",
        }
    hit_rate = _float_or_none(row.get("directional_hit_rate"))
    net_return = _float_or_none(row.get("mean_net_return_normal_cost"))
    stability = str(row.get("stability_status") or "UNKNOWN")
    if hit_rate is None:
        level = "MISSING"
    elif hit_rate < 0.50 or stability == "WEAK_OR_UNSTABLE":
        level = "WEAK_OR_CONFLICTED"
    elif hit_rate >= 0.58 and net_return is not None and net_return > 0 and stability == "READY":
        level = "SUPPORTIVE_BUT_RESEARCH_ONLY"
    else:
        level = "WATCH_ONLY"
    return {
        "horizon": _int_or_none(row.get("horizon")),
        "directional_hit_rate": hit_rate,
        "mean_net_return_normal_cost": net_return,
        "stability_status": stability,
        "reliability_level": level,
        "interpretation_cn": _reliability_text(level),
    }


def _evidence_conflicts(
    *,
    rows: list[dict[str, object]],
    decay: pd.DataFrame,
    primary_horizon: int | None,
    primary_strength: object,
    reliability: dict[str, object],
) -> list[str]:
    conflicts: list[str] = []
    primary_hit = reliability.get("directional_hit_rate")
    primary_level = reliability.get("reliability_level")
    if str(primary_strength) == "high" and (
        primary_level == "WEAK_OR_CONFLICTED"
        or (isinstance(primary_hit, float) and primary_hit < 0.50)
    ):
        conflicts.append(
            "主周期当前信号强度为 high，但历史全样本可靠性偏弱；"
            "这只能说明当前因子同向，不说明历史胜率高。"
        )
    for row in rows:
        if row.get("confidence") != "high":
            continue
        horizon = _int_or_none(row.get("horizon"))
        if horizon is None or horizon == primary_horizon:
            continue
        decay_row = _decay_row(decay, horizon)
        hit_rate = (
            None
            if decay_row is None
            else _float_or_none(decay_row.get("directional_hit_rate"))
        )
        stability = None if decay_row is None else decay_row.get("stability_status")
        if hit_rate is not None and hit_rate < 0.50:
            conflicts.append(
                f"{horizon}D 当前为 high signal_strength，但历史命中率 "
                f"{_fmt_percent(hit_rate)}，稳定性 {stability}，需要按反证处理。"
            )
    return conflicts


def _threshold_interpretation(
    latest: dict[str, object],
    stability: pd.DataFrame | None,
) -> dict[str, object]:
    context = latest.get("signal_threshold_context")
    threshold_context = context if isinstance(context, dict) else {}
    candidates = _threshold_candidates(threshold_context)
    raw_ready_watch = [
        candidate
        for candidate in candidates
        if str(candidate.get("candidate_status")) in {"READY_CANDIDATE", "WATCH_CANDIDATE"}
    ]
    stability_ready_watch = 0
    if stability is not None and not stability.empty and "candidate_status" in stability.columns:
        stability_ready_watch = int(
            stability["candidate_status"]
            .astype(str)
            .isin({"READY_CANDIDATE", "WATCH_CANDIDATE"})
            .sum()
        )
    return {
        "horizon_alignment_status": threshold_context.get("horizon_alignment_status"),
        "raw_ready_watch_count": max(len(raw_ready_watch), stability_ready_watch),
        "publish_status": (
            OOS_REQUIRED_STATUS if raw_ready_watch or stability_ready_watch else "NO_UPGRADE"
        ),
        "oos_validation_required": True,
        "interpretation_cn": (
            "R37/R41 阈值候选只说明历史子样本值得复核；没有 OOS 前必须降级为观察候选。"
        ),
    }


def _validated_stance_context(
    *,
    raw_direction: object,
    primary_strength: object,
    reliability: dict[str, object],
    conflicts: list[str],
    threshold_context: dict[str, object],
    option_context: dict[str, object],
) -> dict[str, object]:
    """给日度报告提供轻量门控：不反转方向，只限制结论等级。"""
    raw_direction_text = str(raw_direction or "unknown")
    reliability_level = str(reliability.get("reliability_level") or "MISSING")
    option_state = str(option_context.get("volatility_state") or "not_connected")
    if conflicts or reliability_level == "WEAK_OR_CONFLICTED":
        stance = VALIDATED_STANCE_BLOCKED
        reason = (
            "原始模型方向保留为观察输入，但历史可靠性或证据冲突不足以支持"
            "方向性升级；系统不做自动反转，只阻止输出 validated bullish/bearish bias。"
        )
    elif threshold_context.get("publish_status") == OOS_REQUIRED_STATUS:
        stance = VALIDATED_STANCE_WATCH
        reason = "阈值候选仍需样本外验证，当前只能进入观察确认。"
    elif option_state in {"low_iv_breakout_not_priced", "not_connected"}:
        stance = VALIDATED_STANCE_WATCH
        reason = "期权波动率确认不足，当前不升级为已验证方向倾向。"
    elif reliability_level == "SUPPORTIVE_BUT_RESEARCH_ONLY":
        stance = VALIDATED_STANCE_BIAS
        reason = "历史可靠性相对支持，但仍需要事件生命周期和人工复核确认。"
    else:
        stance = VALIDATED_STANCE_RAW
        reason = "当前只有原始信号观察，缺少足够验证层支持。"
    return {
        "raw_model_direction": raw_direction_text,
        "signal_strength": primary_strength,
        "stance": stance,
        "stance_reason_cn": reason,
        "auto_reverse_allowed": False,
        "blocking_inputs": {
            "historical_reliability": reliability_level,
            "evidence_conflict_count": len(conflicts),
            "threshold_publish_status": threshold_context.get("publish_status"),
            "option_volatility_state": option_state,
        },
    }


def _option_framework_context(rows: list[dict[str, object]]) -> dict[str, object]:
    row = next((item for item in rows if item.get("option_factor_status")), None)
    if row is None:
        return {
            "option_signal": "not_connected",
            "volatility_state": "not_connected",
            "interpretation_cn": "未接入期权因子，不能用期权市场确认或反证期货信号。",
        }
    iv_rank = _float_or_none(row.get("option_atm_iv_rank"))
    skew = _float_or_none(row.get("option_skew_proxy"))
    volatility_state = "normal_iv"
    notes: list[str] = []
    if iv_rank is not None and iv_rank <= 0.10:
        volatility_state = "low_iv_breakout_not_priced"
        notes.append("ATM IV rank 处于低位，说明突破风险尚未被波动率充分定价。")
    if skew is not None and skew < 0:
        notes.append("skew proxy 为负，需复核下方尾部风险定价。")
    if not notes:
        notes.append("期权当前只作为方向过滤和波动风险观察。")
    return {
        "option_signal": row.get("option_signal", "not_connected"),
        "option_signal_direction": row.get("option_signal_direction"),
        "atm_iv_rank": iv_rank,
        "skew_proxy": skew,
        "volatility_state": volatility_state,
        "interpretation_cn": " ".join(notes),
    }


def _contrarian_scenario_lines(
    *,
    reliability: dict[str, object],
    conflicts: list[str],
    option_context: dict[str, object],
) -> list[str]:
    lines = []
    if reliability.get("reliability_level") == "WEAK_OR_CONFLICTED":
        lines.append(
            "主周期历史可靠性偏弱，当前 S1 可能只是震荡修复或噪音信号，"
            "不能直接按趋势起点处理。"
        )
    if conflicts:
        lines.append("当前强信号与历史低命中存在冲突，人工复核应优先检查失败路径。")
    if option_context.get("volatility_state") == "low_iv_breakout_not_priced":
        lines.append(
            "低 IV 表示期权市场尚未充分定价趋势突破；这既可能是低成本观察窗口，"
            "也可能说明市场并不认可趋势扩张。"
        )
    return lines or ["暂未形成强反证，但仍需按研究边界进行人工复核。"]


def _threshold_candidates(context: dict[str, object]) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for key in ("matched_candidates", "alternate_candidates"):
        value = context.get(key)
        if isinstance(value, list):
            candidates.extend(item for item in value if isinstance(item, dict))
    return candidates


def _decay_row(decay: pd.DataFrame, horizon: int | None) -> dict[str, object] | None:
    if horizon is None or decay.empty or "horizon" not in decay.columns:
        return None
    working = decay.copy()
    working["horizon"] = pd.to_numeric(working["horizon"], errors="coerce")
    selected = working.loc[working["horizon"].eq(horizon)]
    if selected.empty:
        return None
    return selected.iloc[0].to_dict()


def _latest_matrix_rows(latest: dict[str, object]) -> list[dict[str, object]]:
    context = latest.get("signal_matrix_context")
    if not isinstance(context, dict):
        return []
    rows = context.get("rows")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _reliability_text(level: str) -> str:
    return {
        "MISSING": "缺少历史证据，不能评价可靠性。",
        "WEAK_OR_CONFLICTED": "历史全样本可靠性偏弱或与当前强信号冲突。",
        "WATCH_ONLY": "历史证据仅支持继续观察，不支持交易化表达。",
        "SUPPORTIVE_BUT_RESEARCH_ONLY": "历史证据相对支持，但仍是研究证据。",
    }.get(level, "未知可靠性状态。")


def _fmt_percent(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2%}"


def _float_or_none(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _int_or_none(value: object) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(float(value))


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []
