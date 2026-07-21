from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.core.schemas import CoreOptionQuoteDailyRow, CoreQuoteDailyRow
from cotton_factor.research_workbench import build_cf_option_factor_proxy


def test_build_cf_option_factor_proxy_writes_research_outputs(tmp_path: Path) -> None:
    option_core_path = _write_option_core(tmp_path)
    core_quote_path = _write_core_quotes(tmp_path)

    result = build_cf_option_factor_proxy(
        option_core_path=option_core_path,
        core_quote_path=core_quote_path,
        output_dir=tmp_path / "data" / "option_factors",
        report_output_dir=tmp_path / "reports" / "option_factors",
        run_id="r48_unit",
        iv_rank_lookback_days=10,
    )

    assert result.status == "COMPLETED"
    assert result.factor_row_count == 2
    assert result.eligible_option_row_count == 8
    assert result.excluded_option_row_count == 1
    assert result.factor_parquet_path.exists()
    assert result.surface_parquet_path.exists()
    assert result.warning_csv_path.exists()
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.manifest_path.exists()

    factors = pd.read_parquet(result.factor_parquet_path)
    first = factors.loc[factors["trade_date"].astype(str) == "2024-01-02"].iloc[0]
    assert first["factor_status"] == "READY"
    assert first["option_signal_status"] == "not_connected"
    assert first["atm_iv_proxy"] == pytest.approx((200 + 180) / 14000)
    assert first["pcr_volume"] == pytest.approx((120 + 100) / (100 + 80))
    assert first["pcr_oi"] == pytest.approx((240 + 200) / (200 + 100))
    assert first["skew_proxy"] == pytest.approx((60 / 14000) - (70 / 14000))

    second = factors.loc[factors["trade_date"].astype(str) == "2024-01-03"].iloc[0]
    assert second["atm_iv_rank"] == pytest.approx(1.0)

    surface = pd.read_parquet(result.surface_parquet_path)
    excluded = surface.loc[surface["option_symbol"] == "CF401C17000"].iloc[0]
    assert excluded["included_in_factor"] is False or excluded["included_in_factor"] == 0
    assert "LOW_LIQUIDITY_VOLUME" in excluded["exclusion_reason"]
    assert "DEEP_OTM_PROXY" in excluded["exclusion_reason"]

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "美式期权" in markdown
    assert "研究 proxy" in markdown
    assert "不构成交易指令" in markdown
    assert "forward return、回测收益、交易成本不进入本模块" in markdown

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["option_signal_status"] == "not_connected"
    assert "American option IV/Greek not precisely priced" in manifest["model_boundary"]


def test_build_cf_option_factor_proxy_rejects_missing_required_columns(
    tmp_path: Path,
) -> None:
    option_path = tmp_path / "bad_option.parquet"
    pd.DataFrame([{"trade_date": "2024-01-02"}]).to_parquet(option_path, index=False)

    with pytest.raises(ResearchWorkbenchErrorWrapper, match="missing columns"):
        _call_build_with_error_wrapper(option_path=option_path, tmp_path=tmp_path)


