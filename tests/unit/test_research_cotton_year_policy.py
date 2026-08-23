from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench.cotton_year_policy import (
    append_spot_extension,
    build_cf_cotton_year_policy_research,
    build_policy_reference_daily,
    build_policy_reference_historical_validation,
    cotton_year_label,
    load_policy_reference_config,
)


def test_cotton_year_changes_on_september_first() -> None:
    assert cotton_year_label(date(2024, 8, 31)) == "2023/24"
    assert cotton_year_label(date(2024, 9, 1)) == "2024/25"


def test_policy_daily_uses_backward_spot_only_and_excludes_adjusted_price() -> None:
    continuous, spot, _ = _fixture_frames()
    config = load_policy_reference_config(
        Path("configs/research/CF_policy_reference_v1.yaml")
    )

    daily = build_policy_reference_daily(
        continuous=continuous,
        spot=spot,
        config=config,
        max_spot_staleness_days=3,
    )

    august_31 = daily.loc[daily["trade_date"].eq(pd.Timestamp("2024-08-31"))].iloc[0]
    september_1 = daily.loc[daily["trade_date"].eq(pd.Timestamp("2024-09-01"))].iloc[0]
    assert august_31["spot_observation_date"] == pd.Timestamp("2024-08-29")
    assert september_1["spot_observation_date"] == pd.Timestamp("2024-08-29")
    assert september_1["spot_price_observed"] == pytest.approx(18_200.0)
    assert september_1["cotton_year"] == "2024/25"
    assert september_1["futures_gap_to_reference"] == pytest.approx(-300.0)
    assert "adjusted_price" not in daily.columns
    assert "forward_return" not in daily.columns
    assert not daily["contains_forward_label"].any()


def test_current_state_is_stable_when_future_is_truncated_and_labels_are_separate() -> None:
    continuous, spot, _ = _fixture_frames()
    config = load_policy_reference_config(
        Path("configs/research/CF_policy_reference_v1.yaml")
    )
    full = build_policy_reference_daily(
        continuous=continuous,
        spot=spot,
        config=config,
        max_spot_staleness_days=3,
    )
    cutoff = pd.Timestamp("2024-09-01")
    truncated = build_policy_reference_daily(
        continuous=continuous.loc[pd.to_datetime(continuous["trade_date"]).le(cutoff)],
        spot=spot.loc[pd.to_datetime(spot["trade_date"]).le(cutoff)],
        config=config,
        max_spot_staleness_days=3,
    )

    full_at_cutoff = full.loc[full["trade_date"].eq(cutoff)].iloc[0].to_dict()
    truncated_at_cutoff = truncated.iloc[-1].to_dict()
    assert full_at_cutoff == truncated_at_cutoff

    validation = build_policy_reference_historical_validation(
        daily=full,
        horizons=(1,),
    )
    roll_label = validation.loc[
        validation["signal_trade_date"].eq(pd.Timestamp("2024-09-01"))
    ].iloc[0]
    assert not bool(roll_label["futures_same_contract"])
    assert pd.isna(roll_label["futures_gap_converged"])
    assert roll_label["label_type"] == "HISTORICAL_POSTERIOR_ONLY"
    assert validation["contains_forward_label"].all()


def test_r93g_builder_and_cli_write_complete_artifacts(tmp_path: Path) -> None:
    paths = _write_fixture_paths(tmp_path)
    result = build_cf_cotton_year_policy_research(
        continuous_price_path=paths["continuous"],
        spot_price_path=paths["spot"],
        spot_extension_path=paths["spot_extension"],
        fundamental_context_path=paths["context"],
        policy_config_path=Path("configs/research/CF_policy_reference_v1.yaml"),
        horizons=(1, 2),
        max_spot_staleness_days=3,
        output_dir=tmp_path / "data",
        report_output_dir=tmp_path / "reports",
        run_id="r93g_unit",
    )

    for path in (
        result.daily_path,
        result.cotton_year_summary_path,
        result.historical_validation_path,
        result.validation_summary_path,
        result.fundamental_summary_path,
        result.warning_csv_path,
        result.json_path,
        result.manifest_path,
        result.markdown_path,
    ):
        assert path.exists()
        assert path.stat().st_size > 0
    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["current_state_contains_forward_labels"] is False
    assert payload["historical_validation_is_posterior_only"] is True
    assert payload["historical_validation_uses_overlapping_daily_observations"] is True
    assert payload["fundamental_signal_status"] == "not_connected"
    assert payload["summary"]["latest_spot_source_indicator_id"] == "S002885871"
    assert payload["spot_bridge_statistics"]["overlapping_history_overwritten"] is False
    assert payload["spot_bridge_statistics"]["overlap_count"] == 2
    report = result.markdown_path.read_text(encoding="utf-8")
    assert "不能当作郑棉期货支撑位" in report
    assert "不构成交易指令" in report
    assert "没有被本模块读取或并入主仓库" in report
    assert "重叠历史未覆盖" in report

    cli_result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-cotton-year-policy-research",
            "--continuous-price-path",
            str(paths["continuous"]),
            "--spot-price-path",
            str(paths["spot"]),
            "--spot-extension-path",
            str(paths["spot_extension"]),
            "--fundamental-context-path",
            str(paths["context"]),
            "--policy-config-path",
            "configs/research/CF_policy_reference_v1.yaml",
            "--horizons",
            "1,2",
            "--max-spot-staleness-days",
            "3",
            "--output-dir",
            str(tmp_path / "cli_data"),
            "--report-output-dir",
            str(tmp_path / "cli_reports"),
            "--run-id",
            "r93g_cli",
        ],
    )
    assert cli_result.exit_code == 0, cli_result.output
    cli_payload = json.loads(cli_result.output)
    assert cli_payload["run_id"] == "r93g_cli"
    assert cli_payload["target_price"] == 18_600.0
    assert Path(cli_payload["daily_path"]).exists()
    assert cli_payload["latest_spot_source_name"] == "iFinD EDB"


