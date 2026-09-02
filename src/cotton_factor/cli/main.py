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
    "cotton-factor research workbench ready: R00-R22 CF research path is available."
)


if typer is not None:
    app = typer.Typer(
        help=(
            "Cotton factor research workbench CLI. Raw ingestion, core mapping, "
            "and research tools are available."
        )
    )
    core_app = typer.Typer(help="Core fact commands.")
    ingest_app = typer.Typer(help="Raw ingestion commands.")
    raw_app = typer.Typer(help="Raw snapshot replay and manifest commands.")
    smoke_app = typer.Typer(help="Smoke test commands.")
    qa_app = typer.Typer(help="QA validation and audit commands.")
    uat_app = typer.Typer(help="UAT replay commands.")
    release_app = typer.Typer(help="Release freeze commands.")
    research_app = typer.Typer(help="Research workbench commands.")
    strategy_app = typer.Typer(help="CF strategy-accountable research commands.")
    operations_app = typer.Typer(help="Research operations commands.")

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

    @research_app.command("ingest-cf")
    def research_ingest_cf(
        trade_date: Annotated[str, typer.Option("--date", help="Trade date in YYYY-MM-DD format.")],
        input_path: Annotated[
            Path,
            typer.Option("--input-path", help="Local CF source file or folder."),
        ],
        raw_output_dir: Annotated[
            Path | None,
            typer.Option("--raw-output-dir", help="Raw output root. Defaults to data/raw."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional deterministic research raw run id."),
        ] = None,
    ) -> None:
        """Preserve local CF research input files without parsing business fields."""
        from cotton_factor.research_workbench import ingest_cf_raw

        try:
            result = ingest_cf_raw(
                trade_date=_parse_iso_date(trade_date),
                input_path=input_path,
                raw_output_dir=raw_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("normalize-cf-quotes")
    def research_normalize_cf_quotes(
        trade_date: Annotated[str, typer.Option("--date", help="Trade date in YYYY-MM-DD format.")],
        raw_output_dir: Annotated[
            Path | None,
            typer.Option("--raw-output-dir", help="Raw output root. Defaults to data/raw."),
        ] = None,
        core_output_dir: Annotated[
            Path | None,
            typer.Option("--core-output-dir", help="Core output root. Defaults to data/core."),
        ] = None,
        output_path: Annotated[
            Path | None,
            typer.Option("--output-path", help="Optional explicit Parquet output path."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional research raw run id filter."),
        ] = None,
    ) -> None:
        """Normalize preserved CF raw CSV files into core_quote_daily parquet."""
        from cotton_factor.research_workbench import normalize_cf_core_quotes

        try:
            result = normalize_cf_core_quotes(
                trade_date=_parse_iso_date(trade_date),
                raw_output_dir=raw_output_dir,
                core_output_dir=core_output_dir,
                output_path=output_path,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("check-cf-quality")
    def research_check_cf_quality(
        trade_date: Annotated[str, typer.Option("--date", help="Trade date in YYYY-MM-DD format.")],
        core_output_dir: Annotated[
            Path | None,
            typer.Option("--core-output-dir", help="Core output root. Defaults to data/core."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional explicit core quote parquet path."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option(
                "--report-output-dir",
                help="Quality report output directory. Defaults to reports/research/data_quality.",
            ),
        ] = None,
    ) -> None:
        """Run R06 CF core quote quality checks and write CSV/Markdown reports."""
        from cotton_factor.research_workbench import check_cf_data_quality

        try:
            result = check_cf_data_quality(
                trade_date=_parse_iso_date(trade_date),
                core_output_dir=core_output_dir,
                core_quote_path=core_quote_path,
                report_output_dir=report_output_dir,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
        if not result.passed:
            raise typer.Exit(1)

    @research_app.command("review-cf-contract-rules")
    def research_review_cf_contract_rules(
        year: Annotated[int, typer.Option("--year", help="Contract delivery year.")],
        report_output_dir: Annotated[
            Path | None,
            typer.Option(
                "--report-output-dir",
                help="Review report output directory. Defaults to reports/research/contract_rules.",
            ),
        ] = None,
        calendar_path: Annotated[
            Path | None,
            typer.Option("--calendar-path", help="Optional official trading calendar CSV path."),
        ] = None,
    ) -> None:
        """Build the R07 CF contract rule human-review table."""
        from cotton_factor.research_workbench import build_cf_contract_rule_review

        try:
            result = build_cf_contract_rule_review(
                year=year,
                report_output_dir=report_output_dir,
                calendar_path=calendar_path,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-mapping")
    def research_build_cf_mapping(
        start: Annotated[str, typer.Option("--start", help="Start date in YYYY-MM-DD format.")],
        end: Annotated[str, typer.Option("--end", help="End date in YYYY-MM-DD format.")],
        core_output_dir: Annotated[
            Path | None,
            typer.Option("--core-output-dir", help="Core output root. Defaults to data/core."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional explicit core quote parquet path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Mapping output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Mapping Markdown report directory."),
        ] = None,
        calendar_path: Annotated[
            Path | None,
            typer.Option("--calendar-path", help="Optional official trading calendar CSV path."),
        ] = None,
        ltd_buffer_days: Annotated[
            int,
            typer.Option("--ltd-buffer-days", help="Explicit LTD guard buffer in trading days."),
        ] = 0,
        min_volume: Annotated[
            int,
            typer.Option("--min-volume", help="Minimum volume for chain map eligibility."),
        ] = 1,
    ) -> None:
        """Build R08 research-mode CF chain and trade mapping outputs."""
        from cotton_factor.research_workbench import build_cf_research_mapping

        try:
            result = build_cf_research_mapping(
                start=_parse_iso_date(start),
                end=_parse_iso_date(end),
                core_output_dir=core_output_dir,
                core_quote_path=core_quote_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                calendar_path=calendar_path,
                ltd_buffer_days=ltd_buffer_days,
                min_volume=min_volume,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-continuous")
    def research_build_cf_continuous(
        start: Annotated[str, typer.Option("--start", help="Start date in YYYY-MM-DD format.")],
        end: Annotated[str, typer.Option("--end", help="End date in YYYY-MM-DD format.")],
        price_field: Annotated[
            str,
            typer.Option("--price-field", help="Quote field for continuous price."),
        ] = "settle",
        core_output_dir: Annotated[
            Path | None,
            typer.Option("--core-output-dir", help="Core output root. Defaults to data/core."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional explicit core quote parquet path."),
        ] = None,
        chain_map_path: Annotated[
            Path | None,
            typer.Option("--chain-map-path", help="Optional explicit chain map parquet path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Continuous output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Continuous Markdown report directory."),
        ] = None,
    ) -> None:
        """Build R09 CF continuous prices and roll diagnostics."""
        from cotton_factor.research_workbench import build_cf_research_continuous

        try:
            result = build_cf_research_continuous(
                start=_parse_iso_date(start),
                end=_parse_iso_date(end),
                price_field=price_field,
                core_output_dir=core_output_dir,
                core_quote_path=core_quote_path,
                chain_map_path=chain_map_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("write-cf-factor-output-contract")
    def research_write_cf_factor_output_contract(
        output_dir: Annotated[
            Path | None,
            typer.Option(
                "--output-dir",
                help=(
                    "Output contract JSON directory. "
                    "Defaults to data/research/CF/output_contracts."
                ),
            ),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option(
                "--report-output-dir",
                help=(
                    "Output contract Markdown directory. "
                    "Defaults to reports/research/output_contracts."
                ),
            ),
        ] = None,
    ) -> None:
        """Write the R10 downstream factor diagnostic output contract."""
        from cotton_factor.research_workbench import build_cf_factor_output_contract

        try:
            result = build_cf_factor_output_contract(
                output_dir=output_dir,
                report_output_dir=report_output_dir,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-momentum-factor")
    def research_build_cf_momentum_factor(
        start: Annotated[str, typer.Option("--start", help="Start date in YYYY-MM-DD format.")],
        end: Annotated[str, typer.Option("--end", help="End date in YYYY-MM-DD format.")],
        continuous_price_path: Annotated[
            Path | None,
            typer.Option(
                "--continuous-price-path",
                help="Optional R09 continuous price parquet path.",
            ),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Factor output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Momentum Markdown report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable factor run id."),
        ] = None,
        price_field: Annotated[
            str,
            typer.Option("--price-field", help="Continuous price field for momentum."),
        ] = "settle",
        lookback_periods: Annotated[
            int,
            typer.Option("--lookback-periods", help="Momentum lookback observations."),
        ] = 20,
    ) -> None:
        """Build R11 CF momentum factor rows and warnings."""
        from cotton_factor.research_workbench import build_cf_momentum_factor

        try:
            result = build_cf_momentum_factor(
                start=_parse_iso_date(start),
                end=_parse_iso_date(end),
                continuous_price_path=continuous_price_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                price_field=price_field,
                lookback_periods=lookback_periods,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-carry-factor")
    def research_build_cf_carry_factor(
        start: Annotated[str, typer.Option("--start", help="Start date in YYYY-MM-DD format.")],
        end: Annotated[str, typer.Option("--end", help="End date in YYYY-MM-DD format.")],
        core_output_dir: Annotated[
            Path | None,
            typer.Option("--core-output-dir", help="Core output root. Defaults to data/core."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional explicit core quote parquet path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Factor output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Carry Markdown report directory."),
        ] = None,
        calendar_path: Annotated[
            Path | None,
            typer.Option("--calendar-path", help="Optional official trading calendar CSV path."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable factor run id."),
        ] = None,
    ) -> None:
        """Build R12 CF carry factor rows and warnings."""
        from cotton_factor.research_workbench import build_cf_carry_factor

        try:
            result = build_cf_carry_factor(
                start=_parse_iso_date(start),
                end=_parse_iso_date(end),
                core_output_dir=core_output_dir,
                core_quote_path=core_quote_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                calendar_path=calendar_path,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-structure-factors")
    def research_build_cf_structure_factors(
        start: Annotated[str, typer.Option("--start", help="Start date in YYYY-MM-DD format.")],
        end: Annotated[str, typer.Option("--end", help="End date in YYYY-MM-DD format.")],
        core_output_dir: Annotated[
            Path | None,
            typer.Option("--core-output-dir", help="Core output root. Defaults to data/core."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional explicit core quote parquet path."),
        ] = None,
        chain_map_path: Annotated[
            Path | None,
            typer.Option("--chain-map-path", help="Optional explicit chain map parquet path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Factor output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Structure factors Markdown directory."),
        ] = None,
        calendar_path: Annotated[
            Path | None,
            typer.Option("--calendar-path", help="Optional official trading calendar CSV path."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable factor run id."),
        ] = None,
    ) -> None:
        """Build R13 CF curve slope and OI pressure rows and warnings."""
        from cotton_factor.research_workbench import build_cf_structure_factors

        try:
            result = build_cf_structure_factors(
                start=_parse_iso_date(start),
                end=_parse_iso_date(end),
                core_output_dir=core_output_dir,
                core_quote_path=core_quote_path,
                chain_map_path=chain_map_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                calendar_path=calendar_path,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-factor-diagnostics")
    def research_build_cf_factor_diagnostics(
        start: Annotated[str, typer.Option("--start", help="Start date in YYYY-MM-DD format.")],
        end: Annotated[str, typer.Option("--end", help="End date in YYYY-MM-DD format.")],
        factor_value_path: Annotated[
            Path | None,
            typer.Option("--factor-value-path", help="Optional R10 factor value parquet path."),
        ] = None,
        warning_csv_path: Annotated[
            Path | None,
            typer.Option("--warning-csv-path", help="Optional R10/R14 warning CSV path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Factor diagnostic output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Factor diagnostics Markdown directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable diagnostics run id."),
        ] = None,
    ) -> None:
        """Build R14 CF daily factor diagnostic rows and report."""
        from cotton_factor.research_workbench import build_cf_factor_diagnostics

        try:
            result = build_cf_factor_diagnostics(
                start=_parse_iso_date(start),
                end=_parse_iso_date(end),
                factor_value_path=factor_value_path,
                warning_csv_path=warning_csv_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-forward-returns")
    def research_build_cf_forward_returns(
        start: Annotated[str, typer.Option("--start", help="Start date in YYYY-MM-DD format.")],
        end: Annotated[str, typer.Option("--end", help="End date in YYYY-MM-DD format.")],
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Comma-separated forward horizons, e.g. 1,3,5."),
        ] = "1,3,5",
        core_output_dir: Annotated[
            Path | None,
            typer.Option("--core-output-dir", help="Core output root. Defaults to data/core."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional explicit core quote parquet path."),
        ] = None,
        trade_mapping_path: Annotated[
            Path | None,
            typer.Option("--trade-mapping-path", help="Optional R08 trade mapping parquet path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Forward-return output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Forward-return Markdown directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable forward-return run id."),
        ] = None,
        entry_price_field: Annotated[
            str,
            typer.Option("--entry-price-field", help="Entry quote field."),
        ] = "settle",
        exit_price_field: Annotated[
            str,
            typer.Option("--exit-price-field", help="Exit quote field."),
        ] = "settle",
    ) -> None:
        """Build R15 CF forward-return labels from real trade mappings."""
        from cotton_factor.research_workbench import build_cf_forward_returns

        try:
            result = build_cf_forward_returns(
                start=_parse_iso_date(start),
                end=_parse_iso_date(end),
                horizons=_parse_horizons(horizons),
                core_output_dir=core_output_dir,
                core_quote_path=core_quote_path,
                trade_mapping_path=trade_mapping_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                entry_price_field=entry_price_field,
                exit_price_field=exit_price_field,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("run-cf-single-factor-backtest")
    def research_run_cf_single_factor_backtest(
        start: Annotated[str, typer.Option("--start", help="Start date in YYYY-MM-DD format.")],
        end: Annotated[str, typer.Option("--end", help="End date in YYYY-MM-DD format.")],
        factor_ids: Annotated[
            str,
            typer.Option(
                "--factor-ids",
                help="Comma-separated factor ids. Defaults to all four MVP factors.",
            ),
        ] = "mom_20_v1,carry_nf_v1,curve_slope_v1,oi_pressure_v1",
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Comma-separated forward horizons, e.g. 1,3,5."),
        ] = "1,3,5",
        diagnostic_path: Annotated[
            Path | None,
            typer.Option("--diagnostic-path", help="Optional R14 diagnostic parquet path."),
        ] = None,
        forward_return_path: Annotated[
            Path | None,
            typer.Option("--forward-return-path", help="Optional R15 forward-return parquet path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Single-factor backtest output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Single-factor Markdown report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable single-factor backtest run id."),
        ] = None,
        use_processed_value: Annotated[
            bool,
            typer.Option(
                "--use-processed-value/--use-raw-value",
                help="Use processed factor value when available.",
            ),
        ] = True,
    ) -> None:
        """Run R16 CF single-factor research backtest summaries."""
        from cotton_factor.research_workbench import build_cf_single_factor_backtest

        try:
            result = build_cf_single_factor_backtest(
                start=_parse_iso_date(start),
                end=_parse_iso_date(end),
                factor_ids=_parse_factor_ids(factor_ids),
                horizons=_parse_horizons(horizons),
                diagnostic_path=diagnostic_path,
                forward_return_path=forward_return_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                use_processed_value=use_processed_value,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-multifactor-diagnostics")
    def research_build_cf_multifactor_diagnostics(
        start: Annotated[str, typer.Option("--start", help="Start date in YYYY-MM-DD format.")],
        end: Annotated[str, typer.Option("--end", help="End date in YYYY-MM-DD format.")],
        factor_ids: Annotated[
            str,
            typer.Option(
                "--factor-ids",
                help="Comma-separated factor ids. Defaults to all four MVP factors.",
            ),
        ] = "mom_20_v1,carry_nf_v1,curve_slope_v1,oi_pressure_v1",
        diagnostic_path: Annotated[
            Path | None,
            typer.Option("--diagnostic-path", help="Optional R14 diagnostic parquet path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Multifactor output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Multifactor Markdown report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable multifactor run id."),
        ] = None,
        score_id: Annotated[
            str,
            typer.Option("--score-id", help="Multifactor score id."),
        ] = "cf_equal_weight_v1",
        use_processed_value: Annotated[
            bool,
            typer.Option(
                "--use-processed-value/--use-raw-value",
                help="Use processed factor value when available.",
            ),
        ] = True,
        require_all_factors: Annotated[
            bool,
            typer.Option(
                "--require-all-factors/--allow-missing-factors",
                help="Skip dates with missing factors by default.",
            ),
        ] = True,
    ) -> None:
        """Build R17 CF equal-weight multifactor score diagnostics."""
        from cotton_factor.research_workbench import build_cf_multifactor_diagnostics

        try:
            result = build_cf_multifactor_diagnostics(
                start=_parse_iso_date(start),
                end=_parse_iso_date(end),
                factor_ids=_parse_factor_ids(factor_ids),
                diagnostic_path=diagnostic_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                score_id=score_id,
                use_processed_value=use_processed_value,
                require_all_factors=require_all_factors,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-cost-sensitivity")
    def research_build_cf_cost_sensitivity(
        start: Annotated[str, typer.Option("--start", help="Start date in YYYY-MM-DD format.")],
        end: Annotated[str, typer.Option("--end", help="End date in YYYY-MM-DD format.")],
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Comma-separated positive horizons."),
        ] = "1,3,5",
        score_path: Annotated[
            Path | None,
            typer.Option("--score-path", help="Optional R17 multifactor score parquet path."),
        ] = None,
        forward_return_path: Annotated[
            Path | None,
            typer.Option("--forward-return-path", help="Optional R15 forward-return parquet path."),
        ] = None,
        scenario_cost_bps: Annotated[
            str | None,
            typer.Option(
                "--scenario-cost-bps",
                help="Comma-separated scenario=bps pairs, e.g. no_cost=0,normal_cost=5.",
            ),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Cost sensitivity output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Cost sensitivity Markdown report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable cost sensitivity run id."),
        ] = None,
        use_processed_score: Annotated[
            bool,
            typer.Option(
                "--use-processed-score/--use-raw-score",
                help="Use processed multifactor score when available.",
            ),
        ] = True,
    ) -> None:
        """Build R18 CF research cost sensitivity summaries."""
        from cotton_factor.research_workbench import build_cf_cost_sensitivity

        try:
            result = build_cf_cost_sensitivity(
                start=_parse_iso_date(start),
                end=_parse_iso_date(end),
                horizons=_parse_horizons(horizons),
                score_path=score_path,
                forward_return_path=forward_return_path,
                scenario_cost_bps=_parse_scenario_cost_bps(scenario_cost_bps),
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                use_processed_score=use_processed_score,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-daily-brief")
    def research_build_cf_daily_brief(
        trade_date: Annotated[str, typer.Option("--date", help="Brief trade date.")],
        start: Annotated[
            str | None,
            typer.Option("--start", help="Artifact window start date."),
        ] = None,
        end: Annotated[
            str | None,
            typer.Option("--end", help="Artifact window end date."),
        ] = None,
        quality_csv_path: Annotated[
            Path | None,
            typer.Option("--quality-csv-path", help="Optional R06 quality CSV path."),
        ] = None,
        chain_map_path: Annotated[
            Path | None,
            typer.Option("--chain-map-path", help="Optional R08 chain map parquet path."),
        ] = None,
        trade_mapping_path: Annotated[
            Path | None,
            typer.Option("--trade-mapping-path", help="Optional R08 trade mapping parquet path."),
        ] = None,
        diagnostic_path: Annotated[
            Path | None,
            typer.Option("--diagnostic-path", help="Optional R14 diagnostic parquet path."),
        ] = None,
        single_factor_evaluation_path: Annotated[
            Path | None,
            typer.Option("--single-factor-evaluation-path", help="Optional R16 evaluation path."),
        ] = None,
        multifactor_score_path: Annotated[
            Path | None,
            typer.Option("--multifactor-score-path", help="Optional R17 score path."),
        ] = None,
        cost_sensitivity_path: Annotated[
            Path | None,
            typer.Option("--cost-sensitivity-path", help="Optional R18 cost summary path."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Daily brief output directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable daily brief run id."),
        ] = None,
    ) -> None:
        """Build R19 CF daily research brief."""
        from cotton_factor.research_workbench import build_cf_daily_brief

        parsed_trade_date = _parse_iso_date(trade_date)
        try:
            result = build_cf_daily_brief(
                trade_date=parsed_trade_date,
                start=_parse_iso_date(start) if start else None,
                end=_parse_iso_date(end) if end else None,
                quality_csv_path=quality_csv_path,
                chain_map_path=chain_map_path,
                trade_mapping_path=trade_mapping_path,
                diagnostic_path=diagnostic_path,
                single_factor_evaluation_path=single_factor_evaluation_path,
                multifactor_score_path=multifactor_score_path,
                cost_sensitivity_path=cost_sensitivity_path,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-latest-signal-brief")
    def research_build_cf_latest_signal_brief(
        trade_date: Annotated[
            str | None,
            typer.Option("--date", help="Optional latest-signal trade date."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional core quote parquet path."),
        ] = None,
        output_root: Annotated[
            Path | None,
            typer.Option("--output-root", help="Output root. Defaults to runs/daily."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R23 run id."),
        ] = None,
        lookback_days: Annotated[
            int,
            typer.Option("--lookback-days", help="Latest signal lookback observations."),
        ] = 20,
        trend_rule_candidate_path: Annotated[
            Path | None,
            typer.Option(
                "--trend-rule-candidate-path",
                help="Optional R27 trend rule candidate parquet/csv path.",
            ),
        ] = None,
        signal_matrix_path: Annotated[
            Path | None,
            typer.Option(
                "--signal-matrix-path",
                help="Optional R35 signal matrix latest snapshot or daily table path.",
            ),
        ] = None,
        signal_threshold_research_path: Annotated[
            Path | None,
            typer.Option(
                "--signal-threshold-research-path",
                help="Optional R37 signal threshold/weighting aggregate path.",
            ),
        ] = None,
    ) -> None:
        """Build R23 CF latest signal-only brief."""
        from cotton_factor.research_workbench import build_cf_latest_signal_brief

        try:
            result = build_cf_latest_signal_brief(
                trade_date=_parse_iso_date(trade_date) if trade_date else None,
                core_quote_path=core_quote_path,
                output_root=output_root,
                run_id=run_id,
                lookback_days=lookback_days,
                trend_rule_candidate_path=trend_rule_candidate_path,
                signal_matrix_path=signal_matrix_path,
                signal_threshold_research_path=signal_threshold_research_path,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-trend-continuity-board")
    def research_build_cf_trend_continuity_board(
        trade_date: Annotated[
            str | None,
            typer.Option("--date", help="Optional trend board trade date."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional core quote parquet path."),
        ] = None,
        output_root: Annotated[
            Path | None,
            typer.Option("--output-root", help="Output root. Defaults to runs/daily."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R29 run id."),
        ] = None,
        lookback_trading_days: Annotated[
            int,
            typer.Option("--lookback-trading-days", help="Trend board trading-day window."),
        ] = 20,
        trend_rule_candidate_path: Annotated[
            Path | None,
            typer.Option(
                "--trend-rule-candidate-path",
                help="Optional R27 trend rule candidate parquet/csv path.",
            ),
        ] = None,
        trend_quality_calibration_manifest_path: Annotated[
            Path | None,
            typer.Option(
                "--trend-quality-calibration-manifest-path",
                help="Optional R32 trend quality calibration manifest JSON path.",
            ),
        ] = None,
    ) -> None:
        """Build R29 CF latest trend continuity board."""
        from cotton_factor.research_workbench import build_cf_trend_continuity_board

        try:
            result = build_cf_trend_continuity_board(
                trade_date=_parse_iso_date(trade_date) if trade_date else None,
                core_quote_path=core_quote_path,
                output_root=output_root,
                run_id=run_id,
                lookback_trading_days=lookback_trading_days,
                trend_rule_candidate_path=trend_rule_candidate_path,
                trend_quality_calibration_manifest_path=(
                    trend_quality_calibration_manifest_path
                ),
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-daily-operation-audit")
    def research_build_cf_daily_operation_audit(
        latest_signal_json_path: Annotated[
            Path,
            typer.Option(
                "--latest-signal-json-path",
                help="R23 latest signal brief JSON path.",
            ),
        ],
        trend_board_json_path: Annotated[
            Path,
            typer.Option(
                "--trend-board-json-path",
                help="R29/R33 trend continuity board JSON path.",
            ),
        ],
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional core quote parquet path."),
        ] = None,
        output_root: Annotated[
            Path | None,
            typer.Option("--output-root", help="Output root. Defaults to runs/daily."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R34 run id."),
        ] = None,
    ) -> None:
        """Build R34 CF daily operation audit from latest research artifacts."""
        from cotton_factor.research_workbench import build_cf_daily_operation_audit

        try:
            result = build_cf_daily_operation_audit(
                latest_signal_json_path=latest_signal_json_path,
                trend_board_json_path=trend_board_json_path,
                core_quote_path=core_quote_path,
                output_root=output_root,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-data-continuity-audit")
    def research_build_cf_data_continuity_audit(
        trade_date: Annotated[
            str | None,
            typer.Option("--date", help="Target trade date in YYYY-MM-DD format."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="CF futures core quote parquet path."),
        ] = None,
        option_core_path: Annotated[
            Path | None,
            typer.Option("--option-core-path", help="CF option core quote parquet path."),
        ] = None,
        calendar_path: Annotated[
            Path | None,
            typer.Option("--calendar-path", help="Official CZCE calendar CSV path."),
        ] = None,
        official_daily_fetch_json_path: Annotated[
            Path | None,
            typer.Option(
                "--official-daily-fetch-json-path",
                help="Official daily downloader JSON summary path.",
            ),
        ] = None,
        raw_root: Annotated[
            Path | None,
            typer.Option("--raw-root", help="Raw snapshot root. Defaults to data/raw."),
        ] = None,
        output_root: Annotated[
            Path | None,
            typer.Option("--output-root", help="Daily output root. Defaults to runs/daily."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R63 run id."),
        ] = None,
        require_options: Annotated[
            bool,
            typer.Option(
                "--require-options/--no-require-options",
                help="Require option core continuity for this audit.",
            ),
        ] = True,
        require_raw_retention: Annotated[
            bool,
            typer.Option(
                "--require-raw-retention/--skip-raw-retention",
                help="Require raw snapshot retention before cleanup is allowed.",
            ),
        ] = True,
    ) -> None:
        """Build R63 CF data continuity and retained-source audit."""
        from cotton_factor.research_workbench import build_cf_data_continuity_audit

        try:
            result = build_cf_data_continuity_audit(
                trade_date=_parse_iso_date(trade_date) if trade_date else None,
                core_quote_path=core_quote_path,
                option_core_path=option_core_path,
                calendar_path=calendar_path,
                official_daily_fetch_json_path=official_daily_fetch_json_path,
                raw_root=raw_root,
                output_root=output_root,
                run_id=run_id,
                require_options=require_options,
                require_raw_retention=require_raw_retention,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
        if not result.passed:
            raise typer.Exit(1)

    @research_app.command("build-cf-signal-matrix")
    def research_build_cf_signal_matrix(
        start: Annotated[
            str | None,
            typer.Option("--start", help="Optional signal matrix window start date."),
        ] = None,
        end: Annotated[
            str | None,
            typer.Option("--end", help="Optional signal matrix window end date."),
        ] = None,
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Comma-separated positive horizons."),
        ] = "1,3,5,10,20,40",
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional core quote parquet path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R35 table output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R35 Markdown/JSON report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R35 run id."),
        ] = None,
        trend_rule_candidate_path: Annotated[
            Path | None,
            typer.Option(
                "--trend-rule-candidate-path",
                help="Optional R27 trend rule candidate parquet/csv path.",
            ),
        ] = None,
        option_factor_path: Annotated[
            Path | None,
            typer.Option(
                "--option-factor-path",
                help="Optional R48 option factor parquet/csv path.",
            ),
        ] = None,
    ) -> None:
        """Build R35 CF multi-horizon signal matrix."""
        from cotton_factor.research_workbench import build_cf_signal_matrix

        try:
            result = build_cf_signal_matrix(
                start=_parse_iso_date(start) if start else None,
                end=_parse_iso_date(end) if end else None,
                horizons=_parse_horizons(horizons),
                core_quote_path=core_quote_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                trend_rule_candidate_path=trend_rule_candidate_path,
                option_factor_path=option_factor_path,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-signal-matrix-validation")
    def research_build_cf_signal_matrix_validation(
        signal_matrix_path: Annotated[
            Path,
            typer.Option("--signal-matrix-path", help="R35 signal matrix parquet/csv path."),
        ],
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional core quote parquet path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R36 table output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R36 Markdown/JSON report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R36 run id."),
        ] = None,
        windows: Annotated[
            str | None,
            typer.Option("--windows", help="Comma-separated year windows, e.g. 2021-2022."),
        ] = None,
    ) -> None:
        """Build R36 rolling validation for the R35 signal matrix."""
        from cotton_factor.research_workbench import build_cf_signal_matrix_validation

        try:
            result = build_cf_signal_matrix_validation(
                signal_matrix_path=signal_matrix_path,
                core_quote_path=core_quote_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                windows=_parse_optional_csv(windows),
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-signal-threshold-research")
    def research_build_cf_signal_threshold_research(
        validation_daily_path: Annotated[
            Path,
            typer.Option("--validation-daily-path", help="R36 validation daily parquet/csv path."),
        ],
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R37 table output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R37 Markdown/JSON report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R37 run id."),
        ] = None,
    ) -> None:
        """Build R37 CF threshold and weighting research."""
        from cotton_factor.research_workbench import build_cf_signal_threshold_research

        try:
            result = build_cf_signal_threshold_research(
                validation_daily_path=validation_daily_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-historical-evidence-pack")
    def research_build_cf_historical_evidence_pack(
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional core quote parquet path."),
        ] = None,
        signal_matrix_path: Annotated[
            Path | None,
            typer.Option("--signal-matrix-path", help="Optional R35 signal matrix path."),
        ] = None,
        validation_daily_path: Annotated[
            Path | None,
            typer.Option("--validation-daily-path", help="Optional R36 validation daily path."),
        ] = None,
        validation_window_summary_path: Annotated[
            Path | None,
            typer.Option(
                "--validation-window-summary-path",
                help="Optional R36 validation window summary path.",
            ),
        ] = None,
        threshold_weighting_path: Annotated[
            Path | None,
            typer.Option("--threshold-weighting-path", help="Optional R37 weighting path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R41 table output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R41 Markdown/JSON report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R41 run id."),
        ] = None,
        cost_scenarios: Annotated[
            str | None,
            typer.Option(
                "--cost-scenarios",
                help="Comma-separated cost scenarios, e.g. no_cost=0,normal_cost=5.",
            ),
        ] = None,
    ) -> None:
        """Build R41 CF historical multi-factor evidence pack."""
        from cotton_factor.research_workbench import build_cf_historical_evidence_pack
        from cotton_factor.research_workbench.historical_evidence import parse_cost_scenarios

        try:
            result = build_cf_historical_evidence_pack(
                core_quote_path=core_quote_path,
                signal_matrix_path=signal_matrix_path,
                validation_daily_path=validation_daily_path,
                validation_window_summary_path=validation_window_summary_path,
                threshold_weighting_path=threshold_weighting_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                cost_scenarios=parse_cost_scenarios(cost_scenarios),
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-historical-event-explanation")
    def research_build_cf_historical_event_explanation(
        validation_daily_path: Annotated[
            Path | None,
            typer.Option("--validation-daily-path", help="Optional R36 validation daily path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R42 table output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R42 Markdown/JSON report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R42 run id."),
        ] = None,
        primary_horizon: Annotated[
            int,
            typer.Option("--primary-horizon", help="Primary horizon used for event detection."),
        ] = 20,
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Comma-separated outcome horizons."),
        ] = "1,3,5,10,20",
        fundamental_context_path: Annotated[
            Path | None,
            typer.Option(
                "--fundamental-context-path",
                help="Optional R54 fundamental context daily path for R55 event explanations.",
            ),
        ] = None,
    ) -> None:
        """Build R42 CF full-history event explanations."""
        from cotton_factor.research_workbench import build_cf_historical_event_explanation

        try:
            result = build_cf_historical_event_explanation(
                validation_daily_path=validation_daily_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                primary_horizon=primary_horizon,
                horizons=_parse_horizons(horizons),
                fundamental_context_path=fundamental_context_path,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-event-threshold-sensitivity")
    def research_build_cf_event_threshold_sensitivity(
        validation_daily_path: Annotated[
            Path | None,
            typer.Option("--validation-daily-path", help="Optional R36 validation daily path."),
        ] = None,
        event_path: Annotated[
            Path | None,
            typer.Option("--event-path", help="Optional R55 event detail parquet path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R60 table output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R60 Markdown/JSON report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R60 run id."),
        ] = None,
        primary_horizon: Annotated[
            int,
            typer.Option("--primary-horizon", help="Primary horizon used for thresholds."),
        ] = 20,
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Comma-separated outcome horizons."),
        ] = "1,3,5,10,20",
        threshold_quantiles: Annotated[
            str,
            typer.Option("--threshold-quantiles", help="Comma-separated quantiles."),
        ] = "0.90,0.95,0.975",
        min_observation_count: Annotated[
            int,
            typer.Option("--min-observation-count", help="Minimum labelled samples."),
        ] = 20,
    ) -> None:
        """Build R60 CF event threshold sensitivity review."""
        from cotton_factor.research_workbench import build_cf_event_threshold_sensitivity

        try:
            result = build_cf_event_threshold_sensitivity(
                validation_daily_path=validation_daily_path,
                event_path=event_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                primary_horizon=primary_horizon,
                horizons=_parse_horizons(horizons),
                threshold_quantiles=_parse_quantiles(threshold_quantiles),
                min_observation_count=min_observation_count,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-event-threshold-review-ledger")
    def research_build_cf_event_threshold_review_ledger(
        threshold_summary_path: Annotated[
            Path | None,
            typer.Option(
                "--threshold-summary-path",
                help="Optional R60 threshold summary path.",
            ),
        ] = None,
        threshold_detail_path: Annotated[
            Path | None,
            typer.Option(
                "--threshold-detail-path",
                help="Optional R60 threshold detail path.",
            ),
        ] = None,
        event_detail_path: Annotated[
            Path | None,
            typer.Option("--event-detail-path", help="Optional R55 event detail path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R62 ledger output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R62 Markdown/JSON report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R62 run id."),
        ] = None,
        example_event_count: Annotated[
            int,
            typer.Option("--example-event-count", help="Example event rows per candidate."),
        ] = 3,
    ) -> None:
        """Build R62 CF event threshold review ledger."""
        from cotton_factor.research_workbench import build_cf_event_threshold_review_ledger

        try:
            result = build_cf_event_threshold_review_ledger(
                threshold_summary_path=threshold_summary_path,
                threshold_detail_path=threshold_detail_path,
                event_detail_path=event_detail_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                example_event_count=example_event_count,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-validated-research-brief")
    def research_build_cf_validated_research_brief(
        latest_signal_json_path: Annotated[
            Path | None,
            typer.Option("--latest-signal-json-path", help="Optional R23 latest JSON path."),
        ] = None,
        historical_evidence_decay_path: Annotated[
            Path | None,
            typer.Option("--historical-evidence-decay-path", help="Optional R41 decay path."),
        ] = None,
        historical_evidence_stability_path: Annotated[
            Path | None,
            typer.Option(
                "--historical-evidence-stability-path",
                help="Optional R41 stability path.",
            ),
        ] = None,
        event_summary_path: Annotated[
            Path | None,
            typer.Option("--event-summary-path", help="Optional R42 event summary path."),
        ] = None,
        event_detail_path: Annotated[
            Path | None,
            typer.Option("--event-detail-path", help="Optional R55 event detail path."),
        ] = None,
        event_threshold_summary_path: Annotated[
            Path | None,
            typer.Option(
                "--event-threshold-summary-path",
                help="Optional R60 event threshold sensitivity summary path.",
            ),
        ] = None,
        fundamental_observation_json_path: Annotated[
            Path | None,
            typer.Option(
                "--fundamental-observation-json-path",
                help="Optional R53 fundamental observation JSON path.",
            ),
        ] = None,
        futures_option_divergence_json_path: Annotated[
            Path | None,
            typer.Option(
                "--futures-option-divergence-json-path",
                help="Optional R69 futures-option divergence JSON path.",
            ),
        ] = None,
        futures_option_playbook_json_path: Annotated[
            Path | None,
            typer.Option(
                "--futures-option-playbook-json-path",
                help="Optional R71 futures-option playbook JSON path.",
            ),
        ] = None,
        current_watch_window_json_path: Annotated[
            Path | None,
            typer.Option(
                "--current-watch-window-json-path",
                help="Optional R77 current watch window JSON path.",
            ),
        ] = None,
        state_transition_json_path: Annotated[
            Path | None,
            typer.Option(
                "--state-transition-json-path",
                help="Optional R79 competing-risk JSON path.",
            ),
        ] = None,
        option_volatility_json_path: Annotated[
            Path | None,
            typer.Option(
                "--option-volatility-json-path",
                help="Optional R80/R81 option volatility JSON path.",
            ),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R43 report output directory."),
        ] = None,
        daily_output_root: Annotated[
            Path | None,
            typer.Option("--daily-output-root", help="Optional runs/daily sync root."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R43 run id."),
        ] = None,
    ) -> None:
        """Build R43 CF validated Chinese research brief."""
        from cotton_factor.research_workbench import build_cf_validated_research_brief

        try:
            result = build_cf_validated_research_brief(
                latest_signal_json_path=latest_signal_json_path,
                historical_evidence_decay_path=historical_evidence_decay_path,
                historical_evidence_stability_path=historical_evidence_stability_path,
                event_summary_path=event_summary_path,
                event_detail_path=event_detail_path,
                event_threshold_summary_path=event_threshold_summary_path,
                fundamental_observation_json_path=fundamental_observation_json_path,
                futures_option_divergence_json_path=futures_option_divergence_json_path,
                futures_option_playbook_json_path=futures_option_playbook_json_path,
                current_watch_window_json_path=current_watch_window_json_path,
                state_transition_json_path=state_transition_json_path,
                option_volatility_json_path=option_volatility_json_path,
                output_dir=output_dir,
                daily_output_root=daily_output_root,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-publish-pack")
    def research_build_cf_publish_pack(
        latest_signal_json_path: Annotated[
            Path | None,
            typer.Option("--latest-signal-json-path", help="Optional R23 latest JSON path."),
        ] = None,
        validated_brief_path: Annotated[
            Path | None,
            typer.Option("--validated-brief-path", help="Optional R43 validated brief path."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional core quote parquet path."),
        ] = None,
        signal_matrix_path: Annotated[
            Path | None,
            typer.Option("--signal-matrix-path", help="Optional R35 signal matrix path."),
        ] = None,
        historical_evidence_decay_path: Annotated[
            Path | None,
            typer.Option("--historical-evidence-decay-path", help="Optional R41 decay path."),
        ] = None,
        event_summary_path: Annotated[
            Path | None,
            typer.Option("--event-summary-path", help="Optional R42 event summary path."),
        ] = None,
        futures_option_divergence_json_path: Annotated[
            Path | None,
            typer.Option(
                "--futures-option-divergence-json-path",
                help="Optional R69 futures-option divergence JSON path.",
            ),
        ] = None,
        futures_option_playbook_json_path: Annotated[
            Path | None,
            typer.Option(
                "--futures-option-playbook-json-path",
                help="Optional R71 futures-option playbook JSON path.",
            ),
        ] = None,
        current_watch_window_json_path: Annotated[
            Path | None,
            typer.Option(
                "--current-watch-window-json-path",
                help="Optional R77 current watch window JSON path.",
            ),
        ] = None,
        output_root: Annotated[
            Path | None,
            typer.Option("--output-root", help="Optional runs/daily output root."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R45 run id."),
        ] = None,
        price_lookback: Annotated[
            int,
            typer.Option("--price-lookback", help="Main-contract price/OI chart lookback."),
        ] = 120,
    ) -> None:
        """Build R45 CF chart and WeChat publish pack."""
        from cotton_factor.research_workbench import build_cf_publish_pack

        try:
            result = build_cf_publish_pack(
                latest_signal_json_path=latest_signal_json_path,
                validated_brief_path=validated_brief_path,
                core_quote_path=core_quote_path,
                signal_matrix_path=signal_matrix_path,
                historical_evidence_decay_path=historical_evidence_decay_path,
                event_summary_path=event_summary_path,
                futures_option_divergence_json_path=futures_option_divergence_json_path,
                futures_option_playbook_json_path=futures_option_playbook_json_path,
                current_watch_window_json_path=current_watch_window_json_path,
                output_root=output_root,
                run_id=run_id,
                price_lookback=price_lookback,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-weekly-research-audit")
    def research_build_cf_weekly_research_audit(
        weekly_manifest_path: Annotated[
            Path,
            typer.Option("--weekly-manifest-path", help="R58 weekly manifest JSON path."),
        ],
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R59 report output directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R59 run id."),
        ] = None,
    ) -> None:
        """Build R59 CF weekly research audit."""
        from cotton_factor.research_workbench import build_cf_weekly_research_audit

        try:
            result = build_cf_weekly_research_audit(
                weekly_manifest_path=weekly_manifest_path,
                output_dir=output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-stage-decision-pack")
    def research_build_cf_stage_decision_pack(
        weekly_audit_json_path: Annotated[
            Path,
            typer.Option("--weekly-audit-json-path", help="R59 weekly audit JSON path."),
        ],
        expansion_gate_json_path: Annotated[
            Path,
            typer.Option("--expansion-gate-json-path", help="R52 expansion gate JSON path."),
        ],
        latest_signal_json_path: Annotated[
            Path | None,
            typer.Option("--latest-signal-json-path", help="Optional R23 latest signal JSON."),
        ] = None,
        option_factor_json_path: Annotated[
            Path | None,
            typer.Option("--option-factor-json-path", help="Optional R48 option factor JSON."),
        ] = None,
        event_threshold_json_path: Annotated[
            Path | None,
            typer.Option(
                "--event-threshold-json-path",
                help="Optional R60 event threshold sensitivity JSON.",
            ),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R65 report output directory."),
        ] = None,
        daily_output_root: Annotated[
            Path | None,
            typer.Option("--daily-output-root", help="Optional runs/daily output root."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R65 run id."),
        ] = None,
    ) -> None:
        """Build R65 CF stage decision pack before expansion review."""
        from cotton_factor.research_workbench import build_cf_stage_decision_pack

        try:
            result = build_cf_stage_decision_pack(
                weekly_audit_json_path=weekly_audit_json_path,
                expansion_gate_json_path=expansion_gate_json_path,
                latest_signal_json_path=latest_signal_json_path,
                option_factor_json_path=option_factor_json_path,
                event_threshold_json_path=event_threshold_json_path,
                output_dir=output_dir,
                daily_output_root=daily_output_root,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-event-lifecycle-research")
    def research_build_cf_event_lifecycle_research(
        signal_matrix_path: Annotated[
            Path | None,
            typer.Option("--signal-matrix-path", help="Optional R35 signal matrix path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R68 data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R68 report output directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R68 run id."),
        ] = None,
        horizon: Annotated[
            int,
            typer.Option("--horizon", help="Signal matrix horizon used for phase episodes."),
        ] = 20,
        max_holding_days: Annotated[
            int,
            typer.Option("--max-holding-days", help="Simple TBM max holding window."),
        ] = 20,
        profit_barrier: Annotated[
            float,
            typer.Option("--profit-barrier", help="Simple TBM profit barrier."),
        ] = 0.03,
        stop_loss_barrier: Annotated[
            float,
            typer.Option("--stop-loss-barrier", help="Simple TBM stop loss barrier."),
        ] = 0.015,
    ) -> None:
        """Build R68 CF event lifecycle and simple TBM labels."""
        from cotton_factor.research_workbench import build_cf_event_lifecycle_research

        try:
            result = build_cf_event_lifecycle_research(
                signal_matrix_path=signal_matrix_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                horizon=horizon,
                max_holding_days=max_holding_days,
                profit_barrier=profit_barrier,
                stop_loss_barrier=stop_loss_barrier,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-state-transition-competing-risk")
    def research_build_cf_state_transition_competing_risk(
        event_lifecycle_episode_path: Annotated[
            Path | None,
            typer.Option(
                "--event-lifecycle-episode-path",
                help="Optional R68 episode table path.",
            ),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R79 data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R79 report output directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R79 run id."),
        ] = None,
        max_age_days: Annotated[
            int,
            typer.Option("--max-age-days", help="Maximum episode age for risk tables."),
        ] = 20,
        min_sample_size: Annotated[
            int,
            typer.Option("--min-sample-size", help="Minimum READY evidence sample."),
        ] = 30,
    ) -> None:
        """Build R79 CF state-transition competing-risk evidence."""
        from cotton_factor.research_workbench import (
            build_cf_state_transition_competing_risk_research,
        )

        try:
            result = build_cf_state_transition_competing_risk_research(
                event_lifecycle_episode_path=event_lifecycle_episode_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                max_age_days=max_age_days,
                min_sample_size=min_sample_size,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-futures-option-divergence-research")
    def research_build_cf_futures_option_divergence_research(
        signal_matrix_validation_path: Annotated[
            Path | None,
            typer.Option(
                "--signal-matrix-validation-path",
                help="Optional R36 signal matrix validation daily path.",
            ),
        ] = None,
        option_factor_path: Annotated[
            Path | None,
            typer.Option("--option-factor-path", help="Optional R48 option factor proxy path."),
        ] = None,
        event_lifecycle_episode_path: Annotated[
            Path | None,
            typer.Option(
                "--event-lifecycle-episode-path",
                help="Optional R68 event lifecycle episode path.",
            ),
        ] = None,
        event_lifecycle_tbm_path: Annotated[
            Path | None,
            typer.Option("--event-lifecycle-tbm-path", help="Optional R68 TBM label path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R69 data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R69 report output directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R69 run id."),
        ] = None,
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Comma-separated validation horizons."),
        ] = "1,3,5,10,20,40",
        dead_zone_bps: Annotated[
            int,
            typer.Option("--dead-zone-bps", help="Winner dead-zone threshold in bps."),
        ] = 10,
        min_sample_size: Annotated[
            int,
            typer.Option("--min-sample-size", help="Minimum node sample size for evidence level."),
        ] = 30,
    ) -> None:
        """Build R69 CF futures-option divergence battle research."""
        from cotton_factor.research_workbench import (
            build_cf_futures_option_divergence_research,
        )

        try:
            result = build_cf_futures_option_divergence_research(
                signal_matrix_validation_path=signal_matrix_validation_path,
                option_factor_path=option_factor_path,
                event_lifecycle_episode_path=event_lifecycle_episode_path,
                event_lifecycle_tbm_path=event_lifecycle_tbm_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                horizons=_parse_horizons(horizons),
                dead_zone_bps=dead_zone_bps,
                min_sample_size=min_sample_size,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-futures-option-divergence-playbook")
    def research_build_cf_futures_option_divergence_playbook(
        event_path: Annotated[
            Path | None,
            typer.Option("--event-path", help="Optional R69 divergence event table path."),
        ] = None,
        node_summary_path: Annotated[
            Path | None,
            typer.Option("--node-summary-path", help="Optional R69 node summary table path."),
        ] = None,
        latest_signal_json_path: Annotated[
            Path | None,
            typer.Option("--latest-signal-json-path", help="Optional latest signal JSON path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R71 data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R71 report output directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R71 run id."),
        ] = None,
        min_sample_size: Annotated[
            int,
            typer.Option("--min-sample-size", help="Minimum sample size for playbook review."),
        ] = 30,
        edge_threshold: Annotated[
            float,
            typer.Option("--edge-threshold", help="Winner-rate edge threshold."),
        ] = 0.08,
    ) -> None:
        """Build R71 CF futures-option divergence playbook."""
        from cotton_factor.research_workbench import (
            build_cf_futures_option_divergence_playbook,
        )

        try:
            result = build_cf_futures_option_divergence_playbook(
                event_path=event_path,
                node_summary_path=node_summary_path,
                latest_signal_json_path=latest_signal_json_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                min_sample_size=min_sample_size,
                edge_threshold=edge_threshold,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-futures-option-dynamic-wall-research")
    def research_build_cf_futures_option_dynamic_wall_research(
        option_core_path: Annotated[
            Path | None,
            typer.Option("--option-core-path", help="CF core option quote parquet path."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="CF core futures quote parquet path."),
        ] = None,
        option_factor_path: Annotated[
            Path | None,
            typer.Option("--option-factor-path", help="Optional R48 option factor path."),
        ] = None,
        signal_matrix_path: Annotated[
            Path | None,
            typer.Option("--signal-matrix-path", help="Optional R35 signal matrix path."),
        ] = None,
        trend_phase_path: Annotated[
            Path | None,
            typer.Option("--trend-phase-path", help="Optional R76 trend phase path."),
        ] = None,
        option_strike_position_path: Annotated[
            Path | None,
            typer.Option("--option-strike-position-path", help="Optional R84 strike path."),
        ] = None,
        start: Annotated[
            str | None,
            typer.Option("--start", help="Optional analysis start date."),
        ] = None,
        end: Annotated[
            str | None,
            typer.Option("--end", help="Optional analysis end date."),
        ] = None,
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Comma-separated posterior horizons."),
        ] = "1,3,5",
        local_band_ratio: Annotated[
            float,
            typer.Option("--local-band-ratio", help="Local strike band ratio."),
        ] = 0.03,
        touch_band_ratio: Annotated[
            float,
            typer.Option("--touch-band-ratio", help="Wall touch band ratio."),
        ] = 0.01,
        wall_change_bps: Annotated[
            int,
            typer.Option("--wall-change-bps", help="Local OI change threshold."),
        ] = 50,
        wall_shift_bps: Annotated[
            int,
            typer.Option("--wall-shift-bps", help="Wall migration threshold."),
        ] = 50,
        min_sample_size: Annotated[
            int,
            typer.Option("--min-sample-size", help="Minimum evidence sample size."),
        ] = 30,
        fdr_level: Annotated[
            float,
            typer.Option("--fdr-level", help="Benjamini-Hochberg FDR level."),
        ] = 0.10,
        dead_zone_bps: Annotated[
            int,
            typer.Option("--dead-zone-bps", help="Posterior return dead zone."),
        ] = 10,
        tbm_vol_multiplier: Annotated[
            float,
            typer.Option("--tbm-vol-multiplier", help="TBM volatility multiplier."),
        ] = 1.0,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R93N data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R93N report output directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R93N run id."),
        ] = None,
    ) -> None:
        """Build R93N dynamic CF option-wall and 5D incremental research."""
        from cotton_factor.research_workbench import (
            build_cf_futures_option_dynamic_wall_research,
        )

        try:
            result = build_cf_futures_option_dynamic_wall_research(
                option_core_path=option_core_path,
                core_quote_path=core_quote_path,
                option_factor_path=option_factor_path,
                signal_matrix_path=signal_matrix_path,
                trend_phase_path=trend_phase_path,
                option_strike_position_path=option_strike_position_path,
                start=None if start is None else _parse_iso_date(start),
                end=None if end is None else _parse_iso_date(end),
                horizons=_parse_horizons(horizons),
                local_band_ratio=local_band_ratio,
                touch_band_ratio=touch_band_ratio,
                wall_change_bps=wall_change_bps,
                wall_shift_bps=wall_shift_bps,
                min_sample_size=min_sample_size,
                fdr_level=fdr_level,
                dead_zone_bps=dead_zone_bps,
                tbm_vol_multiplier=tbm_vol_multiplier,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-futures-option-wall-factor-v2")
    def research_build_cf_futures_option_wall_factor_v2(
        dynamic_wall_feature_path: Annotated[
            Path | None,
            typer.Option("--dynamic-wall-feature-path", help="R93N冻结动态墙T日特征表。"),
        ] = None,
        dynamic_wall_label_path: Annotated[
            Path | None,
            typer.Option("--dynamic-wall-label-path", help="R93N物理分离的历史后验标签表。"),
        ] = None,
        option_factor_path: Annotated[
            Path | None,
            typer.Option("--option-factor-path", help="可选R48期权因子proxy表。"),
        ] = None,
        start: Annotated[
            str | None,
            typer.Option("--start", help="可选研究起始日期。"),
        ] = None,
        end: Annotated[
            str | None,
            typer.Option("--end", help="可选研究结束日期。"),
        ] = None,
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="逗号分隔的固定后验周期，只允许1,3,5。"),
        ] = "1,3,5",
        min_sample_size: Annotated[
            int,
            typer.Option("--min-sample-size", help="候选最低样本数。"),
        ] = 30,
        fdr_level: Annotated[
            float,
            typer.Option("--fdr-level", help="Benjamini-Hochberg FDR水平。"),
        ] = 0.10,
        dead_zone_bps: Annotated[
            int,
            typer.Option("--dead-zone-bps", help="历史后验收益死区。"),
        ] = 10,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R93O数据输出目录。"),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R93O报告输出目录。"),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="可选稳定运行编号。"),
        ] = None,
    ) -> None:
        """构建R93O期权墙因子v2与统一历史增量证据。"""
        from cotton_factor.research_workbench import (
            build_cf_futures_option_wall_factor_v2_research,
        )

        try:
            result = build_cf_futures_option_wall_factor_v2_research(
                dynamic_wall_feature_path=dynamic_wall_feature_path,
                dynamic_wall_label_path=dynamic_wall_label_path,
                option_factor_path=option_factor_path,
                start=None if start is None else _parse_iso_date(start),
                end=None if end is None else _parse_iso_date(end),
                horizons=_parse_horizons(horizons),
                min_sample_size=min_sample_size,
                fdr_level=fdr_level,
                dead_zone_bps=dead_zone_bps,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-futures-option-event-path-research")
    def research_build_cf_futures_option_event_path_research(
        event_path: Annotated[
            Path | None,
            typer.Option("--event-path", help="R93N T日事件表路径。"),
        ] = None,
        event_lifecycle_label_path: Annotated[
            Path | None,
            typer.Option("--event-lifecycle-label-path", help="R93N事件生命周期后验标签路径。"),
        ] = None,
        feature_path: Annotated[
            Path | None,
            typer.Option("--feature-path", help="可选R93N T日feature路径，用于状态路径。"),
        ] = None,
        start: Annotated[
            str | None,
            typer.Option("--start", help="可选研究起始日期。"),
        ] = None,
        end: Annotated[
            str | None,
            typer.Option("--end", help="可选研究结束日期。"),
        ] = None,
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="固定检查点，只允许1,3,5。"),
        ] = "1,3,5",
        dead_zone_bps: Annotated[
            int,
            typer.Option("--dead-zone-bps", help="方向性收益死区。"),
        ] = 10,
        min_sample_size: Annotated[
            int,
            typer.Option("--min-sample-size", help="预测筛选最低样本数。"),
        ] = 30,
        fdr_level: Annotated[
            float,
            typer.Option("--fdr-level", help="Benjamini-Hochberg FDR水平。"),
        ] = 0.10,
        purge_gap_sessions: Annotated[
            int,
            typer.Option("--purge-gap-sessions", help="留一年验证的事件净化间隔。"),
        ] = 5,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R93P数据输出目录。"),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R93P报告输出目录。"),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="可选稳定运行编号。"),
        ] = None,
    ) -> None:
        """构建R93P期货-期权事件路径与purged LOO研究。"""
        from cotton_factor.research_workbench import (
            build_cf_futures_option_event_path_research,
        )

        try:
            result = build_cf_futures_option_event_path_research(
                event_path=event_path,
                event_lifecycle_label_path=event_lifecycle_label_path,
                feature_path=feature_path,
                start=None if start is None else _parse_iso_date(start),
                end=None if end is None else _parse_iso_date(end),
                horizons=_parse_horizons(horizons),
                dead_zone_bps=dead_zone_bps,
                min_sample_size=min_sample_size,
                fdr_level=fdr_level,
                purge_gap_sessions=purge_gap_sessions,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-futures-option-regime-interaction-research")
    def research_build_cf_futures_option_regime_interaction_research(
        event_path: Annotated[
            Path | None,
            typer.Option("--event-path", help="R93N T日事件表路径。"),
        ] = None,
        checkpoint_path: Annotated[
            Path | None,
            typer.Option("--checkpoint-path", help="R93P固定检查点后验表路径。"),
        ] = None,
        path_path: Annotated[
            Path | None,
            typer.Option("--path-path", help="R93P事件路径表路径。"),
        ] = None,
        feature_path: Annotated[
            Path | None,
            typer.Option("--feature-path", help="R93N T日feature表路径。"),
        ] = None,
        policy_context_path: Annotated[
            Path | None,
            typer.Option("--policy-context-path", help="可选R93G政策具名上下文。"),
        ] = None,
        fundamental_context_path: Annotated[
            Path | None,
            typer.Option("--fundamental-context-path", help="可选基本面具名上下文。"),
        ] = None,
        start: Annotated[
            str | None,
            typer.Option("--start", help="可选研究起始日期。"),
        ] = None,
        end: Annotated[
            str | None,
            typer.Option("--end", help="可选研究结束日期。"),
        ] = None,
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="固定后验周期，只允许1,3,5。"),
        ] = "1,3,5",
        episode_gap_sessions: Annotated[
            int,
            typer.Option("--episode-gap-sessions", help="连续同类事件合并间隔。"),
        ] = 1,
        chain_window_sessions: Annotated[
            int,
            typer.Option("--chain-window-sessions", help="解释型完整事件链窗口。"),
        ] = 5,
        min_sample_size: Annotated[
            int,
            typer.Option("--min-sample-size", help="目标阶段组与对照最低episode数。"),
        ] = 30,
        min_cell_size: Annotated[
            int,
            typer.Option("--min-cell-size", help="交互四格最低episode数。"),
        ] = 5,
        fdr_level: Annotated[
            float,
            typer.Option("--fdr-level", help="Benjamini-Hochberg FDR水平。"),
        ] = 0.10,
        permutation_count: Annotated[
            int,
            typer.Option("--permutation-count", help="差中差置换次数。"),
        ] = 1000,
        purge_gap_sessions: Annotated[
            int,
            typer.Option("--purge-gap-sessions", help="留一年验证净化会话数。"),
        ] = 5,
        random_seed: Annotated[
            int,
            typer.Option("--random-seed", help="可复算置换随机种子。"),
        ] = 93,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R93Q数据输出目录。"),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R93Q报告输出目录。"),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="可选稳定运行编号。"),
        ] = None,
    ) -> None:
        """构建R93Q期货-期权阶段交互、episode和purged LOO研究。"""
        from cotton_factor.research_workbench import (
            build_cf_futures_option_regime_interaction_research,
        )

        try:
            result = build_cf_futures_option_regime_interaction_research(
                event_path=event_path,
                checkpoint_path=checkpoint_path,
                path_path=path_path,
                feature_path=feature_path,
                policy_context_path=policy_context_path,
                fundamental_context_path=fundamental_context_path,
                start=None if start is None else _parse_iso_date(start),
                end=None if end is None else _parse_iso_date(end),
                horizons=_parse_horizons(horizons),
                episode_gap_sessions=episode_gap_sessions,
                chain_window_sessions=chain_window_sessions,
                min_sample_size=min_sample_size,
                min_cell_size=min_cell_size,
                fdr_level=fdr_level,
                permutation_count=permutation_count,
                purge_gap_sessions=purge_gap_sessions,
                random_seed=random_seed,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-futures-option-evidence-gate")
    def research_build_cf_futures_option_evidence_gate(
        r93n_label_path: Annotated[
            Path | None,
            typer.Option("--r93n-label-path", help="R93N生命周期历史后验标签。"),
        ] = None,
        r93o_evidence_path: Annotated[
            Path | None,
            typer.Option("--r93o-evidence-path", help="R93O固定候选证据表。"),
        ] = None,
        r93o_posterior_path: Annotated[
            Path | None,
            typer.Option("--r93o-posterior-path", help="R93O候选历史后验标签。"),
        ] = None,
        r93p_summary_path: Annotated[
            Path | None,
            typer.Option("--r93p-summary-path", help="R93P事件类型摘要。"),
        ] = None,
        r93p_resolution_path: Annotated[
            Path | None,
            typer.Option("--r93p-resolution-path", help="R93P事件解决周期。"),
        ] = None,
        r93p_oos_path: Annotated[
            Path | None,
            typer.Option("--r93p-oos-path", help="R93P purged留一年验证。"),
        ] = None,
        r93q_main_effect_path: Annotated[
            Path | None,
            typer.Option("--r93q-main-effect-path", help="R93Q阶段主效应。"),
        ] = None,
        r93q_primary_path: Annotated[
            Path | None,
            typer.Option("--r93q-primary-path", help="R93Q预注册主交互。"),
        ] = None,
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="固定历史后验周期，只允许1,3,5。"),
        ] = "1,3,5",
        cost_bps_per_side: Annotated[
            str,
            typer.Option(
                "--cost-bps-per-side",
                help="逗号分隔的单边事件成本bps，必须包含0。",
            ),
        ] = "0,5,10",
        min_sample_size: Annotated[
            int,
            typer.Option("--min-sample-size", help="统一门控最低样本数。"),
        ] = 30,
        fdr_level: Annotated[
            float,
            typer.Option("--fdr-level", help="统一Benjamini-Hochberg FDR水平。"),
        ] = 0.10,
        dead_zone_bps: Annotated[
            int,
            typer.Option("--dead-zone-bps", help="成本后命中的收益死区。"),
        ] = 10,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R93R数据输出目录。"),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R93R报告输出目录。"),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="可选稳定运行编号。"),
        ] = None,
    ) -> None:
        """构建R93R统一证据门控与CF期权研究停止决策。"""
        from cotton_factor.research_workbench import (
            build_cf_futures_option_evidence_gate,
        )

        try:
            result = build_cf_futures_option_evidence_gate(
                r93n_label_path=r93n_label_path,
                r93o_evidence_path=r93o_evidence_path,
                r93o_posterior_path=r93o_posterior_path,
                r93p_summary_path=r93p_summary_path,
                r93p_resolution_path=r93p_resolution_path,
                r93p_oos_path=r93p_oos_path,
                r93q_main_effect_path=r93q_main_effect_path,
                r93q_primary_path=r93q_primary_path,
                horizons=_parse_horizons(horizons),
                cost_bps_per_side=_parse_non_negative_ints(cost_bps_per_side),
                min_sample_size=min_sample_size,
                fdr_level=fdr_level,
                dead_zone_bps=dead_zone_bps,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-dual-price-state")
    def research_build_cf_dual_price_state(
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional CF core quote path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R73 data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R73 report output directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R73 run id."),
        ] = None,
        ma_window: Annotated[
            int,
            typer.Option("--ma-window", help="Close/settlement moving-average window."),
        ] = 20,
        gap_alert_bps: Annotated[
            float,
            typer.Option("--gap-alert-bps", help="Close-settlement gap alert threshold."),
        ] = 25.0,
    ) -> None:
        """Build R73 close/settlement dual-price state research."""
        from cotton_factor.research_workbench import build_cf_dual_price_state

        try:
            result = build_cf_dual_price_state(
                core_quote_path=core_quote_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                ma_window=ma_window,
                gap_alert_bps=gap_alert_bps,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-chain-oi-structure")
    def research_build_cf_chain_oi_structure(
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional CF core quote path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R74 data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R74 report output directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R74 run id."),
        ] = None,
        noise_ratio: Annotated[
            float,
            typer.Option("--noise-ratio", help="Chain OI noise ratio."),
        ] = 0.002,
        roll_transfer_threshold: Annotated[
            float,
            typer.Option("--roll-transfer-threshold", help="Roll-transfer ratio threshold."),
        ] = 0.50,
        roll_lookback_days: Annotated[
            int,
            typer.Option(
                "--roll-lookback-days",
                help="Trading-day window for cross-contract roll observation.",
            ),
        ] = 5,
    ) -> None:
        """Build R74 chain OI and roll decomposition research."""
        from cotton_factor.research_workbench import build_cf_chain_oi_structure

        try:
            result = build_cf_chain_oi_structure(
                core_quote_path=core_quote_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                noise_ratio=noise_ratio,
                roll_transfer_threshold=roll_transfer_threshold,
                roll_lookback_days=roll_lookback_days,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-delivery-adjusted-curve")
    def research_build_cf_delivery_adjusted_curve(
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional CF core quote path."),
        ] = None,
        near_contract: Annotated[
            str,
            typer.Option("--near-contract", help="Near delivery contract."),
        ] = "CF609",
        far_contract: Annotated[
            str,
            typer.Option("--far-contract", help="Far delivery contract."),
        ] = "CF611",
        start: Annotated[
            str | None,
            typer.Option("--start", help="Scenario-known start date."),
        ] = "2026-01-09",
        end: Annotated[
            str | None,
            typer.Option("--end", help="Optional research cutoff date."),
        ] = None,
        aging_discount: Annotated[
            float,
            typer.Option("--aging-discount", help="Aging discount scenario, CNY/ton."),
        ] = 248.0,
        storage_cost_per_ton_day: Annotated[
            float,
            typer.Option(
                "--storage-cost-per-ton-day",
                help="Daily storage cost scenario, CNY/ton.",
            ),
        ] = 48.07 / 62.0,
        annual_financing_rate: Annotated[
            float,
            typer.Option("--annual-financing-rate", help="Annual financing rate."),
        ] = 0.025,
        holding_days: Annotated[
            int,
            typer.Option("--holding-days", help="Calendar days in carry scenario."),
        ] = 62,
        near_zero_band: Annotated[
            float,
            typer.Option("--near-zero-band", help="Residual neutral band, CNY/ton."),
        ] = 20.0,
        min_history_days: Annotated[
            int,
            typer.Option("--min-history-days", help="Minimum descriptive history."),
        ] = 30,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Report output directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable run id."),
        ] = None,
    ) -> None:
        """Build a CF delivery-cost-adjusted calendar-spread study."""
        from cotton_factor.research_workbench import build_cf_delivery_adjusted_curve

        try:
            result = build_cf_delivery_adjusted_curve(
                core_quote_path=core_quote_path,
                near_contract=near_contract,
                far_contract=far_contract,
                start=None if start is None else _parse_iso_date(start),
                end=None if end is None else _parse_iso_date(end),
                aging_discount=aging_discount,
                storage_cost_per_ton_day=storage_cost_per_ton_day,
                annual_financing_rate=annual_financing_rate,
                holding_days=holding_days,
                near_zero_band=near_zero_band,
                min_history_days=min_history_days,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-structural-position-attribution")
    def research_build_cf_structural_position_attribution(
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional CF core quote path."),
        ] = None,
        member_detail_path: Annotated[
            Path | None,
            typer.Option("--member-detail-path", help="Optional normalized member detail."),
        ] = None,
        warehouse_receipt_path: Annotated[
            Path | None,
            typer.Option(
                "--warehouse-receipt-path",
                help="Optional normalized aggregate warehouse-receipt table.",
            ),
        ] = None,
        option_strike_position_path: Annotated[
            Path | None,
            typer.Option(
                "--option-strike-position-path",
                help="Optional normalized option strike-position table.",
            ),
        ] = None,
        option_factor_path: Annotated[
            Path | None,
            typer.Option("--option-factor-path", help="Optional option factor table."),
        ] = None,
        delivery_adjusted_curve_path: Annotated[
            Path | None,
            typer.Option(
                "--delivery-adjusted-curve-path",
                help="Optional delivery-adjusted curve daily table.",
            ),
        ] = None,
        target_contract: Annotated[
            str,
            typer.Option("--target-contract", help="Target contract under study."),
        ] = "CF611",
        source_contract: Annotated[
            str,
            typer.Option("--source-contract", help="Source roll contract."),
        ] = "CF609",
        next_contract: Annotated[
            str,
            typer.Option("--next-contract", help="Next crop-year contract."),
        ] = "CF701",
        focus_start: Annotated[
            str | None,
            typer.Option("--focus-start", help="Focus-window start date."),
        ] = "2026-05-15",
        focus_end: Annotated[
            str | None,
            typer.Option("--focus-end", help="Optional focus-window end date."),
        ] = None,
        option_horizons: Annotated[
            str,
            typer.Option("--option-horizons", help="Comma-separated T+1 horizons."),
        ] = "1,3,5,10",
        wall_distance: Annotated[
            float,
            typer.Option("--wall-distance", help="Near-wall distance ratio."),
        ] = 0.01,
        option_oi_noise_ratio: Annotated[
            float,
            typer.Option("--option-oi-noise-ratio", help="Material option OI ratio."),
        ] = 0.005,
        contract_tons: Annotated[
            float,
            typer.Option("--contract-tons", help="Tons per futures lot."),
        ] = 5.0,
        receipt_tons: Annotated[
            float,
            typer.Option("--receipt-tons", help="Tons per warehouse receipt."),
        ] = 40.0,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Report output directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable run id."),
        ] = None,
    ) -> None:
        """Build layered CF611 futures/member/receipt/option attribution."""
        from cotton_factor.research_workbench import (
            build_cf_structural_position_attribution,
        )

        try:
            horizons = tuple(
                int(value.strip())
                for value in option_horizons.split(",")
                if value.strip()
            )
            result = build_cf_structural_position_attribution(
                core_quote_path=core_quote_path,
                member_detail_path=member_detail_path,
                warehouse_receipt_path=warehouse_receipt_path,
                option_strike_position_path=option_strike_position_path,
                option_factor_path=option_factor_path,
                delivery_adjusted_curve_path=delivery_adjusted_curve_path,
                target_contract=target_contract,
                source_contract=source_contract,
                next_contract=next_contract,
                focus_start=(
                    None if focus_start is None else _parse_iso_date(focus_start)
                ),
                focus_end=None if focus_end is None else _parse_iso_date(focus_end),
                option_horizons=horizons,
                wall_distance=wall_distance,
                option_oi_noise_ratio=option_oi_noise_ratio,
                contract_tons=contract_tons,
                receipt_tons=receipt_tons,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except (CottonFactorError, ValueError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-option-structure-research")
    def research_build_cf_option_structure_research(
        option_factor_path: Annotated[
            Path | None,
            typer.Option("--option-factor-path", help="Optional R48 option factor path."),
        ] = None,
        signal_matrix_path: Annotated[
            Path | None,
            typer.Option("--signal-matrix-path", help="Optional R35 signal matrix path."),
        ] = None,
        validation_daily_path: Annotated[
            Path | None,
            typer.Option("--validation-daily-path", help="Optional R36 validation path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R75 data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R75 report output directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R75 run id."),
        ] = None,
        primary_horizon: Annotated[
            int,
            typer.Option("--primary-horizon", help="Futures direction reference horizon."),
        ] = 20,
    ) -> None:
        """Build R75 dynamic option structure and posterior validation."""
        from cotton_factor.research_workbench import build_cf_option_structure_research

        try:
            result = build_cf_option_structure_research(
                option_factor_path=option_factor_path,
                signal_matrix_path=signal_matrix_path,
                validation_daily_path=validation_daily_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                primary_horizon=primary_horizon,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-oi-roll-window-research")
    def research_build_cf_oi_roll_window_research(
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional CF core quote path."),
        ] = None,
        validation_daily_path: Annotated[
            Path | None,
            typer.Option(
                "--validation-daily-path",
                help="Optional R36 historical validation path.",
            ),
        ] = None,
        exclusion_path: Annotated[
            Path | None,
            typer.Option("--exclusion-path", help="Optional resolved/manual date CSV."),
        ] = None,
        end: Annotated[
            str | None,
            typer.Option("--end", help="Optional research cutoff date."),
        ] = None,
        windows: Annotated[
            str,
            typer.Option("--windows", help="Comma-separated OI roll windows."),
        ] = "3,5,10",
        min_sample_size: Annotated[
            int,
            typer.Option("--min-sample-size", help="Minimum evidence sample size."),
        ] = 30,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R78 data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R78 report output directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R78 run id."),
        ] = None,
    ) -> None:
        """Build R78 multi-window OI roll evidence research."""
        from cotton_factor.research_workbench import build_cf_oi_roll_window_research

        try:
            parsed_windows = tuple(
                int(value.strip()) for value in windows.split(",") if value.strip()
            )
            parsed_end = None if end is None else date.fromisoformat(end)
            result = build_cf_oi_roll_window_research(
                core_quote_path=core_quote_path,
                validation_daily_path=validation_daily_path,
                exclusion_path=exclusion_path,
                end=parsed_end,
                windows=parsed_windows,
                min_sample_size=min_sample_size,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except (CottonFactorError, ValueError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-trend-phase-v2")
    def research_build_cf_trend_phase_v2(
        dual_price_path: Annotated[
            Path | None,
            typer.Option("--dual-price-path", help="Optional R73 daily path."),
        ] = None,
        chain_oi_path: Annotated[
            Path | None,
            typer.Option("--chain-oi-path", help="Optional R74 daily path."),
        ] = None,
        option_structure_path: Annotated[
            Path | None,
            typer.Option("--option-structure-path", help="Optional R75 daily path."),
        ] = None,
        signal_matrix_path: Annotated[
            Path | None,
            typer.Option("--signal-matrix-path", help="Optional R35 signal matrix path."),
        ] = None,
        validation_daily_path: Annotated[
            Path | None,
            typer.Option("--validation-daily-path", help="Optional R36 validation path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R76 data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R76 report output directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R76 run id."),
        ] = None,
        primary_horizon: Annotated[
            int,
            typer.Option("--primary-horizon", help="Primary signal-matrix horizon."),
        ] = 20,
    ) -> None:
        """Build R76 evidence-aware trend phase v2."""
        from cotton_factor.research_workbench import build_cf_trend_phase_v2

        try:
            result = build_cf_trend_phase_v2(
                dual_price_path=dual_price_path,
                chain_oi_path=chain_oi_path,
                option_structure_path=option_structure_path,
                signal_matrix_path=signal_matrix_path,
                validation_daily_path=validation_daily_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                primary_horizon=primary_horizon,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-symmetric-trend-research")
    def research_build_cf_symmetric_trend_research(
        continuous_price_path: Annotated[
            Path | None,
            typer.Option("--continuous-price-path", help="Optional R86 continuous price path."),
        ] = None,
        trend_context_path: Annotated[
            Path | None,
            typer.Option("--trend-context-path", help="Optional R76 trend context path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R93A data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R93A report output directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R93A run id."),
        ] = None,
        fast_window: Annotated[
            int,
            typer.Option("--fast-window", help="Fast trend window."),
        ] = 20,
        slow_window: Annotated[
            int,
            typer.Option("--slow-window", help="Slow trend window."),
        ] = 40,
        breakout_window: Annotated[
            int,
            typer.Option("--breakout-window", help="Prior channel breakout window."),
        ] = 20,
        breakout_cooldown: Annotated[
            int,
            typer.Option("--breakout-cooldown", help="Same-side breakout cooldown."),
        ] = 5,
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Comma-separated posterior horizons."),
        ] = "1,3,5,10,20",
        dead_zone_bps: Annotated[
            int,
            typer.Option("--dead-zone-bps", help="Historical outcome dead zone in bps."),
        ] = 10,
        min_sample_size: Annotated[
            int,
            typer.Option("--min-sample-size", help="Minimum evidence-group sample size."),
        ] = 30,
    ) -> None:
        """Build R93A symmetric trend, breakout and option-timing evidence."""
        from cotton_factor.research_workbench import build_cf_symmetric_trend_research

        try:
            result = build_cf_symmetric_trend_research(
                continuous_price_path=continuous_price_path,
                trend_context_path=trend_context_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                fast_window=fast_window,
                slow_window=slow_window,
                breakout_window=breakout_window,
                breakout_cooldown=breakout_cooldown,
                horizons=_parse_horizons(horizons),
                dead_zone_bps=dead_zone_bps,
                min_sample_size=min_sample_size,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-trend-option-timing-research")
    def research_build_cf_trend_option_timing_research(
        symmetric_trend_daily_path: Annotated[
            Path | None,
            typer.Option(
                "--symmetric-trend-daily-path",
                help="Optional R93A symmetric trend daily path.",
            ),
        ] = None,
        breakout_event_path: Annotated[
            Path | None,
            typer.Option(
                "--breakout-event-path",
                help="Optional R93A breakout event path.",
            ),
        ] = None,
        option_structure_path: Annotated[
            Path | None,
            typer.Option(
                "--option-structure-path",
                help="Optional R75 option structure path.",
            ),
        ] = None,
        strike_position_path: Annotated[
            Path | None,
            typer.Option(
                "--strike-position-path",
                help="Optional R84 strike-position path.",
            ),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R93B data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option(
                "--report-output-dir",
                help="R93B report output directory.",
            ),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R93B run id."),
        ] = None,
        rank_window: Annotated[
            int,
            typer.Option("--rank-window", help="Rolling percentile-rank window."),
        ] = 252,
        rank_min_periods: Annotated[
            int,
            typer.Option(
                "--rank-min-periods",
                help="Minimum observations for rolling ranks.",
            ),
        ] = 60,
        min_sample_size: Annotated[
            int,
            typer.Option(
                "--min-sample-size",
                help="Minimum independent episodes for a candidate group.",
            ),
        ] = 30,
        fdr_level: Annotated[
            float,
            typer.Option("--fdr-level", help="Benjamini-Hochberg FDR level."),
        ] = 0.10,
    ) -> None:
        """Build R93B trend-environment and option-timing incremental evidence."""
        from cotton_factor.research_workbench import (
            build_cf_trend_option_timing_research,
        )

        try:
            result = build_cf_trend_option_timing_research(
                symmetric_trend_daily_path=symmetric_trend_daily_path,
                breakout_event_path=breakout_event_path,
                option_structure_path=option_structure_path,
                strike_position_path=strike_position_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                rank_window=rank_window,
                rank_min_periods=rank_min_periods,
                min_sample_size=min_sample_size,
                fdr_level=fdr_level,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-trend-confirmation-timing-research")
    def research_build_cf_trend_confirmation_timing_research(
        symmetric_trend_daily_path: Annotated[
            Path | None,
            typer.Option(
                "--symmetric-trend-daily-path",
                help="Optional R93A symmetric-trend daily path.",
            ),
        ] = None,
        breakout_event_path: Annotated[
            Path | None,
            typer.Option(
                "--breakout-event-path",
                help="Optional R93A breakout-event path.",
            ),
        ] = None,
        chain_oi_path: Annotated[
            Path | None,
            typer.Option("--chain-oi-path", help="Optional R74 chain-OI daily path."),
        ] = None,
        option_structure_path: Annotated[
            Path | None,
            typer.Option(
                "--option-structure-path",
                help="Optional R75 option-structure daily path.",
            ),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R93L data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option(
                "--report-output-dir",
                help="R93L report output directory.",
            ),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R93L run id."),
        ] = None,
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Posterior horizons, comma separated."),
        ] = "5,20",
        pre_window_sessions: Annotated[
            int,
            typer.Option("--pre-window-sessions", help="Sessions before breakout."),
        ] = 10,
        post_window_sessions: Annotated[
            int,
            typer.Option("--post-window-sessions", help="Sessions after breakout."),
        ] = 20,
        confirmation_days: Annotated[
            int,
            typer.Option("--confirmation-days", help="Consecutive confirmation days."),
        ] = 2,
        min_sample_size: Annotated[
            int,
            typer.Option("--min-sample-size", help="Minimum episode-level sample size."),
        ] = 15,
        fdr_level: Annotated[
            float,
            typer.Option("--fdr-level", help="Benjamini-Hochberg FDR level."),
        ] = 0.10,
        min_annual_coverage_years: Annotated[
            int,
            typer.Option(
                "--min-annual-coverage-years",
                help="Minimum eligible years for a research candidate.",
            ),
        ] = 3,
        min_annual_group_size: Annotated[
            int,
            typer.Option(
                "--min-annual-group-size",
                help="Minimum state and control episodes per eligible year.",
            ),
        ] = 2,
        min_annual_direction_consistency: Annotated[
            float,
            typer.Option(
                "--min-annual-direction-consistency",
                help="Minimum aligned-year ratio for a research candidate.",
            ),
        ] = 0.75,
        volume_rank_window: Annotated[
            int,
            typer.Option("--volume-rank-window", help="Chain-volume rank window."),
        ] = 252,
        volume_rank_min_periods: Annotated[
            int,
            typer.Option(
                "--volume-rank-min-periods",
                help="Minimum observations for chain-volume rank.",
            ),
        ] = 60,
        min_option_liquidity_score: Annotated[
            float,
            typer.Option(
                "--min-option-liquidity-score",
                help="Minimum R75 option-liquidity score.",
            ),
        ] = 20.0,
        dead_zone_bps: Annotated[
            int,
            typer.Option(
                "--dead-zone-bps",
                help="Posterior return dead zone in basis points.",
            ),
        ] = 10,
    ) -> None:
        """Build R93L futures/option trend-confirmation timing evidence."""
        from cotton_factor.research_workbench import (
            build_cf_trend_confirmation_timing_research,
        )

        try:
            result = build_cf_trend_confirmation_timing_research(
                symmetric_trend_daily_path=symmetric_trend_daily_path,
                breakout_event_path=breakout_event_path,
                chain_oi_path=chain_oi_path,
                option_structure_path=option_structure_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                horizons=_parse_horizons(horizons),
                pre_window_sessions=pre_window_sessions,
                post_window_sessions=post_window_sessions,
                confirmation_days=confirmation_days,
                min_sample_size=min_sample_size,
                fdr_level=fdr_level,
                min_annual_coverage_years=min_annual_coverage_years,
                min_annual_group_size=min_annual_group_size,
                min_annual_direction_consistency=min_annual_direction_consistency,
                volume_rank_window=volume_rank_window,
                volume_rank_min_periods=volume_rank_min_periods,
                min_option_liquidity_score=min_option_liquidity_score,
                dead_zone_bps=dead_zone_bps,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-option-maturity-confirmation-research")
    def research_build_cf_option_maturity_confirmation_research(
        option_core_path: Annotated[
            Path | None,
            typer.Option("--option-core-path", help="Optional CF option core path."),
        ] = None,
        trend_confirmation_event_path: Annotated[
            Path | None,
            typer.Option(
                "--trend-confirmation-event-path",
                help="Optional R93L event-index path.",
            ),
        ] = None,
        trend_confirmation_trajectory_path: Annotated[
            Path | None,
            typer.Option(
                "--trend-confirmation-trajectory-path",
                help="Optional R93L trajectory path.",
            ),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R93M data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R93M report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R93M run id."),
        ] = None,
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Posterior horizons, comma separated."),
        ] = "5,20",
        checkpoints: Annotated[
            str,
            typer.Option("--checkpoints", help="As-of checkpoints, comma separated."),
        ] = "0,1,3,5,10",
        confirmation_days: Annotated[
            int,
            typer.Option("--confirmation-days", help="Consecutive confirmation days."),
        ] = 2,
        activity_window: Annotated[
            int,
            typer.Option("--activity-window", help="Trailing activity window."),
        ] = 60,
        activity_min_periods: Annotated[
            int,
            typer.Option(
                "--activity-min-periods",
                help="Minimum observations for activity state.",
            ),
        ] = 20,
        baseline_year: Annotated[
            int,
            typer.Option("--baseline-year", help="Frozen option-activity baseline year."),
        ] = 2021,
        expansion_volume_ratio: Annotated[
            float,
            typer.Option(
                "--expansion-volume-ratio",
                help="Expansion volume ratio versus baseline.",
            ),
        ] = 1.50,
        expansion_oi_ratio: Annotated[
            float,
            typer.Option(
                "--expansion-oi-ratio",
                help="Expansion OI ratio versus baseline.",
            ),
        ] = 1.25,
        mature_volume_ratio: Annotated[
            float,
            typer.Option(
                "--mature-volume-ratio",
                help="Mature volume ratio versus baseline.",
            ),
        ] = 3.00,
        mature_oi_ratio: Annotated[
            float,
            typer.Option(
                "--mature-oi-ratio",
                help="Mature OI ratio versus baseline.",
            ),
        ] = 2.50,
        min_sample_size: Annotated[
            int,
            typer.Option("--min-sample-size", help="Minimum samples in both groups."),
        ] = 5,
        fdr_level: Annotated[
            float,
            typer.Option("--fdr-level", help="Benjamini-Hochberg FDR level."),
        ] = 0.10,
        dead_zone_bps: Annotated[
            int,
            typer.Option("--dead-zone-bps", help="Posterior return dead zone in bps."),
        ] = 10,
    ) -> None:
        """Build R93M option-maturity and as-of confirmation evidence."""
        from cotton_factor.research_workbench import (
            build_cf_option_maturity_confirmation_research,
        )

        try:
            result = build_cf_option_maturity_confirmation_research(
                option_core_path=option_core_path,
                trend_confirmation_event_path=trend_confirmation_event_path,
                trend_confirmation_trajectory_path=(
                    trend_confirmation_trajectory_path
                ),
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                horizons=_parse_horizons(horizons),
                checkpoints=_parse_non_negative_ints(checkpoints),
                confirmation_days=confirmation_days,
                activity_window=activity_window,
                activity_min_periods=activity_min_periods,
                baseline_year=baseline_year,
                expansion_volume_ratio=expansion_volume_ratio,
                expansion_oi_ratio=expansion_oi_ratio,
                mature_volume_ratio=mature_volume_ratio,
                mature_oi_ratio=mature_oi_ratio,
                min_sample_size=min_sample_size,
                fdr_level=fdr_level,
                dead_zone_bps=dead_zone_bps,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-rebound-lifecycle")
    def research_build_cf_rebound_lifecycle(
        signal_matrix_path: Annotated[
            Path | None,
            typer.Option("--signal-matrix-path", help="Optional R35 signal matrix path."),
        ] = None,
        symmetric_trend_daily_path: Annotated[
            Path | None,
            typer.Option(
                "--symmetric-trend-daily-path",
                help="Optional R93A symmetric trend daily path.",
            ),
        ] = None,
        option_structure_path: Annotated[
            Path | None,
            typer.Option(
                "--option-structure-path",
                help="Optional R75 option structure daily path.",
            ),
        ] = None,
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Posterior horizons, comma separated."),
        ] = "1,3,5,10,20",
        prepare_max_days: Annotated[
            int,
            typer.Option("--prepare-max-days", help="Maximum PREPARE trading days."),
        ] = 7,
        confirm_max_days: Annotated[
            int,
            typer.Option("--confirm-max-days", help="Maximum TRIGGER-to-CONFIRM days."),
        ] = 3,
        follow_max_days: Annotated[
            int,
            typer.Option("--follow-max-days", help="Confirmed follow-through window."),
        ] = 10,
        break_buffer_bps: Annotated[
            int,
            typer.Option("--break-buffer-bps", help="Setup-low failure buffer in bps."),
        ] = 10,
        min_sample_size: Annotated[
            int,
            typer.Option("--min-sample-size", help="Minimum triggered episode sample."),
        ] = 30,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R93I data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R93I report output directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R93I run id."),
        ] = None,
    ) -> None:
        """Build R93I rebound PREPARE/TRIGGER/CONFIRM/FAIL lifecycle evidence."""
        from cotton_factor.research_workbench import (
            build_cf_rebound_lifecycle_research,
        )

        try:
            result = build_cf_rebound_lifecycle_research(
                signal_matrix_path=signal_matrix_path,
                symmetric_trend_daily_path=symmetric_trend_daily_path,
                option_structure_path=option_structure_path,
                horizons=_parse_horizons(horizons),
                prepare_max_days=prepare_max_days,
                confirm_max_days=confirm_max_days,
                follow_max_days=follow_max_days,
                break_buffer_bps=break_buffer_bps,
                min_sample_size=min_sample_size,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-trend-candidate-stability-research")
    def research_build_cf_trend_candidate_stability_research(
        event_feature_path: Annotated[
            Path | None,
            typer.Option(
                "--event-feature-path",
                help="Optional R93B independent event-feature path.",
            ),
        ] = None,
        spec_path: Annotated[
            Path | None,
            typer.Option("--spec-path", help="Optional frozen R93C spec path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R93C data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option(
                "--report-output-dir",
                help="R93C report output directory.",
            ),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R93C run id."),
        ] = None,
    ) -> None:
        """Build R93C candidate ablation, stability and forward registration."""
        from cotton_factor.research_workbench import (
            build_cf_trend_candidate_stability_research,
        )

        try:
            result = build_cf_trend_candidate_stability_research(
                event_feature_path=event_feature_path,
                spec_path=spec_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-trend-candidate-forward-ledger")
    def research_build_cf_trend_candidate_forward_ledger(
        symmetric_trend_daily_path: Annotated[
            Path | None,
            typer.Option(
                "--symmetric-trend-daily-path",
                help="Optional R93A symmetric daily path.",
            ),
        ] = None,
        breakout_event_path: Annotated[
            Path | None,
            typer.Option(
                "--breakout-event-path",
                help="Optional R93A breakout event path.",
            ),
        ] = None,
        candidate_evaluation_path: Annotated[
            Path | None,
            typer.Option(
                "--candidate-evaluation-path",
                help="Optional R93C primary evaluation path.",
            ),
        ] = None,
        spec_path: Annotated[
            Path | None,
            typer.Option("--spec-path", help="Optional frozen R93C spec path."),
        ] = None,
        as_of_date: Annotated[
            str | None,
            typer.Option("--as-of-date", help="Optional official session date."),
        ] = None,
        ledger_root: Annotated[
            Path | None,
            typer.Option("--ledger-root", help="R93D immutable ledger root."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option(
                "--report-output-dir",
                help="R93D report output directory.",
            ),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R93D run id."),
        ] = None,
        correction_reason: Annotated[
            str | None,
            typer.Option(
                "--correction-reason",
                help="Required only when a recorded outcome changes.",
            ),
        ] = None,
    ) -> None:
        """Build R93D capture-first immutable forward evidence ledger."""
        from cotton_factor.research_workbench import (
            build_cf_trend_candidate_forward_ledger,
        )

        try:
            result = build_cf_trend_candidate_forward_ledger(
                symmetric_trend_daily_path=symmetric_trend_daily_path,
                breakout_event_path=breakout_event_path,
                candidate_evaluation_path=candidate_evaluation_path,
                spec_path=spec_path,
                as_of_date=(
                    _parse_iso_date(as_of_date) if as_of_date is not None else None
                ),
                ledger_root=ledger_root,
                report_output_dir=report_output_dir,
                run_id=run_id,
                correction_reason=correction_reason,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-forward-evidence-weekly")
    def research_build_cf_forward_evidence_weekly(
        as_of_date: Annotated[
            str | None,
            typer.Option("--date", help="Optional weekly evidence as-of date."),
        ] = None,
        strategy_ledger_root: Annotated[
            Path | None,
            typer.Option(
                "--strategy-ledger-root",
                help="Optional R90 shadow ledger directory.",
            ),
        ] = None,
        candidate_ledger_path: Annotated[
            Path | None,
            typer.Option(
                "--candidate-ledger-path",
                help="Optional R93D materialized candidate ledger.",
            ),
        ] = None,
        candidate_event_root: Annotated[
            Path | None,
            typer.Option(
                "--candidate-event-root",
                help="Optional R93D immutable event directory.",
            ),
        ] = None,
        candidate_run_json_path: Annotated[
            Path | None,
            typer.Option(
                "--candidate-run-json-path",
                help="Optional current R93D run JSON used for freshness checks.",
            ),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R93E data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option(
                "--report-output-dir",
                help="R93E report output directory.",
            ),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R93E run id."),
        ] = None,
    ) -> None:
        """Build R93E weekly strategy/candidate forward evidence summary."""
        from cotton_factor.research_workbench import build_cf_forward_evidence_weekly

        try:
            result = build_cf_forward_evidence_weekly(
                as_of_date=(
                    _parse_iso_date(as_of_date) if as_of_date is not None else None
                ),
                strategy_ledger_root=strategy_ledger_root,
                candidate_ledger_path=candidate_ledger_path,
                candidate_event_root=candidate_event_root,
                candidate_run_json_path=candidate_run_json_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-current-watch-window")
    def research_build_cf_current_watch_window(
        latest_signal_json_path: Annotated[
            Path | None,
            typer.Option("--latest-signal-json-path", help="Optional latest signal JSON."),
        ] = None,
        dual_price_path: Annotated[
            Path | None,
            typer.Option("--dual-price-path", help="Optional R73 daily path."),
        ] = None,
        chain_oi_path: Annotated[
            Path | None,
            typer.Option("--chain-oi-path", help="Optional R74 daily path."),
        ] = None,
        option_structure_path: Annotated[
            Path | None,
            typer.Option("--option-structure-path", help="Optional R75 daily path."),
        ] = None,
        trend_phase_v2_path: Annotated[
            Path | None,
            typer.Option("--trend-phase-v2-path", help="Optional R76 daily path."),
        ] = None,
        playbook_json_path: Annotated[
            Path | None,
            typer.Option("--playbook-json-path", help="Optional R71 playbook JSON."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional CF core quote path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R77 data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R77 report output directory."),
        ] = None,
        daily_output_root: Annotated[
            Path | None,
            typer.Option("--daily-output-root", help="Optional runs/daily sync root."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R77 run id."),
        ] = None,
    ) -> None:
        """Build R77 current confirmation/invalidation watch window."""
        from cotton_factor.research_workbench import build_cf_current_watch_window

        try:
            result = build_cf_current_watch_window(
                latest_signal_json_path=latest_signal_json_path,
                dual_price_path=dual_price_path,
                chain_oi_path=chain_oi_path,
                option_structure_path=option_structure_path,
                trend_phase_v2_path=trend_phase_v2_path,
                playbook_json_path=playbook_json_path,
                core_quote_path=core_quote_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                daily_output_root=daily_output_root,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("fetch-cf-official-daily-files")
    def research_fetch_cf_official_daily_files(
        trade_date: Annotated[
            str | None,
            typer.Option("--date", help="Official daily file date in YYYY-MM-DD format."),
        ] = None,
        futures_source_dir: Annotated[
            Path | None,
            typer.Option("--futures-source-dir", help="CF futures incoming history root."),
        ] = None,
        options_source_dir: Annotated[
            Path | None,
            typer.Option("--options-source-dir", help="CF option incoming history root."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Daily fetch report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable daily fetch run id."),
        ] = None,
        include_options: Annotated[
            bool,
            typer.Option(
                "--include-options/--skip-options",
                help="Fetch the official all-product option daily file.",
            ),
        ] = True,
        overwrite: Annotated[
            bool,
            typer.Option("--overwrite/--no-overwrite", help="Overwrite existing incoming files."),
        ] = False,
        futures_url: Annotated[
            str | None,
            typer.Option("--futures-url", help="Override the official futures daily URL."),
        ] = None,
        options_url: Annotated[
            str | None,
            typer.Option("--options-url", help="Override the official options daily URL."),
        ] = None,
    ) -> None:
        """Fetch CF official futures/options daily files into incoming storage."""
        from cotton_factor.research_workbench import fetch_cf_official_daily_files

        try:
            result = fetch_cf_official_daily_files(
                trade_date=_parse_iso_date(trade_date) if trade_date else None,
                futures_source_dir=futures_source_dir,
                options_source_dir=options_source_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                include_options=include_options,
                overwrite=overwrite,
                futures_url=futures_url,
                options_url=options_url,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
        if not result.passed:
            raise typer.Exit(1)

    @research_app.command("build-cf-option-strike-position-research")
    def research_build_cf_option_strike_position_research(
        option_core_path: Annotated[
            Path | None,
            typer.Option("--option-core-path", help="Optional CF option core parquet."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional CF futures core parquet."),
        ] = None,
        option_expiry_path: Annotated[
            Path | None,
            typer.Option("--option-expiry-path", help="Optional R81 expiry registry."),
        ] = None,
        end: Annotated[
            str | None,
            typer.Option("--end", help="Optional inclusive end date."),
        ] = None,
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Historical path horizons."),
        ] = "1,3,5,10",
        near_level_ratio: Annotated[
            float,
            typer.Option("--near-level-ratio", help="Distance defining near-key-level."),
        ] = 0.01,
        min_sample_size: Annotated[
            int,
            typer.Option("--min-sample-size", help="Minimum WATCH sample size."),
        ] = 30,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Optional R84 data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional R84 report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R84 run id."),
        ] = None,
    ) -> None:
        """Build CF option strike OI key levels, migration and posterior paths."""
        from cotton_factor.research_workbench import (
            build_cf_option_strike_position_research,
        )

        try:
            result = build_cf_option_strike_position_research(
                option_core_path=option_core_path,
                core_quote_path=core_quote_path,
                option_expiry_path=option_expiry_path,
                end=_parse_iso_date(end) if end else None,
                horizons=_parse_horizons(horizons),
                near_level_ratio=near_level_ratio,
                min_sample_size=min_sample_size,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("fetch-cf-official-member-position")
    def research_fetch_cf_official_member_position(
        trade_date: Annotated[
            str,
            typer.Option("--date", help="Official trade date in YYYY-MM-DD format."),
        ],
        source_dir: Annotated[
            Path | None,
            typer.Option("--source-dir", help="Optional member-position incoming root."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional R83 fetch report directory."),
        ] = None,
        overwrite: Annotated[
            bool,
            typer.Option("--overwrite", help="Replace an existing daily holding file."),
        ] = False,
        official_url: Annotated[
            str | None,
            typer.Option("--official-url", help="Optional reviewed official URL override."),
        ] = None,
    ) -> None:
        """Download one official CF member-position ranking workbook."""
        from cotton_factor.research_workbench import fetch_cf_official_member_position

        try:
            result = fetch_cf_official_member_position(
                trade_date=_parse_iso_date(trade_date),
                source_dir=source_dir,
                report_output_dir=report_output_dir,
                overwrite=overwrite,
                official_url=official_url,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
        if not result.passed:
            raise typer.Exit(1)

    @research_app.command("fetch-cf-official-member-position-history")
    def research_fetch_cf_official_member_position_history(
        start: Annotated[
            str,
            typer.Option("--start", help="Inclusive backfill start date."),
        ],
        end: Annotated[
            str,
            typer.Option("--end", help="Inclusive backfill end date."),
        ],
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional CF core quote parquet."),
        ] = None,
        source_dir: Annotated[
            Path | None,
            typer.Option("--source-dir", help="Optional member-position incoming root."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional R85 backfill report directory."),
        ] = None,
        overwrite: Annotated[
            bool,
            typer.Option("--overwrite", help="Replace existing daily holding files."),
        ] = False,
        max_workers: Annotated[
            int,
            typer.Option("--max-workers", help="Concurrent trade-date downloads, 1 to 8."),
        ] = 4,
    ) -> None:
        """Incrementally backfill official CF member-position history."""
        from cotton_factor.research_workbench import (
            fetch_cf_official_member_position_history,
        )

        try:
            result = fetch_cf_official_member_position_history(
                start=_parse_iso_date(start),
                end=_parse_iso_date(end),
                core_quote_path=core_quote_path,
                source_dir=source_dir,
                report_output_dir=report_output_dir,
                overwrite=overwrite,
                max_workers=max_workers,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
        if not result.passed:
            raise typer.Exit(1)

    @research_app.command("connect-cf-member-position-history")
    def research_connect_cf_member_position_history(
        source_dir: Annotated[
            Path | None,
            typer.Option("--source-dir", help="Optional member-position incoming root."),
        ] = None,
        raw_root: Annotated[
            Path | None,
            typer.Option("--raw-root", help="Optional raw snapshot root."),
        ] = None,
        core_output_dir: Annotated[
            Path | None,
            typer.Option("--core-output-dir", help="Optional core output directory."),
        ] = None,
        output_path: Annotated[
            Path | None,
            typer.Option("--output-path", help="Optional member-position core parquet."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional R83 ingest report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R83 ingest run id."),
        ] = None,
    ) -> None:
        """Preserve official member-position files and normalize CF rows into core."""
        from cotton_factor.research_workbench import connect_cf_member_position_history

        try:
            result = connect_cf_member_position_history(
                source_dir=source_dir,
                raw_root=raw_root,
                core_output_dir=core_output_dir,
                output_path=output_path,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
        if not result.passed:
            raise typer.Exit(1)

    @research_app.command("build-cf-member-position-research")
    def research_build_cf_member_position_research(
        member_position_path: Annotated[
            Path | None,
            typer.Option("--member-position-path", help="Optional R83 member core parquet."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional CF core quote parquet."),
        ] = None,
        validation_daily_path: Annotated[
            Path | None,
            typer.Option("--validation-daily-path", help="Optional R36 validation parquet."),
        ] = None,
        end: Annotated[
            str | None,
            typer.Option("--end", help="Optional inclusive research end date."),
        ] = None,
        top_ns: Annotated[
            str,
            typer.Option("--top-ns", help="Ranking cutoffs, for example 5,10,20."),
        ] = "5,10,20",
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Posterior validation horizons."),
        ] = "1,3,5,10,20",
        position_change_dead_zone: Annotated[
            float,
            typer.Option("--position-change-dead-zone", help="OI-scaled flow dead zone."),
        ] = 0.002,
        price_dead_zone: Annotated[
            float,
            typer.Option("--price-dead-zone", help="Settlement-return dead zone."),
        ] = 0.001,
        min_sample_size: Annotated[
            int,
            typer.Option("--min-sample-size", help="Minimum WATCH sample size."),
        ] = 30,
        min_history_days: Annotated[
            int,
            typer.Option("--min-history-days", help="Minimum historical coverage warning gate."),
        ] = 60,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Optional R83 data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional R83 report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R83 research run id."),
        ] = None,
    ) -> None:
        """Build CF member concentration, flow, divergence and roll evidence."""
        from cotton_factor.research_workbench import build_cf_member_position_research

        try:
            result = build_cf_member_position_research(
                member_position_path=member_position_path,
                core_quote_path=core_quote_path,
                validation_daily_path=validation_daily_path,
                end=_parse_iso_date(end) if end else None,
                top_ns=_parse_horizons(top_ns),
                horizons=_parse_horizons(horizons),
                position_change_dead_zone=position_change_dead_zone,
                price_dead_zone=price_dead_zone,
                min_sample_size=min_sample_size,
                min_history_days=min_history_days,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-option-data-contract")
    def research_build_cf_option_data_contract(
        source_dir: Annotated[
            Path | None,
            typer.Option("--source-dir", help="Optional CF option incoming history dir."),
        ] = None,
        core_output_dir: Annotated[
            Path | None,
            typer.Option("--core-output-dir", help="Optional core output root."),
        ] = None,
        output_path: Annotated[
            Path | None,
            typer.Option("--output-path", help="Optional core option parquet path."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional R46 report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R46 run id."),
        ] = None,
    ) -> None:
        """Build R46 CF option data contract and incoming-path warning artifacts."""
        from cotton_factor.research_workbench import build_cf_option_data_contract

        try:
            result = build_cf_option_data_contract(
                source_dir=source_dir,
                core_output_dir=core_output_dir,
                output_path=output_path,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("connect-cf-option-history")
    def research_connect_cf_option_history(
        source_dir: Annotated[
            Path | None,
            typer.Option("--source-dir", help="Optional CF option incoming history dir."),
        ] = None,
        raw_root: Annotated[
            Path | None,
            typer.Option("--raw-root", help="Optional raw snapshot root."),
        ] = None,
        core_output_dir: Annotated[
            Path | None,
            typer.Option("--core-output-dir", help="Optional core output root."),
        ] = None,
        output_path: Annotated[
            Path | None,
            typer.Option("--output-path", help="Optional core option parquet path."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional futures core quote path."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional R47 report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R47 run id."),
        ] = None,
        low_volume_threshold: Annotated[
            int,
            typer.Option("--low-volume-threshold", help="Low-liquidity volume cutoff."),
        ] = 1,
        low_open_interest_threshold: Annotated[
            int,
            typer.Option("--low-open-interest-threshold", help="Low-liquidity OI cutoff."),
        ] = 1,
        deep_otm_threshold: Annotated[
            float,
            typer.Option("--deep-otm-threshold", help="Deep OTM proxy threshold."),
        ] = 0.10,
        near_expiry_days: Annotated[
            int,
            typer.Option("--near-expiry-days", help="Near-expiry proxy days."),
        ] = 31,
    ) -> None:
        """Connect local CF option history files into raw snapshots and core table."""
        from cotton_factor.research_workbench import connect_cf_option_history

        try:
            result = connect_cf_option_history(
                source_dir=source_dir,
                raw_root=raw_root,
                core_output_dir=core_output_dir,
                output_path=output_path,
                core_quote_path=core_quote_path,
                report_output_dir=report_output_dir,
                run_id=run_id,
                low_volume_threshold=low_volume_threshold,
                low_open_interest_threshold=low_open_interest_threshold,
                deep_otm_threshold=deep_otm_threshold,
                near_expiry_days=near_expiry_days,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-option-factor-proxy")
    def research_build_cf_option_factor_proxy(
        option_core_path: Annotated[
            Path | None,
            typer.Option("--option-core-path", help="Optional core option quote parquet path."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional futures core quote path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Optional R48 data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional R48 report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R48 run id."),
        ] = None,
        iv_rank_lookback_days: Annotated[
            int,
            typer.Option("--iv-rank-lookback-days", help="ATM IV proxy rank lookback days."),
        ] = 252,
        atm_moneyness_band: Annotated[
            float,
            typer.Option("--atm-moneyness-band", help="ATM proxy moneyness band."),
        ] = 0.03,
        otm_moneyness_min: Annotated[
            float,
            typer.Option("--otm-moneyness-min", help="OTM skew proxy lower moneyness."),
        ] = 0.90,
        otm_moneyness_max: Annotated[
            float,
            typer.Option("--otm-moneyness-max", help="OTM skew proxy upper moneyness."),
        ] = 0.98,
        incremental: Annotated[
            bool,
            typer.Option("--incremental", help="Recompute only the latest option date."),
        ] = False,
    ) -> None:
        """Build R48 CF option factor proxy research artifacts."""
        from cotton_factor.research_workbench import build_cf_option_factor_proxy

        try:
            result = build_cf_option_factor_proxy(
                option_core_path=option_core_path,
                core_quote_path=core_quote_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                iv_rank_lookback_days=iv_rank_lookback_days,
                atm_moneyness_band=atm_moneyness_band,
                otm_moneyness_min=otm_moneyness_min,
                otm_moneyness_max=otm_moneyness_max,
                incremental=incremental,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
        if not result.passed:
            raise typer.Exit(1)

    @research_app.command("build-cf-option-volatility-term-structure")
    def research_build_cf_option_volatility_term_structure(
        option_factor_path: Annotated[
            Path | None,
            typer.Option("--option-factor-path", help="Optional R48 factor path."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional CF core quote path."),
        ] = None,
        option_expiry_path: Annotated[
            Path | None,
            typer.Option(
                "--option-expiry-path",
                help="Optional R81 reviewed CF option expiry registry.",
            ),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R80 data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R80 report output directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R80 run id."),
        ] = None,
        risk_free_rate: Annotated[
            float,
            typer.Option("--risk-free-rate", help="Black-76 annual risk-free rate."),
        ] = 0.02,
        rv_window: Annotated[
            int,
            typer.Option("--rv-window", help="Realized-volatility lookback."),
        ] = 20,
        iv_rank_window: Annotated[
            int,
            typer.Option("--iv-rank-window", help="Approximate IV rank lookback."),
        ] = 252,
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Posterior validation horizons."),
        ] = "5,10,20",
        min_sample_size: Annotated[
            int,
            typer.Option("--min-sample-size", help="Minimum READY evidence sample."),
        ] = 30,
    ) -> None:
        """Build R80 CF expiry-aware IV/RV and term-structure evidence."""
        from cotton_factor.research_workbench import (
            build_cf_option_volatility_term_structure_research,
        )

        try:
            result = build_cf_option_volatility_term_structure_research(
                option_factor_path=option_factor_path,
                core_quote_path=core_quote_path,
                option_expiry_path=option_expiry_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                risk_free_rate=risk_free_rate,
                rv_window=rv_window,
                iv_rank_window=iv_rank_window,
                horizons=_parse_horizons(horizons),
                min_sample_size=min_sample_size,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-product-research-registry")
    def research_build_cf_product_research_registry(
        product_config_path: Annotated[
            Path | None,
            typer.Option("--product-config-path", help="Optional CF product config YAML path."),
        ] = None,
        factor_registry_path: Annotated[
            Path | None,
            typer.Option("--factor-registry-path", help="Optional factor registry YAML path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Optional R50 data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional R50 report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R50 run id."),
        ] = None,
    ) -> None:
        """Build R50 CF product config and research factor registry snapshot."""
        from cotton_factor.research_workbench import build_cf_product_research_registry

        try:
            result = build_cf_product_research_registry(
                product_config_path=product_config_path,
                factor_registry_path=factor_registry_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
        if not result.passed:
            raise typer.Exit(1)

    @research_app.command("build-cf-fundamental-data-contract")
    def research_build_cf_fundamental_data_contract(
        source_dir: Annotated[
            Path | None,
            typer.Option("--source-dir", help="Optional CF fundamental manual input dir."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Optional R51 data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional R51 report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R51 run id."),
        ] = None,
    ) -> None:
        """Build R51 CF fundamental manual-input contract artifacts."""
        from cotton_factor.research_workbench import build_cf_fundamental_data_contract

        try:
            result = build_cf_fundamental_data_contract(
                source_dir=source_dir,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
        if not result.passed:
            raise typer.Exit(1)

    @research_app.command("build-cf-fundamental-observation")
    def research_build_cf_fundamental_observation(
        source_dir: Annotated[
            Path | None,
            typer.Option("--source-dir", help="Optional CF fundamental manual input dir."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Optional R53 data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional R53 report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R53 run id."),
        ] = None,
    ) -> None:
        """Build R53 CF manual fundamental observation artifacts."""
        from cotton_factor.research_workbench import build_cf_fundamental_observation

        try:
            result = build_cf_fundamental_observation(
                source_dir=source_dir,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
        if not result.passed:
            raise typer.Exit(1)

    @research_app.command("build-cf-fundamental-context")
    def research_build_cf_fundamental_context(
        fundamental_observation_json_path: Annotated[
            Path | None,
            typer.Option(
                "--fundamental-observation-json-path",
                help="Optional R53 fundamental observation JSON path.",
            ),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional CF core quote parquet path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Optional R54 data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional R54 report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R54 run id."),
        ] = None,
        change_windows: Annotated[
            str,
            typer.Option("--change-windows", help="Comma-separated observation windows."),
        ] = "1,4,12",
    ) -> None:
        """Build R54 CF fundamental context artifacts."""
        from cotton_factor.research_workbench import build_cf_fundamental_context

        try:
            result = build_cf_fundamental_context(
                fundamental_observation_json_path=fundamental_observation_json_path,
                core_quote_path=core_quote_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                change_windows=_parse_horizons(change_windows),
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
        if not result.passed:
            raise typer.Exit(1)

    @research_app.command("build-cf-cotton-year-policy-research")
    def research_build_cf_cotton_year_policy(
        continuous_price_path: Annotated[
            Path | None,
            typer.Option("--continuous-price-path", help="Optional R86 continuous path."),
        ] = None,
        spot_price_path: Annotated[
            Path | None,
            typer.Option("--spot-price-path", help="Optional R53 spot-price parquet."),
        ] = None,
        spot_extension_path: Annotated[
            Path | None,
            typer.Option(
                "--spot-extension-path",
                help="Optional R93H iFinD 3128B forward-extension parquet.",
            ),
        ] = None,
        fundamental_context_path: Annotated[
            Path | None,
            typer.Option("--fundamental-context-path", help="Optional R54 context parquet."),
        ] = None,
        policy_config_path: Annotated[
            Path | None,
            typer.Option("--policy-config-path", help="Optional R93G policy YAML."),
        ] = None,
        input_dir: Annotated[
            Path | None,
            typer.Option("--input-dir", help="Optional R86 input bundle directory."),
        ] = None,
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Historical posterior horizons."),
        ] = "5,20,60",
        max_spot_staleness_days: Annotated[
            int,
            typer.Option(
                "--max-spot-staleness-days",
                help="Maximum calendar-day lag for a usable spot observation.",
            ),
        ] = 7,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Optional R93G data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional R93G report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R93G run id."),
        ] = None,
    ) -> None:
        """Build CF cotton-year and policy-reference research artifacts."""
        from cotton_factor.research_workbench import (
            build_cf_cotton_year_policy_research,
        )

        try:
            result = build_cf_cotton_year_policy_research(
                continuous_price_path=continuous_price_path,
                spot_price_path=spot_price_path,
                spot_extension_path=spot_extension_path,
                fundamental_context_path=fundamental_context_path,
                policy_config_path=policy_config_path,
                input_dir=input_dir,
                horizons=_parse_horizons(horizons),
                max_spot_staleness_days=max_spot_staleness_days,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("connect-cf-ifind-edb-context")
    def research_connect_cf_ifind_edb_context(
        source_dir: Annotated[
            Path | None,
            typer.Option("--source-dir", help="Optional preserved iFinD EDB bundle."),
        ] = None,
        as_of_date: Annotated[
            str | None,
            typer.Option("--as-of-date", help="Optional future-date validation boundary."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Optional R93H data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional R93H report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R93H run id."),
        ] = None,
    ) -> None:
        """Normalize preserved CF iFinD EDB inputs with explicit research boundaries."""
        from cotton_factor.research_workbench import connect_cf_ifind_edb_context

        try:
            result = connect_cf_ifind_edb_context(
                source_dir=source_dir,
                as_of_date=_parse_iso_date(as_of_date) if as_of_date else None,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-fundamental-data-status")
    def research_build_cf_fundamental_data_status(
        as_of_date: Annotated[
            str | None,
            typer.Option(
                "--as-of-date",
                help="Optional status date; defaults to the latest CF core date.",
            ),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional CF core quote parquet."),
        ] = None,
        fundamental_dir: Annotated[
            Path | None,
            typer.Option("--fundamental-dir", help="Optional normalized fundamental directory."),
        ] = None,
        ifind_edb_manifest_path: Annotated[
            Path | None,
            typer.Option(
                "--ifind-edb-manifest-path",
                help="Optional R93H manifest; defaults to the latest complete manifest.",
            ),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Optional R93J data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional R93J report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R93J run id."),
        ] = None,
    ) -> None:
        """Build a frequency-aware CF fundamental coverage and freshness view."""
        from cotton_factor.research_workbench import build_cf_fundamental_data_status

        try:
            result = build_cf_fundamental_data_status(
                as_of_date=_parse_iso_date(as_of_date) if as_of_date else None,
                core_quote_path=core_quote_path,
                fundamental_dir=fundamental_dir,
                ifind_edb_manifest_path=ifind_edb_manifest_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-fundamental-trend-incremental-research")
    def research_build_cf_fundamental_trend_incremental(
        breakout_event_path: Annotated[
            Path | None,
            typer.Option("--breakout-event-path", help="Optional R93A event parquet."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional CF core trading sessions."),
        ] = None,
        fundamental_dir: Annotated[
            Path | None,
            typer.Option("--fundamental-dir", help="Optional normalized fundamental directory."),
        ] = None,
        ifind_cotton_context_path: Annotated[
            Path | None,
            typer.Option(
                "--ifind-cotton-context-path",
                help="Optional R93H cotton context with source rtime.",
            ),
        ] = None,
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Comma-separated posterior event horizons."),
        ] = "5,20",
        change_periods: Annotated[
            int,
            typer.Option("--change-periods", help="Observation-count change window."),
        ] = 4,
        min_sample_size: Annotated[
            int,
            typer.Option("--min-sample-size", help="Minimum independent event samples."),
        ] = 20,
        fdr_level: Annotated[
            float,
            typer.Option("--fdr-level", help="Benjamini-Hochberg FDR level."),
        ] = 0.10,
        proxy_lags: Annotated[
            str,
            typer.Option(
                "--proxy-lags",
                help="Trading-session lags for unknown historical release dates.",
            ),
        ] = "0,5,10",
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Optional R93K data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional R93K report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R93K run id."),
        ] = None,
    ) -> None:
        """Build release-aware fundamental evidence for independent trend events."""
        from cotton_factor.research_workbench import (
            build_cf_fundamental_trend_incremental_research,
        )

        try:
            result = build_cf_fundamental_trend_incremental_research(
                breakout_event_path=breakout_event_path,
                core_quote_path=core_quote_path,
                fundamental_dir=fundamental_dir,
                ifind_cotton_context_path=ifind_cotton_context_path,
                horizons=_parse_horizons(horizons),
                change_periods=change_periods,
                min_sample_size=min_sample_size,
                fdr_level=fdr_level,
                proxy_lags=_parse_non_negative_ints(proxy_lags),
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-trend-quality-calibration")
    def research_build_cf_trend_quality_calibration(
        start: Annotated[
            str | None,
            typer.Option("--start", help="Optional calibration window start date."),
        ] = None,
        end: Annotated[
            str | None,
            typer.Option("--end", help="Optional calibration window end date."),
        ] = None,
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Comma-separated positive horizons."),
        ] = "1,3,5,10,20",
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional core quote parquet path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R32 table output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R32 Markdown/JSON report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R32 run id."),
        ] = None,
        trend_rule_candidate_path: Annotated[
            Path | None,
            typer.Option(
                "--trend-rule-candidate-path",
                help="Optional R27 trend rule candidate parquet/csv path.",
            ),
        ] = None,
    ) -> None:
        """Build R32 CF trend quality historical calibration."""
        from cotton_factor.research_workbench import build_cf_trend_quality_calibration

        try:
            result = build_cf_trend_quality_calibration(
                start=_parse_iso_date(start) if start else None,
                end=_parse_iso_date(end) if end else None,
                horizons=_parse_horizons(horizons),
                core_quote_path=core_quote_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                trend_rule_candidate_path=trend_rule_candidate_path,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-trend-phase-validation")
    def research_build_cf_trend_phase_validation(
        start: Annotated[str, typer.Option("--start", help="Validation window start date.")],
        end: Annotated[str, typer.Option("--end", help="Validation window end date.")],
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Comma-separated positive horizons."),
        ] = "1,3,5,10,20",
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional core quote parquet path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R25 table output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R25 Markdown report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R25 run id."),
        ] = None,
    ) -> None:
        """Build R25 CF trend phase rolling validation."""
        from cotton_factor.research_workbench import build_cf_trend_phase_validation

        try:
            result = build_cf_trend_phase_validation(
                start=_parse_iso_date(start),
                end=_parse_iso_date(end),
                horizons=_parse_horizons(horizons),
                core_quote_path=core_quote_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-trend-phase-events")
    def research_build_cf_trend_phase_events(
        start: Annotated[str, typer.Option("--start", help="Event window start date.")],
        end: Annotated[str, typer.Option("--end", help="Event window end date.")],
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Comma-separated positive horizons."),
        ] = "1,3,5,10,20",
        trend_phase_daily_path: Annotated[
            Path | None,
            typer.Option("--trend-phase-daily-path", help="Optional R25 daily parquet path."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional core quote path to build R25 first."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R26 table output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R26 Markdown report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R26 run id."),
        ] = None,
    ) -> None:
        """Build R26 CF trend phase transition events."""
        from cotton_factor.research_workbench import build_cf_trend_phase_events

        try:
            result = build_cf_trend_phase_events(
                start=_parse_iso_date(start),
                end=_parse_iso_date(end),
                horizons=_parse_horizons(horizons),
                trend_phase_daily_path=trend_phase_daily_path,
                core_quote_path=core_quote_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("build-cf-trend-rule-candidates")
    def research_build_cf_trend_rule_candidates(
        start: Annotated[str, typer.Option("--start", help="Candidate window start date.")],
        end: Annotated[str, typer.Option("--end", help="Candidate window end date.")],
        event_summary_path: Annotated[
            Path | None,
            typer.Option("--event-summary-path", help="Optional R26 event summary parquet path."),
        ] = None,
        event_path: Annotated[
            Path | None,
            typer.Option("--event-path", help="Optional R26 event parquet path."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="R27 candidate table output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R27 Markdown report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R27 run id."),
        ] = None,
        min_event_count: Annotated[
            int,
            typer.Option("--min-event-count", help="Minimum transition event count."),
        ] = 3,
        min_observation_count: Annotated[
            int,
            typer.Option("--min-observation-count", help="Minimum post-event label count."),
        ] = 3,
        min_directional_hit_rate: Annotated[
            float,
            typer.Option("--min-directional-hit-rate", help="Minimum directional hit rate."),
        ] = 0.60,
    ) -> None:
        """Build R27 CF daily-brief trend rule candidates."""
        from cotton_factor.research_workbench import build_cf_trend_rule_candidates

        try:
            result = build_cf_trend_rule_candidates(
                start=_parse_iso_date(start),
                end=_parse_iso_date(end),
                event_summary_path=event_summary_path,
                event_path=event_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
                min_event_count=min_event_count,
                min_observation_count=min_observation_count,
                min_directional_hit_rate=min_directional_hit_rate,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @research_app.command("run-cf-daily-pipeline")
    def research_run_cf_daily_pipeline(
        trade_date: Annotated[str, typer.Option("--date", help="Pipeline trade date.")],
        input_path: Annotated[
            Path,
            typer.Option("--input-path", help="Local CF file or folder to preserve first."),
        ],
        start: Annotated[
            str | None,
            typer.Option("--start", help="Research artifact window start date."),
        ] = None,
        end: Annotated[
            str | None,
            typer.Option("--end", help="Research artifact window end date."),
        ] = None,
        raw_output_dir: Annotated[
            Path | None,
            typer.Option("--raw-output-dir", help="Research raw output root."),
        ] = None,
        core_output_dir: Annotated[
            Path | None,
            typer.Option("--core-output-dir", help="Research core output root."),
        ] = None,
        research_output_root: Annotated[
            Path | None,
            typer.Option("--research-output-root", help="Research artifact output root."),
        ] = None,
        report_output_root: Annotated[
            Path | None,
            typer.Option("--report-output-root", help="Research report output root."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R20 pipeline run id."),
        ] = None,
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Comma-separated positive horizons."),
        ] = "1,3,5",
        factor_ids: Annotated[
            str,
            typer.Option("--factor-ids", help="Comma-separated factor ids."),
        ] = "mom_20_v1,carry_nf_v1,curve_slope_v1,oi_pressure_v1",
        scenario_cost_bps: Annotated[
            str | None,
            typer.Option(
                "--scenario-cost-bps",
                help="Comma-separated scenario=bps pairs, e.g. no_cost=0,normal_cost=5.",
            ),
        ] = None,
        price_field: Annotated[
            str,
            typer.Option("--price-field", help="Continuous price field."),
        ] = "settle",
        lookback_periods: Annotated[
            int,
            typer.Option("--lookback-periods", help="Momentum lookback periods."),
        ] = 20,
        ltd_buffer_days: Annotated[
            int,
            typer.Option("--ltd-buffer-days", help="LTD guard buffer in trading days."),
        ] = 0,
        min_volume: Annotated[
            int,
            typer.Option("--min-volume", help="Minimum volume for chain ranking."),
        ] = 1,
        require_all_factors: Annotated[
            bool,
            typer.Option(
                "--require-all-factors/--allow-missing-factors",
                help="Require all factors in R17 multifactor scoring.",
            ),
        ] = True,
        use_processed_value: Annotated[
            bool,
            typer.Option(
                "--use-processed-value/--use-raw-value",
                help="Use processed factor values when available.",
            ),
        ] = True,
        use_processed_score: Annotated[
            bool,
            typer.Option(
                "--use-processed-score/--use-raw-score",
                help="Use processed multifactor scores when available.",
            ),
        ] = True,
    ) -> None:
        """Run R20 one-command CF daily research pipeline."""
        from cotton_factor.research_workbench import build_cf_daily_research_pipeline

        parsed_trade_date = _parse_iso_date(trade_date)
        try:
            result = build_cf_daily_research_pipeline(
                trade_date=parsed_trade_date,
                input_path=input_path,
                start=_parse_iso_date(start) if start else None,
                end=_parse_iso_date(end) if end else None,
                raw_output_dir=raw_output_dir,
                core_output_dir=core_output_dir,
                research_output_root=research_output_root,
                report_output_root=report_output_root,
                run_id=run_id,
                horizons=_parse_horizons(horizons),
                factor_ids=_parse_factor_ids(factor_ids),
                scenario_cost_bps=_parse_scenario_cost_bps(scenario_cost_bps),
                price_field=price_field,
                lookback_periods=lookback_periods,
                ltd_buffer_days=ltd_buffer_days,
                min_volume=min_volume,
                require_all_factors=require_all_factors,
                use_processed_value=use_processed_value,
                use_processed_score=use_processed_score,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
        if not result.passed:
            raise typer.Exit(1)

    @research_app.command("replay-cf-daily-pipeline")
    def research_replay_cf_daily_pipeline(
        pipeline_json_path: Annotated[
            Path,
            typer.Option("--pipeline-json-path", help="R20 pipeline JSON log path."),
        ],
        baseline_json_path: Annotated[
            Path | None,
            typer.Option("--baseline-json-path", help="Optional prior R21 replay JSON path."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="R21 replay report output directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R21 replay run id."),
        ] = None,
        require_completed_pipeline: Annotated[
            bool,
            typer.Option(
                "--require-completed-pipeline/--allow-incomplete-pipeline",
                help="Require the source R20 pipeline status to be COMPLETED.",
            ),
        ] = True,
    ) -> None:
        """Replay-check preserved R20 CF research outputs."""
        from cotton_factor.research_workbench import replay_cf_research_pipeline_outputs

        try:
            result = replay_cf_research_pipeline_outputs(
                pipeline_json_path=pipeline_json_path,
                baseline_json_path=baseline_json_path,
                report_output_dir=report_output_dir,
                run_id=run_id,
                require_completed_pipeline=require_completed_pipeline,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
        if not result.passed:
            raise typer.Exit(1)

    @research_app.command("build-cf-expansion-gate")
    def research_build_cf_expansion_gate(
        candidate_scope: Annotated[
            str,
            typer.Option("--candidate-scope", help="Candidate expansion scope."),
        ] = "SR_AP_OR_EXTERNAL_DATA",
        pipeline_json_path: Annotated[
            Path | None,
            typer.Option("--pipeline-json-path", help="Optional R20 pipeline JSON evidence."),
        ] = None,
        replay_json_path: Annotated[
            Path | None,
            typer.Option("--replay-json-path", help="Optional R21 replay JSON evidence."),
        ] = None,
        historical_evidence_manifest_path: Annotated[
            Path | None,
            typer.Option("--historical-evidence-manifest-path", help="Optional R41 manifest."),
        ] = None,
        event_explanation_manifest_path: Annotated[
            Path | None,
            typer.Option("--event-explanation-manifest-path", help="Optional R42 manifest."),
        ] = None,
        signal_matrix_manifest_path: Annotated[
            Path | None,
            typer.Option("--signal-matrix-manifest-path", help="Optional R49 manifest."),
        ] = None,
        publish_pack_manifest_path: Annotated[
            Path | None,
            typer.Option("--publish-pack-manifest-path", help="Optional R45 manifest."),
        ] = None,
        product_registry_manifest_path: Annotated[
            Path | None,
            typer.Option("--product-registry-manifest-path", help="Optional R50 manifest."),
        ] = None,
        fundamental_contract_manifest_path: Annotated[
            Path | None,
            typer.Option("--fundamental-contract-manifest-path", help="Optional R51 manifest."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Expansion gate report output directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable gate run id."),
        ] = None,
        gate_version: Annotated[
            str,
            typer.Option(
                "--gate-version",
                help="Gate version: R52 by default, R22 for legacy pack.",
            ),
        ] = "R52",
    ) -> None:
        """Build the R52 expansion gate report."""
        from cotton_factor.research_workbench import build_cf_expansion_gate

        try:
            result = build_cf_expansion_gate(
                candidate_scope=candidate_scope,
                pipeline_json_path=pipeline_json_path,
                replay_json_path=replay_json_path,
                historical_evidence_manifest_path=historical_evidence_manifest_path,
                event_explanation_manifest_path=event_explanation_manifest_path,
                signal_matrix_manifest_path=signal_matrix_manifest_path,
                publish_pack_manifest_path=publish_pack_manifest_path,
                product_registry_manifest_path=product_registry_manifest_path,
                fundamental_contract_manifest_path=fundamental_contract_manifest_path,
                report_output_dir=report_output_dir,
                run_id=run_id,
                gate_version=gate_version,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
        if not result.passed:
            raise typer.Exit(1)

    @research_app.command("connect-cf-official-history")
    def research_connect_cf_official_history(
        years: Annotated[
            str | None,
            typer.Option("--years", help="Comma-separated years. Defaults to recent 3 full years."),
        ] = None,
        source_dir: Annotated[
            Path | None,
            typer.Option("--source-dir", help="Folder containing ALLFUTURES{year}.zip files."),
        ] = None,
        allow_download: Annotated[
            bool,
            typer.Option(
                "--allow-download/--no-allow-download",
                help="Try downloading missing official annual ZIPs from CZCE.",
            ),
        ] = False,
        raw_root: Annotated[
            Path | None,
            typer.Option("--raw-root", help="Raw snapshot root. Defaults to data/raw."),
        ] = None,
        core_output_dir: Annotated[
            Path | None,
            typer.Option("--core-output-dir", help="Core output root. Defaults to data/core."),
        ] = None,
        output_path: Annotated[
            Path | None,
            typer.Option("--output-path", help="Explicit core_quote_daily parquet path."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Official history report output directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable ingest run id."),
        ] = None,
    ) -> None:
        """Connect CZCE official annual history into CF core quotes."""
        from cotton_factor.research_workbench import connect_cf_official_history

        try:
            result = connect_cf_official_history(
                years=_parse_years(years) if years else None,
                source_dir=source_dir,
                allow_download=allow_download,
                raw_root=raw_root,
                core_output_dir=core_output_dir,
                output_path=output_path,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
        if not result.passed:
            raise typer.Exit(1)

    @research_app.command("run-cf-validation-pack")
    def research_run_cf_validation_pack(
        trade_date: Annotated[
            str,
            typer.Option("--date", help="Validation pack trade date."),
        ] = "2024-01-31",
        start: Annotated[
            str,
            typer.Option("--start", help="Validation research window start date."),
        ] = "2024-01-22",
        end: Annotated[
            str,
            typer.Option("--end", help="Validation research window end date."),
        ] = "2024-01-31",
        output_root: Annotated[
            Path | None,
            typer.Option("--output-root", help="Root for isolated validation runs."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable post-R22 validation run id."),
        ] = None,
        horizons: Annotated[
            str,
            typer.Option("--horizons", help="Comma-separated positive horizons."),
        ] = "1",
        lookback_periods: Annotated[
            int,
            typer.Option("--lookback-periods", help="Momentum lookback periods."),
        ] = 3,
        candidate_scope: Annotated[
            str,
            typer.Option("--candidate-scope", help="Candidate scope for the R22 gate."),
        ] = "POST_R22_CF_VALIDATION",
    ) -> None:
        """Run a post-R22 CF workbench validation pack."""
        from cotton_factor.research_workbench import build_cf_post_r22_validation_pack

        try:
            result = build_cf_post_r22_validation_pack(
                trade_date=_parse_iso_date(trade_date),
                start=_parse_iso_date(start),
                end=_parse_iso_date(end),
                output_root=output_root,
                run_id=run_id,
                horizons=_parse_horizons(horizons),
                lookback_periods=lookback_periods,
                candidate_scope=candidate_scope,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc

        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
        if not result.passed:
            raise typer.Exit(1)

    @strategy_app.command("validate-specs")
    def strategy_validate_specs(
        registry_path: Annotated[
            Path | None,
            typer.Option("--registry-path", help="Optional strategy registry YAML path."),
        ] = None,
    ) -> None:
        """Validate the V5.1 CF strategy registry and all enabled specs."""
        from cotton_factor.strategy import load_strategy_registry

        try:
            registry = load_strategy_registry(registry_path)
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(registry.to_summary(), ensure_ascii=False, sort_keys=True))

    @strategy_app.command("prepare-inputs")
    def strategy_prepare_inputs(
        start: Annotated[
            str | None,
            typer.Option("--start", help="Optional first signal date, YYYY-MM-DD."),
        ] = None,
        end: Annotated[
            str | None,
            typer.Option("--end", help="Optional final signal date, YYYY-MM-DD."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional core quote parquet path."),
        ] = None,
        calendar_dir: Annotated[
            Path | None,
            typer.Option("--calendar-dir", help="Optional official calendar directory."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Optional strategy input output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional Chinese report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable strategy-input run id."),
        ] = None,
    ) -> None:
        """Build canonical cross-year CF strategy inputs from normalized core facts."""
        from cotton_factor.strategy.inputs import prepare_cf_strategy_inputs

        try:
            result = prepare_cf_strategy_inputs(
                start=_parse_iso_date(start) if start else None,
                end=_parse_iso_date(end) if end else None,
                core_quote_path=core_quote_path,
                calendar_dir=calendar_dir,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @strategy_app.command("run-backtest")
    def strategy_run_backtest(
        spec_path: Annotated[
            Path,
            typer.Option("--spec", help="Baseline strategy YAML path."),
        ],
        start: Annotated[
            str | None,
            typer.Option("--start", help="Optional first signal date, YYYY-MM-DD."),
        ] = None,
        end: Annotated[
            str | None,
            typer.Option("--end", help="Optional final signal date, YYYY-MM-DD."),
        ] = None,
        continuous_price_path: Annotated[
            Path | None,
            typer.Option("--continuous-price-path", help="Optional R86 continuous price path."),
        ] = None,
        trade_mapping_path: Annotated[
            Path | None,
            typer.Option("--trade-mapping-path", help="Optional R86 T+1 mapping path."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional normalized core quote path."),
        ] = None,
        signal_matrix_path: Annotated[
            Path | None,
            typer.Option(
                "--signal-matrix-path",
                help="Optional historical signal_matrix_daily path for candidate specs.",
            ),
        ] = None,
        trend_phase_path: Annotated[
            Path | None,
            typer.Option(
                "--trend-phase-path",
                help="Optional trend_phase_v2_daily path for candidate specs.",
            ),
        ] = None,
        input_dir: Annotated[
            Path | None,
            typer.Option("--input-dir", help="Optional R86 input bundle directory."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Optional strategy data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional Chinese report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R87 run id."),
        ] = None,
    ) -> None:
        """Run R87 baseline through real-contract T+1 settlement accounting."""
        from cotton_factor.strategy import (
            load_strategy_spec,
            run_cf_phase_gated_backtest,
            run_cf_tsmom_backtest,
        )

        try:
            spec = load_strategy_spec(spec_path)
            common = {
                "spec_path": spec_path,
                "start": _parse_iso_date(start) if start else None,
                "end": _parse_iso_date(end) if end else None,
                "continuous_price_path": continuous_price_path,
                "trade_mapping_path": trade_mapping_path,
                "core_quote_path": core_quote_path,
                "input_dir": input_dir,
                "output_dir": output_dir,
                "report_output_dir": report_output_dir,
                "run_id": run_id,
            }
            if spec.strategy_type == "baseline_tsmom":
                result = run_cf_tsmom_backtest(**common)
            elif spec.strategy_type == "phase_gated":
                result = run_cf_phase_gated_backtest(
                    **common,
                    signal_matrix_path=signal_matrix_path,
                    trend_phase_path=trend_phase_path,
                )
            else:
                raise CottonFactorError(
                    f"run-backtest does not support strategy_type={spec.strategy_type}"
                )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @strategy_app.command("build-roll-neutral-return-index")
    def strategy_build_roll_neutral_return_index(
        continuous_price_path: Annotated[
            Path | None,
            typer.Option(
                "--continuous-price-path",
                help="Optional R86 additive continuous-settlement parquet path.",
            ),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional normalized CF quote path."),
        ] = None,
        strategy_spec_path: Annotated[
            Path,
            typer.Option("--spec", help="Baseline TSMOM specification path."),
        ] = Path("configs/strategy/CF_tsmom_v0.yaml"),
        input_dir: Annotated[
            Path | None,
            typer.Option("--input-dir", help="Optional R86 input bundle directory."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Optional R93F data output directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional Chinese report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R93F run id."),
        ] = None,
    ) -> None:
        """Build a roll-neutral return index without changing the active strategy."""
        from cotton_factor.strategy import build_cf_roll_neutral_return_research

        try:
            result = build_cf_roll_neutral_return_research(
                continuous_price_path=continuous_price_path,
                core_quote_path=core_quote_path,
                strategy_spec_path=strategy_spec_path,
                input_dir=input_dir,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @strategy_app.command("evaluate")
    def strategy_evaluate(
        spec_path: Annotated[Path, typer.Option("--spec", help="Strategy YAML path.")],
        backtest_daily_path: Annotated[
            Path | None,
            typer.Option("--backtest-daily-path", help="Optional strategy daily parquet."),
        ] = None,
        trend_phase_path: Annotated[
            Path | None,
            typer.Option("--trend-phase-path", help="Optional phase v2 daily parquet."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Optional evaluation data directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional evaluation report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R88 run id."),
        ] = None,
    ) -> None:
        """Build R88 non-overlapping-year and diagnostic-window evidence."""
        from cotton_factor.strategy import evaluate_cf_strategy

        try:
            result = evaluate_cf_strategy(
                spec_path=spec_path,
                backtest_daily_path=backtest_daily_path,
                trend_phase_path=trend_phase_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @strategy_app.command("compare")
    def strategy_compare(
        baseline_spec_path: Annotated[
            Path,
            typer.Option("--spec-a", help="Baseline strategy YAML path."),
        ],
        candidate_spec_path: Annotated[
            Path,
            typer.Option("--spec-b", help="Candidate strategy YAML path."),
        ],
        baseline_evaluation_path: Annotated[
            Path | None,
            typer.Option("--evaluation-a", help="Optional baseline evaluation parquet."),
        ] = None,
        candidate_evaluation_path: Annotated[
            Path | None,
            typer.Option("--evaluation-b", help="Optional candidate evaluation parquet."),
        ] = None,
        output_dir: Annotated[
            Path | None,
            typer.Option("--output-dir", help="Optional comparison data directory."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional comparison report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R89 comparison id."),
        ] = None,
    ) -> None:
        """Apply the fixed R89 candidate promotion gate."""
        from cotton_factor.strategy import compare_cf_strategies

        try:
            result = compare_cf_strategies(
                baseline_spec_path=baseline_spec_path,
                candidate_spec_path=candidate_spec_path,
                baseline_evaluation_path=baseline_evaluation_path,
                candidate_evaluation_path=candidate_evaluation_path,
                output_dir=output_dir,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @strategy_app.command("test-overlay")
    def strategy_test_overlay(
        overlay_ref: Annotated[
            str,
            typer.Option("--overlay", help="Overlay id or YAML path."),
        ],
        base_ref: Annotated[
            str,
            typer.Option("--base", help="Baseline id or YAML path."),
        ] = "CF_tsmom_v0",
        start: Annotated[
            str | None,
            typer.Option("--start", help="Optional first signal date, YYYY-MM-DD."),
        ] = None,
        end: Annotated[
            str | None,
            typer.Option("--end", help="Optional final signal date, YYYY-MM-DD."),
        ] = None,
        continuous_price_path: Annotated[
            Path | None,
            typer.Option("--continuous-price-path", help="Optional R86 continuous path."),
        ] = None,
        trade_mapping_path: Annotated[
            Path | None,
            typer.Option("--trade-mapping-path", help="Optional R86 T+1 mapping path."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional normalized core quote path."),
        ] = None,
        signal_matrix_path: Annotated[
            Path | None,
            typer.Option("--signal-matrix-path", help="Optional historical signal matrix."),
        ] = None,
        member_position_path: Annotated[
            Path | None,
            typer.Option("--member-position-path", help="Optional member-position core table."),
        ] = None,
        strike_position_path: Annotated[
            Path | None,
            typer.Option("--strike-position-path", help="Optional R84 strike-position table."),
        ] = None,
        trend_phase_path: Annotated[
            Path | None,
            typer.Option("--trend-phase-path", help="Optional phase attribution table."),
        ] = None,
        input_dir: Annotated[
            Path | None,
            typer.Option("--input-dir", help="Optional R86 input bundle directory."),
        ] = None,
        output_root: Annotated[
            Path | None,
            typer.Option("--output-root", help="Optional strategy data output root."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional Chinese report directory."),
        ] = None,
        baseline_evaluation_path: Annotated[
            Path | None,
            typer.Option(
                "--baseline-evaluation-path",
                help="Optional already aligned baseline evaluation; otherwise rebuild it.",
            ),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R92 test id."),
        ] = None,
    ) -> None:
        """Run one fixed R92 overlay and emit KEEP/WATCH/REJECT."""
        from cotton_factor.strategy import resolve_strategy_spec_path, test_cf_overlay

        try:
            result = test_cf_overlay(
                overlay_spec_path=resolve_strategy_spec_path(overlay_ref),
                base_spec_path=resolve_strategy_spec_path(base_ref),
                start=_parse_iso_date(start) if start else None,
                end=_parse_iso_date(end) if end else None,
                continuous_price_path=continuous_price_path,
                trade_mapping_path=trade_mapping_path,
                core_quote_path=core_quote_path,
                signal_matrix_path=signal_matrix_path,
                member_position_path=member_position_path,
                strike_position_path=strike_position_path,
                trend_phase_path=trend_phase_path,
                input_dir=input_dir,
                output_root=output_root,
                report_output_dir=report_output_dir,
                baseline_evaluation_path=baseline_evaluation_path,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @strategy_app.command("run-shadow")
    def strategy_run_shadow(
        trade_date: Annotated[
            str | None,
            typer.Option("--date", help="Optional shadow date; defaults to latest core date."),
        ] = None,
        record_mode: Annotated[
            str,
            typer.Option(
                "--record-mode",
                help="FORWARD_CAPTURE or explicitly tagged HISTORICAL_REPLAY.",
            ),
        ] = "FORWARD_CAPTURE",
        registry_path: Annotated[
            Path | None,
            typer.Option("--registry-path", help="Optional strategy registry path."),
        ] = None,
        core_quote_path: Annotated[
            Path | None,
            typer.Option("--core-quote-path", help="Optional normalized core quote path."),
        ] = None,
        continuous_price_path: Annotated[
            Path | None,
            typer.Option("--continuous-price-path", help="Optional R86 continuous path."),
        ] = None,
        chain_map_path: Annotated[
            Path | None,
            typer.Option("--chain-map-path", help="Optional R86 chain map path."),
        ] = None,
        input_dir: Annotated[
            Path | None,
            typer.Option("--input-dir", help="Optional R86 input bundle directory."),
        ] = None,
        event_root: Annotated[
            Path | None,
            typer.Option("--event-root", help="Optional immutable event root."),
        ] = None,
        ledger_root: Annotated[
            Path | None,
            typer.Option("--ledger-root", help="Optional materialized ledger root."),
        ] = None,
        daily_output_root: Annotated[
            Path | None,
            typer.Option("--daily-output-root", help="Optional runs/daily root."),
        ] = None,
        overwrite_reason: Annotated[
            str | None,
            typer.Option("--overwrite-reason", help="Required only for a correction event."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R90 run id."),
        ] = None,
    ) -> None:
        """Append R90 immutable events and atomically rebuild shadow ledger views."""
        from cotton_factor.strategy import run_cf_strategy_shadow

        try:
            result = run_cf_strategy_shadow(
                trade_date=_parse_iso_date(trade_date) if trade_date else None,
                record_mode=record_mode,
                registry_path=registry_path,
                core_quote_path=core_quote_path,
                continuous_price_path=continuous_price_path,
                chain_map_path=chain_map_path,
                input_dir=input_dir,
                event_root=event_root,
                ledger_root=ledger_root,
                daily_output_root=daily_output_root,
                overwrite_reason=overwrite_reason,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @strategy_app.command("weekly-audit")
    def strategy_weekly_audit(
        asof_date: Annotated[
            str | None,
            typer.Option("--date", help="Optional audit date; defaults to latest ledger date."),
        ] = None,
        ledger_root: Annotated[
            Path | None,
            typer.Option("--ledger-root", help="Optional materialized shadow ledger root."),
        ] = None,
        report_output_dir: Annotated[
            Path | None,
            typer.Option("--report-output-dir", help="Optional weekly audit report directory."),
        ] = None,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable R91 audit run id."),
        ] = None,
    ) -> None:
        """Build the R91 weekly shadow-performance and accounting audit."""
        from cotton_factor.strategy import build_cf_weekly_strategy_audit

        try:
            result = build_cf_weekly_strategy_audit(
                asof_date=_parse_iso_date(asof_date) if asof_date else None,
                ledger_root=ledger_root,
                report_output_dir=report_output_dir,
                run_id=run_id,
            )
        except CottonFactorError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))

    @operations_app.command("run-cf-daily-update")
    def operations_run_cf_daily_update(
        trade_date: Annotated[
            str | None,
            typer.Option("--date", help="CF data date in YYYY-MM-DD format."),
        ] = None,
        futures_source_dir: Annotated[
            Path,
            typer.Option(
                "--futures-source-dir",
                help="Official CF futures incoming directory.",
            ),
        ] = Path("data/incoming/CF/history"),
        options_source_dir: Annotated[
            Path,
            typer.Option(
                "--options-source-dir",
                help="Official CF options incoming directory.",
            ),
        ] = Path("data/incoming/CF/options/history"),
        download_official: Annotated[
            bool,
            typer.Option("--download-official", help="Fetch today's official files first."),
        ] = False,
        skip_options: Annotated[
            bool,
            typer.Option("--skip-options", help="Skip the options sidecar."),
        ] = False,
        overwrite_official: Annotated[
            bool,
            typer.Option("--overwrite-official", help="Overwrite existing daily files."),
        ] = False,
        refresh_option_core: Annotated[
            bool,
            typer.Option("--refresh-option-core", help="Refresh option core from incoming files."),
        ] = False,
        refresh_option_factors: Annotated[
            bool,
            typer.Option(
                "--refresh-option-factors",
                help="Refresh option factor proxy incrementally.",
            ),
        ] = False,
        skip_continuity_audit: Annotated[
            bool,
            typer.Option("--skip-continuity-audit", help="Skip the continuity audit."),
        ] = False,
        skip_state_upgrade: Annotated[
            bool,
            typer.Option("--skip-state-upgrade", help="Skip dual-price and state sidecars."),
        ] = False,
        run_daily_operation_audit: Annotated[
            bool,
            typer.Option("--run-daily-operation-audit", help="Write the daily operation audit."),
        ] = False,
        run_id: Annotated[
            str | None,
            typer.Option("--run-id", help="Optional stable daily run id."),
        ] = None,
    ) -> None:
        """Run the testable CF light daily-update orchestrator."""
        from cotton_factor.operations import CfDailyUpdateConfig, run_cf_daily_update
        from cotton_factor.operations.daily_update import default_run_id

        active_date = _parse_iso_date(trade_date) if trade_date else date.today()
        try:
            result = run_cf_daily_update(
                CfDailyUpdateConfig(
                    trade_date=active_date,
                    year=active_date.year,
                    run_id=run_id or default_run_id(active_date),
                    repo_root=Path.cwd(),
                    futures_source_dir=futures_source_dir,
                    options_source_dir=options_source_dir,
                    download_official=download_official,
                    include_options=not skip_options,
                    overwrite_official=overwrite_official,
                    refresh_option_core=refresh_option_core,
                    refresh_option_factors=refresh_option_factors,
                    run_continuity_audit=not skip_continuity_audit,
                    run_state_upgrade=not skip_state_upgrade,
                    run_daily_operation_audit=run_daily_operation_audit,
                )
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
    app.add_typer(research_app, name="research")
    app.add_typer(strategy_app, name="strategy")
    app.add_typer(operations_app, name="operations")

    def cli() -> None:
        """Run the Typer application."""
        app()

else:
    app = None

    def _build_fallback_parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog="cotton-factor",
            description=(
                "Cotton factor research workbench CLI. Install dev dependencies "
                "for the full Typer CLI."
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

        research_parser = subparsers.add_parser("research", help="Research workbench commands.")
        research_subparsers = research_parser.add_subparsers(dest="research_command")
        ingest_cf_parser = research_subparsers.add_parser(
            "ingest-cf",
            help="Preserve local CF research input files.",
        )
        ingest_cf_parser.add_argument("--date", required=True)
        ingest_cf_parser.add_argument("--input-path", required=True, type=Path)
        ingest_cf_parser.add_argument("--raw-output-dir", type=Path)
        ingest_cf_parser.add_argument("--run-id")
        normalize_cf_quotes_parser = research_subparsers.add_parser(
            "normalize-cf-quotes",
            help="Build core quote parquet from preserved CF raw files.",
        )
        normalize_cf_quotes_parser.add_argument("--date", required=True)
        normalize_cf_quotes_parser.add_argument("--raw-output-dir", type=Path)
        normalize_cf_quotes_parser.add_argument("--core-output-dir", type=Path)
        normalize_cf_quotes_parser.add_argument("--output-path", type=Path)
        normalize_cf_quotes_parser.add_argument("--run-id")
        check_cf_quality_parser = research_subparsers.add_parser(
            "check-cf-quality",
            help="Run CF core quote data quality checks.",
        )
        check_cf_quality_parser.add_argument("--date", required=True)
        check_cf_quality_parser.add_argument("--core-output-dir", type=Path)
        check_cf_quality_parser.add_argument("--core-quote-path", type=Path)
        check_cf_quality_parser.add_argument("--report-output-dir", type=Path)
        review_cf_contract_rules_parser = research_subparsers.add_parser(
            "review-cf-contract-rules",
            help="Build the CF contract rule review table.",
        )
        review_cf_contract_rules_parser.add_argument("--year", required=True, type=int)
        review_cf_contract_rules_parser.add_argument("--report-output-dir", type=Path)
        review_cf_contract_rules_parser.add_argument("--calendar-path", type=Path)
        build_cf_mapping_parser = research_subparsers.add_parser(
            "build-cf-mapping",
            help="Build research-mode CF chain/trade mapping files.",
        )
        build_cf_mapping_parser.add_argument("--start", required=True)
        build_cf_mapping_parser.add_argument("--end", required=True)
        build_cf_mapping_parser.add_argument("--core-output-dir", type=Path)
        build_cf_mapping_parser.add_argument("--core-quote-path", type=Path)
        build_cf_mapping_parser.add_argument("--output-dir", type=Path)
        build_cf_mapping_parser.add_argument("--report-output-dir", type=Path)
        build_cf_mapping_parser.add_argument("--calendar-path", type=Path)
        build_cf_mapping_parser.add_argument("--ltd-buffer-days", default=0, type=int)
        build_cf_mapping_parser.add_argument("--min-volume", default=1, type=int)
        build_cf_continuous_parser = research_subparsers.add_parser(
            "build-cf-continuous",
            help="Build research-mode CF continuous price files.",
        )
        build_cf_continuous_parser.add_argument("--start", required=True)
        build_cf_continuous_parser.add_argument("--end", required=True)
        build_cf_continuous_parser.add_argument("--price-field", default="settle")
        build_cf_continuous_parser.add_argument("--core-output-dir", type=Path)
        build_cf_continuous_parser.add_argument("--core-quote-path", type=Path)
        build_cf_continuous_parser.add_argument("--chain-map-path", type=Path)
        build_cf_continuous_parser.add_argument("--output-dir", type=Path)
        build_cf_continuous_parser.add_argument("--report-output-dir", type=Path)
        factor_contract_parser = research_subparsers.add_parser(
            "write-cf-factor-output-contract",
            help="Write the R10 downstream factor diagnostic output contract.",
        )
        factor_contract_parser.add_argument("--output-dir", type=Path)
        factor_contract_parser.add_argument("--report-output-dir", type=Path)
        momentum_parser = research_subparsers.add_parser(
            "build-cf-momentum-factor",
            help="Build R11 CF momentum factor rows and warnings.",
        )
        momentum_parser.add_argument("--start", required=True)
        momentum_parser.add_argument("--end", required=True)
        momentum_parser.add_argument("--continuous-price-path", type=Path)
        momentum_parser.add_argument("--output-dir", type=Path)
        momentum_parser.add_argument("--report-output-dir", type=Path)
        momentum_parser.add_argument("--run-id")
        momentum_parser.add_argument("--price-field", default="settle")
        momentum_parser.add_argument("--lookback-periods", default=20, type=int)
        carry_parser = research_subparsers.add_parser(
            "build-cf-carry-factor",
            help="Build R12 CF carry factor rows and warnings.",
        )
        carry_parser.add_argument("--start", required=True)
        carry_parser.add_argument("--end", required=True)
        carry_parser.add_argument("--core-output-dir", type=Path)
        carry_parser.add_argument("--core-quote-path", type=Path)
        carry_parser.add_argument("--output-dir", type=Path)
        carry_parser.add_argument("--report-output-dir", type=Path)
        carry_parser.add_argument("--calendar-path", type=Path)
        carry_parser.add_argument("--run-id")
        structure_parser = research_subparsers.add_parser(
            "build-cf-structure-factors",
            help="Build R13 CF curve slope and OI pressure rows and warnings.",
        )
        structure_parser.add_argument("--start", required=True)
        structure_parser.add_argument("--end", required=True)
        structure_parser.add_argument("--core-output-dir", type=Path)
        structure_parser.add_argument("--core-quote-path", type=Path)
        structure_parser.add_argument("--chain-map-path", type=Path)
        structure_parser.add_argument("--output-dir", type=Path)
        structure_parser.add_argument("--report-output-dir", type=Path)
        structure_parser.add_argument("--calendar-path", type=Path)
        structure_parser.add_argument("--run-id")
        diagnostics_parser = research_subparsers.add_parser(
            "build-cf-factor-diagnostics",
            help="Build R14 CF daily factor diagnostic rows and report.",
        )
        diagnostics_parser.add_argument("--start", required=True)
        diagnostics_parser.add_argument("--end", required=True)
        diagnostics_parser.add_argument("--factor-value-path", type=Path)
        diagnostics_parser.add_argument("--warning-csv-path", type=Path)
        diagnostics_parser.add_argument("--output-dir", type=Path)
        diagnostics_parser.add_argument("--report-output-dir", type=Path)
        diagnostics_parser.add_argument("--run-id")
        forward_returns_parser = research_subparsers.add_parser(
            "build-cf-forward-returns",
            help="Build R15 CF forward-return labels from real trade mappings.",
        )
        forward_returns_parser.add_argument("--start", required=True)
        forward_returns_parser.add_argument("--end", required=True)
        forward_returns_parser.add_argument("--horizons", default="1,3,5")
        forward_returns_parser.add_argument("--core-output-dir", type=Path)
        forward_returns_parser.add_argument("--core-quote-path", type=Path)
        forward_returns_parser.add_argument("--trade-mapping-path", type=Path)
        forward_returns_parser.add_argument("--output-dir", type=Path)
        forward_returns_parser.add_argument("--report-output-dir", type=Path)
        forward_returns_parser.add_argument("--run-id")
        forward_returns_parser.add_argument("--entry-price-field", default="settle")
        forward_returns_parser.add_argument("--exit-price-field", default="settle")
        single_factor_parser = research_subparsers.add_parser(
            "run-cf-single-factor-backtest",
            help="Run R16 CF single-factor research backtest summaries.",
        )
        single_factor_parser.add_argument("--start", required=True)
        single_factor_parser.add_argument("--end", required=True)
        single_factor_parser.add_argument(
            "--factor-ids",
            default="mom_20_v1,carry_nf_v1,curve_slope_v1,oi_pressure_v1",
        )
        single_factor_parser.add_argument("--horizons", default="1,3,5")
        single_factor_parser.add_argument("--diagnostic-path", type=Path)
        single_factor_parser.add_argument("--forward-return-path", type=Path)
        single_factor_parser.add_argument("--output-dir", type=Path)
        single_factor_parser.add_argument("--report-output-dir", type=Path)
        single_factor_parser.add_argument("--run-id")
        single_factor_parser.add_argument("--use-processed-value", action="store_true")
        single_factor_parser.add_argument("--use-raw-value", action="store_true")
        multifactor_parser = research_subparsers.add_parser(
            "build-cf-multifactor-diagnostics",
            help="Build R17 CF equal-weight multifactor score diagnostics.",
        )
        multifactor_parser.add_argument("--start", required=True)
        multifactor_parser.add_argument("--end", required=True)
        multifactor_parser.add_argument(
            "--factor-ids",
            default="mom_20_v1,carry_nf_v1,curve_slope_v1,oi_pressure_v1",
        )
        multifactor_parser.add_argument("--diagnostic-path", type=Path)
        multifactor_parser.add_argument("--output-dir", type=Path)
        multifactor_parser.add_argument("--report-output-dir", type=Path)
        multifactor_parser.add_argument("--run-id")
        multifactor_parser.add_argument("--score-id", default="cf_equal_weight_v1")
        multifactor_parser.add_argument("--use-processed-value", action="store_true")
        multifactor_parser.add_argument("--use-raw-value", action="store_true")
        multifactor_parser.add_argument("--require-all-factors", action="store_true")
        multifactor_parser.add_argument("--allow-missing-factors", action="store_true")
        cost_parser = research_subparsers.add_parser(
            "build-cf-cost-sensitivity",
            help="Build R18 CF research cost sensitivity summaries.",
        )
        cost_parser.add_argument("--start", required=True)
        cost_parser.add_argument("--end", required=True)
        cost_parser.add_argument("--horizons", default="1,3,5")
        cost_parser.add_argument("--score-path", type=Path)
        cost_parser.add_argument("--forward-return-path", type=Path)
        cost_parser.add_argument("--scenario-cost-bps")
        cost_parser.add_argument("--output-dir", type=Path)
        cost_parser.add_argument("--report-output-dir", type=Path)
        cost_parser.add_argument("--run-id")
        cost_parser.add_argument("--use-processed-score", action="store_true")
        cost_parser.add_argument("--use-raw-score", action="store_true")
        brief_parser = research_subparsers.add_parser(
            "build-cf-daily-brief",
            help="Build R19 CF daily research brief.",
        )
        brief_parser.add_argument("--date", required=True)
        brief_parser.add_argument("--start")
        brief_parser.add_argument("--end")
        brief_parser.add_argument("--quality-csv-path", type=Path)
        brief_parser.add_argument("--chain-map-path", type=Path)
        brief_parser.add_argument("--trade-mapping-path", type=Path)
        brief_parser.add_argument("--diagnostic-path", type=Path)
        brief_parser.add_argument("--single-factor-evaluation-path", type=Path)
        brief_parser.add_argument("--multifactor-score-path", type=Path)
        brief_parser.add_argument("--cost-sensitivity-path", type=Path)
        brief_parser.add_argument("--report-output-dir", type=Path)
        brief_parser.add_argument("--run-id")
        latest_signal_parser = research_subparsers.add_parser(
            "build-cf-latest-signal-brief",
            help="Build R23 CF latest signal-only brief.",
        )
        latest_signal_parser.add_argument("--date")
        latest_signal_parser.add_argument("--core-quote-path", type=Path)
        latest_signal_parser.add_argument("--output-root", type=Path)
        latest_signal_parser.add_argument("--run-id")
        latest_signal_parser.add_argument("--lookback-days", type=int, default=20)
        latest_signal_parser.add_argument("--trend-rule-candidate-path", type=Path)
        latest_signal_parser.add_argument("--signal-matrix-path", type=Path)
        latest_signal_parser.add_argument("--signal-threshold-research-path", type=Path)
        trend_continuity_parser = research_subparsers.add_parser(
            "build-cf-trend-continuity-board",
            help="Build R29 CF latest trend continuity board.",
        )
        trend_continuity_parser.add_argument("--date")
        trend_continuity_parser.add_argument("--core-quote-path", type=Path)
        trend_continuity_parser.add_argument("--output-root", type=Path)
        trend_continuity_parser.add_argument("--run-id")
        trend_continuity_parser.add_argument("--lookback-trading-days", type=int, default=20)
        trend_continuity_parser.add_argument("--trend-rule-candidate-path", type=Path)
        trend_continuity_parser.add_argument(
            "--trend-quality-calibration-manifest-path",
            type=Path,
        )
        daily_audit_parser = research_subparsers.add_parser(
            "build-cf-daily-operation-audit",
            help="Build R34 CF daily operation audit.",
        )
        daily_audit_parser.add_argument("--latest-signal-json-path", type=Path, required=True)
        daily_audit_parser.add_argument("--trend-board-json-path", type=Path, required=True)
        daily_audit_parser.add_argument("--core-quote-path", type=Path)
        daily_audit_parser.add_argument("--output-root", type=Path)
        daily_audit_parser.add_argument("--run-id")
        data_continuity_parser = research_subparsers.add_parser(
            "build-cf-data-continuity-audit",
            help="Build R63 CF data continuity and retained-source audit.",
        )
        data_continuity_parser.add_argument("--date")
        data_continuity_parser.add_argument("--core-quote-path", type=Path)
        data_continuity_parser.add_argument("--option-core-path", type=Path)
        data_continuity_parser.add_argument("--calendar-path", type=Path)
        data_continuity_parser.add_argument("--official-daily-fetch-json-path", type=Path)
        data_continuity_parser.add_argument("--raw-root", type=Path)
        data_continuity_parser.add_argument("--output-root", type=Path)
        data_continuity_parser.add_argument("--run-id")
        data_continuity_parser.add_argument("--no-require-options", action="store_true")
        data_continuity_parser.add_argument("--skip-raw-retention", action="store_true")
        signal_matrix_parser = research_subparsers.add_parser(
            "build-cf-signal-matrix",
            help="Build R35 CF multi-horizon signal matrix.",
        )
        signal_matrix_parser.add_argument("--start")
        signal_matrix_parser.add_argument("--end")
        signal_matrix_parser.add_argument("--horizons", default="1,3,5,10,20,40")
        signal_matrix_parser.add_argument("--core-quote-path", type=Path)
        signal_matrix_parser.add_argument("--output-dir", type=Path)
        signal_matrix_parser.add_argument("--report-output-dir", type=Path)
        signal_matrix_parser.add_argument("--run-id")
        signal_matrix_parser.add_argument("--trend-rule-candidate-path", type=Path)
        signal_matrix_parser.add_argument("--option-factor-path", type=Path)
        signal_matrix_validation_parser = research_subparsers.add_parser(
            "build-cf-signal-matrix-validation",
            help="Build R36 rolling validation for the R35 signal matrix.",
        )
        signal_matrix_validation_parser.add_argument(
            "--signal-matrix-path",
            type=Path,
            required=True,
        )
        signal_matrix_validation_parser.add_argument("--core-quote-path", type=Path)
        signal_matrix_validation_parser.add_argument("--output-dir", type=Path)
        signal_matrix_validation_parser.add_argument("--report-output-dir", type=Path)
        signal_matrix_validation_parser.add_argument("--run-id")
        signal_matrix_validation_parser.add_argument("--windows")
        signal_threshold_parser = research_subparsers.add_parser(
            "build-cf-signal-threshold-research",
            help="Build R37 CF threshold and weighting research.",
        )
        signal_threshold_parser.add_argument(
            "--validation-daily-path",
            type=Path,
            required=True,
        )
        signal_threshold_parser.add_argument("--output-dir", type=Path)
        signal_threshold_parser.add_argument("--report-output-dir", type=Path)
        signal_threshold_parser.add_argument("--run-id")
        historical_evidence_parser = research_subparsers.add_parser(
            "build-cf-historical-evidence-pack",
            help="Build R41 CF historical multi-factor evidence pack.",
        )
        historical_evidence_parser.add_argument("--core-quote-path", type=Path)
        historical_evidence_parser.add_argument("--signal-matrix-path", type=Path)
        historical_evidence_parser.add_argument("--validation-daily-path", type=Path)
        historical_evidence_parser.add_argument("--validation-window-summary-path", type=Path)
        historical_evidence_parser.add_argument("--threshold-weighting-path", type=Path)
        historical_evidence_parser.add_argument("--output-dir", type=Path)
        historical_evidence_parser.add_argument("--report-output-dir", type=Path)
        historical_evidence_parser.add_argument("--run-id")
        historical_evidence_parser.add_argument("--cost-scenarios")
        event_explanation_parser = research_subparsers.add_parser(
            "build-cf-historical-event-explanation",
            help="Build R42 CF full-history event explanations.",
        )
        event_explanation_parser.add_argument("--validation-daily-path", type=Path)
        event_explanation_parser.add_argument("--output-dir", type=Path)
        event_explanation_parser.add_argument("--report-output-dir", type=Path)
        event_explanation_parser.add_argument("--run-id")
        event_explanation_parser.add_argument("--primary-horizon", type=int, default=20)
        event_explanation_parser.add_argument("--horizons", default="1,3,5,10,20")
        event_explanation_parser.add_argument("--fundamental-context-path", type=Path)
        event_threshold_parser = research_subparsers.add_parser(
            "build-cf-event-threshold-sensitivity",
            help="Build R60 CF event threshold sensitivity review.",
        )
        event_threshold_parser.add_argument("--validation-daily-path", type=Path)
        event_threshold_parser.add_argument("--event-path", type=Path)
        event_threshold_parser.add_argument("--output-dir", type=Path)
        event_threshold_parser.add_argument("--report-output-dir", type=Path)
        event_threshold_parser.add_argument("--run-id")
        event_threshold_parser.add_argument("--primary-horizon", type=int, default=20)
        event_threshold_parser.add_argument("--horizons", default="1,3,5,10,20")
        event_threshold_parser.add_argument(
            "--threshold-quantiles",
            default="0.90,0.95,0.975",
        )
        event_threshold_parser.add_argument("--min-observation-count", type=int, default=20)
        event_threshold_review_parser = research_subparsers.add_parser(
            "build-cf-event-threshold-review-ledger",
            help="Build R62 CF event threshold review ledger.",
        )
        event_threshold_review_parser.add_argument("--threshold-summary-path", type=Path)
        event_threshold_review_parser.add_argument("--threshold-detail-path", type=Path)
        event_threshold_review_parser.add_argument("--event-detail-path", type=Path)
        event_threshold_review_parser.add_argument("--output-dir", type=Path)
        event_threshold_review_parser.add_argument("--report-output-dir", type=Path)
        event_threshold_review_parser.add_argument("--run-id")
        event_threshold_review_parser.add_argument("--example-event-count", type=int, default=3)
        validated_brief_parser = research_subparsers.add_parser(
            "build-cf-validated-research-brief",
            help="Build R43 CF validated Chinese research brief.",
        )
        validated_brief_parser.add_argument("--latest-signal-json-path", type=Path)
        validated_brief_parser.add_argument("--historical-evidence-decay-path", type=Path)
        validated_brief_parser.add_argument("--historical-evidence-stability-path", type=Path)
        validated_brief_parser.add_argument("--event-summary-path", type=Path)
        validated_brief_parser.add_argument("--event-detail-path", type=Path)
        validated_brief_parser.add_argument("--event-threshold-summary-path", type=Path)
        validated_brief_parser.add_argument("--fundamental-observation-json-path", type=Path)
        validated_brief_parser.add_argument("--futures-option-divergence-json-path", type=Path)
        validated_brief_parser.add_argument("--futures-option-playbook-json-path", type=Path)
        validated_brief_parser.add_argument("--current-watch-window-json-path", type=Path)
        validated_brief_parser.add_argument("--state-transition-json-path", type=Path)
        validated_brief_parser.add_argument("--option-volatility-json-path", type=Path)
        validated_brief_parser.add_argument("--output-dir", type=Path)
        validated_brief_parser.add_argument("--daily-output-root", type=Path)
        validated_brief_parser.add_argument("--run-id")
        publish_pack_parser = research_subparsers.add_parser(
            "build-cf-publish-pack",
            help="Build R45 CF chart and WeChat publish pack.",
        )
        publish_pack_parser.add_argument("--latest-signal-json-path", type=Path)
        publish_pack_parser.add_argument("--validated-brief-path", type=Path)
        publish_pack_parser.add_argument("--core-quote-path", type=Path)
        publish_pack_parser.add_argument("--signal-matrix-path", type=Path)
        publish_pack_parser.add_argument("--historical-evidence-decay-path", type=Path)
        publish_pack_parser.add_argument("--event-summary-path", type=Path)
        publish_pack_parser.add_argument("--futures-option-divergence-json-path", type=Path)
        publish_pack_parser.add_argument("--futures-option-playbook-json-path", type=Path)
        publish_pack_parser.add_argument("--current-watch-window-json-path", type=Path)
        publish_pack_parser.add_argument("--output-root", type=Path)
        publish_pack_parser.add_argument("--run-id")
        publish_pack_parser.add_argument("--price-lookback", type=int, default=120)
        weekly_audit_parser = research_subparsers.add_parser(
            "build-cf-weekly-research-audit",
            help="Build R59 CF weekly research audit.",
        )
        weekly_audit_parser.add_argument("--weekly-manifest-path", type=Path, required=True)
        weekly_audit_parser.add_argument("--output-dir", type=Path)
        weekly_audit_parser.add_argument("--run-id")
        stage_decision_parser = research_subparsers.add_parser(
            "build-cf-stage-decision-pack",
            help="Build R65 CF stage decision pack before expansion review.",
        )
        stage_decision_parser.add_argument("--weekly-audit-json-path", type=Path, required=True)
        stage_decision_parser.add_argument("--expansion-gate-json-path", type=Path, required=True)
        stage_decision_parser.add_argument("--latest-signal-json-path", type=Path)
        stage_decision_parser.add_argument("--option-factor-json-path", type=Path)
        stage_decision_parser.add_argument("--event-threshold-json-path", type=Path)
        stage_decision_parser.add_argument("--output-dir", type=Path)
        stage_decision_parser.add_argument("--daily-output-root", type=Path)
        stage_decision_parser.add_argument("--run-id")
        event_lifecycle_parser = research_subparsers.add_parser(
            "build-cf-event-lifecycle-research",
            help="Build R68 CF event lifecycle and simple TBM labels.",
        )
        event_lifecycle_parser.add_argument("--signal-matrix-path", type=Path)
        event_lifecycle_parser.add_argument("--output-dir", type=Path)
        event_lifecycle_parser.add_argument("--report-output-dir", type=Path)
        event_lifecycle_parser.add_argument("--run-id")
        event_lifecycle_parser.add_argument("--horizon", type=int, default=20)
        event_lifecycle_parser.add_argument("--max-holding-days", type=int, default=20)
        event_lifecycle_parser.add_argument("--profit-barrier", type=float, default=0.03)
        event_lifecycle_parser.add_argument("--stop-loss-barrier", type=float, default=0.015)
        state_transition_parser = research_subparsers.add_parser(
            "build-cf-state-transition-competing-risk",
            help="Build R79 CF state-transition competing-risk evidence.",
        )
        state_transition_parser.add_argument("--event-lifecycle-episode-path", type=Path)
        state_transition_parser.add_argument("--output-dir", type=Path)
        state_transition_parser.add_argument("--report-output-dir", type=Path)
        state_transition_parser.add_argument("--run-id")
        state_transition_parser.add_argument("--max-age-days", type=int, default=20)
        state_transition_parser.add_argument("--min-sample-size", type=int, default=30)
        divergence_parser = research_subparsers.add_parser(
            "build-cf-futures-option-divergence-research",
            help="Build R69 CF futures-option divergence battle research.",
        )
        divergence_parser.add_argument("--signal-matrix-validation-path", type=Path)
        divergence_parser.add_argument("--option-factor-path", type=Path)
        divergence_parser.add_argument("--event-lifecycle-episode-path", type=Path)
        divergence_parser.add_argument("--event-lifecycle-tbm-path", type=Path)
        divergence_parser.add_argument("--output-dir", type=Path)
        divergence_parser.add_argument("--report-output-dir", type=Path)
        divergence_parser.add_argument("--run-id")
        divergence_parser.add_argument("--horizons", default="1,3,5,10,20,40")
        divergence_parser.add_argument("--dead-zone-bps", type=int, default=10)
        divergence_parser.add_argument("--min-sample-size", type=int, default=30)
        dynamic_wall_parser = research_subparsers.add_parser(
            "build-cf-futures-option-dynamic-wall-research",
            help="Build R93N CF dynamic option-wall and incremental research.",
        )
        dynamic_wall_parser.add_argument("--option-core-path", type=Path)
        dynamic_wall_parser.add_argument("--core-quote-path", type=Path)
        dynamic_wall_parser.add_argument("--option-factor-path", type=Path)
        dynamic_wall_parser.add_argument("--signal-matrix-path", type=Path)
        dynamic_wall_parser.add_argument("--trend-phase-path", type=Path)
        dynamic_wall_parser.add_argument("--option-strike-position-path", type=Path)
        dynamic_wall_parser.add_argument("--start", type=date.fromisoformat)
        dynamic_wall_parser.add_argument("--end", type=date.fromisoformat)
        dynamic_wall_parser.add_argument("--horizons", default="1,3,5")
        dynamic_wall_parser.add_argument("--local-band-ratio", type=float, default=0.03)
        dynamic_wall_parser.add_argument("--touch-band-ratio", type=float, default=0.01)
        dynamic_wall_parser.add_argument("--wall-change-bps", type=int, default=50)
        dynamic_wall_parser.add_argument("--wall-shift-bps", type=int, default=50)
        dynamic_wall_parser.add_argument("--min-sample-size", type=int, default=30)
        dynamic_wall_parser.add_argument("--fdr-level", type=float, default=0.10)
        dynamic_wall_parser.add_argument("--dead-zone-bps", type=int, default=10)
        dynamic_wall_parser.add_argument("--tbm-vol-multiplier", type=float, default=1.0)
        dynamic_wall_parser.add_argument("--output-dir", type=Path)
        dynamic_wall_parser.add_argument("--report-output-dir", type=Path)
        dynamic_wall_parser.add_argument("--run-id")
        event_path_parser = research_subparsers.add_parser(
            "build-cf-futures-option-event-path-research",
            help="Build R93P CF futures-option event path and purged LOO research.",
        )
        event_path_parser.add_argument("--event-path", type=Path)
        event_path_parser.add_argument("--event-lifecycle-label-path", type=Path)
        event_path_parser.add_argument("--feature-path", type=Path)
        event_path_parser.add_argument("--start", type=date.fromisoformat)
        event_path_parser.add_argument("--end", type=date.fromisoformat)
        event_path_parser.add_argument("--horizons", default="1,3,5")
        event_path_parser.add_argument("--dead-zone-bps", type=int, default=10)
        event_path_parser.add_argument("--min-sample-size", type=int, default=30)
        event_path_parser.add_argument("--fdr-level", type=float, default=0.10)
        event_path_parser.add_argument("--purge-gap-sessions", type=int, default=5)
        event_path_parser.add_argument("--output-dir", type=Path)
        event_path_parser.add_argument("--report-output-dir", type=Path)
        event_path_parser.add_argument("--run-id")
        regime_interaction_parser = research_subparsers.add_parser(
            "build-cf-futures-option-regime-interaction-research",
            help="Build R93Q CF futures-option regime interaction research.",
        )
        regime_interaction_parser.add_argument("--event-path", type=Path)
        regime_interaction_parser.add_argument("--checkpoint-path", type=Path)
        regime_interaction_parser.add_argument("--path-path", type=Path)
        regime_interaction_parser.add_argument("--feature-path", type=Path)
        regime_interaction_parser.add_argument("--policy-context-path", type=Path)
        regime_interaction_parser.add_argument("--fundamental-context-path", type=Path)
        regime_interaction_parser.add_argument("--start", type=date.fromisoformat)
        regime_interaction_parser.add_argument("--end", type=date.fromisoformat)
        regime_interaction_parser.add_argument("--horizons", default="1,3,5")
        regime_interaction_parser.add_argument("--episode-gap-sessions", type=int, default=1)
        regime_interaction_parser.add_argument("--chain-window-sessions", type=int, default=5)
        regime_interaction_parser.add_argument("--min-sample-size", type=int, default=30)
        regime_interaction_parser.add_argument("--min-cell-size", type=int, default=5)
        regime_interaction_parser.add_argument("--fdr-level", type=float, default=0.10)
        regime_interaction_parser.add_argument("--permutation-count", type=int, default=1000)
        regime_interaction_parser.add_argument("--purge-gap-sessions", type=int, default=5)
        regime_interaction_parser.add_argument("--random-seed", type=int, default=93)
        regime_interaction_parser.add_argument("--output-dir", type=Path)
        regime_interaction_parser.add_argument("--report-output-dir", type=Path)
        regime_interaction_parser.add_argument("--run-id")
        divergence_playbook_parser = research_subparsers.add_parser(
            "build-cf-futures-option-divergence-playbook",
            help="Build R71 CF futures-option divergence playbook.",
        )
        divergence_playbook_parser.add_argument("--event-path", type=Path)
        divergence_playbook_parser.add_argument("--node-summary-path", type=Path)
        divergence_playbook_parser.add_argument("--latest-signal-json-path", type=Path)
        divergence_playbook_parser.add_argument("--output-dir", type=Path)
        divergence_playbook_parser.add_argument("--report-output-dir", type=Path)
        divergence_playbook_parser.add_argument("--run-id")
        divergence_playbook_parser.add_argument("--min-sample-size", type=int, default=30)
        divergence_playbook_parser.add_argument("--edge-threshold", type=float, default=0.08)
        dual_price_parser = research_subparsers.add_parser(
            "build-cf-dual-price-state",
            help="Build R73 close/settlement dual-price state research.",
        )
        dual_price_parser.add_argument("--core-quote-path", type=Path)
        dual_price_parser.add_argument("--output-dir", type=Path)
        dual_price_parser.add_argument("--report-output-dir", type=Path)
        dual_price_parser.add_argument("--run-id")
        dual_price_parser.add_argument("--ma-window", type=int, default=20)
        dual_price_parser.add_argument("--gap-alert-bps", type=float, default=25.0)
        chain_oi_parser = research_subparsers.add_parser(
            "build-cf-chain-oi-structure",
            help="Build R74 chain OI and roll decomposition research.",
        )
        chain_oi_parser.add_argument("--core-quote-path", type=Path)
        chain_oi_parser.add_argument("--output-dir", type=Path)
        chain_oi_parser.add_argument("--report-output-dir", type=Path)
        chain_oi_parser.add_argument("--run-id")
        chain_oi_parser.add_argument("--noise-ratio", type=float, default=0.002)
        chain_oi_parser.add_argument("--roll-transfer-threshold", type=float, default=0.50)
        chain_oi_parser.add_argument("--roll-lookback-days", type=int, default=5)
        delivery_curve_parser = research_subparsers.add_parser(
            "build-cf-delivery-adjusted-curve",
            help="Build a CF delivery-cost-adjusted calendar-spread study.",
        )
        delivery_curve_parser.add_argument("--core-quote-path", type=Path)
        delivery_curve_parser.add_argument("--near-contract", default="CF609")
        delivery_curve_parser.add_argument("--far-contract", default="CF611")
        delivery_curve_parser.add_argument(
            "--start", type=date.fromisoformat, default=date(2026, 1, 9)
        )
        delivery_curve_parser.add_argument("--end", type=date.fromisoformat)
        delivery_curve_parser.add_argument("--aging-discount", type=float, default=248.0)
        delivery_curve_parser.add_argument(
            "--storage-cost-per-ton-day", type=float, default=48.07 / 62.0
        )
        delivery_curve_parser.add_argument(
            "--annual-financing-rate", type=float, default=0.025
        )
        delivery_curve_parser.add_argument("--holding-days", type=int, default=62)
        delivery_curve_parser.add_argument("--near-zero-band", type=float, default=20.0)
        delivery_curve_parser.add_argument("--min-history-days", type=int, default=30)
        delivery_curve_parser.add_argument("--output-dir", type=Path)
        delivery_curve_parser.add_argument("--report-output-dir", type=Path)
        delivery_curve_parser.add_argument("--run-id")
        structural_attribution_parser = research_subparsers.add_parser(
            "build-cf-structural-position-attribution",
            help="Build layered CF611 futures/member/receipt/option attribution.",
        )
        structural_attribution_parser.add_argument("--core-quote-path", type=Path)
        structural_attribution_parser.add_argument("--member-detail-path", type=Path)
        structural_attribution_parser.add_argument(
            "--warehouse-receipt-path", type=Path
        )
        structural_attribution_parser.add_argument(
            "--option-strike-position-path", type=Path
        )
        structural_attribution_parser.add_argument("--option-factor-path", type=Path)
        structural_attribution_parser.add_argument(
            "--delivery-adjusted-curve-path", type=Path
        )
        structural_attribution_parser.add_argument(
            "--target-contract", default="CF611"
        )
        structural_attribution_parser.add_argument(
            "--source-contract", default="CF609"
        )
        structural_attribution_parser.add_argument("--next-contract", default="CF701")
        structural_attribution_parser.add_argument(
            "--focus-start", type=date.fromisoformat, default=date(2026, 5, 15)
        )
        structural_attribution_parser.add_argument(
            "--focus-end", type=date.fromisoformat
        )
        structural_attribution_parser.add_argument(
            "--option-horizons", default="1,3,5,10"
        )
        structural_attribution_parser.add_argument(
            "--wall-distance", type=float, default=0.01
        )
        structural_attribution_parser.add_argument(
            "--option-oi-noise-ratio", type=float, default=0.005
        )
        structural_attribution_parser.add_argument(
            "--contract-tons", type=float, default=5.0
        )
        structural_attribution_parser.add_argument(
            "--receipt-tons", type=float, default=40.0
        )
        structural_attribution_parser.add_argument("--output-dir", type=Path)
        structural_attribution_parser.add_argument("--report-output-dir", type=Path)
        structural_attribution_parser.add_argument("--run-id")
        oi_roll_parser = research_subparsers.add_parser(
            "build-cf-oi-roll-window-research",
            help="Build R78 multi-window OI roll evidence research.",
        )
        oi_roll_parser.add_argument("--core-quote-path", type=Path)
        oi_roll_parser.add_argument("--validation-daily-path", type=Path)
        oi_roll_parser.add_argument("--exclusion-path", type=Path)
        oi_roll_parser.add_argument("--end", type=date.fromisoformat)
        oi_roll_parser.add_argument("--windows", default="3,5,10")
        oi_roll_parser.add_argument("--min-sample-size", type=int, default=30)
        oi_roll_parser.add_argument("--output-dir", type=Path)
        oi_roll_parser.add_argument("--report-output-dir", type=Path)
        oi_roll_parser.add_argument("--run-id")
        option_structure_parser = research_subparsers.add_parser(
            "build-cf-option-structure-research",
            help="Build R75 dynamic option structure research.",
        )
        option_structure_parser.add_argument("--option-factor-path", type=Path)
        option_structure_parser.add_argument("--signal-matrix-path", type=Path)
        option_structure_parser.add_argument("--validation-daily-path", type=Path)
        option_structure_parser.add_argument("--output-dir", type=Path)
        option_structure_parser.add_argument("--report-output-dir", type=Path)
        option_structure_parser.add_argument("--run-id")
        option_structure_parser.add_argument("--primary-horizon", type=int, default=20)
        phase_v2_parser = research_subparsers.add_parser(
            "build-cf-trend-phase-v2",
            help="Build R76 evidence-aware trend phase v2.",
        )
        phase_v2_parser.add_argument("--dual-price-path", type=Path)
        phase_v2_parser.add_argument("--chain-oi-path", type=Path)
        phase_v2_parser.add_argument("--option-structure-path", type=Path)
        phase_v2_parser.add_argument("--signal-matrix-path", type=Path)
        phase_v2_parser.add_argument("--validation-daily-path", type=Path)
        phase_v2_parser.add_argument("--output-dir", type=Path)
        phase_v2_parser.add_argument("--report-output-dir", type=Path)
        phase_v2_parser.add_argument("--run-id")
        phase_v2_parser.add_argument("--primary-horizon", type=int, default=20)
        symmetric_trend_parser = research_subparsers.add_parser(
            "build-cf-symmetric-trend-research",
            help="Build R93A symmetric trend and breakout timing research.",
        )
        symmetric_trend_parser.add_argument("--continuous-price-path", type=Path)
        symmetric_trend_parser.add_argument("--trend-context-path", type=Path)
        symmetric_trend_parser.add_argument("--output-dir", type=Path)
        symmetric_trend_parser.add_argument("--report-output-dir", type=Path)
        symmetric_trend_parser.add_argument("--run-id")
        symmetric_trend_parser.add_argument("--fast-window", type=int, default=20)
        symmetric_trend_parser.add_argument("--slow-window", type=int, default=40)
        symmetric_trend_parser.add_argument("--breakout-window", type=int, default=20)
        symmetric_trend_parser.add_argument("--breakout-cooldown", type=int, default=5)
        symmetric_trend_parser.add_argument("--horizons", default="1,3,5,10,20")
        symmetric_trend_parser.add_argument("--dead-zone-bps", type=int, default=10)
        symmetric_trend_parser.add_argument("--min-sample-size", type=int, default=30)
        trend_option_timing_parser = research_subparsers.add_parser(
            "build-cf-trend-option-timing-research",
            help="Build R93B trend-environment and option-timing evidence.",
        )
        trend_option_timing_parser.add_argument(
            "--symmetric-trend-daily-path", type=Path
        )
        trend_option_timing_parser.add_argument("--breakout-event-path", type=Path)
        trend_option_timing_parser.add_argument("--option-structure-path", type=Path)
        trend_option_timing_parser.add_argument("--strike-position-path", type=Path)
        trend_option_timing_parser.add_argument("--output-dir", type=Path)
        trend_option_timing_parser.add_argument("--report-output-dir", type=Path)
        trend_option_timing_parser.add_argument("--run-id")
        trend_option_timing_parser.add_argument("--rank-window", type=int, default=252)
        trend_option_timing_parser.add_argument(
            "--rank-min-periods", type=int, default=60
        )
        trend_option_timing_parser.add_argument(
            "--min-sample-size", type=int, default=30
        )
        trend_option_timing_parser.add_argument(
            "--fdr-level", type=float, default=0.10
        )
        trend_confirmation_timing_parser = research_subparsers.add_parser(
            "build-cf-trend-confirmation-timing-research",
            help="Build R93L futures/option trend-confirmation timing evidence.",
        )
        trend_confirmation_timing_parser.add_argument(
            "--symmetric-trend-daily-path", type=Path
        )
        trend_confirmation_timing_parser.add_argument(
            "--breakout-event-path", type=Path
        )
        trend_confirmation_timing_parser.add_argument("--chain-oi-path", type=Path)
        trend_confirmation_timing_parser.add_argument(
            "--option-structure-path", type=Path
        )
        trend_confirmation_timing_parser.add_argument("--output-dir", type=Path)
        trend_confirmation_timing_parser.add_argument(
            "--report-output-dir", type=Path
        )
        trend_confirmation_timing_parser.add_argument("--run-id")
        trend_confirmation_timing_parser.add_argument(
            "--horizons", default="5,20"
        )
        trend_confirmation_timing_parser.add_argument(
            "--pre-window-sessions", type=int, default=10
        )
        trend_confirmation_timing_parser.add_argument(
            "--post-window-sessions", type=int, default=20
        )
        trend_confirmation_timing_parser.add_argument(
            "--confirmation-days", type=int, default=2
        )
        trend_confirmation_timing_parser.add_argument(
            "--min-sample-size", type=int, default=15
        )
        trend_confirmation_timing_parser.add_argument(
            "--fdr-level", type=float, default=0.10
        )
        trend_confirmation_timing_parser.add_argument(
            "--min-annual-coverage-years", type=int, default=3
        )
        trend_confirmation_timing_parser.add_argument(
            "--min-annual-group-size", type=int, default=2
        )
        trend_confirmation_timing_parser.add_argument(
            "--min-annual-direction-consistency", type=float, default=0.75
        )
        trend_confirmation_timing_parser.add_argument(
            "--volume-rank-window", type=int, default=252
        )
        trend_confirmation_timing_parser.add_argument(
            "--volume-rank-min-periods", type=int, default=60
        )
        trend_confirmation_timing_parser.add_argument(
            "--min-option-liquidity-score", type=float, default=20.0
        )
        trend_confirmation_timing_parser.add_argument(
            "--dead-zone-bps", type=int, default=10
        )
        option_maturity_confirmation_parser = research_subparsers.add_parser(
            "build-cf-option-maturity-confirmation-research",
            help="Build R93M option-maturity and as-of confirmation evidence.",
        )
        option_maturity_confirmation_parser.add_argument(
            "--option-core-path", type=Path
        )
        option_maturity_confirmation_parser.add_argument(
            "--trend-confirmation-event-path", type=Path
        )
        option_maturity_confirmation_parser.add_argument(
            "--trend-confirmation-trajectory-path", type=Path
        )
        option_maturity_confirmation_parser.add_argument("--output-dir", type=Path)
        option_maturity_confirmation_parser.add_argument(
            "--report-output-dir", type=Path
        )
        option_maturity_confirmation_parser.add_argument("--run-id")
        option_maturity_confirmation_parser.add_argument(
            "--horizons", default="5,20"
        )
        option_maturity_confirmation_parser.add_argument(
            "--checkpoints", default="0,1,3,5,10"
        )
        option_maturity_confirmation_parser.add_argument(
            "--confirmation-days", type=int, default=2
        )
        option_maturity_confirmation_parser.add_argument(
            "--activity-window", type=int, default=60
        )
        option_maturity_confirmation_parser.add_argument(
            "--activity-min-periods", type=int, default=20
        )
        option_maturity_confirmation_parser.add_argument(
            "--baseline-year", type=int, default=2021
        )
        option_maturity_confirmation_parser.add_argument(
            "--expansion-volume-ratio", type=float, default=1.50
        )
        option_maturity_confirmation_parser.add_argument(
            "--expansion-oi-ratio", type=float, default=1.25
        )
        option_maturity_confirmation_parser.add_argument(
            "--mature-volume-ratio", type=float, default=3.00
        )
        option_maturity_confirmation_parser.add_argument(
            "--mature-oi-ratio", type=float, default=2.50
        )
        option_maturity_confirmation_parser.add_argument(
            "--min-sample-size", type=int, default=5
        )
        option_maturity_confirmation_parser.add_argument(
            "--fdr-level", type=float, default=0.10
        )
        option_maturity_confirmation_parser.add_argument(
            "--dead-zone-bps", type=int, default=10
        )
        rebound_lifecycle_parser = research_subparsers.add_parser(
            "build-cf-rebound-lifecycle",
            help="Build R93I rebound lifecycle and posterior path evidence.",
        )
        rebound_lifecycle_parser.add_argument("--signal-matrix-path", type=Path)
        rebound_lifecycle_parser.add_argument(
            "--symmetric-trend-daily-path", type=Path
        )
        rebound_lifecycle_parser.add_argument("--option-structure-path", type=Path)
        rebound_lifecycle_parser.add_argument("--horizons", default="1,3,5,10,20")
        rebound_lifecycle_parser.add_argument(
            "--prepare-max-days", type=int, default=7
        )
        rebound_lifecycle_parser.add_argument(
            "--confirm-max-days", type=int, default=3
        )
        rebound_lifecycle_parser.add_argument(
            "--follow-max-days", type=int, default=10
        )
        rebound_lifecycle_parser.add_argument(
            "--break-buffer-bps", type=int, default=10
        )
        rebound_lifecycle_parser.add_argument(
            "--min-sample-size", type=int, default=30
        )
        rebound_lifecycle_parser.add_argument("--output-dir", type=Path)
        rebound_lifecycle_parser.add_argument("--report-output-dir", type=Path)
        rebound_lifecycle_parser.add_argument("--run-id")
        trend_candidate_stability_parser = research_subparsers.add_parser(
            "build-cf-trend-candidate-stability-research",
            help="Build R93C candidate stability and forward registration.",
        )
        trend_candidate_stability_parser.add_argument(
            "--event-feature-path", type=Path
        )
        trend_candidate_stability_parser.add_argument("--spec-path", type=Path)
        trend_candidate_stability_parser.add_argument("--output-dir", type=Path)
        trend_candidate_stability_parser.add_argument(
            "--report-output-dir", type=Path
        )
        trend_candidate_stability_parser.add_argument("--run-id")
        trend_candidate_forward_parser = research_subparsers.add_parser(
            "build-cf-trend-candidate-forward-ledger",
            help="Build R93D immutable candidate forward ledger.",
        )
        trend_candidate_forward_parser.add_argument(
            "--symmetric-trend-daily-path", type=Path
        )
        trend_candidate_forward_parser.add_argument("--breakout-event-path", type=Path)
        trend_candidate_forward_parser.add_argument(
            "--candidate-evaluation-path", type=Path
        )
        trend_candidate_forward_parser.add_argument("--spec-path", type=Path)
        trend_candidate_forward_parser.add_argument("--as-of-date")
        trend_candidate_forward_parser.add_argument("--ledger-root", type=Path)
        trend_candidate_forward_parser.add_argument(
            "--report-output-dir", type=Path
        )
        trend_candidate_forward_parser.add_argument("--run-id")
        trend_candidate_forward_parser.add_argument("--correction-reason")
        forward_evidence_weekly_parser = research_subparsers.add_parser(
            "build-cf-forward-evidence-weekly",
            help="Build R93E weekly strategy/candidate forward evidence summary.",
        )
        forward_evidence_weekly_parser.add_argument("--date")
        forward_evidence_weekly_parser.add_argument(
            "--strategy-ledger-root", type=Path
        )
        forward_evidence_weekly_parser.add_argument(
            "--candidate-ledger-path", type=Path
        )
        forward_evidence_weekly_parser.add_argument(
            "--candidate-event-root", type=Path
        )
        forward_evidence_weekly_parser.add_argument(
            "--candidate-run-json-path", type=Path
        )
        forward_evidence_weekly_parser.add_argument("--output-dir", type=Path)
        forward_evidence_weekly_parser.add_argument(
            "--report-output-dir", type=Path
        )
        forward_evidence_weekly_parser.add_argument("--run-id")
        watch_window_parser = research_subparsers.add_parser(
            "build-cf-current-watch-window",
            help="Build R77 current confirmation/invalidation watch window.",
        )
        watch_window_parser.add_argument("--latest-signal-json-path", type=Path)
        watch_window_parser.add_argument("--dual-price-path", type=Path)
        watch_window_parser.add_argument("--chain-oi-path", type=Path)
        watch_window_parser.add_argument("--option-structure-path", type=Path)
        watch_window_parser.add_argument("--trend-phase-v2-path", type=Path)
        watch_window_parser.add_argument("--playbook-json-path", type=Path)
        watch_window_parser.add_argument("--core-quote-path", type=Path)
        watch_window_parser.add_argument("--output-dir", type=Path)
        watch_window_parser.add_argument("--report-output-dir", type=Path)
        watch_window_parser.add_argument("--daily-output-root", type=Path)
        watch_window_parser.add_argument("--run-id")
        official_daily_parser = research_subparsers.add_parser(
            "fetch-cf-official-daily-files",
            help="Fetch CF official futures/options daily files into incoming storage.",
        )
        official_daily_parser.add_argument("--date")
        official_daily_parser.add_argument("--futures-source-dir", type=Path)
        official_daily_parser.add_argument("--options-source-dir", type=Path)
        official_daily_parser.add_argument("--report-output-dir", type=Path)
        official_daily_parser.add_argument("--run-id")
        official_daily_parser.add_argument("--skip-options", action="store_true")
        official_daily_parser.add_argument("--overwrite", action="store_true")
        official_daily_parser.add_argument("--futures-url")
        official_daily_parser.add_argument("--options-url")
        option_strike_parser = research_subparsers.add_parser(
            "build-cf-option-strike-position-research",
            help="Build R84 CF option strike OI key-level research.",
        )
        option_strike_parser.add_argument("--option-core-path", type=Path)
        option_strike_parser.add_argument("--core-quote-path", type=Path)
        option_strike_parser.add_argument("--option-expiry-path", type=Path)
        option_strike_parser.add_argument("--end", type=_parse_iso_date)
        option_strike_parser.add_argument("--horizons", default="1,3,5,10")
        option_strike_parser.add_argument("--near-level-ratio", type=float, default=0.01)
        option_strike_parser.add_argument("--min-sample-size", type=int, default=30)
        option_strike_parser.add_argument("--output-dir", type=Path)
        option_strike_parser.add_argument("--report-output-dir", type=Path)
        option_strike_parser.add_argument("--run-id")
        member_fetch_parser = research_subparsers.add_parser(
            "fetch-cf-official-member-position",
            help="Download one official CF member-position workbook.",
        )
        member_fetch_parser.add_argument("--date", required=True)
        member_fetch_parser.add_argument("--source-dir", type=Path)
        member_fetch_parser.add_argument("--report-output-dir", type=Path)
        member_fetch_parser.add_argument("--overwrite", action="store_true")
        member_fetch_parser.add_argument("--official-url")
        member_history_fetch_parser = research_subparsers.add_parser(
            "fetch-cf-official-member-position-history",
            help="Incrementally backfill R85 CF member-position history.",
        )
        member_history_fetch_parser.add_argument("--start", required=True)
        member_history_fetch_parser.add_argument("--end", required=True)
        member_history_fetch_parser.add_argument("--core-quote-path", type=Path)
        member_history_fetch_parser.add_argument("--source-dir", type=Path)
        member_history_fetch_parser.add_argument("--report-output-dir", type=Path)
        member_history_fetch_parser.add_argument("--overwrite", action="store_true")
        member_history_fetch_parser.add_argument("--max-workers", type=int, default=4)
        member_ingest_parser = research_subparsers.add_parser(
            "connect-cf-member-position-history",
            help="Preserve and normalize CF member-position history.",
        )
        member_ingest_parser.add_argument("--source-dir", type=Path)
        member_ingest_parser.add_argument("--raw-root", type=Path)
        member_ingest_parser.add_argument("--core-output-dir", type=Path)
        member_ingest_parser.add_argument("--output-path", type=Path)
        member_ingest_parser.add_argument("--report-output-dir", type=Path)
        member_ingest_parser.add_argument("--run-id")
        member_research_parser = research_subparsers.add_parser(
            "build-cf-member-position-research",
            help="Build R83 CF member concentration and roll evidence.",
        )
        member_research_parser.add_argument("--member-position-path", type=Path)
        member_research_parser.add_argument("--core-quote-path", type=Path)
        member_research_parser.add_argument("--validation-daily-path", type=Path)
        member_research_parser.add_argument("--end", type=_parse_iso_date)
        member_research_parser.add_argument("--top-ns", default="5,10,20")
        member_research_parser.add_argument("--horizons", default="1,3,5,10,20")
        member_research_parser.add_argument(
            "--position-change-dead-zone", type=float, default=0.002
        )
        member_research_parser.add_argument("--price-dead-zone", type=float, default=0.001)
        member_research_parser.add_argument("--min-sample-size", type=int, default=30)
        member_research_parser.add_argument("--min-history-days", type=int, default=60)
        member_research_parser.add_argument("--output-dir", type=Path)
        member_research_parser.add_argument("--report-output-dir", type=Path)
        member_research_parser.add_argument("--run-id")
        option_contract_parser = research_subparsers.add_parser(
            "build-cf-option-data-contract",
            help="Build R46 CF option data contract and incoming warning artifacts.",
        )
        option_contract_parser.add_argument("--source-dir", type=Path)
        option_contract_parser.add_argument("--core-output-dir", type=Path)
        option_contract_parser.add_argument("--output-path", type=Path)
        option_contract_parser.add_argument("--report-output-dir", type=Path)
        option_contract_parser.add_argument("--run-id")
        option_history_parser = research_subparsers.add_parser(
            "connect-cf-option-history",
            help="Connect R47 CF option history files into raw snapshots and core.",
        )
        option_history_parser.add_argument("--source-dir", type=Path)
        option_history_parser.add_argument("--raw-root", type=Path)
        option_history_parser.add_argument("--core-output-dir", type=Path)
        option_history_parser.add_argument("--output-path", type=Path)
        option_history_parser.add_argument("--core-quote-path", type=Path)
        option_history_parser.add_argument("--report-output-dir", type=Path)
        option_history_parser.add_argument("--run-id")
        option_history_parser.add_argument("--low-volume-threshold", type=int, default=1)
        option_history_parser.add_argument("--low-open-interest-threshold", type=int, default=1)
        option_history_parser.add_argument("--deep-otm-threshold", type=float, default=0.10)
        option_history_parser.add_argument("--near-expiry-days", type=int, default=31)
        option_factor_parser = research_subparsers.add_parser(
            "build-cf-option-factor-proxy",
            help="Build R48 CF option factor proxy research artifacts.",
        )
        option_factor_parser.add_argument("--option-core-path", type=Path)
        option_factor_parser.add_argument("--core-quote-path", type=Path)
        option_factor_parser.add_argument("--output-dir", type=Path)
        option_factor_parser.add_argument("--report-output-dir", type=Path)
        option_factor_parser.add_argument("--run-id")
        option_factor_parser.add_argument("--iv-rank-lookback-days", type=int, default=252)
        option_factor_parser.add_argument("--atm-moneyness-band", type=float, default=0.03)
        option_factor_parser.add_argument("--otm-moneyness-min", type=float, default=0.90)
        option_factor_parser.add_argument("--otm-moneyness-max", type=float, default=0.98)
        option_factor_parser.add_argument("--incremental", action="store_true")
        option_volatility_parser = research_subparsers.add_parser(
            "build-cf-option-volatility-term-structure",
            help="Build R80 CF expiry-aware IV/RV and term-structure evidence.",
        )
        option_volatility_parser.add_argument("--option-factor-path", type=Path)
        option_volatility_parser.add_argument("--core-quote-path", type=Path)
        option_volatility_parser.add_argument("--option-expiry-path", type=Path)
        option_volatility_parser.add_argument("--output-dir", type=Path)
        option_volatility_parser.add_argument("--report-output-dir", type=Path)
        option_volatility_parser.add_argument("--run-id")
        option_volatility_parser.add_argument("--risk-free-rate", type=float, default=0.02)
        option_volatility_parser.add_argument("--rv-window", type=int, default=20)
        option_volatility_parser.add_argument("--iv-rank-window", type=int, default=252)
        option_volatility_parser.add_argument("--horizons", default="5,10,20")
        option_volatility_parser.add_argument("--min-sample-size", type=int, default=30)
        product_registry_parser = research_subparsers.add_parser(
            "build-cf-product-research-registry",
            help="Build R50 CF product config and research factor registry snapshot.",
        )
        product_registry_parser.add_argument("--product-config-path", type=Path)
        product_registry_parser.add_argument("--factor-registry-path", type=Path)
        product_registry_parser.add_argument("--output-dir", type=Path)
        product_registry_parser.add_argument("--report-output-dir", type=Path)
        product_registry_parser.add_argument("--run-id")
        fundamental_contract_parser = research_subparsers.add_parser(
            "build-cf-fundamental-data-contract",
            help="Build R51 CF fundamental manual-input contract artifacts.",
        )
        fundamental_contract_parser.add_argument("--source-dir", type=Path)
        fundamental_contract_parser.add_argument("--output-dir", type=Path)
        fundamental_contract_parser.add_argument("--report-output-dir", type=Path)
        fundamental_contract_parser.add_argument("--run-id")
        fundamental_observation_parser = research_subparsers.add_parser(
            "build-cf-fundamental-observation",
            help="Build R53 CF manual fundamental observation artifacts.",
        )
        fundamental_observation_parser.add_argument("--source-dir", type=Path)
        fundamental_observation_parser.add_argument("--output-dir", type=Path)
        fundamental_observation_parser.add_argument("--report-output-dir", type=Path)
        fundamental_observation_parser.add_argument("--run-id")
        fundamental_context_parser = research_subparsers.add_parser(
            "build-cf-fundamental-context",
            help="Build R54 CF fundamental context artifacts.",
        )
        fundamental_context_parser.add_argument(
            "--fundamental-observation-json-path", type=Path
        )
        fundamental_context_parser.add_argument("--core-quote-path", type=Path)
        fundamental_context_parser.add_argument("--output-dir", type=Path)
        fundamental_context_parser.add_argument("--report-output-dir", type=Path)
        fundamental_context_parser.add_argument("--run-id")
        fundamental_context_parser.add_argument("--change-windows", default="1,4,12")
        trend_quality_parser = research_subparsers.add_parser(
            "build-cf-trend-quality-calibration",
            help="Build R32 CF trend quality historical calibration.",
        )
        trend_quality_parser.add_argument("--start")
        trend_quality_parser.add_argument("--end")
        trend_quality_parser.add_argument("--horizons", default="1,3,5,10,20")
        trend_quality_parser.add_argument("--core-quote-path", type=Path)
        trend_quality_parser.add_argument("--output-dir", type=Path)
        trend_quality_parser.add_argument("--report-output-dir", type=Path)
        trend_quality_parser.add_argument("--run-id")
        trend_quality_parser.add_argument("--trend-rule-candidate-path", type=Path)
        trend_phase_validation_parser = research_subparsers.add_parser(
            "build-cf-trend-phase-validation",
            help="Build R25 CF trend phase rolling validation.",
        )
        trend_phase_validation_parser.add_argument("--start", required=True)
        trend_phase_validation_parser.add_argument("--end", required=True)
        trend_phase_validation_parser.add_argument("--horizons", default="1,3,5,10,20")
        trend_phase_validation_parser.add_argument("--core-quote-path", type=Path)
        trend_phase_validation_parser.add_argument("--output-dir", type=Path)
        trend_phase_validation_parser.add_argument("--report-output-dir", type=Path)
        trend_phase_validation_parser.add_argument("--run-id")
        trend_phase_events_parser = research_subparsers.add_parser(
            "build-cf-trend-phase-events",
            help="Build R26 CF trend phase transition events.",
        )
        trend_phase_events_parser.add_argument("--start", required=True)
        trend_phase_events_parser.add_argument("--end", required=True)
        trend_phase_events_parser.add_argument("--horizons", default="1,3,5,10,20")
        trend_phase_events_parser.add_argument("--trend-phase-daily-path", type=Path)
        trend_phase_events_parser.add_argument("--core-quote-path", type=Path)
        trend_phase_events_parser.add_argument("--output-dir", type=Path)
        trend_phase_events_parser.add_argument("--report-output-dir", type=Path)
        trend_phase_events_parser.add_argument("--run-id")
        trend_rule_candidates_parser = research_subparsers.add_parser(
            "build-cf-trend-rule-candidates",
            help="Build R27 CF daily-brief trend rule candidates.",
        )
        trend_rule_candidates_parser.add_argument("--start", required=True)
        trend_rule_candidates_parser.add_argument("--end", required=True)
        trend_rule_candidates_parser.add_argument("--event-summary-path", type=Path)
        trend_rule_candidates_parser.add_argument("--event-path", type=Path)
        trend_rule_candidates_parser.add_argument("--output-dir", type=Path)
        trend_rule_candidates_parser.add_argument("--report-output-dir", type=Path)
        trend_rule_candidates_parser.add_argument("--run-id")
        trend_rule_candidates_parser.add_argument("--min-event-count", type=int, default=3)
        trend_rule_candidates_parser.add_argument("--min-observation-count", type=int, default=3)
        trend_rule_candidates_parser.add_argument(
            "--min-directional-hit-rate",
            type=float,
            default=0.60,
        )
        pipeline_parser = research_subparsers.add_parser(
            "run-cf-daily-pipeline",
            help="Run R20 one-command CF daily research pipeline.",
        )
        pipeline_parser.add_argument("--date", required=True)
        pipeline_parser.add_argument("--input-path", type=Path, required=True)
        pipeline_parser.add_argument("--start")
        pipeline_parser.add_argument("--end")
        pipeline_parser.add_argument("--raw-output-dir", type=Path)
        pipeline_parser.add_argument("--core-output-dir", type=Path)
        pipeline_parser.add_argument("--research-output-root", type=Path)
        pipeline_parser.add_argument("--report-output-root", type=Path)
        pipeline_parser.add_argument("--run-id")
        pipeline_parser.add_argument("--horizons", default="1,3,5")
        pipeline_parser.add_argument(
            "--factor-ids",
            default="mom_20_v1,carry_nf_v1,curve_slope_v1,oi_pressure_v1",
        )
        pipeline_parser.add_argument("--scenario-cost-bps")
        pipeline_parser.add_argument("--price-field", default="settle")
        pipeline_parser.add_argument("--lookback-periods", type=int, default=20)
        pipeline_parser.add_argument("--ltd-buffer-days", type=int, default=0)
        pipeline_parser.add_argument("--min-volume", type=int, default=1)
        pipeline_parser.add_argument("--allow-missing-factors", action="store_true")
        pipeline_parser.add_argument("--use-raw-value", action="store_true")
        pipeline_parser.add_argument("--use-raw-score", action="store_true")
        replay_pipeline_parser = research_subparsers.add_parser(
            "replay-cf-daily-pipeline",
            help="Replay-check preserved R20 CF research outputs.",
        )
        replay_pipeline_parser.add_argument("--pipeline-json-path", type=Path, required=True)
        replay_pipeline_parser.add_argument("--baseline-json-path", type=Path)
        replay_pipeline_parser.add_argument("--report-output-dir", type=Path)
        replay_pipeline_parser.add_argument("--run-id")
        replay_pipeline_parser.add_argument("--allow-incomplete-pipeline", action="store_true")
        expansion_gate_parser = research_subparsers.add_parser(
            "build-cf-expansion-gate",
            help="Build the R52 expansion gate report.",
        )
        expansion_gate_parser.add_argument(
            "--candidate-scope",
            default="SR_AP_OR_EXTERNAL_DATA",
        )
        expansion_gate_parser.add_argument("--pipeline-json-path", type=Path)
        expansion_gate_parser.add_argument("--replay-json-path", type=Path)
        expansion_gate_parser.add_argument("--historical-evidence-manifest-path", type=Path)
        expansion_gate_parser.add_argument("--event-explanation-manifest-path", type=Path)
        expansion_gate_parser.add_argument("--signal-matrix-manifest-path", type=Path)
        expansion_gate_parser.add_argument("--publish-pack-manifest-path", type=Path)
        expansion_gate_parser.add_argument("--product-registry-manifest-path", type=Path)
        expansion_gate_parser.add_argument("--fundamental-contract-manifest-path", type=Path)
        expansion_gate_parser.add_argument("--report-output-dir", type=Path)
        expansion_gate_parser.add_argument("--run-id")
        expansion_gate_parser.add_argument("--gate-version", default="R52")
        official_history_parser = research_subparsers.add_parser(
            "connect-cf-official-history",
            help="Connect CZCE official annual history into CF core quotes.",
        )
        official_history_parser.add_argument("--years")
        official_history_parser.add_argument("--source-dir", type=Path)
        official_history_parser.add_argument("--allow-download", action="store_true")
        official_history_parser.add_argument("--raw-root", type=Path)
        official_history_parser.add_argument("--core-output-dir", type=Path)
        official_history_parser.add_argument("--output-path", type=Path)
        official_history_parser.add_argument("--report-output-dir", type=Path)
        official_history_parser.add_argument("--run-id")
        validation_pack_parser = research_subparsers.add_parser(
            "run-cf-validation-pack",
            help="Run an isolated post-R22 CF workbench validation pack.",
        )
        validation_pack_parser.add_argument("--date", default="2024-01-31")
        validation_pack_parser.add_argument("--start", default="2024-01-22")
        validation_pack_parser.add_argument("--end", default="2024-01-31")
        validation_pack_parser.add_argument("--output-root", type=Path)
        validation_pack_parser.add_argument("--run-id")
        validation_pack_parser.add_argument("--horizons", default="1")
        validation_pack_parser.add_argument("--lookback-periods", type=int, default=3)
        validation_pack_parser.add_argument(
            "--candidate-scope",
            default="POST_R22_CF_VALIDATION",
        )
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
        if args.command == "research" and args.research_command == "ingest-cf":
            from cotton_factor.research_workbench import ingest_cf_raw

            try:
                result = ingest_cf_raw(
                    trade_date=_parse_iso_date(args.date),
                    input_path=args.input_path,
                    raw_output_dir=args.raw_output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "research" and args.research_command == "normalize-cf-quotes":
            from cotton_factor.research_workbench import normalize_cf_core_quotes

            try:
                result = normalize_cf_core_quotes(
                    trade_date=_parse_iso_date(args.date),
                    raw_output_dir=args.raw_output_dir,
                    core_output_dir=args.core_output_dir,
                    output_path=args.output_path,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "research" and args.research_command == "check-cf-quality":
            from cotton_factor.research_workbench import check_cf_data_quality

            try:
                result = check_cf_data_quality(
                    trade_date=_parse_iso_date(args.date),
                    core_output_dir=args.core_output_dir,
                    core_quote_path=args.core_quote_path,
                    report_output_dir=args.report_output_dir,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0 if result.passed else 1
        if args.command == "research" and args.research_command == "review-cf-contract-rules":
            from cotton_factor.research_workbench import build_cf_contract_rule_review

            try:
                result = build_cf_contract_rule_review(
                    year=args.year,
                    report_output_dir=args.report_output_dir,
                    calendar_path=args.calendar_path,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "research" and args.research_command == "build-cf-mapping":
            from cotton_factor.research_workbench import build_cf_research_mapping

            try:
                result = build_cf_research_mapping(
                    start=_parse_iso_date(args.start),
                    end=_parse_iso_date(args.end),
                    core_output_dir=args.core_output_dir,
                    core_quote_path=args.core_quote_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    calendar_path=args.calendar_path,
                    ltd_buffer_days=args.ltd_buffer_days,
                    min_volume=args.min_volume,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "research" and args.research_command == "build-cf-continuous":
            from cotton_factor.research_workbench import build_cf_research_continuous

            try:
                result = build_cf_research_continuous(
                    start=_parse_iso_date(args.start),
                    end=_parse_iso_date(args.end),
                    price_field=args.price_field,
                    core_output_dir=args.core_output_dir,
                    core_quote_path=args.core_quote_path,
                    chain_map_path=args.chain_map_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command
            == "build-cf-option-maturity-confirmation-research"
        ):
            from cotton_factor.research_workbench import (
                build_cf_option_maturity_confirmation_research,
            )

            try:
                result = build_cf_option_maturity_confirmation_research(
                    option_core_path=args.option_core_path,
                    trend_confirmation_event_path=(
                        args.trend_confirmation_event_path
                    ),
                    trend_confirmation_trajectory_path=(
                        args.trend_confirmation_trajectory_path
                    ),
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    horizons=_parse_horizons(args.horizons),
                    checkpoints=_parse_non_negative_ints(args.checkpoints),
                    confirmation_days=args.confirmation_days,
                    activity_window=args.activity_window,
                    activity_min_periods=args.activity_min_periods,
                    baseline_year=args.baseline_year,
                    expansion_volume_ratio=args.expansion_volume_ratio,
                    expansion_oi_ratio=args.expansion_oi_ratio,
                    mature_volume_ratio=args.mature_volume_ratio,
                    mature_oi_ratio=args.mature_oi_ratio,
                    min_sample_size=args.min_sample_size,
                    fdr_level=args.fdr_level,
                    dead_zone_bps=args.dead_zone_bps,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1
            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-rebound-lifecycle"
        ):
            from cotton_factor.research_workbench import (
                build_cf_rebound_lifecycle_research,
            )

            try:
                result = build_cf_rebound_lifecycle_research(
                    signal_matrix_path=args.signal_matrix_path,
                    symmetric_trend_daily_path=args.symmetric_trend_daily_path,
                    option_structure_path=args.option_structure_path,
                    horizons=_parse_horizons(args.horizons),
                    prepare_max_days=args.prepare_max_days,
                    confirm_max_days=args.confirm_max_days,
                    follow_max_days=args.follow_max_days,
                    break_buffer_bps=args.break_buffer_bps,
                    min_sample_size=args.min_sample_size,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1
            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-symmetric-trend-research"
        ):
            from cotton_factor.research_workbench import build_cf_symmetric_trend_research

            try:
                result = build_cf_symmetric_trend_research(
                    continuous_price_path=args.continuous_price_path,
                    trend_context_path=args.trend_context_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    fast_window=args.fast_window,
                    slow_window=args.slow_window,
                    breakout_window=args.breakout_window,
                    breakout_cooldown=args.breakout_cooldown,
                    horizons=_parse_horizons(args.horizons),
                    dead_zone_bps=args.dead_zone_bps,
                    min_sample_size=args.min_sample_size,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1
            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command
            == "build-cf-trend-option-timing-research"
        ):
            from cotton_factor.research_workbench import (
                build_cf_trend_option_timing_research,
            )

            try:
                result = build_cf_trend_option_timing_research(
                    symmetric_trend_daily_path=args.symmetric_trend_daily_path,
                    breakout_event_path=args.breakout_event_path,
                    option_structure_path=args.option_structure_path,
                    strike_position_path=args.strike_position_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    rank_window=args.rank_window,
                    rank_min_periods=args.rank_min_periods,
                    min_sample_size=args.min_sample_size,
                    fdr_level=args.fdr_level,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1
            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command
            == "build-cf-trend-confirmation-timing-research"
        ):
            from cotton_factor.research_workbench import (
                build_cf_trend_confirmation_timing_research,
            )

            try:
                result = build_cf_trend_confirmation_timing_research(
                    symmetric_trend_daily_path=args.symmetric_trend_daily_path,
                    breakout_event_path=args.breakout_event_path,
                    chain_oi_path=args.chain_oi_path,
                    option_structure_path=args.option_structure_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    horizons=_parse_horizons(args.horizons),
                    pre_window_sessions=args.pre_window_sessions,
                    post_window_sessions=args.post_window_sessions,
                    confirmation_days=args.confirmation_days,
                    min_sample_size=args.min_sample_size,
                    fdr_level=args.fdr_level,
                    min_annual_coverage_years=args.min_annual_coverage_years,
                    min_annual_group_size=args.min_annual_group_size,
                    min_annual_direction_consistency=(
                        args.min_annual_direction_consistency
                    ),
                    volume_rank_window=args.volume_rank_window,
                    volume_rank_min_periods=args.volume_rank_min_periods,
                    min_option_liquidity_score=args.min_option_liquidity_score,
                    dead_zone_bps=args.dead_zone_bps,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1
            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command
            == "build-cf-trend-candidate-stability-research"
        ):
            from cotton_factor.research_workbench import (
                build_cf_trend_candidate_stability_research,
            )

            try:
                result = build_cf_trend_candidate_stability_research(
                    event_feature_path=args.event_feature_path,
                    spec_path=args.spec_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1
            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command
            == "build-cf-trend-candidate-forward-ledger"
        ):
            from cotton_factor.research_workbench import (
                build_cf_trend_candidate_forward_ledger,
            )

            try:
                result = build_cf_trend_candidate_forward_ledger(
                    symmetric_trend_daily_path=args.symmetric_trend_daily_path,
                    breakout_event_path=args.breakout_event_path,
                    candidate_evaluation_path=args.candidate_evaluation_path,
                    spec_path=args.spec_path,
                    as_of_date=(
                        _parse_iso_date(args.as_of_date)
                        if args.as_of_date is not None
                        else None
                    ),
                    ledger_root=args.ledger_root,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    correction_reason=args.correction_reason,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1
            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-forward-evidence-weekly"
        ):
            from cotton_factor.research_workbench import (
                build_cf_forward_evidence_weekly,
            )

            try:
                result = build_cf_forward_evidence_weekly(
                    as_of_date=(
                        _parse_iso_date(args.date) if args.date is not None else None
                    ),
                    strategy_ledger_root=args.strategy_ledger_root,
                    candidate_ledger_path=args.candidate_ledger_path,
                    candidate_event_root=args.candidate_event_root,
                    candidate_run_json_path=args.candidate_run_json_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1
            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "write-cf-factor-output-contract"
        ):
            from cotton_factor.research_workbench import build_cf_factor_output_contract

            try:
                result = build_cf_factor_output_contract(
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "research" and args.research_command == "build-cf-momentum-factor":
            from cotton_factor.research_workbench import build_cf_momentum_factor

            try:
                result = build_cf_momentum_factor(
                    start=_parse_iso_date(args.start),
                    end=_parse_iso_date(args.end),
                    continuous_price_path=args.continuous_price_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    price_field=args.price_field,
                    lookback_periods=args.lookback_periods,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "research" and args.research_command == "build-cf-carry-factor":
            from cotton_factor.research_workbench import build_cf_carry_factor

            try:
                result = build_cf_carry_factor(
                    start=_parse_iso_date(args.start),
                    end=_parse_iso_date(args.end),
                    core_output_dir=args.core_output_dir,
                    core_quote_path=args.core_quote_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    calendar_path=args.calendar_path,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "research" and args.research_command == "build-cf-structure-factors":
            from cotton_factor.research_workbench import build_cf_structure_factors

            try:
                result = build_cf_structure_factors(
                    start=_parse_iso_date(args.start),
                    end=_parse_iso_date(args.end),
                    core_output_dir=args.core_output_dir,
                    core_quote_path=args.core_quote_path,
                    chain_map_path=args.chain_map_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    calendar_path=args.calendar_path,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "research" and args.research_command == "build-cf-factor-diagnostics":
            from cotton_factor.research_workbench import build_cf_factor_diagnostics

            try:
                result = build_cf_factor_diagnostics(
                    start=_parse_iso_date(args.start),
                    end=_parse_iso_date(args.end),
                    factor_value_path=args.factor_value_path,
                    warning_csv_path=args.warning_csv_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "research" and args.research_command == "build-cf-forward-returns":
            from cotton_factor.research_workbench import build_cf_forward_returns

            try:
                result = build_cf_forward_returns(
                    start=_parse_iso_date(args.start),
                    end=_parse_iso_date(args.end),
                    horizons=_parse_horizons(args.horizons),
                    core_output_dir=args.core_output_dir,
                    core_quote_path=args.core_quote_path,
                    trade_mapping_path=args.trade_mapping_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    entry_price_field=args.entry_price_field,
                    exit_price_field=args.exit_price_field,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "run-cf-single-factor-backtest"
        ):
            from cotton_factor.research_workbench import build_cf_single_factor_backtest

            try:
                result = build_cf_single_factor_backtest(
                    start=_parse_iso_date(args.start),
                    end=_parse_iso_date(args.end),
                    factor_ids=_parse_factor_ids(args.factor_ids),
                    horizons=_parse_horizons(args.horizons),
                    diagnostic_path=args.diagnostic_path,
                    forward_return_path=args.forward_return_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    use_processed_value=not args.use_raw_value,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-multifactor-diagnostics"
        ):
            from cotton_factor.research_workbench import build_cf_multifactor_diagnostics

            try:
                result = build_cf_multifactor_diagnostics(
                    start=_parse_iso_date(args.start),
                    end=_parse_iso_date(args.end),
                    factor_ids=_parse_factor_ids(args.factor_ids),
                    diagnostic_path=args.diagnostic_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    score_id=args.score_id,
                    use_processed_value=not args.use_raw_value,
                    require_all_factors=not args.allow_missing_factors,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "research" and args.research_command == "build-cf-cost-sensitivity":
            from cotton_factor.research_workbench import build_cf_cost_sensitivity

            try:
                result = build_cf_cost_sensitivity(
                    start=_parse_iso_date(args.start),
                    end=_parse_iso_date(args.end),
                    horizons=_parse_horizons(args.horizons),
                    score_path=args.score_path,
                    forward_return_path=args.forward_return_path,
                    scenario_cost_bps=_parse_scenario_cost_bps(args.scenario_cost_bps),
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    use_processed_score=not args.use_raw_score,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "research" and args.research_command == "build-cf-daily-brief":
            from cotton_factor.research_workbench import build_cf_daily_brief

            parsed_trade_date = _parse_iso_date(args.date)
            try:
                result = build_cf_daily_brief(
                    trade_date=parsed_trade_date,
                    start=_parse_iso_date(args.start) if args.start else None,
                    end=_parse_iso_date(args.end) if args.end else None,
                    quality_csv_path=args.quality_csv_path,
                    chain_map_path=args.chain_map_path,
                    trade_mapping_path=args.trade_mapping_path,
                    diagnostic_path=args.diagnostic_path,
                    single_factor_evaluation_path=args.single_factor_evaluation_path,
                    multifactor_score_path=args.multifactor_score_path,
                    cost_sensitivity_path=args.cost_sensitivity_path,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-latest-signal-brief"
        ):
            from cotton_factor.research_workbench import build_cf_latest_signal_brief

            try:
                result = build_cf_latest_signal_brief(
                    trade_date=_parse_iso_date(args.date) if args.date else None,
                    core_quote_path=args.core_quote_path,
                    output_root=args.output_root,
                    run_id=args.run_id,
                    lookback_days=args.lookback_days,
                    trend_rule_candidate_path=args.trend_rule_candidate_path,
                    signal_matrix_path=args.signal_matrix_path,
                    signal_threshold_research_path=args.signal_threshold_research_path,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-trend-continuity-board"
        ):
            from cotton_factor.research_workbench import build_cf_trend_continuity_board

            try:
                result = build_cf_trend_continuity_board(
                    trade_date=_parse_iso_date(args.date) if args.date else None,
                    core_quote_path=args.core_quote_path,
                    output_root=args.output_root,
                    run_id=args.run_id,
                    lookback_trading_days=args.lookback_trading_days,
                    trend_rule_candidate_path=args.trend_rule_candidate_path,
                    trend_quality_calibration_manifest_path=(
                        args.trend_quality_calibration_manifest_path
                    ),
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-daily-operation-audit"
        ):
            from cotton_factor.research_workbench import build_cf_daily_operation_audit

            try:
                result = build_cf_daily_operation_audit(
                    latest_signal_json_path=args.latest_signal_json_path,
                    trend_board_json_path=args.trend_board_json_path,
                    core_quote_path=args.core_quote_path,
                    output_root=args.output_root,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-data-continuity-audit"
        ):
            from cotton_factor.research_workbench import build_cf_data_continuity_audit

            try:
                result = build_cf_data_continuity_audit(
                    trade_date=_parse_iso_date(args.date) if args.date else None,
                    core_quote_path=args.core_quote_path,
                    option_core_path=args.option_core_path,
                    calendar_path=args.calendar_path,
                    official_daily_fetch_json_path=args.official_daily_fetch_json_path,
                    raw_root=args.raw_root,
                    output_root=args.output_root,
                    run_id=args.run_id,
                    require_options=not args.no_require_options,
                    require_raw_retention=not args.skip_raw_retention,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0 if result.passed else 1
        if args.command == "research" and args.research_command == "build-cf-signal-matrix":
            from cotton_factor.research_workbench import build_cf_signal_matrix

            try:
                result = build_cf_signal_matrix(
                    start=_parse_iso_date(args.start) if args.start else None,
                    end=_parse_iso_date(args.end) if args.end else None,
                    horizons=_parse_horizons(args.horizons),
                    core_quote_path=args.core_quote_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    trend_rule_candidate_path=args.trend_rule_candidate_path,
                    option_factor_path=args.option_factor_path,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-signal-matrix-validation"
        ):
            from cotton_factor.research_workbench import build_cf_signal_matrix_validation

            try:
                result = build_cf_signal_matrix_validation(
                    signal_matrix_path=args.signal_matrix_path,
                    core_quote_path=args.core_quote_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    windows=_parse_optional_csv(args.windows),
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-signal-threshold-research"
        ):
            from cotton_factor.research_workbench import build_cf_signal_threshold_research

            try:
                result = build_cf_signal_threshold_research(
                    validation_daily_path=args.validation_daily_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-historical-evidence-pack"
        ):
            from cotton_factor.research_workbench import build_cf_historical_evidence_pack
            from cotton_factor.research_workbench.historical_evidence import parse_cost_scenarios

            try:
                result = build_cf_historical_evidence_pack(
                    core_quote_path=args.core_quote_path,
                    signal_matrix_path=args.signal_matrix_path,
                    validation_daily_path=args.validation_daily_path,
                    validation_window_summary_path=args.validation_window_summary_path,
                    threshold_weighting_path=args.threshold_weighting_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    cost_scenarios=parse_cost_scenarios(args.cost_scenarios),
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-historical-event-explanation"
        ):
            from cotton_factor.research_workbench import build_cf_historical_event_explanation

            try:
                result = build_cf_historical_event_explanation(
                    validation_daily_path=args.validation_daily_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    primary_horizon=args.primary_horizon,
                    horizons=_parse_horizons(args.horizons),
                    fundamental_context_path=args.fundamental_context_path,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-event-threshold-sensitivity"
        ):
            from cotton_factor.research_workbench import build_cf_event_threshold_sensitivity

            try:
                result = build_cf_event_threshold_sensitivity(
                    validation_daily_path=args.validation_daily_path,
                    event_path=args.event_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    primary_horizon=args.primary_horizon,
                    horizons=_parse_horizons(args.horizons),
                    threshold_quantiles=_parse_quantiles(args.threshold_quantiles),
                    min_observation_count=args.min_observation_count,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-event-threshold-review-ledger"
        ):
            from cotton_factor.research_workbench import build_cf_event_threshold_review_ledger

            try:
                result = build_cf_event_threshold_review_ledger(
                    threshold_summary_path=args.threshold_summary_path,
                    threshold_detail_path=args.threshold_detail_path,
                    event_detail_path=args.event_detail_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    example_event_count=args.example_event_count,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-validated-research-brief"
        ):
            from cotton_factor.research_workbench import build_cf_validated_research_brief

            try:
                result = build_cf_validated_research_brief(
                    latest_signal_json_path=args.latest_signal_json_path,
                    historical_evidence_decay_path=args.historical_evidence_decay_path,
                    historical_evidence_stability_path=args.historical_evidence_stability_path,
                    event_summary_path=args.event_summary_path,
                    event_detail_path=args.event_detail_path,
                    event_threshold_summary_path=args.event_threshold_summary_path,
                    fundamental_observation_json_path=args.fundamental_observation_json_path,
                    futures_option_divergence_json_path=(
                        args.futures_option_divergence_json_path
                    ),
                    futures_option_playbook_json_path=args.futures_option_playbook_json_path,
                    current_watch_window_json_path=args.current_watch_window_json_path,
                    state_transition_json_path=args.state_transition_json_path,
                    option_volatility_json_path=args.option_volatility_json_path,
                    output_dir=args.output_dir,
                    daily_output_root=args.daily_output_root,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "research" and args.research_command == "build-cf-publish-pack":
            from cotton_factor.research_workbench import build_cf_publish_pack

            try:
                result = build_cf_publish_pack(
                    latest_signal_json_path=args.latest_signal_json_path,
                    validated_brief_path=args.validated_brief_path,
                    core_quote_path=args.core_quote_path,
                    signal_matrix_path=args.signal_matrix_path,
                    historical_evidence_decay_path=args.historical_evidence_decay_path,
                    event_summary_path=args.event_summary_path,
                    futures_option_divergence_json_path=(
                        args.futures_option_divergence_json_path
                    ),
                    futures_option_playbook_json_path=args.futures_option_playbook_json_path,
                    current_watch_window_json_path=args.current_watch_window_json_path,
                    output_root=args.output_root,
                    run_id=args.run_id,
                    price_lookback=args.price_lookback,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-weekly-research-audit"
        ):
            from cotton_factor.research_workbench import build_cf_weekly_research_audit

            try:
                result = build_cf_weekly_research_audit(
                    weekly_manifest_path=args.weekly_manifest_path,
                    output_dir=args.output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-stage-decision-pack"
        ):
            from cotton_factor.research_workbench import build_cf_stage_decision_pack

            try:
                result = build_cf_stage_decision_pack(
                    weekly_audit_json_path=args.weekly_audit_json_path,
                    expansion_gate_json_path=args.expansion_gate_json_path,
                    latest_signal_json_path=args.latest_signal_json_path,
                    option_factor_json_path=args.option_factor_json_path,
                    event_threshold_json_path=args.event_threshold_json_path,
                    output_dir=args.output_dir,
                    daily_output_root=args.daily_output_root,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-event-lifecycle-research"
        ):
            from cotton_factor.research_workbench import build_cf_event_lifecycle_research

            try:
                result = build_cf_event_lifecycle_research(
                    signal_matrix_path=args.signal_matrix_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    horizon=args.horizon,
                    max_holding_days=args.max_holding_days,
                    profit_barrier=args.profit_barrier,
                    stop_loss_barrier=args.stop_loss_barrier,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-state-transition-competing-risk"
        ):
            from cotton_factor.research_workbench import (
                build_cf_state_transition_competing_risk_research,
            )

            try:
                result = build_cf_state_transition_competing_risk_research(
                    event_lifecycle_episode_path=args.event_lifecycle_episode_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    max_age_days=args.max_age_days,
                    min_sample_size=args.min_sample_size,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-futures-option-divergence-research"
        ):
            from cotton_factor.research_workbench import (
                build_cf_futures_option_divergence_research,
            )

            try:
                result = build_cf_futures_option_divergence_research(
                    signal_matrix_validation_path=args.signal_matrix_validation_path,
                    option_factor_path=args.option_factor_path,
                    event_lifecycle_episode_path=args.event_lifecycle_episode_path,
                    event_lifecycle_tbm_path=args.event_lifecycle_tbm_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    horizons=_parse_horizons(args.horizons),
                    dead_zone_bps=args.dead_zone_bps,
                    min_sample_size=args.min_sample_size,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-futures-option-dynamic-wall-research"
        ):
            from cotton_factor.research_workbench import (
                build_cf_futures_option_dynamic_wall_research,
            )

            try:
                result = build_cf_futures_option_dynamic_wall_research(
                    option_core_path=args.option_core_path,
                    core_quote_path=args.core_quote_path,
                    option_factor_path=args.option_factor_path,
                    signal_matrix_path=args.signal_matrix_path,
                    trend_phase_path=args.trend_phase_path,
                    option_strike_position_path=args.option_strike_position_path,
                    start=args.start,
                    end=args.end,
                    horizons=_parse_horizons(args.horizons),
                    local_band_ratio=args.local_band_ratio,
                    touch_band_ratio=args.touch_band_ratio,
                    wall_change_bps=args.wall_change_bps,
                    wall_shift_bps=args.wall_shift_bps,
                    min_sample_size=args.min_sample_size,
                    fdr_level=args.fdr_level,
                    dead_zone_bps=args.dead_zone_bps,
                    tbm_vol_multiplier=args.tbm_vol_multiplier,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-futures-option-event-path-research"
        ):
            from cotton_factor.research_workbench import (
                build_cf_futures_option_event_path_research,
            )

            try:
                result = build_cf_futures_option_event_path_research(
                    event_path=args.event_path,
                    event_lifecycle_label_path=args.event_lifecycle_label_path,
                    feature_path=args.feature_path,
                    start=args.start,
                    end=args.end,
                    horizons=_parse_horizons(args.horizons),
                    dead_zone_bps=args.dead_zone_bps,
                    min_sample_size=args.min_sample_size,
                    fdr_level=args.fdr_level,
                    purge_gap_sessions=args.purge_gap_sessions,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command
            == "build-cf-futures-option-regime-interaction-research"
        ):
            from cotton_factor.research_workbench import (
                build_cf_futures_option_regime_interaction_research,
            )

            try:
                result = build_cf_futures_option_regime_interaction_research(
                    event_path=args.event_path,
                    checkpoint_path=args.checkpoint_path,
                    path_path=args.path_path,
                    feature_path=args.feature_path,
                    policy_context_path=args.policy_context_path,
                    fundamental_context_path=args.fundamental_context_path,
                    start=args.start,
                    end=args.end,
                    horizons=_parse_horizons(args.horizons),
                    episode_gap_sessions=args.episode_gap_sessions,
                    chain_window_sessions=args.chain_window_sessions,
                    min_sample_size=args.min_sample_size,
                    min_cell_size=args.min_cell_size,
                    fdr_level=args.fdr_level,
                    permutation_count=args.permutation_count,
                    purge_gap_sessions=args.purge_gap_sessions,
                    random_seed=args.random_seed,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-futures-option-divergence-playbook"
        ):
            from cotton_factor.research_workbench import (
                build_cf_futures_option_divergence_playbook,
            )

            try:
                result = build_cf_futures_option_divergence_playbook(
                    event_path=args.event_path,
                    node_summary_path=args.node_summary_path,
                    latest_signal_json_path=args.latest_signal_json_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    min_sample_size=args.min_sample_size,
                    edge_threshold=args.edge_threshold,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "research" and args.research_command == "build-cf-dual-price-state":
            from cotton_factor.research_workbench import build_cf_dual_price_state

            try:
                result = build_cf_dual_price_state(
                    core_quote_path=args.core_quote_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    ma_window=args.ma_window,
                    gap_alert_bps=args.gap_alert_bps,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1
            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-chain-oi-structure"
        ):
            from cotton_factor.research_workbench import build_cf_chain_oi_structure

            try:
                result = build_cf_chain_oi_structure(
                    core_quote_path=args.core_quote_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    noise_ratio=args.noise_ratio,
                    roll_transfer_threshold=args.roll_transfer_threshold,
                    roll_lookback_days=args.roll_lookback_days,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1
            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-delivery-adjusted-curve"
        ):
            from cotton_factor.research_workbench import build_cf_delivery_adjusted_curve

            try:
                result = build_cf_delivery_adjusted_curve(
                    core_quote_path=args.core_quote_path,
                    near_contract=args.near_contract,
                    far_contract=args.far_contract,
                    start=args.start,
                    end=args.end,
                    aging_discount=args.aging_discount,
                    storage_cost_per_ton_day=args.storage_cost_per_ton_day,
                    annual_financing_rate=args.annual_financing_rate,
                    holding_days=args.holding_days,
                    near_zero_band=args.near_zero_band,
                    min_history_days=args.min_history_days,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1
            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-structural-position-attribution"
        ):
            from cotton_factor.research_workbench import (
                build_cf_structural_position_attribution,
            )

            try:
                horizons = tuple(
                    int(value.strip())
                    for value in args.option_horizons.split(",")
                    if value.strip()
                )
                result = build_cf_structural_position_attribution(
                    core_quote_path=args.core_quote_path,
                    member_detail_path=args.member_detail_path,
                    warehouse_receipt_path=args.warehouse_receipt_path,
                    option_strike_position_path=args.option_strike_position_path,
                    option_factor_path=args.option_factor_path,
                    delivery_adjusted_curve_path=args.delivery_adjusted_curve_path,
                    target_contract=args.target_contract,
                    source_contract=args.source_contract,
                    next_contract=args.next_contract,
                    focus_start=args.focus_start,
                    focus_end=args.focus_end,
                    option_horizons=horizons,
                    wall_distance=args.wall_distance,
                    option_oi_noise_ratio=args.option_oi_noise_ratio,
                    contract_tons=args.contract_tons,
                    receipt_tons=args.receipt_tons,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except (CottonFactorError, ValueError) as exc:
                print(str(exc))
                return 1
            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-oi-roll-window-research"
        ):
            from cotton_factor.research_workbench import build_cf_oi_roll_window_research

            try:
                parsed_windows = tuple(
                    int(value.strip())
                    for value in args.windows.split(",")
                    if value.strip()
                )
                result = build_cf_oi_roll_window_research(
                    core_quote_path=args.core_quote_path,
                    validation_daily_path=args.validation_daily_path,
                    exclusion_path=args.exclusion_path,
                    end=args.end,
                    windows=parsed_windows,
                    min_sample_size=args.min_sample_size,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except (CottonFactorError, ValueError) as exc:
                print(str(exc))
                return 1
            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-option-structure-research"
        ):
            from cotton_factor.research_workbench import build_cf_option_structure_research

            try:
                result = build_cf_option_structure_research(
                    option_factor_path=args.option_factor_path,
                    signal_matrix_path=args.signal_matrix_path,
                    validation_daily_path=args.validation_daily_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    primary_horizon=args.primary_horizon,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1
            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "research" and args.research_command == "build-cf-trend-phase-v2":
            from cotton_factor.research_workbench import build_cf_trend_phase_v2

            try:
                result = build_cf_trend_phase_v2(
                    dual_price_path=args.dual_price_path,
                    chain_oi_path=args.chain_oi_path,
                    option_structure_path=args.option_structure_path,
                    signal_matrix_path=args.signal_matrix_path,
                    validation_daily_path=args.validation_daily_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    primary_horizon=args.primary_horizon,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1
            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-current-watch-window"
        ):
            from cotton_factor.research_workbench import build_cf_current_watch_window

            try:
                result = build_cf_current_watch_window(
                    latest_signal_json_path=args.latest_signal_json_path,
                    dual_price_path=args.dual_price_path,
                    chain_oi_path=args.chain_oi_path,
                    option_structure_path=args.option_structure_path,
                    trend_phase_v2_path=args.trend_phase_v2_path,
                    playbook_json_path=args.playbook_json_path,
                    core_quote_path=args.core_quote_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    daily_output_root=args.daily_output_root,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1
            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "fetch-cf-official-daily-files"
        ):
            from cotton_factor.research_workbench import fetch_cf_official_daily_files

            try:
                result = fetch_cf_official_daily_files(
                    trade_date=_parse_iso_date(args.date) if args.date else None,
                    futures_source_dir=args.futures_source_dir,
                    options_source_dir=args.options_source_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    include_options=not args.skip_options,
                    overwrite=args.overwrite,
                    futures_url=args.futures_url,
                    options_url=args.options_url,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0 if result.passed else 1
        if (
            args.command == "research"
            and args.research_command == "build-cf-option-strike-position-research"
        ):
            from cotton_factor.research_workbench import (
                build_cf_option_strike_position_research,
            )

            try:
                result = build_cf_option_strike_position_research(
                    option_core_path=args.option_core_path,
                    core_quote_path=args.core_quote_path,
                    option_expiry_path=args.option_expiry_path,
                    end=args.end,
                    horizons=_parse_horizons(args.horizons),
                    near_level_ratio=args.near_level_ratio,
                    min_sample_size=args.min_sample_size,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1
            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "fetch-cf-official-member-position"
        ):
            from cotton_factor.research_workbench import fetch_cf_official_member_position

            try:
                result = fetch_cf_official_member_position(
                    trade_date=_parse_iso_date(args.date),
                    source_dir=args.source_dir,
                    report_output_dir=args.report_output_dir,
                    overwrite=args.overwrite,
                    official_url=args.official_url,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1
            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0 if result.passed else 1
        if (
            args.command == "research"
            and args.research_command == "fetch-cf-official-member-position-history"
        ):
            from cotton_factor.research_workbench import (
                fetch_cf_official_member_position_history,
            )

            try:
                result = fetch_cf_official_member_position_history(
                    start=_parse_iso_date(args.start),
                    end=_parse_iso_date(args.end),
                    core_quote_path=args.core_quote_path,
                    source_dir=args.source_dir,
                    report_output_dir=args.report_output_dir,
                    overwrite=args.overwrite,
                    max_workers=args.max_workers,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1
            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0 if result.passed else 1
        if (
            args.command == "research"
            and args.research_command == "connect-cf-member-position-history"
        ):
            from cotton_factor.research_workbench import connect_cf_member_position_history

            try:
                result = connect_cf_member_position_history(
                    source_dir=args.source_dir,
                    raw_root=args.raw_root,
                    core_output_dir=args.core_output_dir,
                    output_path=args.output_path,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1
            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0 if result.passed else 1
        if (
            args.command == "research"
            and args.research_command == "build-cf-member-position-research"
        ):
            from cotton_factor.research_workbench import build_cf_member_position_research

            try:
                result = build_cf_member_position_research(
                    member_position_path=args.member_position_path,
                    core_quote_path=args.core_quote_path,
                    validation_daily_path=args.validation_daily_path,
                    end=args.end,
                    top_ns=_parse_horizons(args.top_ns),
                    horizons=_parse_horizons(args.horizons),
                    position_change_dead_zone=args.position_change_dead_zone,
                    price_dead_zone=args.price_dead_zone,
                    min_sample_size=args.min_sample_size,
                    min_history_days=args.min_history_days,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1
            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-option-data-contract"
        ):
            from cotton_factor.research_workbench import build_cf_option_data_contract

            try:
                result = build_cf_option_data_contract(
                    source_dir=args.source_dir,
                    core_output_dir=args.core_output_dir,
                    output_path=args.output_path,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "research" and args.research_command == "connect-cf-option-history":
            from cotton_factor.research_workbench import connect_cf_option_history

            try:
                result = connect_cf_option_history(
                    source_dir=args.source_dir,
                    raw_root=args.raw_root,
                    core_output_dir=args.core_output_dir,
                    output_path=args.output_path,
                    core_quote_path=args.core_quote_path,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    low_volume_threshold=args.low_volume_threshold,
                    low_open_interest_threshold=args.low_open_interest_threshold,
                    deep_otm_threshold=args.deep_otm_threshold,
                    near_expiry_days=args.near_expiry_days,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-option-factor-proxy"
        ):
            from cotton_factor.research_workbench import build_cf_option_factor_proxy

            try:
                result = build_cf_option_factor_proxy(
                    option_core_path=args.option_core_path,
                    core_quote_path=args.core_quote_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    iv_rank_lookback_days=args.iv_rank_lookback_days,
                    atm_moneyness_band=args.atm_moneyness_band,
                    otm_moneyness_min=args.otm_moneyness_min,
                    otm_moneyness_max=args.otm_moneyness_max,
                    incremental=args.incremental,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0 if result.passed else 1
        if (
            args.command == "research"
            and args.research_command == "build-cf-option-volatility-term-structure"
        ):
            from cotton_factor.research_workbench import (
                build_cf_option_volatility_term_structure_research,
            )

            try:
                result = build_cf_option_volatility_term_structure_research(
                    option_factor_path=args.option_factor_path,
                    core_quote_path=args.core_quote_path,
                    option_expiry_path=args.option_expiry_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    risk_free_rate=args.risk_free_rate,
                    rv_window=args.rv_window,
                    iv_rank_window=args.iv_rank_window,
                    horizons=_parse_horizons(args.horizons),
                    min_sample_size=args.min_sample_size,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-product-research-registry"
        ):
            from cotton_factor.research_workbench import build_cf_product_research_registry

            try:
                result = build_cf_product_research_registry(
                    product_config_path=args.product_config_path,
                    factor_registry_path=args.factor_registry_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0 if result.passed else 1
        if (
            args.command == "research"
            and args.research_command == "build-cf-fundamental-data-contract"
        ):
            from cotton_factor.research_workbench import build_cf_fundamental_data_contract

            try:
                result = build_cf_fundamental_data_contract(
                    source_dir=args.source_dir,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0 if result.passed else 1
        if (
            args.command == "research"
            and args.research_command == "build-cf-fundamental-observation"
        ):
            from cotton_factor.research_workbench import build_cf_fundamental_observation

            try:
                result = build_cf_fundamental_observation(
                    source_dir=args.source_dir,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0 if result.passed else 1
        if (
            args.command == "research"
            and args.research_command == "build-cf-fundamental-context"
        ):
            from cotton_factor.research_workbench import build_cf_fundamental_context

            try:
                result = build_cf_fundamental_context(
                    fundamental_observation_json_path=args.fundamental_observation_json_path,
                    core_quote_path=args.core_quote_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    change_windows=_parse_horizons(args.change_windows),
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0 if result.passed else 1
        if (
            args.command == "research"
            and args.research_command == "build-cf-trend-quality-calibration"
        ):
            from cotton_factor.research_workbench import build_cf_trend_quality_calibration

            try:
                result = build_cf_trend_quality_calibration(
                    start=_parse_iso_date(args.start) if args.start else None,
                    end=_parse_iso_date(args.end) if args.end else None,
                    horizons=_parse_horizons(args.horizons),
                    core_quote_path=args.core_quote_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    trend_rule_candidate_path=args.trend_rule_candidate_path,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-trend-phase-validation"
        ):
            from cotton_factor.research_workbench import build_cf_trend_phase_validation

            try:
                result = build_cf_trend_phase_validation(
                    start=_parse_iso_date(args.start),
                    end=_parse_iso_date(args.end),
                    horizons=_parse_horizons(args.horizons),
                    core_quote_path=args.core_quote_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-trend-phase-events"
        ):
            from cotton_factor.research_workbench import build_cf_trend_phase_events

            try:
                result = build_cf_trend_phase_events(
                    start=_parse_iso_date(args.start),
                    end=_parse_iso_date(args.end),
                    horizons=_parse_horizons(args.horizons),
                    trend_phase_daily_path=args.trend_phase_daily_path,
                    core_quote_path=args.core_quote_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if (
            args.command == "research"
            and args.research_command == "build-cf-trend-rule-candidates"
        ):
            from cotton_factor.research_workbench import build_cf_trend_rule_candidates

            try:
                result = build_cf_trend_rule_candidates(
                    start=_parse_iso_date(args.start),
                    end=_parse_iso_date(args.end),
                    event_summary_path=args.event_summary_path,
                    event_path=args.event_path,
                    output_dir=args.output_dir,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    min_event_count=args.min_event_count,
                    min_observation_count=args.min_observation_count,
                    min_directional_hit_rate=args.min_directional_hit_rate,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "research" and args.research_command == "run-cf-daily-pipeline":
            from cotton_factor.research_workbench import build_cf_daily_research_pipeline

            parsed_trade_date = _parse_iso_date(args.date)
            try:
                result = build_cf_daily_research_pipeline(
                    trade_date=parsed_trade_date,
                    input_path=args.input_path,
                    start=_parse_iso_date(args.start) if args.start else None,
                    end=_parse_iso_date(args.end) if args.end else None,
                    raw_output_dir=args.raw_output_dir,
                    core_output_dir=args.core_output_dir,
                    research_output_root=args.research_output_root,
                    report_output_root=args.report_output_root,
                    run_id=args.run_id,
                    horizons=_parse_horizons(args.horizons),
                    factor_ids=_parse_factor_ids(args.factor_ids),
                    scenario_cost_bps=_parse_scenario_cost_bps(args.scenario_cost_bps),
                    price_field=args.price_field,
                    lookback_periods=args.lookback_periods,
                    ltd_buffer_days=args.ltd_buffer_days,
                    min_volume=args.min_volume,
                    require_all_factors=not args.allow_missing_factors,
                    use_processed_value=not args.use_raw_value,
                    use_processed_score=not args.use_raw_score,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0 if result.passed else 1
        if args.command == "research" and args.research_command == "replay-cf-daily-pipeline":
            from cotton_factor.research_workbench import replay_cf_research_pipeline_outputs

            try:
                result = replay_cf_research_pipeline_outputs(
                    pipeline_json_path=args.pipeline_json_path,
                    baseline_json_path=args.baseline_json_path,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    require_completed_pipeline=not args.allow_incomplete_pipeline,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0 if result.passed else 1
        if args.command == "research" and args.research_command == "build-cf-expansion-gate":
            from cotton_factor.research_workbench import build_cf_expansion_gate

            try:
                result = build_cf_expansion_gate(
                    candidate_scope=args.candidate_scope,
                    pipeline_json_path=args.pipeline_json_path,
                    replay_json_path=args.replay_json_path,
                    historical_evidence_manifest_path=args.historical_evidence_manifest_path,
                    event_explanation_manifest_path=args.event_explanation_manifest_path,
                    signal_matrix_manifest_path=args.signal_matrix_manifest_path,
                    publish_pack_manifest_path=args.publish_pack_manifest_path,
                    product_registry_manifest_path=args.product_registry_manifest_path,
                    fundamental_contract_manifest_path=args.fundamental_contract_manifest_path,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                    gate_version=args.gate_version,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0 if result.passed else 1
        if (
            args.command == "research"
            and args.research_command == "connect-cf-official-history"
        ):
            from cotton_factor.research_workbench import connect_cf_official_history

            try:
                result = connect_cf_official_history(
                    years=_parse_years(args.years) if args.years else None,
                    source_dir=args.source_dir,
                    allow_download=args.allow_download,
                    raw_root=args.raw_root,
                    core_output_dir=args.core_output_dir,
                    output_path=args.output_path,
                    report_output_dir=args.report_output_dir,
                    run_id=args.run_id,
                )
            except CottonFactorError as exc:
                print(str(exc))
                return 1

            print(json.dumps(result.to_summary(), ensure_ascii=False, sort_keys=True))
            return 0 if result.passed else 1
        if args.command == "research" and args.research_command == "run-cf-validation-pack":
            from cotton_factor.research_workbench import build_cf_post_r22_validation_pack

            try:
                result = build_cf_post_r22_validation_pack(
                    trade_date=_parse_iso_date(args.date),
                    start=_parse_iso_date(args.start),
                    end=_parse_iso_date(args.end),
                    output_root=args.output_root,
                    run_id=args.run_id,
                    horizons=_parse_horizons(args.horizons),
                    lookback_periods=args.lookback_periods,
                    candidate_scope=args.candidate_scope,
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


def _parse_horizons(value: str) -> tuple[int, ...]:
    try:
        horizons = tuple(
            int(item.strip())
            for item in value.split(",")
            if item.strip()
        )
    except ValueError as exc:
        message = f"horizons must be comma-separated integers: {value!r}"
        if typer is not None:
            raise typer.BadParameter(message) from exc
        raise argparse.ArgumentTypeError(message) from exc
    if not horizons or any(horizon <= 0 for horizon in horizons):
        message = f"horizons must contain positive integers: {value!r}"
        if typer is not None:
            raise typer.BadParameter(message)
        raise argparse.ArgumentTypeError(message)
    return horizons


def _parse_non_negative_ints(value: str) -> tuple[int, ...]:
    try:
        numbers = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        message = f"values must be comma-separated integers: {value!r}"
        if typer is not None:
            raise typer.BadParameter(message) from exc
        raise argparse.ArgumentTypeError(message) from exc
    if not numbers or any(number < 0 for number in numbers):
        message = f"values must contain non-negative integers: {value!r}"
        if typer is not None:
            raise typer.BadParameter(message)
        raise argparse.ArgumentTypeError(message)
    return numbers


def _parse_quantiles(value: str) -> tuple[float, ...]:
    try:
        quantiles = tuple(
            float(item.strip())
            for item in value.split(",")
            if item.strip()
        )
    except ValueError as exc:
        message = f"quantiles must be comma-separated numbers: {value!r}"
        if typer is not None:
            raise typer.BadParameter(message) from exc
        raise argparse.ArgumentTypeError(message) from exc
    if not quantiles or any(quantile <= 0 or quantile >= 1 for quantile in quantiles):
        message = f"quantiles must be between 0 and 1: {value!r}"
        if typer is not None:
            raise typer.BadParameter(message)
        raise argparse.ArgumentTypeError(message)
    return quantiles


def _parse_optional_csv(value: str | None) -> tuple[str, ...] | None:
    if value is None or not value.strip():
        return None
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    if not items:
        return None
    return items


def _parse_factor_ids(value: str) -> tuple[str, ...]:
    factor_ids = tuple(
        factor_id.strip()
        for factor_id in value.split(",")
        if factor_id.strip()
    )
    if not factor_ids:
        message = "at least one factor id is required"
        if typer is not None:
            raise typer.BadParameter(message)
        raise argparse.ArgumentTypeError(message)
    return factor_ids


def _parse_years(value: str) -> tuple[int, ...]:
    try:
        years = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        message = f"years must be comma-separated integers: {value!r}"
        if typer is not None:
            raise typer.BadParameter(message) from exc
        raise argparse.ArgumentTypeError(message) from exc
    if not years:
        message = "at least one year is required"
        if typer is not None:
            raise typer.BadParameter(message)
        raise argparse.ArgumentTypeError(message)
    return years


def _parse_scenario_cost_bps(value: str | None) -> dict[str, float] | None:
    if value is None or not value.strip():
        return None
    result: dict[str, float] = {}
    for item in value.split(","):
        if not item.strip():
            continue
        if "=" not in item:
            message = f"scenario cost must use scenario=bps pairs: {value!r}"
            if typer is not None:
                raise typer.BadParameter(message)
            raise argparse.ArgumentTypeError(message)
        scenario_id, raw_bps = item.split("=", 1)
        scenario = scenario_id.strip()
        try:
            bps = float(raw_bps.strip())
        except ValueError as exc:
            message = f"scenario bps must be numeric: {item!r}"
            if typer is not None:
                raise typer.BadParameter(message) from exc
            raise argparse.ArgumentTypeError(message) from exc
        if not scenario or bps < 0:
            message = f"scenario id must be non-empty and bps non-negative: {item!r}"
            if typer is not None:
                raise typer.BadParameter(message)
            raise argparse.ArgumentTypeError(message)
        result[scenario] = bps
    if not result:
        message = "at least one scenario=bps pair is required"
        if typer is not None:
            raise typer.BadParameter(message)
        raise argparse.ArgumentTypeError(message)
    return result


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
