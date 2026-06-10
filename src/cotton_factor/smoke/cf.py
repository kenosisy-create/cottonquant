"""D19 CF full-chain smoke workflow."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from cotton_factor.archive import (
    AuditLogWriter,
    build_archive_bundle,
    build_audit_event,
    build_run_manifest,
    register_artifact,
    write_artifact_registry,
    write_audit_event,
    write_run_manifest,
)
from cotton_factor.archive.artifact_registry import ArtifactRecord
from cotton_factor.archive.report_renderer import render_backtest_report
from cotton_factor.backtest import build_target_lots_from_scores, run_daily_backtest
from cotton_factor.common.exceptions import SmokeError
from cotton_factor.common.paths import data_dir, project_root
from cotton_factor.common.time import utc_now
from cotton_factor.core import (
    CoreChainMapDailyRow,
    CoreContractMasterRow,
    CoreQuoteDailyRow,
    ResearchContinuousPriceDailyRow,
    ResearchFactorValueDailyRow,
    build_chain_map,
    build_contract_master,
    build_trade_mapping,
    build_trading_calendar,
    normalize_quote_snapshots,
    normalize_settlement_snapshots,
)
from cotton_factor.ingest.czce_history import ingest_czce_history
from cotton_factor.ingest.czce_settlement_param import ingest_czce_settlement_param
from cotton_factor.research import (
    CARRY_FACTOR_ID,
    CURVE_SLOPE_FACTOR_ID,
    MOMENTUM_FACTOR_ID,
    OI_PRESSURE_FACTOR_ID,
    FactorInputBundle,
    build_continuous_price,
    build_equal_weight_scores,
    build_forward_returns,
    compute_carry_factor,
    compute_curve_slope_factor,
    compute_momentum_factor,
    compute_oi_pressure_factor,
    evaluate_single_factor,
)

DEFAULT_PRODUCT_CODE = "CF"
DEFAULT_SIGNAL_OBJECT_ID = "CF.C1"
DEFAULT_UNIVERSE = "CF_MAIN"
DEFAULT_STRATEGY_ID = "cf_equal_weight_v1"


@dataclass(frozen=True)
class CfSmokeResult:
    """Result of the D19 CF full-chain smoke workflow."""

    run_id: str
    start: date
    end: date
    archive_dir: Path
    report_path: Path
    manifest_path: Path
    audit_path: Path
    checksums_path: Path
    registry_path: Path
    bundle_path: Path
    row_counts: dict[str, int]
    input_snapshot_ids: list[str]
    warnings: list[str]

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable summary for CLI output."""
        return {
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "archive_dir": str(self.archive_dir),
            "report_path": str(self.report_path),
            "manifest_path": str(self.manifest_path),
            "audit_path": str(self.audit_path),
            "checksums_path": str(self.checksums_path),
            "registry_path": str(self.registry_path),
            "bundle_path": str(self.bundle_path),
            "row_counts": self.row_counts,
            "input_snapshot_ids": self.input_snapshot_ids,
            "warnings": self.warnings,
        }


