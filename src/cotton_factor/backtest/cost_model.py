"""Backtest transaction cost model."""

from __future__ import annotations

from dataclasses import dataclass

TODO_REQUIRES_HUMAN_REVIEW = "TODO_REQUIRES_HUMAN_REVIEW"
DEFAULT_COST_MODEL_ID = "cost_placeholder_v1"


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

    def estimate(self, *, order_lots: int) -> CostEstimate:
        """Return a deterministic cost estimate for a signed order size."""
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
