from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import (
    build_cf_chain_oi_structure,
    build_cf_current_watch_window,
    build_cf_dual_price_state,
    build_cf_option_structure_research,
    build_cf_trend_phase_v2,
)
from cotton_factor.research_workbench.trend_phase_v2 import _classify


def test_r73_to_r77_state_upgrade_pack(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    r73 = build_cf_dual_price_state(
        core_quote_path=paths["core"],
        output_dir=tmp_path / "research" / "dual",
        report_output_dir=tmp_path / "reports" / "dual",
        run_id="r73_unit",
        ma_window=5,
    )
    dual = pd.read_parquet(r73.daily_parquet_path)
    assert dual.iloc[-2]["dual_price_state"] == "CLOSE_BREAK_SETTLE_HOLD"
    assert dual.iloc[-1]["dual_price_state"] == "BOTH_ABOVE"
    assert "forward return 仅为后验验证标签" in r73.markdown_path.read_text(
        encoding="utf-8"
    )

    r74 = build_cf_chain_oi_structure(
        core_quote_path=paths["core"],
        output_dir=tmp_path / "research" / "oi",
        report_output_dir=tmp_path / "reports" / "oi",
        run_id="r74_unit",
        noise_ratio=0.001,
    )
    oi = pd.read_parquet(r74.daily_parquet_path)
    assert oi.iloc[-1]["participation_state"] == "SHORT_COVER_OR_EXIT"
    assert oi.iloc[-1]["chain_oi_change"] < 0
    assert "roll_context" in oi.columns
    assert "roll_transfer_ratio_window" in oi.columns
    assert "chain_oi_change_adjusted" in oi.columns
    assert r74.contract_detail_parquet_path.exists()

    r75 = build_cf_option_structure_research(
        option_factor_path=paths["option"],
        signal_matrix_path=paths["matrix"],
        validation_daily_path=paths["validation"],
        output_dir=tmp_path / "research" / "option",
        report_output_dir=tmp_path / "reports" / "option",
        run_id="r75_unit",
        primary_horizon=20,
    )
    option = pd.read_parquet(r75.daily_parquet_path)
    assert option.iloc[-1]["option_direction"] == "long"
    assert option.iloc[-1]["confirmation_state"] == "CONFIRM_LONG"
    assert option.iloc[-1]["enters_composite_score"] == False  # noqa: E712
    assert not pd.read_parquet(r75.validation_parquet_path).empty

    r76 = build_cf_trend_phase_v2(
        dual_price_path=r73.daily_parquet_path,
        chain_oi_path=r74.daily_parquet_path,
        option_structure_path=r75.daily_parquet_path,
        signal_matrix_path=paths["matrix"],
        validation_daily_path=paths["validation"],
        output_dir=tmp_path / "research" / "phase",
        report_output_dir=tmp_path / "reports" / "phase",
        run_id="r76_unit",
        primary_horizon=20,
    )
    phase = pd.read_parquet(r76.daily_parquet_path)
    assert phase.iloc[-1]["phase_v2"] == "S3"
    assert phase.iloc[-1]["phase_quality"] == "weak"
    assert "CHAIN_OI_EXIT" in phase.iloc[-1]["risk_flags"]
    assert phase.iloc[-1]["roll_context"] == "EXIT_DOMINANT"
    assert "roll_context" in pd.read_parquet(r76.validation_parquet_path).columns

    r77 = build_cf_current_watch_window(
        latest_signal_json_path=paths["latest"],
        dual_price_path=r73.daily_parquet_path,
        chain_oi_path=r74.daily_parquet_path,
        option_structure_path=r75.daily_parquet_path,
        trend_phase_v2_path=r76.daily_parquet_path,
        playbook_json_path=paths["playbook"],
        core_quote_path=paths["core"],
        output_dir=tmp_path / "research" / "watch",
        report_output_dir=tmp_path / "reports" / "watch",
        daily_output_root=tmp_path / "daily",
        run_id="r77_unit",
    )
    assert r77.phase_v2 == "S3"
    assert r77.watch_status == "EXHAUSTION_OR_FAILURE_WATCH"
    assert r77.expected_resolution_days == 8.0
    assert r77.daily_markdown_path.exists()
    markdown = r77.markdown_path.read_text(encoding="utf-8")
    assert "结构确认条件" in markdown
    assert "结构失效条件" in markdown
    assert "多日移仓" in markdown
    assert "同步站回并维持在各自20日均线上方（BOTH_ABOVE）" in markdown
    assert "期权转为或维持 CONFIRM_LONG" in markdown
    assert "不构成交易指令" in markdown


def test_r73_to_r77_cli_commands(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)
    runner = CliRunner()
    commands = [
        (
            "build-cf-dual-price-state",
            [
                "--core-quote-path",
                str(paths["core"]),
                "--output-dir",
                str(tmp_path / "cli" / "dual"),
                "--report-output-dir",
                str(tmp_path / "cli_reports" / "dual"),
                "--ma-window",
                "5",
            ],
        ),
        (
            "build-cf-chain-oi-structure",
            [
                "--core-quote-path",
                str(paths["core"]),
                "--output-dir",
                str(tmp_path / "cli" / "oi"),
                "--report-output-dir",
                str(tmp_path / "cli_reports" / "oi"),
                "--noise-ratio",
                "0.001",
            ],
        ),
        (
            "build-cf-option-structure-research",
            [
                "--option-factor-path",
                str(paths["option"]),
                "--signal-matrix-path",
                str(paths["matrix"]),
                "--validation-daily-path",
                str(paths["validation"]),
                "--output-dir",
                str(tmp_path / "cli" / "option"),
                "--report-output-dir",
                str(tmp_path / "cli_reports" / "option"),
            ],
        ),
    ]
    outputs: dict[str, dict[str, object]] = {}
    for command, arguments in commands:
        result = runner.invoke(app, ["research", command, *arguments])
        assert result.exit_code == 0, result.output
        outputs[command] = json.loads(result.output)

    phase_result = runner.invoke(
        app,
        [
            "research",
            "build-cf-trend-phase-v2",
            "--dual-price-path",
            str(outputs["build-cf-dual-price-state"]["daily_parquet_path"]),
            "--chain-oi-path",
            str(outputs["build-cf-chain-oi-structure"]["daily_parquet_path"]),
            "--option-structure-path",
            str(outputs["build-cf-option-structure-research"]["daily_parquet_path"]),
            "--signal-matrix-path",
            str(paths["matrix"]),
            "--validation-daily-path",
            str(paths["validation"]),
            "--output-dir",
            str(tmp_path / "cli" / "phase"),
            "--report-output-dir",
            str(tmp_path / "cli_reports" / "phase"),
        ],
    )
    assert phase_result.exit_code == 0, phase_result.output
    phase_output = json.loads(phase_result.output)

    watch_result = runner.invoke(
        app,
        [
            "research",
            "build-cf-current-watch-window",
            "--latest-signal-json-path",
            str(paths["latest"]),
            "--dual-price-path",
            str(outputs["build-cf-dual-price-state"]["daily_parquet_path"]),
            "--chain-oi-path",
            str(outputs["build-cf-chain-oi-structure"]["daily_parquet_path"]),
            "--option-structure-path",
            str(outputs["build-cf-option-structure-research"]["daily_parquet_path"]),
            "--trend-phase-v2-path",
            str(phase_output["daily_parquet_path"]),
            "--playbook-json-path",
            str(paths["playbook"]),
            "--core-quote-path",
            str(paths["core"]),
            "--output-dir",
            str(tmp_path / "cli" / "watch"),
            "--report-output-dir",
            str(tmp_path / "cli_reports" / "watch"),
            "--daily-output-root",
            str(tmp_path / "daily"),
        ],
    )
    assert watch_result.exit_code == 0, watch_result.output
    watch_output = json.loads(watch_result.output)
    assert watch_output["phase_v2"] == "S3"
    assert Path(watch_output["daily_markdown_path"]).exists()


def test_r74_distinguishes_multi_day_roll_from_net_exit(tmp_path: Path) -> None:
    core_path = tmp_path / "roll_core.parquet"
    dates = pd.bdate_range("2026-07-06", periods=6)
    main_oi = [1000, 990, 980, 970, 960, 900]
    far_one_oi = [500, 510, 520, 530, 540, 550]
    far_two_oi = [300, 304, 308, 312, 316, 320]
    rows: list[dict[str, object]] = []
    for index, timestamp in enumerate(dates):
        for contract, open_interest, price in (
            ("CF609", main_oi[index], 100.0 + index),
            ("CF611", far_one_oi[index], 101.0 + index),
            ("CF701", far_two_oi[index], 102.0 + index),
        ):
            rows.append(
                {
                    "trade_date": timestamp.date(),
                    "contract_code": contract,
                    "close": price,
                    "settle": price,
                    "volume": 100,
                    "open_interest": open_interest,
                }
            )
    pd.DataFrame(rows).to_parquet(core_path, index=False)

    result = build_cf_chain_oi_structure(
        core_quote_path=core_path,
        output_dir=tmp_path / "research" / "roll",
        report_output_dir=tmp_path / "reports" / "roll",
        run_id="r74_roll_window",
        roll_lookback_days=5,
    )

    daily = pd.read_parquet(result.daily_parquet_path)
    latest = daily.iloc[-1]
    assert latest["main_oi_change_window"] == -100
    assert latest["positive_other_oi_change_window"] == 70
    assert latest["chain_oi_change_window"] == -30
    assert latest["roll_transfer_ratio_window"] == pytest.approx(0.70)
    assert latest["roll_context"] == "ROLL_WITH_NET_EXIT"
    assert result.latest_roll_context == "ROLL_WITH_NET_EXIT"
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "最新交易日合约持仓变化" in markdown
    assert "存在明显移仓，同时全链净退出" in markdown


def test_r76_uses_roll_context_without_hiding_net_exit() -> None:
    common = {
        "futures_direction": "long",
        "momentum_signal": "long",
        "dual_price_state": "BOTH_ABOVE",
        "participation_state": "SHORT_COVER_OR_EXIT",
        "option_direction": "long",
        "confirmation_strength": "low",
        "volatility_repricing_state": "LOW_VOL_UNPRICED",
    }
    dominant = _classify(SimpleNamespace(**common, roll_context="ROLL_DOMINANT"))
    mixed = _classify(SimpleNamespace(**common, roll_context="ROLL_WITH_NET_EXIT"))

    assert dominant[0] == "S2"
    assert "ROLL_TRANSFER_CONTEXT" in dominant[5]
    assert "CHAIN_OI_EXIT" not in dominant[5]
    assert mixed[0] == "S3"
    assert "ROLL_WITH_NET_EXIT" in mixed[5]
    assert "移仓承接明显但全链仍净退出" in mixed[4]

    exit_with_option_confirmation = _classify(
        SimpleNamespace(
            **{
                **common,
                "roll_context": "EXIT_DOMINANT",
                "confirmation_strength": "medium",
            }
        )
    )
    assert exit_with_option_confirmation[0] == "S3"
    assert "CHAIN_OI_EXIT" in exit_with_option_confirmation[5]

    daily_roll_but_window_exit = _classify(
        SimpleNamespace(
            **{
                **common,
                "participation_state": "ROLL_TRANSFER",
                "roll_context": "EXIT_DOMINANT",
                "confirmation_strength": "medium",
            }
        )
    )
    assert daily_roll_but_window_exit[0] == "S3"
    assert "CHAIN_OI_EXIT" in daily_roll_but_window_exit[5]
    assert "全链资金退出" in daily_roll_but_window_exit[4]


def test_r74_excludes_last_trade_day_oi_reset_from_adjusted_flow(
    tmp_path: Path,
) -> None:
    core_path = tmp_path / "expiry_core.parquet"
    dates = pd.bdate_range("2026-07-01", periods=10)
    rows: list[dict[str, object]] = []
    for index, timestamp in enumerate(dates):
        rows.extend(
            [
                {
                    "trade_date": timestamp.date(),
                    "contract_code": "CF609",
                    "close": 16000.0,
                    "settle": 16000.0,
                    "volume": 1000,
                    "open_interest": 1000 - index * 10,
                },
                {
                    "trade_date": timestamp.date(),
                    "contract_code": "CF607",
                    "close": 15900.0,
                    "settle": 15900.0,
                    "volume": 10,
                    "open_interest": 0 if index == len(dates) - 1 else 100,
                },
            ]
        )
    pd.DataFrame(rows).to_parquet(core_path, index=False)

    result = build_cf_chain_oi_structure(
        core_quote_path=core_path,
        output_dir=tmp_path / "research" / "expiry",
        report_output_dir=tmp_path / "reports" / "expiry",
        run_id="r74_expiry",
    )

    daily = pd.read_parquet(result.daily_parquet_path)
    latest = daily.iloc[-1]
    assert latest["trade_date"] == dates[-1].date()
    assert latest["expiry_oi_change"] == -100
    assert latest["chain_oi_change"] == -110
    assert latest["chain_oi_change_adjusted"] == -10
    detail = pd.read_parquet(result.contract_detail_parquet_path)
    expiry_row = detail.loc[
        detail["trade_date"].eq(dates[-1].date())
        & detail["contract_code"].eq("CF607")
    ].iloc[0]
    assert expiry_row["is_last_trade_date"]
    assert expiry_row["contract_oi_change_adjusted"] == 0


def _write_inputs(tmp_path: Path) -> dict[str, Path]:
    core_path = tmp_path / "core.parquet"
    option_path = tmp_path / "option.parquet"
    matrix_path = tmp_path / "matrix.parquet"
    validation_path = tmp_path / "validation.parquet"
    latest_path = tmp_path / "daily" / "CF" / "2026-02-11" / "latest_signal_brief.json"
    playbook_path = tmp_path / "playbook.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    dates = pd.bdate_range("2026-01-01", periods=30)
    rows: list[dict[str, object]] = []
    for index, timestamp in enumerate(dates):
        settle = 100.0 + index * 0.25
        close = settle + 0.1
        main_oi = 1000 + index * 10
        far_oi = 500 + index * 5
        if index == len(dates) - 2:
            close = 103.0
            settle = 107.0
            main_oi -= 120
            far_oi += 20
        if index == len(dates) - 1:
            close = 108.0
            settle = 108.0
            main_oi -= 260
            far_oi -= 40
        rows.extend(
            [
                {
                    "trade_date": timestamp.date(),
                    "contract_code": "CF609",
                    "open": settle - 0.5,
                    "high": max(close, settle) + 1.0,
                    "low": min(close, settle) - 1.0,
                    "close": close,
                    "settle": settle,
                    "volume": 1000 + index,
                    "open_interest": main_oi,
                },
                {
                    "trade_date": timestamp.date(),
                    "contract_code": "CF701",
                    "open": settle + 1.0,
                    "high": settle + 2.0,
                    "low": settle,
                    "close": settle + 1.0,
                    "settle": settle + 1.0,
                    "volume": 400 + index,
                    "open_interest": far_oi,
                },
            ]
        )
    pd.DataFrame(rows).to_parquet(core_path, index=False)

    option_rows = []
    matrix_rows = []
    validation_rows = []
    for index, timestamp in enumerate(dates):
        option_rows.append(
            {
                "trade_date": timestamp.date(),
                "underlying_contract": "CF609",
                "atm_iv_proxy": 0.03,
                "atm_iv_rank": 0.05,
                "pcr_volume": 0.78 if index == len(dates) - 1 else 0.85,
                "pcr_oi": 0.82,
                "skew_proxy": 0.0,
                "factor_status": "READY",
                "eligible_option_count": 20,
                "option_liquidity_score": 75.0,
            }
        )
        matrix_rows.append(
            {
                "trade_date": timestamp.date(),
                "horizon": 20,
                "main_contract": "CF609",
                "direction": "long",
                "momentum_signal": "long",
                "trend_phase": "S1",
            }
        )
        validation_rows.append(
            {
                "trade_date": timestamp.date(),
                "horizon": 20,
                "main_contract": "CF609",
                "forward_return": 0.01 if index % 2 == 0 else -0.005,
                "forward_label_available": index < len(dates) - 3,
                "directional_hit": 1 if index % 2 == 0 else 0,
            }
        )
    pd.DataFrame(option_rows).to_parquet(option_path, index=False)
    pd.DataFrame(matrix_rows).to_parquet(matrix_path, index=False)
    pd.DataFrame(validation_rows).to_parquet(validation_path, index=False)
    latest_path.write_text(
        json.dumps(
            {
                "data_asof": dates[-1].date().isoformat(),
                "main_contract": "CF609",
                "signal_direction": "long",
                "summary": {"data_status": {"data_asof": dates[-1].date().isoformat()}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    playbook_path.write_text(
        json.dumps(
            {
                "report_type": "futures_option_divergence_playbook",
                "current_mapping_rows": [
                    {
                        "data_asof": dates[-1].date().isoformat(),
                        "horizon": 20,
                        "matched_node_id": "R71_NODE_TEST",
                        "matched_playbook_label_cn": "同向确认观察",
                        "matched_sample_count": 50,
                        "matched_average_resolution_horizon": 8.0,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {
        "core": core_path,
        "option": option_path,
        "matrix": matrix_path,
        "validation": validation_path,
        "latest": latest_path,
        "playbook": playbook_path,
    }
