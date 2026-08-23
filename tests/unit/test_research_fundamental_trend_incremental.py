from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench.fundamental_trend_incremental import (
    build_cf_fundamental_trend_incremental_research,
)


def test_r93k_separates_exact_and_proxy_knowledge_dates(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    result = build_cf_fundamental_trend_incremental_research(
        breakout_event_path=paths["events"],
        core_quote_path=paths["core"],
        fundamental_dir=paths["fundamentals"],
        ifind_cotton_context_path=paths["ifind"],
        output_dir=tmp_path / "data",
        report_output_dir=tmp_path / "reports",
        run_id="r93k_unit",
        horizons=(5, 20),
        change_periods=1,
        min_sample_size=1,
        proxy_lags=(0, 2),
    )

    assert result.status.startswith("FUNDAMENTAL_TREND_INCREMENTAL_READY")
    assert result.event_row_count == 6
    assert result.independent_episode_count == 3
    assert result.exact_event_feature_count > 0
    assert result.proxy_event_feature_count > 0
    assert result.feature_row_count == (
        result.exact_event_feature_count + result.proxy_event_feature_count
    )
    assert any(
        item.warning_code == "R93K_CANONICAL_SERIES_STITCHED"
        for item in result.warning_records
    )
    for path in (
        result.knowledge_calendar_path,
        result.event_feature_path,
        result.summary_path,
        result.sensitivity_path,
        result.warning_csv_path,
        result.json_path,
        result.markdown_path,
        result.manifest_path,
    ):
        assert path.exists()
        assert path.stat().st_size > 0

    calendar = pd.read_parquet(result.knowledge_calendar_path)
    features = pd.read_parquet(result.event_feature_path)
    summary = pd.read_parquet(result.summary_path)
    assert set(calendar["knowledge_quality"]) == {
        "RELEASE_DATE_EXACT",
        "OBSERVATION_DATE_PROXY",
    }
    assert features.groupby(
        ["direction_episode_id", "horizon", "knowledge_quality", "proxy_lag_sessions"]
    )["event_id"].nunique().eq(1).all()
    assert not features.duplicated(
        [
            "event_id",
            "horizon",
            "knowledge_quality",
            "proxy_lag_sessions",
            "feature_name",
            "dataset_type",
            "indicator_name",
        ]
    ).any()
    assert (
        pd.to_datetime(features["knowledge_date"]).dt.date <= features["event_date"]
    ).all()
    assert features["event_features_use_known_date_or_earlier"].all()

    late_release = calendar.loc[
        calendar["indicator_id"].eq("S002885871")
        & pd.to_datetime(calendar["source_release_time"]).eq(
            pd.Timestamp("2026-01-08 16:00:00")
        )
    ].iloc[0]
    assert pd.Timestamp(late_release["knowledge_date"]).date() == date(2026, 1, 9)

    event_before_release = features.loc[
        pd.to_datetime(features["event_date"]).eq(pd.Timestamp("2026-01-08"))
        & features["indicator_id"].eq("S002885871")
        & features["feature_name"].eq("indicator_alignment")
    ].iloc[0]
    assert pd.Timestamp(event_before_release["observation_date"]).date() == date(
        2026, 1, 2
    )
    stitched_inventory = features.loc[
        pd.to_datetime(features["event_date"]).eq(pd.Timestamp("2026-01-12"))
        & features["indicator_name"].eq("纺企棉纱库存")
        & features["horizon"].eq(5)
        & features["proxy_lag_sessions"].eq(0)
    ].iloc[0]
    assert stitched_inventory["indicator_id"] == "TTEB_纱线综合库存"

    proxy_summary = summary.loc[
        summary["knowledge_quality"].eq("OBSERVATION_DATE_PROXY")
    ]
    assert not proxy_summary["promotion_eligible"].any()
    assert proxy_summary["incremental_status"].str.startswith("PROXY_").all()
    assert set(features["trading_instruction"]) == {"not_a_trading_instruction"}

    report = result.markdown_path.read_text(encoding="utf-8")
    assert "代理证据无论统计结果如何" in report
    assert "规范指标改名" in report
    assert "代理滞后(交易日)" in report
    assert "| 不适用 |" in report
    assert "| 2 |" in report
    assert "knowledge_date <= event_date" in report
    assert "不进入signal matrix或composite_score" in report
    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["historical_returns_are_posterior_labels"] is True
    assert payload["fundamental_signal_status"] == "not_connected"
    assert payload["summary"]["exact_event_feature_count"] > 0


def test_r93k_cli_writes_bundle_and_parses_zero_proxy_lag(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-fundamental-trend-incremental-research",
            "--breakout-event-path",
            str(paths["events"]),
            "--core-quote-path",
            str(paths["core"]),
            "--fundamental-dir",
            str(paths["fundamentals"]),
            "--ifind-cotton-context-path",
            str(paths["ifind"]),
            "--horizons",
            "5,20",
            "--change-periods",
            "1",
            "--min-sample-size",
            "1",
            "--proxy-lags",
            "0,2",
            "--output-dir",
            str(tmp_path / "cli_data"),
            "--report-output-dir",
            str(tmp_path / "cli_reports"),
            "--run-id",
            "r93k_cli",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["run_id"] == "r93k_cli"
    assert payload["event_row_count"] == 6
    assert payload["fundamental_signal_status"] == "not_connected"
    assert Path(payload["manifest_path"]).exists()


def test_r93k_rejects_conflicting_duplicate_observations(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    textile_path = paths["fundamentals"] / "CF_fundamental_textile_chain_daily.parquet"
    textile = pd.read_parquet(textile_path)
    conflict = textile.iloc[[0]].copy()
    conflict["indicator_value"] = conflict["indicator_value"] + 1.0
    pd.concat([textile, conflict], ignore_index=True).to_parquet(
        textile_path, index=False
    )

    with pytest.raises(ResearchWorkbenchError, match="同日存在冲突值"):
        build_cf_fundamental_trend_incremental_research(
            breakout_event_path=paths["events"],
            core_quote_path=paths["core"],
            fundamental_dir=paths["fundamentals"],
            ifind_cotton_context_path=paths["ifind"],
            output_dir=tmp_path / "data",
            report_output_dir=tmp_path / "reports",
            change_periods=1,
            min_sample_size=1,
        )


def _write_fixture(tmp_path: Path) -> dict[str, Path]:
    sessions = pd.to_datetime(
        [
            "2026-01-02",
            "2026-01-05",
            "2026-01-06",
            "2026-01-07",
            "2026-01-08",
            "2026-01-09",
            "2026-01-12",
            "2026-01-13",
            "2026-01-14",
            "2026-01-15",
            "2026-01-16",
            "2026-01-19",
            "2026-01-20",
        ]
    )
    core_path = tmp_path / "core.parquet"
    pd.DataFrame(
        {
            "trade_date": sessions,
            "contract_code": "CF605",
        }
    ).to_parquet(core_path, index=False)

    event_rows: list[dict[str, object]] = []
    for number, (event_date, direction) in enumerate(
        (("2026-01-08", "long"), ("2026-01-09", "short"), ("2026-01-12", "long")),
        start=1,
    ):
        for horizon in (5, 20):
            for suffix, day_offset in (("FIRST", 0), ("SECOND", 1)):
                event_rows.append(
                    {
                        "event_id": f"EP{number}_{horizon}_{suffix}",
                        "event_date": pd.Timestamp(event_date)
                        + pd.Timedelta(days=day_offset),
                        "direction": direction,
                        "direction_episode_id": f"EP{number}",
                        "horizon": horizon,
                        "directional_return": 0.02 if number != 2 else -0.01,
                        "label_available": True,
                        "outcome": (
                            "FOLLOW_THROUGH" if number != 2 else "FAILED_BREAKOUT"
                        ),
                        "historical_posterior_label": True,
                    }
                )
    event_path = tmp_path / "events.parquet"
    pd.DataFrame(event_rows).to_parquet(event_path, index=False)

    fundamental_dir = tmp_path / "fundamentals"
    fundamental_dir.mkdir()
    observation_dates = ["2026-01-02", "2026-01-07", "2026-01-09"]
    _write_basic_table(
        fundamental_dir / "CF_fundamental_spot_price_daily.parquet",
        observation_dates,
        "indicator_value",
        "中国棉花价格指数:3128B",
        [100.0, 102.0, 101.0],
    )
    pd.DataFrame(
        {
            "trade_date": observation_dates,
            "basis_indicator_name": "基差",
            "basis": [10.0, 12.0, 11.0],
            "indicator_id": "BASIS",
            "source_name": "fixture",
        }
    ).to_parquet(fundamental_dir / "CF_fundamental_basis_daily.parquet", index=False)
    _write_basic_table(
        fundamental_dir / "CF_fundamental_warehouse_receipt_daily.parquet",
        observation_dates,
        "warehouse_receipt",
        "仓单数量:一号棉",
        [1000.0, 1100.0, 1050.0],
    )
    inventory = pd.concat(
        [
            _basic_frame(
                observation_dates,
                "inventory_value",
                name,
                values,
            )
            for name, values in (
                ("中国:商业库存量:棉花", [300.0, 310.0, 305.0]),
                ("中国:工业库存量:棉花", [80.0, 82.0, 83.0]),
            )
        ],
        ignore_index=True,
    )
    inventory.to_parquet(
        fundamental_dir / "CF_fundamental_inventory_daily.parquet", index=False
    )
    _write_basic_table(
        fundamental_dir / "CF_fundamental_import_daily.parquet",
        observation_dates,
        "import_value",
        "棉花:进口数量:当月值",
        [10.0, 12.0, 11.0],
    )
    textile_rows: list[dict[str, object]] = []
    for name, values in (
        ("纯棉纱厂负荷", [50.0, 52.0, 51.0]),
        ("全棉坯布负荷", [45.0, 47.0, 48.0]),
        ("纺企棉纱库存", [20.0, 21.0, 19.0]),
        ("全棉坯布库存", [30.0, 31.0, 29.0]),
    ):
        for observation_date, value in zip(observation_dates, values, strict=True):
            indicator_id = f"TTEB_{name}"
            if name == "纺企棉纱库存" and observation_date == observation_dates[-1]:
                # 模拟来源口径改名后的新ID，规范指标仍只能作为一条连续序列计票。
                indicator_id = "TTEB_纱线综合库存"
            textile_rows.append(
                {
                    "trade_date": observation_date,
                    "indicator_name": name,
                    "metric_name": "周均",
                    "indicator_value": value,
                    "indicator_id": indicator_id,
                    "source_name": "TTEB",
                }
            )
    pd.DataFrame(textile_rows).to_parquet(
        fundamental_dir / "CF_fundamental_textile_chain_daily.parquet", index=False
    )

    ifind_path = tmp_path / "ifind.parquet"
    pd.DataFrame(
        [
            {
                "trade_date": "2026-01-01",
                "dataset_type": "spot",
                "indicator_id": "S002885871",
                "indicator_name": "现货价:棉花(3128B级)",
                "indicator_value": 100.0,
                "rtime": "2026-01-02 09:00:00",
                "source_name": "iFinD EDB",
            },
            {
                "trade_date": "2026-01-02",
                "dataset_type": "spot",
                "indicator_id": "S002885871",
                "indicator_name": "现货价:棉花(3128B级)",
                "indicator_value": 101.0,
                "rtime": "2026-01-02 10:00:00",
                "source_name": "iFinD EDB",
            },
            {
                "trade_date": "2026-01-07",
                "dataset_type": "spot",
                "indicator_id": "S002885871",
                "indicator_name": "现货价:棉花(3128B级)",
                "indicator_value": 103.0,
                "rtime": "2026-01-08 16:00:00",
                "source_name": "iFinD EDB",
            },
            {
                "trade_date": "2026-01-09",
                "dataset_type": "spot",
                "indicator_id": "S002885871",
                "indicator_name": "现货价:棉花(3128B级)",
                "indicator_value": 102.0,
                "rtime": "2026-01-12 09:00:00",
                "source_name": "iFinD EDB",
            },
            {
                "trade_date": "2026-01-07",
                "dataset_type": "policy",
                "indicator_id": "POLICY_FIXTURE",
                "indicator_name": "储备棉抛储:计划投放量",
                "indicator_value": 1000.0,
                "rtime": "2026-01-08 09:00:00",
                "source_name": "iFinD EDB",
            },
        ]
    ).to_parquet(ifind_path, index=False)
    return {
        "core": core_path,
        "events": event_path,
        "fundamentals": fundamental_dir,
        "ifind": ifind_path,
    }


def _write_basic_table(
    path: Path,
    observation_dates: list[str],
    value_column: str,
    indicator_name: str,
    values: list[float],
) -> None:
    _basic_frame(
        observation_dates,
        value_column,
        indicator_name,
        values,
    ).to_parquet(path, index=False)


def _basic_frame(
    observation_dates: list[str],
    value_column: str,
    indicator_name: str,
    values: list[float],
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": observation_dates,
            "indicator_name": indicator_name,
            value_column: values,
            "indicator_id": f"FIXTURE_{indicator_name}",
            "source_name": "fixture",
        }
    )
