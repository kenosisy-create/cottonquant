"""Public CLI entrypoint for cotton-factor."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Annotated

from cotton_factor import __version__
from cotton_factor.common.exceptions import (
    ChainMapError,
    ConfigError,
    ContinuousPriceError,
    ContractMasterError,
    CottonFactorError,
    FetchError,
    TradeMappingError,
    TradingCalendarError,
)

try:
    import typer
except ModuleNotFoundError:  # pragma: no cover - exercised only before dev deps install.
    typer = None  # type: ignore[assignment]

STATUS_MESSAGE = (
    "cotton-factor D23 ready: release freeze packages are available."
)


if typer is not None:
    app = typer.Typer(
        help=(
            "Cotton factor MVP CLI. Raw ingestion, core mapping, and archive tools "
            "are available."
        )
    )
    core_app = typer.Typer(help="Core fact commands.")
    ingest_app = typer.Typer(help="Raw ingestion commands.")
    raw_app = typer.Typer(help="Raw snapshot replay and manifest commands.")
    smoke_app = typer.Typer(help="Smoke test commands.")
    qa_app = typer.Typer(help="QA validation and audit commands.")
    uat_app = typer.Typer(help="UAT replay commands.")
    release_app = typer.Typer(help="Release freeze commands.")

    def _version_callback(value: bool) -> None:
        if value:
            typer.echo(__version__)
            raise typer.Exit()

    @app.callback()
    def main(
        version: Annotated[
            bool,
            typer.Option(
                "--version",
                callback=_version_callback,
                help="Show package version and exit.",
                is_eager=True,
            ),
        ] = False,
    ) -> None:
        """Run cotton-factor commands."""

    @app.command()
    def status() -> None:
        """Show the project status."""
        typer.echo(STATUS_MESSAGE)

    @ingest_app.command("czce-daily-quote")
    def ingest_czce_daily_quote_command(
        trade_date: Annotated[str, typer.Option("--date", help="Trade date in YYYY-MM-DD format.")],
        product: Annotated[str, typer.Option("--product", help="Product code, e.g. CF.")],
        fixture: Annotated[
            Path | None,
            typer.Option(
                "--fixture",
                help="Local raw payload fixture path for network-free tests.",
            ),
        ] = None,
        raw_root: Annotated[
            Path | None,
            typer.Option("--raw-root", help="Raw store root. Defaults to data/raw."),
        ] = None,
    ) -> None:
        """Capture a CZCE daily quote payload as an immutable raw snapshot."""
        from cotton_factor.ingest.czce_daily_quote import ingest_czce_daily_quote

        try:
            result = ingest_czce_daily_quote(
                trade_date=_parse_iso_date(trade_date),
                product_code=product,
                fixture_path=fixture,
                raw_root=raw_root,
            )
        except FetchError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(
            json.dumps(_snapshot_summary(result.snapshot), ensure_ascii=False, sort_keys=True)
        )

    @core_app.command("build-contract-master")
    def build_contract_master_command(
        product: Annotated[str, typer.Option("--product", help="Product code, e.g. CF.")],
        year: Annotated[int, typer.Option("--year", help="Delivery year.")],
        config_dir: Annotated[
            Path | None,
            typer.Option("--config-dir", help="Product config directory."),
        ] = None,
    ) -> None:
        """Build contract master rows from product config."""
        from cotton_factor.core import build_contract_master

        try:
            result = build_contract_master(
                product_code=product,
                year=year,
                config_dir=config_dir,
            )
        except (ConfigError, ContractMasterError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(_contract_master_summary(result), ensure_ascii=False, sort_keys=True))

    @core_app.command("build-calendar")
    def build_calendar_command(
        start: Annotated[str, typer.Option("--start", help="Start date in YYYY-MM-DD format.")],
        end: Annotated[str, typer.Option("--end", help="End date in YYYY-MM-DD format.")],
        exchange: Annotated[str, typer.Option("--exchange", help="Exchange code, e.g. CZCE.")],
        fixture: Annotated[
            Path | None,
            typer.Option("--fixture", help="Optional CSV calendar fixture path."),
        ] = None,
    ) -> None:
        """Build a core trading calendar from fixture or provisional weekdays."""
        from cotton_factor.core import build_trading_calendar

        try:
            result = build_trading_calendar(
                start=_parse_iso_date(start),
                end=_parse_iso_date(end),
                exchange=exchange,
                fixture_path=fixture,
            )
        except TradingCalendarError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(_calendar_summary(result), ensure_ascii=False, sort_keys=True))

    @core_app.command("build-chain-map")
    def build_chain_map_command(
        product: Annotated[str, typer.Option("--product", help="Product code, e.g. CF.")],
        start: Annotated[str, typer.Option("--start", help="Start date in YYYY-MM-DD format.")],
        end: Annotated[str, typer.Option("--end", help="End date in YYYY-MM-DD format.")],
        quote_fixture: Annotated[
            Path,
            typer.Option("--quote-fixture", help="Normalized core quote CSV fixture."),
        ],
        signal_object: Annotated[
            str,
            typer.Option("--signal-object", help="Signal object id, e.g. CF.C1."),
        ] = "CF.C1",
        ltd_buffer_days: Annotated[
            int,
            typer.Option("--ltd-buffer-days", help="Explicit LTD guard buffer in trading days."),
        ] = 0,
    ) -> None:
        """Build chain_map_daily rows from normalized quote fixtures."""
        from cotton_factor.core import (
            build_chain_map,
            build_contract_master,
            build_trading_calendar,
            load_core_quote_daily_csv,
        )

        try:
            start_date = _parse_iso_date(start)
            end_date = _parse_iso_date(end)
            # D8 的 LTD guard 需要交割月完整交易日历；不能只用用户请求的短窗口计算规则。
            calendar_result = build_trading_calendar(
                start=date(start_date.year, 1, 1),
                end=date(start_date.year, 12, 31),
                exchange="CZCE",
            )
            contract_result = build_contract_master(
                product_code=product,
                year=start_date.year,
                trading_dates=calendar_result.calendar.trading_dates,
            )
            chain_result = build_chain_map(
                quotes=_filter_quotes(
                    load_core_quote_daily_csv(quote_fixture),
                    start=start_date,
                    end=end_date,
                ),
                contracts=contract_result.contracts,
                calendar=calendar_result.calendar,
                product_code=product,
                signal_object_id=signal_object,
                ltd_buffer_days=ltd_buffer_days,
            )
        except (ChainMapError, ConfigError, ContractMasterError, TradingCalendarError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(_chain_map_summary(chain_result), ensure_ascii=False, sort_keys=True))

    @core_app.command("build-trade-mapping")
    def build_trade_mapping_command(
        product: Annotated[str, typer.Option("--product", help="Product code, e.g. CF.")],
        start: Annotated[str, typer.Option("--start", help="Start date in YYYY-MM-DD format.")],
        end: Annotated[str, typer.Option("--end", help="End date in YYYY-MM-DD format.")],
        quote_fixture: Annotated[
            Path,
            typer.Option("--quote-fixture", help="Normalized core quote CSV fixture."),
        ],
        signal_object: Annotated[
            str,
            typer.Option("--signal-object", help="Signal object id, e.g. CF.C1."),
        ] = "CF.C1",
        ltd_buffer_days: Annotated[
            int,
            typer.Option("--ltd-buffer-days", help="Explicit LTD guard buffer in trading days."),
        ] = 0,
        settlement_fixture: Annotated[
            Path | None,
            typer.Option(
                "--settlement-fixture",
                help="Optional normalized settlement parameter CSV fixture.",
            ),
        ] = None,
    ) -> None:
        """Build trade_mapping_daily rows for T signal and T+1 execution."""
        from cotton_factor.core import (
            build_chain_map,
            build_contract_master,
            build_trade_mapping,
            build_trading_calendar,
            load_core_quote_daily_csv,
            load_core_settlement_param_daily_csv,
        )

        try:
            start_date = _parse_iso_date(start)
            end_date = _parse_iso_date(end)
            calendar_result = build_trading_calendar(
                start=date(start_date.year, 1, 1),
                end=date(start_date.year, 12, 31),
                exchange="CZCE",
            )
            contract_result = build_contract_master(
                product_code=product,
                year=start_date.year,
                trading_dates=calendar_result.calendar.trading_dates,
            )
            chain_result = build_chain_map(
                quotes=_filter_quotes(
                    load_core_quote_daily_csv(quote_fixture),
                    start=start_date,
                    end=end_date,
                ),
                contracts=contract_result.contracts,
                calendar=calendar_result.calendar,
                product_code=product,
                signal_object_id=signal_object,
                ltd_buffer_days=ltd_buffer_days,
            )
            settlement_rows = (
                _filter_settlement_rows(
                    load_core_settlement_param_daily_csv(settlement_fixture),
                    start=start_date,
                    end=end_date,
                    calendar=calendar_result.calendar,
                )
                if settlement_fixture is not None
                else []
            )
            trade_result = build_trade_mapping(
                chain_rows=chain_result.rows,
                contracts=contract_result.contracts,
                calendar=calendar_result.calendar,
                product_code=product,
                signal_object_id=signal_object,
                settlement_rows=settlement_rows,
                ltd_buffer_days=ltd_buffer_days,
            )
        except (
            ChainMapError,
            ConfigError,
            ContractMasterError,
            TradeMappingError,
            TradingCalendarError,
        ) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(
            json.dumps(_trade_mapping_summary(trade_result), ensure_ascii=False, sort_keys=True)
        )

    @core_app.command("build-continuous-price")
    def build_continuous_price_command(
        product: Annotated[str, typer.Option("--product", help="Product code, e.g. CF.")],
        start: Annotated[str, typer.Option("--start", help="Start date in YYYY-MM-DD format.")],
        end: Annotated[str, typer.Option("--end", help="End date in YYYY-MM-DD format.")],
        quote_fixture: Annotated[
            Path,
            typer.Option("--quote-fixture", help="Normalized core quote CSV fixture."),
        ],
        signal_object: Annotated[
            str,
            typer.Option("--signal-object", help="Signal object id, e.g. CF.C1."),
        ] = "CF.C1",
        ltd_buffer_days: Annotated[
            int,
            typer.Option("--ltd-buffer-days", help="Explicit LTD guard buffer in trading days."),
        ] = 0,
        price_field: Annotated[
            str,
            typer.Option("--price-field", help="Quote field for continuous price."),
        ] = "settle",
    ) -> None:
        """Build research continuous price rows from chain map and quotes."""
        from cotton_factor.core import (
            build_chain_map,
            build_contract_master,
            build_trading_calendar,
            load_core_quote_daily_csv,
        )
        from cotton_factor.research import build_continuous_price

        try:
            start_date = _parse_iso_date(start)
            end_date = _parse_iso_date(end)
            calendar_result = build_trading_calendar(
                start=date(start_date.year, 1, 1),
                end=date(start_date.year, 12, 31),
                exchange="CZCE",
            )
            contract_result = build_contract_master(
                product_code=product,
                year=start_date.year,
                trading_dates=calendar_result.calendar.trading_dates,
            )
            quotes = _filter_quotes(
                load_core_quote_daily_csv(quote_fixture),
                start=start_date,
                end=end_date,
            )
            chain_result = build_chain_map(
                quotes=quotes,
                contracts=contract_result.contracts,
                calendar=calendar_result.calendar,
                product_code=product,
                signal_object_id=signal_object,
                ltd_buffer_days=ltd_buffer_days,
            )
            continuous_result = build_continuous_price(
                quotes=quotes,
                chain_rows=chain_result.rows,
                product_code=product,
                signal_object_id=signal_object,
                price_field=price_field,
            )
        except (
            ChainMapError,
            ConfigError,
            ContractMasterError,
            ContinuousPriceError,
            TradingCalendarError,
        ) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(
            json.dumps(
                _continuous_price_summary(continuous_result),
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    @ingest_app.command("czce-history")
    def ingest_czce_history_command(
        year: Annotated[int, typer.Option("--year", help="Historical quote year.")],
        product: Annotated[str, typer.Option("--product", help="Product code, e.g. CF.")],
        file_type: Annotated[
            str | None,
            typer.Option("--file-type", help="Fixture file type: csv, html, htm, xls, xlsx."),
        ] = None,
        fixture: Annotated[
            Path | None,
            typer.Option(
                "--fixture",
                help="Local fixture file or directory for network-free tests.",
            ),
        ] = None,
        raw_root: Annotated[
            Path | None,
            typer.Option("--raw-root", help="Raw store root. Defaults to data/raw."),
        ] = None,
    ) -> None:
        """Capture CZCE historical quote payloads as immutable raw snapshots."""
        from cotton_factor.ingest.czce_history import ingest_czce_history

        try:
            result = ingest_czce_history(
                year=year,
                product_code=product,
                file_type=file_type,
                fixture_path=fixture,
                raw_root=raw_root,
            )
        except FetchError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(
            json.dumps(
                [_snapshot_summary(snapshot) for snapshot in result.snapshots],
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    @ingest_app.command("czce-settlement")
    def ingest_czce_settlement_command(
        trade_date: Annotated[str, typer.Option("--date", help="Trade date in YYYY-MM-DD format.")],
        product: Annotated[str, typer.Option("--product", help="Product code, e.g. CF.")],
        fixture: Annotated[
            Path | None,
            typer.Option(
                "--fixture",
                help="Local raw payload fixture path for network-free tests.",
            ),
        ] = None,
        raw_root: Annotated[
            Path | None,
            typer.Option("--raw-root", help="Raw store root. Defaults to data/raw."),
        ] = None,
    ) -> None:
        """Capture a CZCE settlement parameter payload as an immutable raw snapshot."""
        from cotton_factor.ingest.czce_settlement_param import ingest_czce_settlement_param

        try:
            result = ingest_czce_settlement_param(
                trade_date=_parse_iso_date(trade_date),
                product_code=product,
                fixture_path=fixture,
                raw_root=raw_root,
            )
        except FetchError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(
            json.dumps(_snapshot_summary(result.snapshot), ensure_ascii=False, sort_keys=True)
        )

    @raw_app.command("list")
    def list_raw_snapshots_command(
        source: Annotated[
            str | None,
            typer.Option("--source", help="Filter by raw source name."),
        ] = None,
        product: Annotated[
            str | None,
            typer.Option("--product", help="Filter by product code."),
        ] = None,
        year: Annotated[
            int | None,
            typer.Option("--year", help="Filter by biz_date year or history_year metadata."),
        ] = None,
        raw_root: Annotated[
            Path | None,
            typer.Option("--raw-root", help="Raw store root. Defaults to data/raw."),
        ] = None,
    ) -> None:
        """List replayable raw snapshot manifest records."""
        from cotton_factor.raw import RawSnapshotStore

        store = RawSnapshotStore(raw_root)
        records = store.find_records(source_name=source, product_code=product, year=year)
        typer.echo(
            json.dumps(
                [_snapshot_summary(record) for record in records],
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    @smoke_app.command("cf")
    def smoke_cf(
        start: Annotated[str, typer.Option(help="Start date in YYYY-MM-DD format.")],
        end: Annotated[str, typer.Option(help="End date in YYYY-MM-DD format.")],
        dry_run: Annotated[
            bool,
            typer.Option(
                "--dry-run/--run",
                help="Print the planned smoke chain instead of executing it.",
            ),
        ] = False,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable run id for archive outputs."),
        ] = None,
        history_fixture: Annotated[
            Path | None,
            typer.Option("--history-fixture", help="Optional D19 history fixture path."),
        ] = None,
        settlement_fixture: Annotated[
            Path | None,
            typer.Option("--settlement-fixture", help="Optional settlement fixture path."),
        ] = None,
        raw_root: Annotated[
            Path | None,
            typer.Option("--raw-root", help="Raw store root. Defaults to data/raw."),
        ] = None,
        archive_root: Annotated[
            Path | None,
            typer.Option("--archive-root", help="Archive root. Defaults to data/archive."),
        ] = None,
    ) -> None:
        """Run the D19 CF full-chain smoke command."""
        if dry_run:
            typer.echo(
                f"CF smoke dry-run: {start} to {end}. "
                "D19 full chain will ingest fixtures, normalize core facts, "
                "run factors/backtest, render a report, and build an archive bundle."
            )
            return

        from cotton_factor.smoke import run_cf_smoke

        try:
            result = run_cf_smoke(
                start=_parse_iso_date(start),
                end=_parse_iso_date(end),
                run_id=run_id,
                history_fixture_path=history_fixture,
                settlement_fixture_path=settlement_fixture,
                raw_root=raw_root,
                archive_root=archive_root,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @smoke_app.command("products")
    def smoke_products(
        products: Annotated[
            str,
            typer.Option("--products", help="Comma-separated product codes for config smoke."),
        ] = "SR,AP",
        year: Annotated[int, typer.Option("--year", help="Contract delivery year.")] = 2024,
    ) -> None:
        """Run config-only product extension smoke."""
        from cotton_factor.smoke import run_product_config_smoke

        try:
            result = run_product_config_smoke(
                product_codes=_parse_product_codes(products),
                year=year,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @qa_app.command("validate-csv")
    def qa_validate_csv(
        table: Annotated[str, typer.Option("--table", help="Registered table schema name.")],
        csv_path: Annotated[Path, typer.Option("--csv", help="CSV artifact path.")],
    ) -> None:
        """Validate a CSV artifact against a registered schema."""
        from cotton_factor.qa import validate_csv_table

        try:
            result = validate_csv_table(table_name=table, csv_path=csv_path)
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @qa_app.command("audit-csv")
    def qa_audit_csv(
        table: Annotated[str, typer.Option("--table", help="Registered table schema name.")],
        csv_path: Annotated[Path, typer.Option("--csv", help="CSV artifact path.")],
        min_row_count: Annotated[
            int,
            typer.Option("--min-row-count", help="Minimum expected row count."),
        ] = 1,
        max_null_ratio: Annotated[
            list[str] | None,
            typer.Option(
                "--max-null-ratio",
                help="Field threshold formatted as field=max_ratio. Can be repeated.",
            ),
        ] = None,
    ) -> None:
        """Audit a validated CSV artifact for row count and null ratios."""
        from cotton_factor.qa import audit_csv_table, parse_null_ratio_thresholds

        try:
            result = audit_csv_table(
                table_name=table,
                csv_path=csv_path,
                min_row_count=min_row_count,
                max_null_ratio_by_field=parse_null_ratio_thresholds(max_null_ratio or []),
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @uat_app.command("replay")
    def uat_replay(
        scenario: Annotated[
            str,
            typer.Option("--scenario", help="UAT scenario name."),
        ] = "cf_mvp_fixture",
        output_root: Annotated[
            Path | None,
            typer.Option("--output-root", help="UAT report output root."),
        ] = None,
        raw_root: Annotated[
            Path | None,
            typer.Option("--raw-root", help="Raw store root for replay."),
        ] = None,
        archive_root: Annotated[
            Path | None,
            typer.Option("--archive-root", help="Smoke archive root for replay."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional deterministic UAT run id."),
        ] = None,
    ) -> None:
        """Run a D22 UAT replay scenario and write pass/fail reports."""
        from cotton_factor.uat import run_uat_replay

        try:
            result = run_uat_replay(
                scenario=scenario,
                output_root=output_root,
                raw_root=raw_root,
                archive_root=archive_root,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
        if not result.passed:
            raise typer.Exit(1)

    @release_app.command("freeze")
    def release_freeze(
        version: Annotated[
            str,
            typer.Option("--version", help="Release candidate version, e.g. 0.1.0."),
        ],
        output_root: Annotated[
            Path | None,
            typer.Option("--output-root", help="Archive output root. Defaults to data/archive."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional deterministic release run id."),
        ] = None,
    ) -> None:
        """Build a D23 release freeze package."""
        from cotton_factor.release import run_release_freeze

        try:
            result = run_release_freeze(
                version=version,
                output_root=output_root,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
        if not result.passed:
            raise typer.Exit(1)

    app.add_typer(core_app, name="core")
    app.add_typer(ingest_app, name="ingest")
    app.add_typer(raw_app, name="raw")
    app.add_typer(smoke_app, name="smoke")
    app.add_typer(qa_app, name="qa")
    app.add_typer(uat_app, name="uat")
    app.add_typer(release_app, name="release")

    def cli() -> None:
        """Run the Typer application."""
        app()

else:
    app = None

    def _build_fallback_parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog="cotton-factor",
            description=(
                "Cotton factor MVP CLI. Install dev dependencies for the full Typer CLI."
            ),
        )
        parser.add_argument("--version", action="store_true", help="Show package version and exit.")
        subparsers = parser.add_subparsers(dest="command")

        subparsers.add_parser("status", help="Show the project status.")

        core_parser = subparsers.add_parser("core", help="Core fact commands.")
        core_subparsers = core_parser.add_subparsers(dest="core_command")
        contract_master_parser = core_subparsers.add_parser(
            "build-contract-master",
            help="Build contract master rows from product config.",
        )
        contract_master_parser.add_argument("--product", required=True)
        contract_master_parser.add_argument("--year", required=True, type=int)
        contract_master_parser.add_argument("--config-dir", type=Path)

        calendar_parser = core_subparsers.add_parser(
            "build-calendar",
            help="Build a core trading calendar from fixture or provisional weekdays.",
        )
        calendar_parser.add_argument("--start", required=True)
        calendar_parser.add_argument("--end", required=True)
        calendar_parser.add_argument("--exchange", required=True)
        calendar_parser.add_argument("--fixture", type=Path)

        chain_map_parser = core_subparsers.add_parser(
            "build-chain-map",
            help="Build chain_map_daily rows from normalized quote fixtures.",
        )
        chain_map_parser.add_argument("--product", required=True)
        chain_map_parser.add_argument("--start", required=True)
        chain_map_parser.add_argument("--end", required=True)
        chain_map_parser.add_argument("--quote-fixture", required=True, type=Path)
        chain_map_parser.add_argument("--signal-object", default="CF.C1")
        chain_map_parser.add_argument("--ltd-buffer-days", default=0, type=int)

        trade_mapping_parser = core_subparsers.add_parser(
            "build-trade-mapping",
            help="Build trade_mapping_daily rows for T signal and T+1 execution.",
        )
        trade_mapping_parser.add_argument("--product", required=True)
        trade_mapping_parser.add_argument("--start", required=True)
        trade_mapping_parser.add_argument("--end", required=True)
        trade_mapping_parser.add_argument("--quote-fixture", required=True, type=Path)
        trade_mapping_parser.add_argument("--signal-object", default="CF.C1")
        trade_mapping_parser.add_argument("--ltd-buffer-days", default=0, type=int)
        trade_mapping_parser.add_argument("--settlement-fixture", type=Path)

        continuous_price_parser = core_subparsers.add_parser(
            "build-continuous-price",
            help="Build research continuous price rows from chain map and quotes.",
        )
        continuous_price_parser.add_argument("--product", required=True)
        continuous_price_parser.add_argument("--start", required=True)
        continuous_price_parser.add_argument("--end", required=True)
        continuous_price_parser.add_argument("--quote-fixture", required=True, type=Path)
        continuous_price_parser.add_argument("--signal-object", default="CF.C1")
        continuous_price_parser.add_argument("--ltd-buffer-days", default=0, type=int)
        continuous_price_parser.add_argument("--price-field", default="settle")

        ingest_parser = subparsers.add_parser("ingest", help="Raw ingestion commands.")
        ingest_subparsers = ingest_parser.add_subparsers(dest="ingest_command")
        daily_parser = ingest_subparsers.add_parser(
            "czce-daily-quote",
            help="Capture a CZCE daily quote payload as an immutable raw snapshot.",
        )
        daily_parser.add_argument("--date", required=True, dest="trade_date")
        daily_parser.add_argument("--product", required=True)
        daily_parser.add_argument("--fixture", type=Path)
        daily_parser.add_argument("--raw-root", type=Path)

        history_parser = ingest_subparsers.add_parser(
            "czce-history",
            help="Capture CZCE historical quote payloads as immutable raw snapshots.",
        )
        history_parser.add_argument("--year", required=True, type=int)
        history_parser.add_argument("--product", required=True)
        history_parser.add_argument("--file-type")
        history_parser.add_argument("--fixture", type=Path)
        history_parser.add_argument("--raw-root", type=Path)

        settlement_parser = ingest_subparsers.add_parser(
            "czce-settlement",
            help="Capture a CZCE settlement parameter payload as an immutable raw snapshot.",
        )
        settlement_parser.add_argument("--date", required=True, dest="trade_date")
        settlement_parser.add_argument("--product", required=True)
        settlement_parser.add_argument("--fixture", type=Path)
        settlement_parser.add_argument("--raw-root", type=Path)

        raw_parser = subparsers.add_parser("raw", help="Raw snapshot replay and manifest commands.")
        raw_subparsers = raw_parser.add_subparsers(dest="raw_command")
        raw_list_parser = raw_subparsers.add_parser(
            "list",
            help="List replayable raw snapshot manifest records.",
        )
        raw_list_parser.add_argument("--source")
        raw_list_parser.add_argument("--product")
        raw_list_parser.add_argument("--year", type=int)
        raw_list_parser.add_argument("--raw-root", type=Path)

        smoke_parser = subparsers.add_parser("smoke", help="Smoke test commands.")
        smoke_subparsers = smoke_parser.add_subparsers(dest="smoke_command")
        cf_parser = smoke_subparsers.add_parser("cf", help="Show the planned CF smoke command.")
        cf_parser.add_argument("--start", required=True, help="Start date in YYYY-MM-DD format.")
        cf_parser.add_argument("--end", required=True, help="End date in YYYY-MM-DD format.")
        cf_mode = cf_parser.add_mutually_exclusive_group()
        cf_mode.add_argument("--dry-run", action="store_true", default=False)
        cf_mode.add_argument("--run", action="store_false", dest="dry_run")
        cf_parser.add_argument("--run-id")
        cf_parser.add_argument("--history-fixture", type=Path)
        cf_parser.add_argument("--settlement-fixture", type=Path)
        cf_parser.add_argument("--raw-root", type=Path)
        cf_parser.add_argument("--archive-root", type=Path)
        products_parser = smoke_subparsers.add_parser(
            "products",
            help="Run config-only product extension smoke.",
        )
        products_parser.add_argument("--products", default="SR,AP")
        products_parser.add_argument("--year", default=2024, type=int)

        qa_parser = subparsers.add_parser("qa", help="QA validation and audit commands.")
        qa_subparsers = qa_parser.add_subparsers(dest="qa_command")
        validate_csv_parser = qa_subparsers.add_parser(
            "validate-csv",
            help="Validate a CSV artifact against a registered schema.",
        )
        validate_csv_parser.add_argument("--table", required=True)
        validate_csv_parser.add_argument("--csv", required=True, type=Path, dest="csv_path")
        audit_csv_parser = qa_subparsers.add_parser(
            "audit-csv",
            help="Audit a validated CSV artifact for row count and null ratios.",
        )
        audit_csv_parser.add_argument("--table", required=True)
        audit_csv_parser.add_argument("--csv", required=True, type=Path, dest="csv_path")
        audit_csv_parser.add_argument("--min-row-count", default=1, type=int)
        audit_csv_parser.add_argument("--max-null-ratio", action="append", default=[])

        uat_parser = subparsers.add_parser("uat", help="UAT replay commands.")
        uat_subparsers = uat_parser.add_subparsers(dest="uat_command")
        replay_parser = uat_subparsers.add_parser(
            "replay",
            help="Run a D22 UAT replay scenario and write pass/fail reports.",
        )
        replay_parser.add_argument("--scenario", default="cf_mvp_fixture")
        replay_parser.add_argument("--output-root", type=Path)
        replay_parser.add_argument("--raw-root", type=Path)
        replay_parser.add_argument("--archive-root", type=Path)
        replay_parser.add_argument("--run-id")

        release_parser = subparsers.add_parser("release", help="Release freeze commands.")
        release_subparsers = release_parser.add_subparsers(dest="release_command")
        freeze_parser = release_subparsers.add_parser(
            "freeze",
            help="Build a D23 release freeze package.",
        )
        freeze_parser.add_argument("--version", required=True)
        freeze_parser.add_argument("--output-root", type=Path)
        freeze_parser.add_argument("--run-id")
        return parser

    def cli() -> int:
        """Run a minimal dependency-free fallback CLI."""
        parser = _build_fallback_parser()
        args = parser.parse_args()

        if args.version:
            print(__version__)
            return 0
        if args.command == "status":
            print(STATUS_MESSAGE)
            return 0
        if args.command == "core" and args.core_command == "build-contract-master":
            from cotton_factor.core import build_contract_master

            try:
                result = build_contract_master(
                    product_code=args.product,
                    year=args.year,
                    config_dir=args.config_dir,
                )
            except (ConfigError, ContractMasterError) as exc:
                print(str(exc))
                return 1

            print(json.dumps(_contract_master_summary(result), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "core" and args.core_command == "build-calendar":
            from cotton_factor.core import build_trading_calendar

            try:
                result = build_trading_calendar(
                    start=_parse_iso_date(args.start),
                    end=_parse_iso_date(args.end),
                    exchange=args.exchange,
                    fixture_path=args.fixture,
                )
            except TradingCalendarError as exc:
                print(str(exc))
                return 1

            print(json.dumps(_calendar_summary(result), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "core" and args.core_command == "build-chain-map":
            from cotton_factor.core import (
                build_chain_map,
                build_contract_master,
                build_trading_calendar,
                load_core_quote_daily_csv,
            )

            try:
                start_date = _parse_iso_date(args.start)
                end_date = _parse_iso_date(args.end)
                calendar_result = build_trading_calendar(
                    start=date(start_date.year, 1, 1),
                    end=date(start_date.year, 12, 31),
                    exchange="CZCE",
                )
                contract_result = build_contract_master(
                    product_code=args.product,
                    year=start_date.year,
                    trading_dates=calendar_result.calendar.trading_dates,
                )
                chain_result = build_chain_map(
                    quotes=_filter_quotes(
                        load_core_quote_daily_csv(args.quote_fixture),
                        start=start_date,
                        end=end_date,
                    ),
                    contracts=contract_result.contracts,
                    calendar=calendar_result.calendar,
                    product_code=args.product,
                    signal_object_id=args.signal_object,
                    ltd_buffer_days=args.ltd_buffer_days,
                )
            except (ChainMapError, ConfigError, ContractMasterError, TradingCalendarError) as exc:
                print(str(exc))
                return 1

            print(json.dumps(_chain_map_summary(chain_result), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "core" and args.core_command == "build-trade-mapping":
            from cotton_factor.core import (
                build_chain_map,
                build_contract_master,
                build_trade_mapping,
                build_trading_calendar,
                load_core_quote_daily_csv,
                load_core_settlement_param_daily_csv,
            )

            try:
                start_date = _parse_iso_date(args.start)
                end_date = _parse_iso_date(args.end)
                calendar_result = build_trading_calendar(
                    start=date(start_date.year, 1, 1),
                    end=date(start_date.year, 12, 31),
                    exchange="CZCE",
                )
                contract_result = build_contract_master(
                    product_code=args.product,
                    year=start_date.year,
                    trading_dates=calendar_result.calendar.trading_dates,
                )
                chain_result = build_chain_map(
                    quotes=_filter_quotes(
                        load_core_quote_daily_csv(args.quote_fixture),
                        start=start_date,
                        end=end_date,
                    ),
                    contracts=contract_result.contracts,
                    calendar=calendar_result.calendar,
                    product_code=args.product,
                    signal_object_id=args.signal_object,
                    ltd_buffer_days=args.ltd_buffer_days,
                )
                settlement_rows = (
                    _filter_settlement_rows(
                        load_core_settlement_param_daily_csv(args.settlement_fixture),
                        start=start_date,
                        end=end_date,
                        calendar=calendar_result.calendar,
                    )
                    if args.settlement_fixture is not None
                    else []
                )
                trade_result = build_trade_mapping(
                    chain_rows=chain_result.rows,
                    contracts=contract_result.contracts,
                    calendar=calendar_result.calendar,
                    product_code=args.product,
                    signal_object_id=args.signal_object,
                    settlement_rows=settlement_rows,
                    ltd_buffer_days=args.ltd_buffer_days,
                )
            except (
                ChainMapError,
                ConfigError,
                ContractMasterError,
                TradeMappingError,
                TradingCalendarError,
            ) as exc:
                print(str(exc))
                return 1

            print(
                json.dumps(
                    _trade_mapping_summary(trade_result),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "core" and args.core_command == "build-continuous-price":
            from cotton_factor.core import (
                build_chain_map,
                build_contract_master,
                build_trading_calendar,
                load_core_quote_daily_csv,
            )
            from cotton_factor.research import build_continuous_price

            try:
                start_date = _parse_iso_date(args.start)
                end_date = _parse_iso_date(args.end)
                calendar_result = build_trading_calendar(
                    start=date(start_date.year, 1, 1),
                    end=date(start_date.year, 12, 31),
                    exchange="CZCE",
                )
                contract_result = build_contract_master(
                    product_code=args.product,
                    year=start_date.year,
                    trading_dates=calendar_result.calendar.trading_dates,
                )
                quotes = _filter_quotes(
                    load_core_quote_daily_csv(args.quote_fixture),
                    start=start_date,
                    end=end_date,
                )
                chain_result = build_chain_map(
                    quotes=quotes,
                    contracts=contract_result.contracts,
                    calendar=calendar_result.calendar,
                    product_code=args.product,
                    signal_object_id=args.signal_object,
                    ltd_buffer_days=args.ltd_buffer_days,
                )
                continuous_result = build_continuous_price(
                    quotes=quotes,
                    chain_rows=chain_result.rows,
                    product_code=args.product,
                    signal_object_id=args.signal_object,
                    price_field=args.price_field,
                )
            except (
                ChainMapError,
                ConfigError,
                ContractMasterError,
                ContinuousPriceError,
                TradingCalendarError,
            ) as exc:
                print(str(exc))
                return 1

            print(
                json.dumps(
                    _continuous_price_summary(continuous_result),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "ingest" and args.ingest_command == "czce-daily-quote":
            from cotton_factor.ingest.czce_daily_quote import ingest_czce_daily_quote

            try:
                result = ingest_czce_daily_quote(
                    trade_date=_parse_iso_date(args.trade_date),
                    product_code=args.product,
                    fixture_path=args.fixture,
                    raw_root=args.raw_root,
                )
            except FetchError as exc:
                print(str(exc))
                return 1

            print(
                json.dumps(_snapshot_summary(result.snapshot), ensure_ascii=False, sort_keys=True)
            )
            return 0
        if args.command == "ingest" and args.ingest_command == "czce-history":
            from cotton_factor.ingest.czce_history import ingest_czce_history

            try:
                result = ingest_czce_history(
                    year=args.year,
                    product_code=args.product,
                    file_type=args.file_type,
                    fixture_path=args.fixture,
                    raw_root=args.raw_root,
                )
            except FetchError as exc:
                print(str(exc))
                return 1

            print(
                json.dumps(
                    [_snapshot_summary(snapshot) for snapshot in result.snapshots],
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "ingest" and args.ingest_command == "czce-settlement":
            from cotton_factor.ingest.czce_settlement_param import ingest_czce_settlement_param

            try:
                result = ingest_czce_settlement_param(
                    trade_date=_parse_iso_date(args.trade_date),
                    product_code=args.product,
                    fixture_path=args.fixture,
                    raw_root=args.raw_root,
                )
            except FetchError as exc:
                print(str(exc))
                return 1

            print(
                json.dumps(_snapshot_summary(result.snapshot), ensure_ascii=False, sort_keys=True)
            )
            return 0
        if args.command == "raw" and args.raw_command == "list":
            from cotton_factor.raw import RawSnapshotStore

            store = RawSnapshotStore(args.raw_root)
            records = store.find_records(
                source_name=args.source,
                product_code=args.product,
                year=args.year,
            )
            print(
                json.dumps(
                    [_snapshot_summary(record) for record in records],
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "smoke" and args.smoke_command == "cf":
            if args.dry_run:
                print(
                    f"CF smoke dry-run: {args.start} to {args.end}. "
                    "D19 full chain will ingest fixtures, normalize core facts, "
                    "run factors/backtest, render a report, and build an archive bundle."
                )
                return 0

            from cotton_factor.smoke import run_cf_smoke

            try:
                result = run_cf_smoke(
                    start=_parse_iso_date(args.start),
                    end=_parse_iso_date(args.end),
                    run_id=args.run_id,
                    history_fixture_path=args.history_fixture,
                    settlement_fixture_path=args.settlement_fixture,
                    raw_root=args.raw_root,
                    archive_root=args.archive_root,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "smoke" and args.smoke_command == "products":
            from cotton_factor.smoke import run_product_config_smoke

            try:
                result = run_product_config_smoke(
                    product_codes=_parse_product_codes(args.products),
                    year=args.year,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "qa" and args.qa_command == "validate-csv":
            from cotton_factor.qa import validate_csv_table

            try:
                result = validate_csv_table(table_name=args.table, csv_path=args.csv_path)
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "qa" and args.qa_command == "audit-csv":
            from cotton_factor.qa import audit_csv_table, parse_null_ratio_thresholds

            try:
                result = audit_csv_table(
                    table_name=args.table,
                    csv_path=args.csv_path,
                    min_row_count=args.min_row_count,
                    max_null_ratio_by_field=parse_null_ratio_thresholds(args.max_null_ratio),
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "uat" and args.uat_command == "replay":
            from cotton_factor.uat import run_uat_replay

            try:
                result = run_uat_replay(
                    scenario=args.scenario,
                    output_root=args.output_root,
                    raw_root=args.raw_root,
                    archive_root=args.archive_root,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0 if result.passed else 1
        if args.command == "release" and args.release_command == "freeze":
            from cotton_factor.release import run_release_freeze

            try:
                result = run_release_freeze(
                    version=args.version,
                    output_root=args.output_root,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0 if result.passed else 1

        parser.print_help()
        return 0


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        message = f"date must be YYYY-MM-DD: {value!r}"
        if typer is not None:
            raise typer.BadParameter(message) from exc
        raise argparse.ArgumentTypeError(message) from exc


def _parse_product_codes(value: str) -> tuple[str, ...]:
    product_codes = tuple(
        product_code.strip().upper()
        for product_code in value.split(",")
        if product_code.strip()
    )
    if not product_codes:
        message = "at least one product code is required"
        if typer is not None:
            raise typer.BadParameter(message)
        raise argparse.ArgumentTypeError(message)
    return product_codes


def _snapshot_summary(snapshot: object) -> dict[str, object]:
    return {
        "snapshot_id": getattr(snapshot, "snapshot_id"),
        "source_name": getattr(snapshot, "source_name"),
        "product_code": getattr(snapshot, "product_code"),
        "biz_date": getattr(snapshot, "biz_date"),
        "content_type": getattr(snapshot, "content_type"),
        "byte_size": getattr(snapshot, "byte_size"),
        "sha256": getattr(snapshot, "sha256"),
        "payload_path": getattr(snapshot, "payload_path"),
        "parser_version": getattr(snapshot, "parser_version"),
        "status": getattr(snapshot, "status"),
        "metadata": getattr(snapshot, "metadata"),
    }


def _contract_master_summary(result: object) -> dict[str, object]:
    product_config = getattr(result, "product_config")
    rule_version = getattr(result, "rule_version")
    contracts = getattr(result, "contracts")
    return {
        "product_code": product_config.product_code,
        "exchange": product_config.exchange,
        "rule_version": rule_version.model_dump(mode="json"),
        "contracts": [contract.model_dump(mode="json") for contract in contracts],
        "warnings": getattr(result, "warnings"),
    }


def _calendar_summary(result: object) -> dict[str, object]:
    calendar = getattr(result, "calendar")
    rows = getattr(result, "rows")
    return {
        "exchange": calendar.exchange,
        "calendar_version": calendar.calendar_version,
        "row_count": len(rows),
        "trading_day_count": len(calendar.trading_dates),
        "rows": [row.model_dump(mode="json") for row in rows],
        "warnings": getattr(result, "warnings"),
    }


def _chain_map_summary(result: object) -> dict[str, object]:
    rows = getattr(result, "rows")
    return {
        "row_count": len(rows),
        "rows": [row.model_dump(mode="json") for row in rows],
        "warnings": getattr(result, "warnings"),
    }


def _trade_mapping_summary(result: object) -> dict[str, object]:
    rows = getattr(result, "rows")
    return {
        "row_count": len(rows),
        "blocked_count": sum(1 for row in rows if row.is_blocked),
        "rows": [row.model_dump(mode="json") for row in rows],
        "warnings": getattr(result, "warnings"),
    }


def _continuous_price_summary(result: object) -> dict[str, object]:
    rows = getattr(result, "rows")
    return {
        "row_count": len(rows),
        "roll_count": sum(1 for row in rows if row.is_roll),
        "rows": [row.model_dump(mode="json") for row in rows],
        "warnings": getattr(result, "warnings"),
    }


def _filter_quotes(quotes: object, *, start: date, end: date) -> list[object]:
    return [quote for quote in quotes if start <= quote.trade_date <= end]


def _filter_settlement_rows(
    rows: object,
    *,
    start: date,
    end: date,
    calendar: object,
) -> list[object]:
    next_dates = set()
    for row_date in (start, end):
        try:
            next_dates.add(calendar.next_trade_date(row_date))
        except TradingCalendarError:
            continue
    return [
        row
        for row in rows
        if start <= row.trade_date <= end or row.trade_date in next_dates
    ]


if __name__ == "__main__":
    raise SystemExit(cli())
