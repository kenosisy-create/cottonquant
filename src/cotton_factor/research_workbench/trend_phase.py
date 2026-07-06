"""R24 CF trend phase classification for latest signal-only reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PhaseCode = Literal["S0", "S1", "S2", "S3", "S4"]
SignalDirection = Literal["long", "short", "neutral", "unknown"]


@dataclass(frozen=True)
class TrendPhaseResult:
    """Current trend phase for a CF signal-only report."""

    phase_code: PhaseCode
    phase_label: str
    direction: SignalDirection
    confidence: str
    reason: str
    support_count: int
    available_signal_count: int

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable summary."""
        return {
            "phase_code": self.phase_code,
            "phase_label": self.phase_label,
            "direction": self.direction,
            "confidence": self.confidence,
            "reason": self.reason,
            "support_count": self.support_count,
            "available_signal_count": self.available_signal_count,
        }


def classify_cf_trend_phase(
    *,
    signal_states: dict[str, SignalDirection],
    latest_settle: float | None,
    ma20: float | None,
    momentum_20: float | None,
    latest_return: float | None,
    oi_pressure: float | None,
) -> TrendPhaseResult:
    """Classify the latest CF trend phase from observable T-day signals."""
    available_states = [
        state for state in signal_states.values() if state != "unknown"
    ]
    long_count = sum(1 for state in available_states if state == "long")
    short_count = sum(1 for state in available_states if state == "short")
    available_count = len(available_states)
    if (
        available_count < 3
        or latest_settle is None
        or ma20 is None
        or momentum_20 is None
    ):
        return _result(
            phase_code="S0",
            direction="unknown",
            support_count=max(long_count, short_count),
            available_count=available_count,
            reason="可用信号不足，或 20 日均线/动量尚未形成。",
        )

    price_above_ma = latest_settle > ma20
    price_below_ma = latest_settle < ma20
    oi_confirms_long = oi_pressure is not None and oi_pressure > 0
    # 下跌过程中增仓代表空向参与度上升，这里作为终点/反向风险确认条件之一。
    oi_confirms_short = oi_pressure is not None and oi_pressure > 0

    # R24 只做当前阶段判别，不把观察阶段直接升级成交易结论。
    if short_count >= 3 and price_below_ma and momentum_20 < 0:
        return _result(
            phase_code="S4",
            direction="short",
            support_count=short_count,
            available_count=available_count,
            reason="价格位于 20 日均线下方，20 日动量为负，空向信号占优。",
        )
    if (
        price_above_ma
        and momentum_20 > 0
        and long_count >= 3
        and latest_return is not None
        and latest_return >= 0
        and oi_confirms_long
    ):
        return _result(
            phase_code="S2",
            direction="long",
            support_count=long_count,
            available_count=available_count,
            reason="价格位于 20 日均线上方，动量与持仓压力同向，多数信号支持。",
        )
    if price_above_ma and long_count >= 3 and (
        momentum_20 <= 0 or latest_return is not None and latest_return < 0
    ):
        return _result(
            phase_code="S3",
            direction="long",
            support_count=long_count,
            available_count=available_count,
            reason="结构信号仍偏多，但动量或最新价格变化出现背离。",
        )
    if long_count >= 3 and (price_above_ma or momentum_20 > 0 or oi_confirms_long):
        return _result(
            phase_code="S1",
            direction="long",
            support_count=long_count,
            available_count=available_count,
            reason="多数信号偏多，但价格、动量、持仓尚未形成完整共振。",
        )
    if short_count >= 2 and (price_below_ma or momentum_20 < 0 or oi_confirms_short):
        return _result(
            phase_code="S3",
            direction="short",
            support_count=short_count,
            available_count=available_count,
            reason="空向信号增加，趋势质量下降或反向风险上升。",
        )
    return _result(
        phase_code="S0",
        direction="neutral",
        support_count=max(long_count, short_count),
        available_count=available_count,
        reason="信号分歧，尚未形成可复核趋势阶段。",
    )


def _result(
    *,
    phase_code: PhaseCode,
    direction: SignalDirection,
    support_count: int,
    available_count: int,
    reason: str,
) -> TrendPhaseResult:
    labels = {
        "S0": "未确认",
        "S1": "起点观察",
        "S2": "趋势中",
        "S3": "衰竭观察",
        "S4": "终点确认",
    }
    confidence = _confidence(support_count=support_count, available_count=available_count)
    return TrendPhaseResult(
        phase_code=phase_code,
        phase_label=labels[phase_code],
        direction=direction,
        confidence=confidence,
        reason=reason,
        support_count=support_count,
        available_signal_count=available_count,
    )


def _confidence(*, support_count: int, available_count: int) -> str:
    if available_count == 0:
        return "low"
    ratio = support_count / available_count
    if support_count >= 4 and ratio >= 0.75:
        return "high"
    if support_count >= 3 and ratio >= 0.6:
        return "medium"
    return "low"
