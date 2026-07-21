from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench import (
    build_cf_option_volatility_term_structure_research,
)
from cotton_factor.research_workbench.option_expiry_registry import (
    load_option_expiry_registry,
    resolve_option_expiry,
)
from cotton_factor.research_workbench.option_volatility_term_structure import (
    _black76_price,
    _implied_volatility_bisection,
)


def test_black76_implied_volatility_recovers_input() -> None:
    call_price = _black76_price(
        futures_price=16000.0,
        strike=16000.0,
        time_to_expiry=0.25,
        risk_free_rate=0.02,
        volatility=0.25,
        option_type="C",
    )
    recovered = _implied_volatility_bisection(
        option_price=call_price,
        futures_price=16000.0,
        strike=16000.0,
        time_to_expiry=0.25,
        risk_free_rate=0.02,
        option_type="C",
    )

    assert recovered == pytest.approx(0.25, abs=1e-6)


def test_r80_builds_expiry_aware_option_volatility_outputs(tmp_path: Path) -> None:
    factor_path, core_path, expiry_path = _write_inputs(tmp_path)
    result = build_cf_option_volatility_term_structure_research(
        option_factor_path=factor_path,
        core_quote_path=core_path,
        option_expiry_path=expiry_path,
        output_dir=tmp_path / "data" / "option_volatility",
        report_output_dir=tmp_path / "reports" / "option_volatility",
        run_id="r80_unit",
        risk_free_rate=0.02,
        rv_window=5,
        iv_rank_window=10,
        horizons=(2, 3),
        min_sample_size=2,
    )

    assert result.contract_row_count == 60
    assert result.curve_row_count == 30
    assert result.latest_main_contract == "CF405"
    assert result.latest_atm_iv == pytest.approx(0.20, abs=1e-5)
    assert result.latest_term_structure_state == "DEFERRED_IV_PREMIUM"
    assert result.latest_option_expiry_date == date(2024, 4, 11)
    assert result.latest_expiry_date_source == "EXPLICIT_EXPIRY_REGISTRY"
    assert result.expiry_fallback_row_count == 0
    assert result.contract_parquet_path.exists()
    assert result.curve_parquet_path.exists()
    assert result.validation_parquet_path.exists()
    assert result.validation_summary_parquet_path.exists()
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.manifest_path.exists()

    contracts = pd.read_parquet(result.contract_parquet_path)
    latest_main = contracts.loc[
        (contracts["trade_date"].astype(str) == result.end.isoformat())
        & (contracts["underlying_contract"] == "CF405")
    ].iloc[0]
    assert latest_main["atm_iv_approx"] == pytest.approx(0.20, abs=1e-5)
    assert "AMERICAN_OPTION_BLACK76_APPROX" in latest_main["risk_flags"]
    assert "OPTION_EXPIRY_REGISTRY" in latest_main["risk_flags"]
    assert latest_main["option_expiry_date"] == date(2024, 4, 11)

    validation = pd.read_parquet(result.validation_parquet_path)
    usable = validation.loc[validation["is_posterior_label_available"]]
    assert not usable.empty
    assert (pd.to_datetime(usable["execution_date"]) > pd.to_datetime(usable["trade_date"])).all()
    latest_labels = validation.loc[validation["trade_date"].astype(str) == result.end.isoformat()]
    assert not latest_labels["is_posterior_label_available"].any()

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "期权波动率与期限结构研究" in markdown
    assert "Black-76欧式近似" in markdown
    assert "到期日优先读取显式登记表" in markdown
    assert "倒数第3个交易日" in markdown
    assert "不进入 `composite_score`" in markdown
    assert "不构成交易指令" in markdown