def test_ifind_spot_extension_only_appends_after_primary_history() -> None:
    _, spot, _ = _fixture_frames()
    config = load_policy_reference_config(
        Path("configs/research/CF_policy_reference_v1.yaml")
    )

    combined = append_spot_extension(
        primary_spot=spot,
        extension_spot=_fixture_spot_extension(),
        config=config,
    )

    primary_end = pd.Timestamp("2024-09-02")
    assert combined.loc[
        combined["trade_date"].eq(pd.Timestamp("2024-09-01"))
        & combined["source_indicator_id"].eq("S002885871")
    ].empty
    extension = combined.loc[
        combined["spot_bridge_status"].eq("FORWARD_EXTENSION_AFTER_PRIMARY_END")
    ]
    assert extension["trade_date"].min() > primary_end
    assert extension.iloc[0]["indicator_id"] == config.spot_indicator_id
    assert extension.iloc[0]["source_indicator_id"] == "S002885871"


def _write_fixture_paths(tmp_path: Path) -> dict[str, Path]:
    continuous, spot, context = _fixture_frames()
    paths = {
        "continuous": tmp_path / "continuous.parquet",
        "spot": tmp_path / "spot.parquet",
        "spot_extension": tmp_path / "spot_extension.parquet",
        "context": tmp_path / "context.parquet",
    }
    continuous.to_parquet(paths["continuous"], index=False)
    spot.to_parquet(paths["spot"], index=False)
    _fixture_spot_extension().to_parquet(paths["spot_extension"], index=False)
    context.to_parquet(paths["context"], index=False)
    return paths


def _fixture_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = [date(2024, 8, 29) + timedelta(days=index) for index in range(6)]
    contracts = ["CF501", "CF501", "CF501", "CF501", "CF505", "CF505"]
    futures_prices = [18_000.0, 18_100.0, 18_200.0, 18_300.0, 18_500.0, 18_650.0]
    continuous = pd.DataFrame(
        [
            {
                "trade_date": trade_date,
                "product_code": "CF",
                "signal_object_id": "CF.C1",
                "mapped_contract": contract,
                "price_field": "settle",
                "raw_price": price,
                "adjusted_price": price + 500.0,
                "input_snapshot_ids": [f"snapshot_{trade_date:%Y%m%d}"],
            }
            for trade_date, contract, price in zip(
                dates, contracts, futures_prices, strict=True
            )
        ]
    )
    spot = pd.DataFrame(
        [
            {
                "trade_date": dates[0],
                "indicator_id": "S0031714",
                "indicator_name": "中国棉花价格指数:3128B",
                "indicator_value": 18_200.0,
                "unit": "元/吨",
                "source_name": "fixture",
                "data_quality_flag": "REVIEW_REQUIRED",
                "human_review_required": True,
            },
            {
                "trade_date": dates[4],
                "indicator_id": "S0031714",
                "indicator_name": "中国棉花价格指数:3128B",
                "indicator_value": 18_700.0,
                "unit": "元/吨",
                "source_name": "fixture",
                "data_quality_flag": "REVIEW_REQUIRED",
                "human_review_required": True,
            },
        ]
    )
    context = pd.DataFrame(
        [
            {
                "trade_date": dates[0],
                "dataset_type": "warehouse_receipt",
                "indicator_name": "warehouse_fixture",
                "metric_name": "warehouse_receipt",
                "indicator_value": 1000.0,
                "unit": "lot",
                "source_name": "fixture",
                "human_review_required": True,
            },
            {
                "trade_date": dates[-1],
                "dataset_type": "warehouse_receipt",
                "indicator_name": "warehouse_fixture",
                "metric_name": "warehouse_receipt",
                "indicator_value": 900.0,
                "unit": "lot",
                "source_name": "fixture",
                "human_review_required": True,
            },
        ]
    )
    return continuous, spot, context


def _fixture_spot_extension() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_date": date(2024, 8, 29),
                "indicator_id": "S002885871",
                "indicator_name": "现货价:棉花(3128B级)",
                "indicator_value": 18_150.0,
                "unit": "元/吨",
                "source_name": "iFinD EDB",
                "data_quality_flag": "REVIEW_REQUIRED",
                "human_review_required": True,
            },
            {
                "trade_date": date(2024, 9, 1),
                "indicator_id": "S002885871",
                "indicator_name": "现货价:棉花(3128B级)",
                "indicator_value": 17_900.0,
                "unit": "元/吨",
                "source_name": "iFinD EDB",
                "data_quality_flag": "REVIEW_REQUIRED",
                "human_review_required": True,
            },
            {
                "trade_date": date(2024, 9, 2),
                "indicator_id": "S002885871",
                "indicator_name": "现货价:棉花(3128B级)",
                "indicator_value": 18_650.0,
                "unit": "元/吨",
                "source_name": "iFinD EDB",
                "data_quality_flag": "REVIEW_REQUIRED",
                "human_review_required": True,
            },
            {
                "trade_date": date(2024, 9, 3),
                "indicator_id": "S002885871",
                "indicator_name": "现货价:棉花(3128B级)",
                "indicator_value": 17_600.0,
                "unit": "元/吨",
                "source_name": "iFinD EDB",
                "data_quality_flag": "REVIEW_REQUIRED",
                "human_review_required": True,
            },
        ]
    )