def run_cf_smoke(
    *,
    start: date,
    end: date,
    run_id: str | None = None,
    history_fixture_path: Path | None = None,
    settlement_fixture_path: Path | None = None,
    raw_root: Path | None = None,
    archive_root: Path | None = None,
) -> CfSmokeResult:
    """Run the D19 CF fixture/raw to report/archive smoke chain."""
    if start > end:
        raise SmokeError("start must be <= end")
    if start.year != end.year:
        raise SmokeError("D19 CF smoke currently expects one calendar year")

    active_run_id = run_id or _default_run_id(start=start, end=end)
    active_archive_dir = (archive_root or data_dir() / "archive") / active_run_id
    active_archive_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = active_archive_dir / "artifacts"
    reports_dir = active_archive_dir / "reports"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    audit_path = active_archive_dir / "audit.jsonl"
    manifest_path = active_archive_dir / "manifest.json"
    checksums_path = active_archive_dir / "checksums.json"
    registry_path = active_archive_dir / "artifact_registry.json"
    bundle_path = active_archive_dir / f"{active_run_id}_bundle.zip"
    report_path = reports_dir / "backtest.html"
    audit = AuditLogWriter(audit_path)
    started_at = utc_now()
    audit.record(
        run_id=active_run_id,
        event_type="smoke_started",
        message="D19 CF full-chain smoke started",
        payload={"start": start.isoformat(), "end": end.isoformat()},
        created_at_utc=started_at,
    )

    history_fixture = history_fixture_path or default_history_fixture_path()
    settlement_fixture = settlement_fixture_path or default_settlement_fixture_path()
    history_ingest = ingest_czce_history(
        year=start.year,
        product_code=DEFAULT_PRODUCT_CODE,
        file_type="csv",
        fixture_path=history_fixture,
        raw_root=raw_root,
    )
    settlement_ingest = ingest_czce_settlement_param(
        trade_date=start,
        product_code=DEFAULT_PRODUCT_CODE,
        fixture_path=settlement_fixture,
        raw_root=raw_root,
    )
    input_snapshot_ids = [
        *(snapshot.snapshot_id for snapshot in history_ingest.snapshots),
        settlement_ingest.snapshot.snapshot_id,
    ]
    audit.record(
        run_id=active_run_id,
        event_type="raw_ingested",
        message="raw fixture snapshots captured",
        payload={"snapshot_ids": input_snapshot_ids},
    )

    quote_result = normalize_quote_snapshots(
        snapshot_ids=[snapshot.snapshot_id for snapshot in history_ingest.snapshots],
        raw_root=raw_root,
    )
    settlement_result = normalize_settlement_snapshots(
        snapshot_ids=[settlement_ingest.snapshot.snapshot_id],
        raw_root=raw_root,
    )
    quotes = quote_result.rows
    signal_quotes = _quote_window(quotes=quotes, start=start, end=end)
    if not signal_quotes:
        raise SmokeError("D19 CF smoke produced no quote rows in requested window")

    calendar_result = build_trading_calendar(
        start=date(start.year, 1, 1),
        end=date(start.year, 12, 31),
        exchange="CZCE",
    )
    contract_result = build_contract_master(
        product_code=DEFAULT_PRODUCT_CODE,
        year=start.year,
        trading_dates=calendar_result.calendar.trading_dates,
    )
    chain_result = build_chain_map(
        quotes=signal_quotes,
        contracts=contract_result.contracts,
        calendar=calendar_result.calendar,
        product_code=DEFAULT_PRODUCT_CODE,
        signal_object_id=DEFAULT_SIGNAL_OBJECT_ID,
    )
    trade_result = build_trade_mapping(
        chain_rows=chain_result.rows,
        contracts=contract_result.contracts,
        calendar=calendar_result.calendar,
        product_code=DEFAULT_PRODUCT_CODE,
        signal_object_id=DEFAULT_SIGNAL_OBJECT_ID,
        settlement_rows=settlement_result.rows,
    )
    continuous_result = build_continuous_price(
        quotes=signal_quotes,
        chain_rows=chain_result.rows,
        product_code=DEFAULT_PRODUCT_CODE,
        signal_object_id=DEFAULT_SIGNAL_OBJECT_ID,
    )

    factor_rows = _compute_factor_rows(
        run_id=active_run_id,
        quotes=signal_quotes,
        contracts=contract_result.contracts,
        chain_rows=chain_result.rows,
        continuous_rows=continuous_result.rows,
    )
    forward_result = build_forward_returns(
        trade_mappings=trade_result.rows,
        quotes=quotes,
        run_id=active_run_id,
        product_code=DEFAULT_PRODUCT_CODE,
        universe=DEFAULT_UNIVERSE,
        signal_object_id=DEFAULT_SIGNAL_OBJECT_ID,
        horizon=1,
    )
    evaluation_result = evaluate_single_factor(
        factor_rows=[
            row for row in factor_rows.rows if row.factor_id == MOMENTUM_FACTOR_ID
        ],
        forward_returns=forward_result.rows,
        run_id=active_run_id,
        factor_id=MOMENTUM_FACTOR_ID,
        product_code=DEFAULT_PRODUCT_CODE,
        universe=DEFAULT_UNIVERSE,
        horizon=1,
    )
    score_result = build_equal_weight_scores(
        factor_rows=factor_rows.rows,
        run_id=active_run_id,
        product_code=DEFAULT_PRODUCT_CODE,
        universe=DEFAULT_UNIVERSE,
        signal_object_id=DEFAULT_SIGNAL_OBJECT_ID,
        factor_ids=[
            CARRY_FACTOR_ID,
            MOMENTUM_FACTOR_ID,
            CURVE_SLOPE_FACTOR_ID,
            OI_PRESSURE_FACTOR_ID,
        ],
    )
    target_result = build_target_lots_from_scores(
        score_rows=score_result.rows,
        trade_mappings=trade_result.rows,
        run_id=active_run_id,
        product_code=DEFAULT_PRODUCT_CODE,
        strategy_id=DEFAULT_STRATEGY_ID,
        universe=DEFAULT_UNIVERSE,
        signal_object_id=DEFAULT_SIGNAL_OBJECT_ID,
    )
    backtest_result = run_daily_backtest(
        target_lot_rows=target_result.rows,
        quotes=quotes,
        contracts=contract_result.contracts,
        run_id=active_run_id,
        product_code=DEFAULT_PRODUCT_CODE,
        strategy_id=DEFAULT_STRATEGY_ID,
        universe=DEFAULT_UNIVERSE,
        signal_object_id=DEFAULT_SIGNAL_OBJECT_ID,
    )

    warnings = _unique_warnings(
        [
            *quote_result.warnings,
            *settlement_result.warnings,
            *calendar_result.warnings,
            *contract_result.warnings,
            *chain_result.warnings,
            *trade_result.warnings,
            *continuous_result.warnings,
            *factor_rows.warnings,
            *forward_result.warnings,
            *evaluation_result.warnings,
            *score_result.warnings,
            *target_result.warnings,
            *backtest_result.warnings,
        ]
    )
    row_counts = {
        "raw_snapshots": len(input_snapshot_ids),
        "core_quote_daily": len(quotes),
        "core_quote_daily_signal_window": len(signal_quotes),
        "core_settlement_param_daily": len(settlement_result.rows),
        "core_contract_master": len(contract_result.contracts),
        "core_chain_map_daily": len(chain_result.rows),
        "core_trade_mapping_daily": len(trade_result.rows),
        "research_continuous_price_daily": len(continuous_result.rows),
        "research_factor_value_daily": len(factor_rows.rows),
        "research_forward_return_daily": len(forward_result.rows),
        "research_factor_evaluation": len(evaluation_result.rows),
        "research_multifactor_score_daily": len(score_result.rows),
        "backtest_target_lot_daily": len(target_result.rows),
        "backtest_orders": len(backtest_result.orders),
        "backtest_fills": len(backtest_result.fills),
        "backtest_equity_points": len(backtest_result.equity_curve),
        "backtest_blocked_signals": len(backtest_result.blocked_signals),
    }
    _assert_smoke_outputs(row_counts=row_counts)

    render_backtest_report(
        run_id=active_run_id,
        summary=backtest_result.report_summary(),
        equity_curve=backtest_result.equity_records(),
        trades=backtest_result.trade_records(),
        output_path=report_path,
        warnings=warnings,
        input_snapshot_ids=input_snapshot_ids,
    )
    audit.record(
        run_id=active_run_id,
        event_type="analytics_completed",
        message="core, research, backtest, and report artifacts completed",
        payload=row_counts,
    )

    manifest = build_run_manifest(
        run_id=active_run_id,
        run_type="cf_full_chain_smoke",
        input_snapshot_ids=input_snapshot_ids,
        row_counts=row_counts,
        artifact_paths=[
            _relative_path(path=report_path, root=active_archive_dir),
            _relative_path(path=audit_path, root=active_archive_dir),
            _relative_path(path=checksums_path, root=active_archive_dir),
            _relative_path(path=registry_path, root=active_archive_dir),
        ],
        warnings=warnings,
        started_at_utc=started_at,
        ended_at_utc=utc_now(),
    )
    write_run_manifest(manifest, manifest_path)
    write_audit_event(
        audit_path,
        build_audit_event(
            run_id=active_run_id,
            event_type="manifest_written",
            message="run manifest written before archive bundling",
            payload={"manifest_path": str(manifest_path)},
        ),
    )

    primary_records = [
        register_artifact(
            path=manifest_path,
            artifact_type="run_manifest",
            root=active_archive_dir,
        ),
        register_artifact(path=audit_path, artifact_type="audit_log", root=active_archive_dir),
        register_artifact(path=report_path, artifact_type="html_report", root=active_archive_dir),
    ]
    _write_checksums(records=primary_records, path=checksums_path)
    records = [
        *primary_records,
        register_artifact(path=checksums_path, artifact_type="checksums", root=active_archive_dir),
    ]
    write_artifact_registry(records, registry_path)
    bundle_result = build_archive_bundle(
        bundle_path=bundle_path,
        artifact_paths=[manifest_path, audit_path, checksums_path, registry_path, report_path],
        root=active_archive_dir,
    )
    row_counts["archive_artifacts"] = bundle_result.artifact_count
    row_counts["archive_bundle_bytes"] = bundle_result.byte_size

    return CfSmokeResult(
        run_id=active_run_id,
        start=start,
        end=end,
        archive_dir=active_archive_dir,
        report_path=report_path,
        manifest_path=manifest_path,
        audit_path=audit_path,
        checksums_path=checksums_path,
        registry_path=registry_path,
        bundle_path=bundle_path,
        row_counts=row_counts,
        input_snapshot_ids=input_snapshot_ids,
        warnings=warnings,
    )


