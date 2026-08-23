from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench import (
    build_cf_futures_option_dynamic_wall_research,
    build_cf_futures_option_wall_factor_v2_research,
)


def test_dynamic_wall_fixture_writes_features_labels_events_and_oos(tmp_path: Path) -> None:
    quote_path, option_path, signal_path = _write_fixture(tmp_path)

    result = build_cf_futures_option_dynamic_wall_research(
        option_core_path=option_path,
        core_quote_path=quote_path,
        signal_matrix_path=signal_path,
        output_dir=tmp_path / "data" / "dynamic_wall",
        report_output_dir=tmp_path / "reports" / "dynamic_wall",
        run_id="r93n_unit",
        horizons=(1, 3, 5),
        local_band_ratio=0.05,
        touch_band_ratio=0.01,
        min_sample_size=30,
    )

    assert result.feature_row_count == 12
    assert result.event_row_count > 0
    assert result.label_row_count == 36
    assert result.event_label_row_count > 0
    assert result.oos_summary_parquet_path.exists()
    assert result.manifest_path.exists()
    assert result.warning_csv_path.exists()

    features = pd.read_parquet(result.feature_parquet_path)
    labels = pd.read_parquet(result.label_parquet_path)
    events = pd.read_parquet(result.event_parquet_path)
    summary = pd.read_parquet(result.summary_by_node_parquet_path)

    assert features["feature_uses_t_or_earlier"].all()
    assert not features["contains_posterior_outcome"].any()
    assert features["dynamic_call_total_open_interest"].le(
        features["static_call_total_open_interest"]
    ).all()
    assert features["dynamic_wall_rule_version"].notna().all()
    assert features["r48_option_direction_5d"].isin(["long", "short", "neutral"]).all()
    assert set(labels["horizon"]) == {1, 3, 5}
    available = labels.loc[labels["forward_label_available"]].copy()
    assert (
        pd.to_datetime(available["execution_date"])
        > pd.to_datetime(available["trade_date"])
    ).all()
    assert (
        pd.to_datetime(available["exit_date"])
        >= pd.to_datetime(available["execution_date"])
    ).all()
    assert (available["execution_date"] != available["trade_date"]).all()
    assert labels["forward_returns_are_historical_posterior_labels"].all()
    assert events["event_trigger_observable_at_t"].all()
    assert "dynamic_minus_r48_mean_return" in summary.columns
    assert "fdr_q_value" in summary.columns
    assert "WEAK_OR_SMALL_SAMPLE" in set(summary["evidence_status"])

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "forward return仅为历史后验验证标签" in markdown
    assert "不构成交易指令" in markdown
    assert "期权IV/Greek" in markdown
    assert "HUMAN_REVIEW_REQUIRED" in markdown


def test_cli_dynamic_wall_writes_json_bundle(tmp_path: Path) -> None:
    quote_path, option_path, _ = _write_fixture(tmp_path)
    output_dir = tmp_path / "data" / "dynamic_wall"
    report_dir = tmp_path / "reports" / "dynamic_wall"

    invocation = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-futures-option-dynamic-wall-research",
            "--option-core-path",
            str(option_path),
            "--core-quote-path",
            str(quote_path),
            "--horizons",
            "1",
            "--min-sample-size",
            "1",
            "--local-band-ratio",
            "0.05",
            "--output-dir",
            str(output_dir),
            "--report-output-dir",
            str(report_dir),
            "--run-id",
            "r93n_cli",
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    payload = json.loads(invocation.stdout)
    assert payload["run_id"] == "r93n_cli"
    assert payload["latest_main_contract"] == "CF609"
    assert payload["promotion_eligible"] is False
    assert Path(payload["feature_parquet_path"]).exists()
    assert Path(payload["markdown_path"]).exists()


