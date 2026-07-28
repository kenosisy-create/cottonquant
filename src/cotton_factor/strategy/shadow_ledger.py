"""R90 immutable forward shadow events and atomic ledger views."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import pandas as pd

from cotton_factor.common.exceptions import StrategyError
from cotton_factor.common.paths import data_dir, project_root
from cotton_factor.core.contract_master import load_product_config
from cotton_factor.core.schemas import CoreChainMapDailyRow, ResearchContinuousPriceDailyRow
from cotton_factor.strategy.io import (
    default_core_quote_path,
    latest_strategy_input_paths,
    load_core_quotes,
    load_typed_parquet,
)
from cotton_factor.strategy.phase_gated import (
    _carry_multiplier,
    _gate,
    _latest_signal_matrix_path,
    _latest_trend_phase_path,
    _load_signal_matrix,
    _load_trend_phase,
    _option_multiplier,
    _phase_multiplier,
    _rows_by_date,
    _s3_no_add,
)
from cotton_factor.strategy.registry import load_strategy_registry
from cotton_factor.strategy.signals import TsmomSignalSnapshot, compute_tsmom_signal_snapshot
from cotton_factor.strategy.spec import StrategySpec

SHADOW_SCHEMA_VERSION = "V5.1_R90_shadow_event_v2"
SHADOW_RULE_VERSION = "V5.1_R90_shadow_accounting_v2"
RESEARCH_BOUNDARY = (
    "影子台账为研究仿真，前向记录、无未来函数，不构成交易指令；"
    "NAV为记账值非真实资金。"
)
RecordMode = Literal["FORWARD_CAPTURE", "HISTORICAL_REPLAY"]


@dataclass(frozen=True)
class ShadowStrategyStatus:
    """One strategy's event and materialized ledger status."""

    strategy_key: str
    status: str
    event_path: Path
    ledger_path: Path
    nav: float
    target_lots: int
    target_contract: str
    warning_count: int

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe strategy status."""
        return {
            "strategy_key": self.strategy_key,
            "status": self.status,
            "event_path": str(self.event_path),
            "ledger_path": str(self.ledger_path),
            "nav": self.nav,
            "target_lots": self.target_lots,
            "target_contract": self.target_contract,
            "warning_count": self.warning_count,
        }


@dataclass(frozen=True)
class ShadowRunResult:
    """R90 daily result across all active strategy specs."""

    trade_date: date
    record_mode: str
    run_id: str
    strategies: tuple[ShadowStrategyStatus, ...]
    json_path: Path
    markdown_path: Path

    def to_summary(self) -> dict[str, object]:
        """Return a CLI summary."""
        return {
            "trade_date": self.trade_date.isoformat(),
            "record_mode": self.record_mode,
            "run_id": self.run_id,
            "strategy_count": len(self.strategies),
            "strategies": [item.to_dict() for item in self.strategies],
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
        }


def run_cf_strategy_shadow(
    *,
    trade_date: date | None = None,
    record_mode: RecordMode = "FORWARD_CAPTURE",
    registry_path: Path | None = None,
    core_quote_path: Path | None = None,
    continuous_price_path: Path | None = None,
    chain_map_path: Path | None = None,
    input_dir: Path | None = None,
    event_root: Path | None = None,
    ledger_root: Path | None = None,
    daily_output_root: Path | None = None,
    overwrite_reason: str | None = None,
    run_id: str | None = None,
) -> ShadowRunResult:
    """Append one daily shadow event per active strategy and rebuild its view."""
    if record_mode not in {"FORWARD_CAPTURE", "HISTORICAL_REPLAY"}:
        raise StrategyError(f"unsupported shadow record_mode: {record_mode}")
    registry = load_strategy_registry(registry_path)
    active_specs = [spec for spec in registry.specs if spec.status in {"baseline", "candidate"}]
    if not active_specs:
        raise StrategyError("strategy registry has no active baseline or candidate specs")
    bundle = (
        latest_strategy_input_paths(input_dir)
        if continuous_price_path is None or chain_map_path is None
        else {}
    )
    continuous_path = continuous_price_path or bundle["continuous"]
    chain_path = chain_map_path or bundle["chain"]
    quote_path = core_quote_path or default_core_quote_path()
    quotes = load_core_quotes(quote_path)
    continuous = load_typed_parquet(continuous_path, ResearchContinuousPriceDailyRow)
    chains = load_typed_parquet(chain_path, CoreChainMapDailyRow)
    core_dates = sorted({row.trade_date for row in quotes})
    target_date = trade_date or core_dates[-1]
    if target_date not in core_dates:
        raise StrategyError(f"shadow date is absent from core quote dates: {target_date}")
    if record_mode == "FORWARD_CAPTURE" and target_date != core_dates[-1]:
        raise StrategyError(
            "FORWARD_CAPTURE requires the latest core date; use HISTORICAL_REPLAY otherwise"
        )
    shanghai_today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if record_mode == "FORWARD_CAPTURE" and target_date != shanghai_today:
        raise StrategyError(
            "FORWARD_CAPTURE requires today's Shanghai trade date; stale history must use "
            "HISTORICAL_REPLAY"
        )
    if target_date not in {row.trade_date for row in continuous}:
        raise StrategyError("strategy inputs are stale; run strategy prepare-inputs first")

    config = load_product_config("CF")
    if not isinstance(config.multiplier, int | float):
        raise StrategyError("CF multiplier must be confirmed before shadow accounting")
    active_run_id = run_id or _default_run_id(target_date)
    event_base = event_root or data_dir() / "strategy" / "CF" / "shadow_events"
    ledger_base = ledger_root or data_dir() / "strategy" / "CF"
    statuses: list[ShadowStrategyStatus] = []
    for spec in active_specs:
        statuses.append(
            _run_one_strategy(
                spec=spec,
                registry_specs=registry.specs,
                trade_date=target_date,
                record_mode=record_mode,
                quotes=quotes,
                continuous=continuous,
                chains=chains,
                core_dates=core_dates,
                multiplier=float(config.multiplier),
                quote_path=quote_path,
                continuous_path=continuous_path,
                chain_path=chain_path,
                event_root=event_base,
                ledger_root=ledger_base,
                overwrite_reason=overwrite_reason,
                run_id=active_run_id,
            )
        )
    daily_root = daily_output_root or project_root() / "runs" / "daily"
    output_dir = daily_root / "CF" / target_date.isoformat()
    result = ShadowRunResult(
        trade_date=target_date,
        record_mode=record_mode,
        run_id=active_run_id,
        strategies=tuple(statuses),
        json_path=output_dir / "strategy_shadow.json",
        markdown_path=output_dir / "strategy_shadow.md",
    )
    _write_daily_summary(result)
    return result


def _run_one_strategy(
    *,
    spec: StrategySpec,
    registry_specs: list[StrategySpec],
    trade_date: date,
    record_mode: str,
    quotes: list[object],
    continuous: list[ResearchContinuousPriceDailyRow],
    chains: list[CoreChainMapDailyRow],
    core_dates: list[date],
    multiplier: float,
    quote_path: Path,
    continuous_path: Path,
    chain_path: Path,
    event_root: Path,
    ledger_root: Path,
    overwrite_reason: str | None,
    run_id: str,
) -> ShadowStrategyStatus:
    strategy_dir = event_root / spec.strategy_id
    ledger_path = ledger_root / f"{spec.strategy_id}_{spec.version}_shadow_ledger.parquet"
    existing = _load_ledger(ledger_path)
    latest_existing_date = (
        pd.to_datetime(existing["trade_date"]).dt.date.max() if not existing.empty else None
    )
    if latest_existing_date is not None and trade_date < latest_existing_date:
        raise StrategyError("shadow corrections are allowed only for the latest ledger date")
    if latest_existing_date is not None and trade_date > latest_existing_date:
        expected = _next_date(core_dates, latest_existing_date)
        if expected != trade_date:
            raise StrategyError(
                f"shadow ledger gap after {latest_existing_date}; "
                f"expected {expected}, got {trade_date}"
            )
    _assert_record_mode_transition(
        existing=existing,
        trade_date=trade_date,
        record_mode=record_mode,
    )
    previous_row = _previous_row(existing, trade_date)
    row = _build_business_row(
        spec=spec,
        registry_specs=registry_specs,
        trade_date=trade_date,
        record_mode=record_mode,
        previous_row=previous_row,
        quotes=quotes,
        continuous=continuous,
        chains=chains,
        core_dates=core_dates,
        multiplier=multiplier,
        input_paths=(quote_path, continuous_path, chain_path),
    )
    same_date = _same_date_row(existing, trade_date)
    if same_date is not None and same_date["business_fingerprint"] == row["business_fingerprint"]:
        event_path = Path(str(same_date["event_path"]))
        return ShadowStrategyStatus(
            strategy_key=spec.spec_key,
            status="NO_CHANGES",
            event_path=event_path,
            ledger_path=ledger_path,
            nav=float(same_date["nav"]),
            target_lots=int(same_date["target_lots"]),
            target_contract=str(same_date["target_contract"]),
            warning_count=len(json.loads(str(same_date["warnings_json"]))),
        )
    if same_date is not None and not overwrite_reason:
        raise StrategyError(
            f"shadow row changed for {spec.spec_key} {trade_date}; --overwrite-reason is required"
        )

    prior_event_path = _latest_event_path(strategy_dir)
    event_id = f"{trade_date:%Y%m%d}_{datetime.now(UTC):%H%M%S%f}_{uuid.uuid4().hex[:8]}"
    event_path = strategy_dir / trade_date.isoformat() / f"{event_id}.json"
    event_payload = {
        "schema_version": SHADOW_SCHEMA_VERSION,
        "event_id": event_id,
        "event_type": "CORRECTION" if same_date is not None else "SHADOW_DAILY",
        "recorded_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "previous_event_sha256": _sha256(prior_event_path) if prior_event_path else None,
        "supersedes_event_sha256": (
            _sha256(Path(str(same_date["event_path"]))) if same_date is not None else None
        ),
        "overwrite_reason": overwrite_reason if same_date is not None else None,
        "business_row": row,
    }
    _atomic_write_json(event_path, event_payload)
    materialized_row = {
        **row,
        "event_id": event_id,
        "event_type": event_payload["event_type"],
        "recorded_at": event_payload["recorded_at"],
        "run_id": run_id,
        "event_path": str(event_path),
        "event_sha256": _sha256(event_path),
        "overwrite_reason": event_payload["overwrite_reason"],
    }
    updated = _materialized_with_row(existing, materialized_row)
    _assert_prior_rows_unchanged(existing=existing, updated=updated, trade_date=trade_date)
    _atomic_write_parquet(ledger_path, updated)
    return ShadowStrategyStatus(
        strategy_key=spec.spec_key,
        status="CORRECTED" if same_date is not None else "APPENDED",
        event_path=event_path,
        ledger_path=ledger_path,
        nav=float(row["nav"]),
        target_lots=int(row["target_lots"]),
        target_contract=str(row["target_contract"]),
        warning_count=len(json.loads(str(row["warnings_json"]))),
    )


def _build_business_row(
    *,
    spec: StrategySpec,
    registry_specs: list[StrategySpec],
    trade_date: date,
    record_mode: str,
    previous_row: dict[str, object] | None,
    quotes: list[object],
    continuous: list[ResearchContinuousPriceDailyRow],
    chains: list[CoreChainMapDailyRow],
    core_dates: list[date],
    multiplier: float,
    input_paths: tuple[Path, ...],
) -> dict[str, object]:
    quote_by_key = {(row.contract_code, row.trade_date): row for row in quotes}
    chain_by_date = {row.trade_date: row for row in chains}
    chain = chain_by_date.get(trade_date)
    if chain is None:
        raise StrategyError(f"chain map missing for shadow date {trade_date}")

    # 历史回放只用于工程验收，首次真实前向记录必须从独立的零仓账户段开始。
    accounting_segment_start = record_mode == "FORWARD_CAPTURE" and (
        previous_row is None
        or str(previous_row.get("record_mode", "")) != "FORWARD_CAPTURE"
    )
    accounting_previous_row = None if accounting_segment_start else previous_row
    held_contract_before = (
        str(accounting_previous_row["held_contract_after"])
        if accounting_previous_row
        else ""
    )
    held_lots_before = (
        int(accounting_previous_row["held_lots_after"])
        if accounting_previous_row
        else 0
    )
    previous_trade_date = (
        pd.to_datetime(accounting_previous_row["trade_date"]).date()
        if accounting_previous_row
        else None
    )
    gross_pnl = _holding_pnl(
        held_contract=held_contract_before,
        held_lots=held_lots_before,
        previous_date=previous_trade_date,
        current_date=trade_date,
        quote_by_key=quote_by_key,
        multiplier=multiplier,
    )
    executed_contract = (
        str(accounting_previous_row["target_contract"])
        if accounting_previous_row
        else ""
    )
    executed_target_lots = (
        int(accounting_previous_row["target_lots"])
        if accounting_previous_row
        else 0
    )
    executed_signal_date = (
        str(accounting_previous_row["trade_date"])
        if accounting_previous_row
        else ""
    )
    cost_bps = spec.costs["normal_cost"].one_way_bps
    cost, turnover_lots, turnover_notional, fill_price = _execution_cost(
        held_contract=held_contract_before,
        held_lots=held_lots_before,
        target_contract=executed_contract,
        target_lots=executed_target_lots,
        trade_date=trade_date,
        quote_by_key=quote_by_key,
        multiplier=multiplier,
        one_way_bps=cost_bps,
    )
    held_contract_after = executed_contract if executed_target_lots else ""
    held_lots_after = executed_target_lots
    net_pnl = gross_pnl - cost
    previous_nav = (
        float(accounting_previous_row["nav"])
        if accounting_previous_row
        else spec.sizing.capital_base
    )
    nav = previous_nav + net_pnl
    previous_high = (
        float(accounting_previous_row["high_watermark"])
        if accounting_previous_row
        else spec.sizing.capital_base
    )
    high_watermark = max(previous_high, nav)
    entry_date, holding_days = _entry_state(
        previous_row=accounting_previous_row,
        held_contract_after=held_contract_after,
        held_lots_after=held_lots_after,
        trade_date=trade_date,
    )
    signal, gate_multipliers, warnings = _strategy_signal(
        spec=spec,
        registry_specs=registry_specs,
        trade_date=trade_date,
        target_contract=chain.mapped_contract,
        previous_target_lots=(
            int(accounting_previous_row["target_lots"])
            if accounting_previous_row
            else 0
        ),
        quotes=quotes,
        continuous=continuous,
        multiplier=multiplier,
    )
    next_date = _next_date(core_dates, trade_date, required=False)
    execution_status = (
        "NO_PRIOR_TARGET" if accounting_previous_row is None else "EXECUTED_AT_SETTLE"
    )
    row = {
        "schema_version": SHADOW_SCHEMA_VERSION,
        "rule_version": SHADOW_RULE_VERSION,
        "trade_date": trade_date.isoformat(),
        "product": "CF",
        "strategy_id": spec.strategy_id,
        "spec_version": spec.version,
        "strategy_key": spec.spec_key,
        "record_mode": record_mode,
        "accounting_segment_start": accounting_segment_start,
        "cost_scenario": "normal_cost",
        "one_way_bps": cost_bps,
        "executed_signal_date": executed_signal_date,
        "execution_status": execution_status,
        "executed_contract": executed_contract,
        "executed_target_lots": executed_target_lots,
        "executed_change_lots": executed_target_lots - held_lots_before,
        "fill_price": fill_price,
        "held_contract_before": held_contract_before,
        "held_lots_before": held_lots_before,
        "held_contract_after": held_contract_after,
        "held_lots_after": held_lots_after,
        "entry_date": entry_date,
        "holding_days": holding_days,
        "gross_pnl": gross_pnl,
        "cost": cost,
        "net_pnl": net_pnl,
        "nav": nav,
        "high_watermark": high_watermark,
        "drawdown": nav / high_watermark - 1.0,
        "turnover_lots": turnover_lots,
        "turnover_notional": turnover_notional,
        "signal_direction": signal.direction,
        "annualized_sigma": signal.annualized_sigma,
        "momentum": signal.momentum,
        "target_contract": signal.target_contract,
        "target_lots": signal.target_lots,
        "planned_execution_date": next_date.isoformat() if next_date else None,
        "target_status": (
            "READY_FOR_T_PLUS_1" if next_date else "PENDING_NEXT_OFFICIAL_SESSION"
        ),
        "gate_multipliers_json": json.dumps(
            gate_multipliers, ensure_ascii=False, sort_keys=True
        ),
        "signals_snapshot_json": json.dumps(
            {
                "adjusted_settle": signal.adjusted_settle,
                "momentum": signal.momentum,
                "direction": signal.direction,
                "annualized_sigma": signal.annualized_sigma,
                "warning_code": signal.warning_code,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        "warnings_json": json.dumps(warnings, ensure_ascii=False, sort_keys=True),
        "input_snapshot_ids_json": json.dumps(
            list(signal.input_snapshot_ids), ensure_ascii=False, sort_keys=True
        ),
        "input_sha256_json": json.dumps(
            {str(path): _sha256(path) for path in input_paths},
            ensure_ascii=False,
            sort_keys=True,
        ),
        "research_boundary": RESEARCH_BOUNDARY,
    }
    row["business_fingerprint"] = _business_fingerprint(row)
    return row


def _strategy_signal(
    *,
    spec: StrategySpec,
    registry_specs: list[StrategySpec],
    trade_date: date,
    target_contract: str,
    previous_target_lots: int,
    quotes: list[object],
    continuous: list[ResearchContinuousPriceDailyRow],
    multiplier: float,
) -> tuple[TsmomSignalSnapshot, dict[str, float], list[str]]:
    baseline = spec
    if spec.strategy_type == "phase_gated":
        matches = [item for item in registry_specs if item.spec_key == spec.base_strategy]
        if len(matches) != 1:
            raise StrategyError(f"cannot resolve candidate base strategy {spec.base_strategy}")
        baseline = matches[0]
    signal = compute_tsmom_signal_snapshot(
        spec=baseline,
        continuous_rows=continuous,
        quotes=quotes,
        trade_date=trade_date,
        target_contract=target_contract,
        multiplier=multiplier,
    )
    warnings = [signal.warning_code] if signal.warning_code else []
    gates = {"phase": 1.0, "carry": 1.0, "option": 1.0}
    if spec.strategy_type != "phase_gated":
        return signal, gates, warnings

    matrix = _load_signal_matrix(_latest_signal_matrix_path(), horizon=spec.signal_horizon)
    phases = _load_trend_phase(_latest_trend_phase_path())
    matrix_row = _rows_by_date(matrix).get(trade_date)
    phase_row = _rows_by_date(phases).get(trade_date)
    g_phase, phase_code, phase_warning = _phase_multiplier(
        row=phase_row,
        direction=signal.direction,
        parameters=_gate(spec, "phase").parameters,
    )
    g_carry = _carry_multiplier(
        row=matrix_row,
        direction=signal.direction,
        parameters=_gate(spec, "carry_tilt").parameters,
    )
    g_option, option_warning = _option_multiplier(
        row=matrix_row,
        direction=signal.direction,
        parameters=_gate(spec, "option_veto").parameters,
    )
    target_lots = int(round(signal.target_lots * g_phase * g_carry * g_option))
    if phase_code == "S3":
        target_lots = _s3_no_add(
            raw_target=target_lots,
            previous_target=previous_target_lots,
        )
    signal = TsmomSignalSnapshot(
        **{**signal.__dict__, "target_lots": target_lots}
    )
    warnings.extend(value for value in (phase_warning, option_warning) if value)
    return signal, {"phase": g_phase, "carry": g_carry, "option": g_option}, warnings


def _holding_pnl(
    *,
    held_contract: str,
    held_lots: int,
    previous_date: date | None,
    current_date: date,
    quote_by_key: dict[tuple[str, date], object],
    multiplier: float,
) -> float:
    if held_lots == 0 or not held_contract or previous_date is None:
        return 0.0
    previous = quote_by_key.get((held_contract, previous_date))
    current = quote_by_key.get((held_contract, current_date))
    if previous is None or current is None or previous.settle is None or current.settle is None:
        raise StrategyError(
            f"cannot mark shadow holding {held_contract} from {previous_date} to {current_date}"
        )
    return held_lots * (float(current.settle) - float(previous.settle)) * multiplier


def _execution_cost(
    *,
    held_contract: str,
    held_lots: int,
    target_contract: str,
    target_lots: int,
    trade_date: date,
    quote_by_key: dict[tuple[str, date], object],
    multiplier: float,
    one_way_bps: float,
) -> tuple[float, int, float, float | None]:
    orders: list[tuple[str, int]] = []
    if held_contract and held_contract != target_contract and held_lots:
        orders.append((held_contract, -held_lots))
        if target_contract and target_lots:
            orders.append((target_contract, target_lots))
    elif target_contract:
        delta = target_lots - held_lots
        if delta:
            orders.append((target_contract, delta))
    elif held_contract and held_lots:
        orders.append((held_contract, -held_lots))
    cost = 0.0
    turnover_lots = 0
    turnover_notional = 0.0
    fill_price: float | None = None
    for contract, lots in orders:
        quote = quote_by_key.get((contract, trade_date))
        if quote is None or quote.settle is None:
            raise StrategyError(f"execution settlement missing for {contract} on {trade_date}")
        price = float(quote.settle)
        notional = abs(lots) * price * multiplier
        cost += notional * one_way_bps / 10_000.0
        turnover_lots += abs(lots)
        turnover_notional += notional
        if contract == target_contract:
            fill_price = price
    return cost, turnover_lots, turnover_notional, fill_price


def _entry_state(
    *,
    previous_row: dict[str, object] | None,
    held_contract_after: str,
    held_lots_after: int,
    trade_date: date,
) -> tuple[str | None, int]:
    if held_lots_after == 0:
        return None, 0
    if previous_row is not None:
        previous_lots = int(previous_row["held_lots_after"])
        same_direction = (previous_lots > 0) == (held_lots_after > 0) and previous_lots != 0
        if same_direction:
            return str(previous_row["entry_date"]), int(previous_row["holding_days"]) + 1
    return trade_date.isoformat(), 1


def _load_ledger(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


def _previous_row(frame: pd.DataFrame, trade_date: date) -> dict[str, object] | None:
    if frame.empty:
        return None
    dates = pd.to_datetime(frame["trade_date"]).dt.date
    selected = frame.loc[dates < trade_date]
    if selected.empty:
        return None
    return selected.sort_values("trade_date").iloc[-1].to_dict()


def _same_date_row(frame: pd.DataFrame, trade_date: date) -> dict[str, object] | None:
    if frame.empty:
        return None
    selected = frame.loc[pd.to_datetime(frame["trade_date"]).dt.date.eq(trade_date)]
    return selected.iloc[-1].to_dict() if not selected.empty else None


def _assert_record_mode_transition(
    *,
    existing: pd.DataFrame,
    trade_date: date,
    record_mode: str,
) -> None:
    """前向记录启用后，禁止把同日或后续日期重新标记为历史回放。"""
    if existing.empty or record_mode != "HISTORICAL_REPLAY":
        return
    dates = pd.to_datetime(existing["trade_date"]).dt.date
    prior_or_same = existing.loc[dates <= trade_date]
    if prior_or_same["record_mode"].eq("FORWARD_CAPTURE").any():
        raise StrategyError(
            "shadow ledger cannot return to HISTORICAL_REPLAY after FORWARD_CAPTURE starts"
        )


def _materialized_with_row(frame: pd.DataFrame, row: dict[str, object]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame([row])
    dates = pd.to_datetime(frame["trade_date"]).dt.date
    retained = frame.loc[dates != date.fromisoformat(str(row["trade_date"]))].copy()
    return pd.concat([retained, pd.DataFrame([row])], ignore_index=True).sort_values(
        "trade_date"
    )


def _assert_prior_rows_unchanged(
    *,
    existing: pd.DataFrame,
    updated: pd.DataFrame,
    trade_date: date,
) -> None:
    if existing.empty:
        return
    old = existing.loc[pd.to_datetime(existing["trade_date"]).dt.date < trade_date]
    new = updated.loc[pd.to_datetime(updated["trade_date"]).dt.date < trade_date]
    old_values = old.sort_values("trade_date")["business_fingerprint"].tolist()
    new_values = new.sort_values("trade_date")["business_fingerprint"].tolist()
    if old_values != new_values:
        raise StrategyError("shadow ledger historical rows changed during materialization")


def _business_fingerprint(row: dict[str, object]) -> str:
    payload = {key: value for key, value in row.items() if key != "business_fingerprint"}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f".tmp.{uuid.uuid4().hex}.json")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)


def _atomic_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f".tmp.{uuid.uuid4().hex}.parquet")
    frame.to_parquet(temp, index=False)
    os.replace(temp, path)


def _latest_event_path(strategy_dir: Path) -> Path | None:
    paths = sorted(strategy_dir.glob("*/*.json"), key=lambda path: path.stat().st_mtime_ns)
    return paths[-1] if paths else None


def _next_date(values: list[date], value: date, *, required: bool = True) -> date | None:
    for candidate in values:
        if candidate > value:
            return candidate
    if required:
        raise StrategyError(f"no next core trading date after {value}")
    return None


def _write_daily_summary(result: ShadowRunResult) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**result.to_summary(), "research_boundary": RESEARCH_BOUNDARY}
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        f"# CF 策略影子台账 - {result.trade_date}",
        "",
        f"- 记录模式：`{result.record_mode}`",
        "",
        "| 策略 | 状态 | NAV | 当前目标 | 合约 | 警告 |",
        "| --- | --- | ---: | ---: | --- | ---: |",
    ]
    for item in result.strategies:
        lines.append(
            f"| {item.strategy_key} | {item.status} | {item.nav:.2f} | "
            f"{item.target_lots} | {item.target_contract} | {item.warning_count} |"
        )
    lines.extend(["", "## 研究边界", "", f"- {RESEARCH_BOUNDARY}"])
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sha256(path: Path | None) -> str | None:
    if path is None:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_run_id(trade_date: date) -> str:
    return f"cf_shadow_{trade_date:%Y%m%d}_{datetime.now(UTC):%H%M%S}_{uuid.uuid4().hex[:8]}"