@dataclass(frozen=True)
class _FactorRowsResult:
    rows: list[ResearchFactorValueDailyRow]
    warnings: list[str]


def _compute_factor_rows(
    *,
    run_id: str,
    quotes: Sequence[CoreQuoteDailyRow],
    contracts: Sequence[CoreContractMasterRow],
    chain_rows: Sequence[CoreChainMapDailyRow],
    continuous_rows: Sequence[ResearchContinuousPriceDailyRow],
) -> _FactorRowsResult:
    core_inputs = FactorInputBundle(
        tables={
            "core_quote_daily": quotes,
            "core_contract_master": contracts,
            "core_chain_map_daily": chain_rows,
            "research_continuous_price_daily": continuous_rows,
        }
    )
    results = [
        compute_carry_factor(
            inputs=core_inputs,
            run_id=run_id,
            product_code=DEFAULT_PRODUCT_CODE,
            universe=DEFAULT_UNIVERSE,
            signal_object_id=DEFAULT_SIGNAL_OBJECT_ID,
        ),
        compute_momentum_factor(
            inputs=core_inputs,
            run_id=run_id,
            product_code=DEFAULT_PRODUCT_CODE,
            universe=DEFAULT_UNIVERSE,
            signal_object_id=DEFAULT_SIGNAL_OBJECT_ID,
        ),
        compute_curve_slope_factor(
            inputs=core_inputs,
            run_id=run_id,
            product_code=DEFAULT_PRODUCT_CODE,
            universe=DEFAULT_UNIVERSE,
            signal_object_id=DEFAULT_SIGNAL_OBJECT_ID,
        ),
        compute_oi_pressure_factor(
            inputs=core_inputs,
            run_id=run_id,
            product_code=DEFAULT_PRODUCT_CODE,
            universe=DEFAULT_UNIVERSE,
            signal_object_id=DEFAULT_SIGNAL_OBJECT_ID,
        ),
    ]
    rows = [row for result in results for row in result.rows]
    warnings = _unique_warnings([warning for result in results for warning in result.warnings])
    return _FactorRowsResult(rows=rows, warnings=warnings)


