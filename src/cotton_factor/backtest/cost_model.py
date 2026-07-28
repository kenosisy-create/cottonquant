"""Backtest transaction cost model."""

from __future__ import annotations

from dataclasses import dataclass

TODO_REQUIRES_HUMAN_REVIEW = "TODO_REQUIRES_HUMAN_REVIEW"
DEFAULT_COST_MODEL_ID = "cost_placeholder_v1"
NOTIONAL_BPS_COST_MODEL_ID = "notional_one_way_bps_v1"


@dataclass(frozen=True)
class CostEstimate:
    """Cost estimate for one fill."""

    model_id: str
    fee: float
    slippage: float
    impact: float
    total_cost: float
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class CostModel:
    """Simple per-lot cost model used by D16 backtests."""

    model_id: str = DEFAULT_COST_MODEL_ID
    fee_per_lot: float = 0.0
    slippage_per_lot: float = 0.0
    impact_per_lot: float = 0.0
    human_review_required: tuple[str, ...] = ("fee", "slippage", "impact")

    def estimate(
        self,
        *,
        order_lots: int,
        fill_price: float | None = None,
        multiplier: float | None = None,
    ) -> CostEstimate:
        """Return a deterministic cost estimate for a signed order size."""
        del fill_price, multiplier
        lots = abs(order_lots)
        fee = lots * self.fee_per_lot
        slippage = lots * self.slippage_per_lot
        impact = lots * self.impact_per_lot
        warnings = tuple(
            f"{TODO_REQUIRES_HUMAN_REVIEW}: {field_name} uses D16 placeholder cost"
            for field_name in self.human_review_required
        )
        return CostEstimate(
            model_id=self.model_id,
            fee=fee,
            slippage=slippage,
            impact=impact,
            total_cost=fee + slippage + impact,
            warnings=warnings,
        )


@dataclass(frozen=True)
class NotionalBpsCostModel:
    """All-in one-way cost charged on each real-contract fill notional."""

    one_way_bps: float
    model_id: str = NOTIONAL_BPS_COST_MODEL_ID

    def __post_init__(self) -> None:
        if self.one_way_bps < 0:
            raise ValueError("one_way_bps must be non-negative")

    def estimate(
        self,
        *,
        order_lots: int,
        fill_price: float | None = None,
        multiplier: float | None = None,
    ) -> CostEstimate:
        """Estimate all-in cost from the actual fill notional."""
        if fill_price is None or fill_price <= 0:
            raise ValueError("fill_price must be positive for notional bps cost")
        if multiplier is None or multiplier <= 0:
            raise ValueError("multiplier must be positive for notional bps cost")
        notional = abs(order_lots) * fill_price * multiplier
        total_cost = notional * self.one_way_bps / 10_000.0
        return CostEstimate(
            model_id=self.model_id,
            fee=total_cost,
            slippage=0.0,
            impact=0.0,
            total_cost=total_cost,
            warnings=(),
        )