def test_stale_phase_sidecar_is_explicitly_marked(tmp_path: Path) -> None:
    quote_path, option_path, signal_path = _write_fixture(tmp_path)
    dates = pd.date_range("2026-01-02", periods=11, freq="B")
    phase_path = tmp_path / "trend_phase_v2_daily.parquet"
    pd.DataFrame(
        {
            "trade_date": dates,
            "main_contract": "CF609",
            "phase_v2": "S0",
        }
    ).to_parquet(phase_path, index=False)

    result = build_cf_futures_option_dynamic_wall_research(
        option_core_path=option_path,
        core_quote_path=quote_path,
        signal_matrix_path=signal_path,
        trend_phase_path=phase_path,
        output_dir=tmp_path / "data" / "stale_wall",
        report_output_dir=tmp_path / "reports" / "stale_wall",
        run_id="r93n_stale_sidecar",
        horizons=(1,),
        min_sample_size=1,
    )

    features = pd.read_parquet(result.feature_parquet_path)
    warnings = pd.read_csv(result.warning_csv_path)
    latest = features.sort_values("trade_date").iloc[-1]

    assert latest["phase_v2"] == "not_connected"
    stale = warnings.loc[
        warnings["warning_code"].eq("OPTION_RESEARCH_SIDECAR_ASOF_BEHIND")
    ]
    assert len(stale) == 1
    assert stale.iloc[0]["severity"] == "WARN"


def test_wall_factor_v2_keeps_t_features_separate_from_posterior_labels(
    tmp_path: Path,
) -> None:
    quote_path, option_path, signal_path = _write_fixture(tmp_path)
    r93n = build_cf_futures_option_dynamic_wall_research(
        option_core_path=option_path,
        core_quote_path=quote_path,
        signal_matrix_path=signal_path,
        output_dir=tmp_path / "data" / "r93n_for_r93o",
        report_output_dir=tmp_path / "reports" / "r93n_for_r93o",
        run_id="r93n_for_r93o",
        horizons=(1, 3, 5),
        local_band_ratio=0.05,
        min_sample_size=1,
    )

    result = build_cf_futures_option_wall_factor_v2_research(
        dynamic_wall_feature_path=r93n.feature_parquet_path,
        dynamic_wall_label_path=r93n.label_parquet_path,
        output_dir=tmp_path / "data" / "r93o",
        report_output_dir=tmp_path / "reports" / "r93o",
        run_id="r93o_unit",
        min_sample_size=1,
    )

    assert result.feature_row_count == 12
    assert result.candidate_count == 16
    assert result.candidate_signal_row_count == 12 * 16
    assert result.posterior_label_row_count == 12 * 16 * 3
    assert result.manifest_path.exists()
    assert result.warning_csv_path.exists()

    features = pd.read_parquet(result.feature_parquet_path)
    labels = pd.read_parquet(result.posterior_label_parquet_path)
    evidence = pd.read_parquet(result.candidate_evidence_parquet_path)

    assert "forward_return" not in features.columns
    assert features["r93o_feature_uses_t_or_earlier"].all()
    assert not features["r93o_contains_posterior_outcome"].any()
    available = labels.loc[labels["forward_label_available"]].copy()
    assert (
        pd.to_datetime(available["execution_date"])
        > pd.to_datetime(available["trade_date"])
    ).all()
    assert labels["forward_returns_are_historical_posterior_labels"].all()
    assert set(evidence["decision"]) <= {"KEEP", "WATCH", "REJECT"}

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "预注册定义" in markdown
    assert "forward return仅为历史后验验证标签" in markdown
    assert "不构成交易指令" in markdown
    assert "期权IV/Greek" in markdown


def test_wall_factor_v2_cli_writes_json_bundle(tmp_path: Path) -> None:
    quote_path, option_path, signal_path = _write_fixture(tmp_path)
    r93n = build_cf_futures_option_dynamic_wall_research(
        option_core_path=option_path,
        core_quote_path=quote_path,
        signal_matrix_path=signal_path,
        output_dir=tmp_path / "data" / "r93n_cli_source",
        report_output_dir=tmp_path / "reports" / "r93n_cli_source",
        run_id="r93n_cli_source",
        horizons=(1, 3, 5),
        local_band_ratio=0.05,
        min_sample_size=1,
    )
    invocation = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-futures-option-wall-factor-v2",
            "--dynamic-wall-feature-path",
            str(r93n.feature_parquet_path),
            "--dynamic-wall-label-path",
            str(r93n.label_parquet_path),
            "--horizons",
            "1,3,5",
            "--min-sample-size",
            "1",
            "--output-dir",
            str(tmp_path / "data" / "r93o_cli"),
            "--report-output-dir",
            str(tmp_path / "reports" / "r93o_cli"),
            "--run-id",
            "r93o_cli",
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    payload = json.loads(invocation.stdout)
    assert payload["run_id"] == "r93o_cli"
    assert payload["promotion_eligible"] is False
    assert Path(payload["candidate_evidence_parquet_path"]).exists()
    assert Path(payload["markdown_path"]).exists()