def default_history_fixture_path() -> Path:
    """Return the default D19 history fixture path."""
    return project_root() / "tests" / "fixtures" / "czce_history_full_chain_2024"


def default_settlement_fixture_path() -> Path:
    """Return the default D19 settlement fixture path."""
    return project_root() / "tests" / "fixtures" / "czce_settlement_param_sample.csv"


def _quote_window(
    *,
    quotes: Sequence[CoreQuoteDailyRow],
    start: date,
    end: date,
) -> list[CoreQuoteDailyRow]:
    return [quote for quote in quotes if start <= quote.trade_date <= end]


def _write_checksums(*, records: Sequence[ArtifactRecord], path: Path) -> Path:
    payload = [
        {
            "artifact_id": record.artifact_id,
            "artifact_type": record.artifact_type,
            "path": record.path,
            "sha256": record.sha256,
            "byte_size": record.byte_size,
        }
        for record in sorted(records, key=lambda item: item.path)
    ]
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _assert_smoke_outputs(*, row_counts: Mapping[str, int]) -> None:
    required_positive = [
        "core_quote_daily",
        "core_chain_map_daily",
        "core_trade_mapping_daily",
        "research_factor_value_daily",
        "research_forward_return_daily",
        "research_factor_evaluation",
        "research_multifactor_score_daily",
        "backtest_target_lot_daily",
        "backtest_orders",
        "backtest_fills",
    ]
    missing = [name for name in required_positive if row_counts.get(name, 0) <= 0]
    if missing:
        raise SmokeError(f"D19 CF smoke did not produce required outputs: {missing}")


def _default_run_id(*, start: date, end: date) -> str:
    timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    return f"cf_smoke_{start.isoformat()}_{end.isoformat()}_{timestamp}"


def _relative_path(*, path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _unique_warnings(warnings: Sequence[str]) -> list[str]:
    values: list[str] = []
    for warning in warnings:
        if warning not in values:
            values.append(warning)
    return values