def test_cli_build_cf_option_factor_proxy(tmp_path: Path) -> None:
    option_core_path = _write_option_core(tmp_path)
    core_quote_path = _write_core_quotes(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-option-factor-proxy",
            "--option-core-path",
            str(option_core_path),
            "--core-quote-path",
            str(core_quote_path),
            "--output-dir",
            str(tmp_path / "data" / "option_factors"),
            "--report-output-dir",
            str(tmp_path / "reports" / "option_factors"),
            "--run-id",
            "r48_cli",
            "--iv-rank-lookback-days",
            "10",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "r48_cli"
    assert output["status"] == "COMPLETED"
    assert output["factor_row_count"] == 2
    assert Path(output["factor_parquet_path"]).exists()
    assert Path(output["surface_parquet_path"]).exists()


def test_option_factor_incremental_recomputes_latest_date_only(tmp_path: Path) -> None:
    option_core_path = _write_option_core(tmp_path)
    core_quote_path = _write_core_quotes(tmp_path)
    output_dir = tmp_path / "data" / "option_factors"
    report_dir = tmp_path / "reports" / "option_factors"
    build_cf_option_factor_proxy(
        option_core_path=option_core_path,
        core_quote_path=core_quote_path,
        output_dir=output_dir,
        report_output_dir=report_dir,
        run_id="r48_full_base",
        iv_rank_lookback_days=10,
    )

    option_frame = pd.read_parquet(option_core_path)
    extra_options = [
        _option_row("2024-01-04", "CF401C14000", "C", 14000, 360, 120, 220, 1.0),
        _option_row("2024-01-04", "CF401P14000", "P", 14000, 300, 140, 260, 1.0),
        _option_row("2024-01-04", "CF401C15000", "C", 15000, 80, 90, 120, 14200 / 15000),
        _option_row("2024-01-04", "CF401P13000", "P", 13000, 70, 110, 210, 13000 / 14200),
    ]
    pd.concat(
        [
            option_frame,
            pd.DataFrame([row.model_dump(mode="json") for row in extra_options]),
        ],
        ignore_index=True,
    ).to_parquet(option_core_path, index=False)
    quote_frame = pd.read_parquet(core_quote_path)
    extra_quote = CoreQuoteDailyRow(
        source_snapshot_id="quote_fixture_20240104",
        exchange="CZCE",
        product_code="CF",
        contract_code="CF401",
        trade_date="2024-01-04",
        settle=14200,
        volume=1300,
        open_interest=2200,
    )
    pd.concat(
        [quote_frame, pd.DataFrame([extra_quote.model_dump(mode="json")])],
        ignore_index=True,
    ).to_parquet(core_quote_path, index=False)

    result = build_cf_option_factor_proxy(
        option_core_path=option_core_path,
        core_quote_path=core_quote_path,
        output_dir=output_dir,
        report_output_dir=report_dir,
        run_id="r48_incremental",
        iv_rank_lookback_days=10,
        incremental=True,
    )

    assert result.build_mode == "INCREMENTAL_LATEST_DATE"
    assert result.factor_row_count == 3
    assert result.surface_row_count == 13
    factors = pd.read_parquet(result.factor_parquet_path)
    assert factors["trade_date"].astype(str).tolist() == [
        "2024-01-02",
        "2024-01-03",
        "2024-01-04",
    ]
    full_result = build_cf_option_factor_proxy(
        option_core_path=option_core_path,
        core_quote_path=core_quote_path,
        output_dir=tmp_path / "data" / "option_factors_full_check",
        report_output_dir=tmp_path / "reports" / "option_factors_full_check",
        run_id="r48_full_check",
        iv_rank_lookback_days=10,
    )
    full_factors = pd.read_parquet(full_result.factor_parquet_path)
    comparison_columns = [
        "trade_date",
        "underlying_contract",
        "atm_iv_proxy",
        "atm_iv_rank",
        "pcr_volume",
        "pcr_oi",
        "skew_proxy",
        "factor_status",
    ]
    pd.testing.assert_frame_equal(
        factors[comparison_columns].reset_index(drop=True),
        full_factors[comparison_columns].reset_index(drop=True),
        check_dtype=False,
    )


class ResearchWorkbenchErrorWrapper(Exception):
    """Small wrapper so pytest does not need to import internal exception twice."""


def _call_build_with_error_wrapper(*, option_path: Path, tmp_path: Path) -> None:
    from cotton_factor.common.exceptions import ResearchWorkbenchError

    try:
        build_cf_option_factor_proxy(
            option_core_path=option_path,
            core_quote_path=_write_core_quotes(tmp_path),
            output_dir=tmp_path / "data",
            report_output_dir=tmp_path / "reports",
            run_id="r48_bad_columns",
        )
    except ResearchWorkbenchError as exc:
        raise ResearchWorkbenchErrorWrapper(str(exc)) from exc


def _write_option_core(tmp_path: Path) -> Path:
    rows = [
        _option_row("2024-01-02", "CF401C14000", "C", 14000, 200, 100, 200, 1.0),
        _option_row("2024-01-02", "CF401P14000", "P", 14000, 180, 120, 240, 1.0),
        _option_row("2024-01-02", "CF401C15000", "C", 15000, 70, 80, 100, 14000 / 15000),
        _option_row("2024-01-02", "CF401P13000", "P", 13000, 60, 100, 200, 13000 / 14000),
        _option_row(
            "2024-01-02",
            "CF401C17000",
            "C",
            17000,
            10,
            0,
            1,
            14000 / 17000,
            data_quality_flag="LOW_LIQUIDITY_VOLUME;DEEP_OTM_PROXY",
            liquidity_flag="low_liquidity",
        ),
        _option_row("2024-01-03", "CF401C14000", "C", 14000, 320, 110, 210, 14100 / 14000),
        _option_row("2024-01-03", "CF401P14000", "P", 14000, 280, 130, 250, 14000 / 14100),
        _option_row("2024-01-03", "CF401C15000", "C", 15000, 75, 85, 110, 14100 / 15000),
        _option_row("2024-01-03", "CF401P13000", "P", 13000, 65, 105, 205, 13000 / 14100),
    ]
    path = tmp_path / "core" / "CF" / "core_option_quote_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _option_row(
    trade_date: str,
    option_symbol: str,
    option_type: str,
    strike: float,
    settle: float,
    volume: int,
    open_interest: int,
    moneyness: float,
    *,
    data_quality_flag: str = "normal",
    liquidity_flag: str = "normal_liquidity",
) -> CoreOptionQuoteDailyRow:
    return CoreOptionQuoteDailyRow(
        source_snapshot_id=f"option_fixture_{option_symbol}_{trade_date}",
        exchange="CZCE",
        product_code="CF",
        trade_date=trade_date,
        option_symbol=option_symbol,
        underlying_contract="CF401",
        option_type=option_type,
        strike=strike,
        settle=settle,
        volume=volume,
        open_interest=open_interest,
        moneyness=moneyness,
        liquidity_flag=liquidity_flag,
        data_quality_flag=data_quality_flag,
    )


def _write_core_quotes(tmp_path: Path) -> Path:
    rows = [
        CoreQuoteDailyRow(
            source_snapshot_id="quote_fixture_20240102",
            exchange="CZCE",
            product_code="CF",
            contract_code="CF401",
            trade_date="2024-01-02",
            settle=14000,
            volume=1000,
            open_interest=2000,
        ),
        CoreQuoteDailyRow(
            source_snapshot_id="quote_fixture_20240103",
            exchange="CZCE",
            product_code="CF",
            contract_code="CF401",
            trade_date="2024-01-03",
            settle=14100,
            volume=1200,
            open_interest=2100,
        ),
    ]
    path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path