def test_r80_cli_writes_summary(tmp_path: Path) -> None:
    factor_path, core_path, expiry_path = _write_inputs(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-option-volatility-term-structure",
            "--option-factor-path",
            str(factor_path),
            "--core-quote-path",
            str(core_path),
            "--option-expiry-path",
            str(expiry_path),
            "--output-dir",
            str(tmp_path / "data"),
            "--report-output-dir",
            str(tmp_path / "reports"),
            "--run-id",
            "r80_cli",
            "--rv-window",
            "5",
            "--iv-rank-window",
            "10",
            "--horizons",
            "2,3",
            "--min-sample-size",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "r80_cli"
    assert output["latest_main_contract"] == "CF405"
    assert output["latest_option_expiry_date"] == "2024-04-11"
    assert Path(output["markdown_path"]).exists()


def test_r81_missing_expiry_uses_visible_fallback(tmp_path: Path) -> None:
    factor_path, core_path, _ = _write_inputs(tmp_path)
    expiry_path = _write_expiry_registry(tmp_path, include_deferred=False)
    result = build_cf_option_volatility_term_structure_research(
        option_factor_path=factor_path,
        core_quote_path=core_path,
        option_expiry_path=expiry_path,
        output_dir=tmp_path / "fallback_data",
        report_output_dir=tmp_path / "fallback_report",
        run_id="r81_fallback",
        rv_window=5,
        iv_rank_window=10,
        horizons=(2,),
        min_sample_size=2,
    )

    assert result.expiry_fallback_row_count == 30
    contracts = pd.read_parquet(result.contract_parquet_path)
    deferred = contracts.loc[contracts["underlying_contract"] == "CF407"]
    assert set(deferred["expiry_date_source"]) == {"MONTH_START_PROXY_FALLBACK"}
    warnings = pd.read_csv(result.warning_csv_path)
    assert "EXPIRY_DATE_MONTH_START_FALLBACK" in set(warnings["warning_code"])


def test_r81_expired_registry_date_fails_clearly(tmp_path: Path) -> None:
    path = tmp_path / "expired_registry.csv"
    pd.DataFrame(
        [
            {
                "underlying_contract": "CF405",
                "option_expiry_date": "2024-01-01",
                "rule_code": "EXPLICIT_MANUAL_DATE",
                "source_name": "unit test",
                "source_url": "https://example.test/expiry",
                "quality_flag": "TEST_ONLY",
                "human_review_required": True,
            }
        ]
    ).to_csv(path, index=False)
    registry = load_option_expiry_registry(path)

    with pytest.raises(ResearchWorkbenchError, match="before trade_date"):
        resolve_option_expiry(
            underlying_contract="CF405",
            trade_date=date(2024, 1, 2),
            registry=registry,
        )


def test_r81_shorter_expiry_requires_higher_iv_for_same_price() -> None:
    option_price = _black76_price(
        futures_price=16000.0,
        strike=16000.0,
        time_to_expiry=60 / 365.0,
        risk_free_rate=0.02,
        volatility=0.20,
        option_type="C",
    )
    long_expiry_iv = _implied_volatility_bisection(
        option_price=option_price,
        futures_price=16000.0,
        strike=16000.0,
        time_to_expiry=60 / 365.0,
        risk_free_rate=0.02,
        option_type="C",
    )
    short_expiry_iv = _implied_volatility_bisection(
        option_price=option_price,
        futures_price=16000.0,
        strike=16000.0,
        time_to_expiry=30 / 365.0,
        risk_free_rate=0.02,
        option_type="C",
    )

    assert long_expiry_iv == pytest.approx(0.20, abs=1e-6)
    assert short_expiry_iv is not None
    assert short_expiry_iv > long_expiry_iv


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    dates = pd.bdate_range("2024-01-02", periods=30)
    expiries = {
        "CF405": date(2024, 4, 11),
        "CF407": date(2024, 6, 12),
    }
    factor_rows: list[dict[str, object]] = []
    quote_rows: list[dict[str, object]] = []
    for index, timestamp in enumerate(dates):
        trade_date = timestamp.date()
        main_price = 14000.0 + index * 8.0 + (index % 3) * 5.0
        deferred_price = 14200.0 + index * 7.0 + (index % 4) * 4.0
        quote_rows.extend(
            [
                _quote_row(trade_date, "CF405", main_price, 10000 - index * 20, 5000),
                _quote_row(trade_date, "CF407", deferred_price, 6000 + index * 10, 3000),
            ]
        )
        factor_rows.extend(
            [
                _factor_row(
                    trade_date,
                    "CF405",
                    main_price,
                    14000.0,
                    0.20,
                    expiries["CF405"],
                ),
                _factor_row(
                    trade_date,
                    "CF407",
                    deferred_price,
                    14200.0,
                    0.25,
                    expiries["CF407"],
                ),
            ]
        )
    factor_path = tmp_path / "option_factor.parquet"
    core_path = tmp_path / "core_quote.parquet"
    pd.DataFrame(factor_rows).to_parquet(factor_path, index=False)
    pd.DataFrame(quote_rows).to_parquet(core_path, index=False)
    return factor_path, core_path, _write_expiry_registry(tmp_path)


def _write_expiry_registry(
    tmp_path: Path, *, include_deferred: bool = True
) -> Path:
    rows = [
        {
            "underlying_contract": "CF405",
            "option_expiry_date": "2024-04-11",
            "rule_code": "CZCE_OPTION_PREV_MONTH_DAY15_THIRD_LAST_TRADING_DAY",
            "source_name": "CZCE unit fixture",
            "source_url": "https://www.czce.com.cn/cotton-option",
            "quality_flag": "OFFICIAL_RULE_TEST_FIXTURE",
            "human_review_required": False,
        }
    ]
    if include_deferred:
        rows.append(
            {
                "underlying_contract": "CF407",
                "option_expiry_date": "2024-06-12",
                "rule_code": "CZCE_OPTION_PREV_MONTH_DAY15_THIRD_LAST_TRADING_DAY",
                "source_name": "CZCE unit fixture",
                "source_url": "https://www.czce.com.cn/cotton-option",
                "quality_flag": "OFFICIAL_RULE_TEST_FIXTURE",
                "human_review_required": False,
            }
        )
    path = tmp_path / (
        "option_expiry_full.csv" if include_deferred else "option_expiry_partial.csv"
    )
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _factor_row(
    trade_date: date,
    contract: str,
    futures_price: float,
    strike: float,
    volatility: float,
    expiry: date,
) -> dict[str, object]:
    time_to_expiry = max((expiry - trade_date).days, 1) / 365.0
    call_price = _black76_price(
        futures_price=futures_price,
        strike=strike,
        time_to_expiry=time_to_expiry,
        risk_free_rate=0.02,
        volatility=volatility,
        option_type="C",
    )
    put_price = _black76_price(
        futures_price=futures_price,
        strike=strike,
        time_to_expiry=time_to_expiry,
        risk_free_rate=0.02,
        volatility=volatility,
        option_type="P",
    )
    return {
        "trade_date": trade_date,
        "underlying_contract": contract,
        "underlying_settle": futures_price,
        "atm_strike": strike,
        "atm_call_settle": call_price,
        "atm_put_settle": put_price,
        "atm_iv_rank": 0.5,
        "pcr_volume": 0.9,
        "pcr_oi": 1.0,
        "skew_proxy": -0.001,
        "option_liquidity_score": 0.8,
        "factor_status": "READY",
    }


def _quote_row(
    trade_date: date,
    contract: str,
    settle: float,
    open_interest: int,
    volume: int,
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "contract_code": contract,
        "settle": settle,
        "open_interest": open_interest,
        "volume": volume,
    }