def test_wall_factor_v2_rejects_non_t_plus_one_label(tmp_path: Path) -> None:
    quote_path, option_path, signal_path = _write_fixture(tmp_path)
    r93n = build_cf_futures_option_dynamic_wall_research(
        option_core_path=option_path,
        core_quote_path=quote_path,
        signal_matrix_path=signal_path,
        output_dir=tmp_path / "data" / "r93n_invalid_source",
        report_output_dir=tmp_path / "reports" / "r93n_invalid_source",
        run_id="r93n_invalid_source",
        horizons=(1,),
        local_band_ratio=0.05,
        min_sample_size=1,
    )
    invalid_path = tmp_path / "invalid_label.parquet"
    labels = pd.read_parquet(r93n.label_parquet_path)
    available_index = labels.index[labels["forward_label_available"]][0]
    labels.loc[available_index, "execution_date"] = labels.loc[available_index, "trade_date"]
    labels.to_parquet(invalid_path, index=False)

    with pytest.raises(ResearchWorkbenchError, match="execution_date必须晚于trade_date"):
        build_cf_futures_option_wall_factor_v2_research(
            dynamic_wall_feature_path=r93n.feature_parquet_path,
            dynamic_wall_label_path=invalid_path,
            output_dir=tmp_path / "data" / "r93o_invalid",
            report_output_dir=tmp_path / "reports" / "r93o_invalid",
            run_id="r93o_invalid",
            horizons=(1,),
            min_sample_size=1,
        )


def _write_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    dates = pd.date_range("2026-01-02", periods=12, freq="B")
    settles = [100.0, 101.0, 104.0, 103.0, 105.0, 106.0, 104.0, 107.0, 108.0, 109.0, 110.0, 111.0]
    quote_rows = []
    for index, (trade_date, settle) in enumerate(zip(dates, settles, strict=True)):
        quote_rows.append(
            {
                "exchange": "CZCE",
                "product_code": "CF",
                "contract_code": "CF609",
                "trade_date": trade_date,
                "pre_settle": settle - 0.5,
                "open": settle - 0.25,
                "high": settle + 1.5,
                "low": settle - 1.5,
                "close": settle,
                "settle": settle,
                "volume": 1000 + index * 10,
                "open_interest": 10000 + index * 20,
                "turnover": 100000.0,
            }
        )

    option_rows = []
    strikes = [("C", 103.0, 500), ("C", 100.0, 100), ("P", 97.0, 450), ("P", 100.0, 80)]
    for index, trade_date in enumerate(dates):
        for option_type, strike, base_oi in strikes:
            option_rows.append(
                {
                    "exchange": "CZCE",
                    "trade_date": trade_date,
                    "option_symbol": f"CF609{option_type}{int(strike)}",
                    "underlying_contract": "CF609",
                    "option_type": option_type,
                    "strike": strike,
                    "settle": 1.0,
                    "volume": 20 + index,
                    "open_interest": base_oi + index * (30 if option_type == "C" else 10),
                    "liquidity_flag": "normal",
                    "data_quality_flag": "normal",
                }
            )
        # 该行保留在静态基线，但必须被动态核心排除。
        option_rows.append(
            {
                "exchange": "CZCE",
                "trade_date": trade_date,
                "option_symbol": "CF609C130",
                "underlying_contract": "CF609",
                "option_type": "C",
                "strike": 130.0,
                "settle": 0.1,
                "volume": 0,
                "open_interest": 900 + index,
                "liquidity_flag": "low_liquidity",
                "data_quality_flag": "DEEP_OTM_PROXY",
            }
        )

    signal_rows = [
        {
            "trade_date": trade_date,
            "horizon": 5,
            "main_contract": "CF609",
            "direction": "long",
            "confidence": "medium",
            "composite_score": 1.0,
            "option_signal": "confirm_long",
            "option_signal_direction": "long",
            "option_underlying_contract": "CF609",
            "option_factor_status": "READY",
        }
        for trade_date in dates
    ]

    quote_path = tmp_path / "core_quote_daily.parquet"
    option_path = tmp_path / "core_option_quote_daily.parquet"
    signal_path = tmp_path / "signal_matrix_daily.parquet"
    pd.DataFrame(quote_rows).to_parquet(quote_path, index=False)
    pd.DataFrame(option_rows).to_parquet(option_path, index=False)
    pd.DataFrame(signal_rows).to_parquet(signal_path, index=False)
    return quote_path, option_path, signal_path
