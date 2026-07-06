from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import build_cf_product_research_registry


def test_build_cf_product_research_registry_writes_snapshot(tmp_path: Path) -> None:
    result = build_cf_product_research_registry(
        output_dir=tmp_path / "registry",
        report_output_dir=tmp_path / "reports",
        run_id="r50_unit",
    )

    assert result.status == "COMPLETED"
    assert result.futures_factor_count == 4
    assert result.option_proxy_factor_count == 6
    assert result.json_path.exists()
    assert result.markdown_path.exists()
    assert result.manifest_path.exists()
    assert result.factor_csv_path.exists()
    assert "tick_size" in result.human_review_required
    assert "option_signal_filter_rules_before_trading_use" in result.human_review_required

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "cf_product_research_registry"
    assert payload["product"]["product_code"] == "CF"
    assert payload["product"]["signal_object_id"] == "CF.C1"
    assert payload["product"]["delivery_months"] == [1, 3, 5, 7, 9, 11]
    assert payload["registry_boundary"]["cf_first_only"] is True
    assert payload["registry_boundary"]["option_proxy_not_strategy"] is True
    assert {row["factor_id"] for row in payload["futures_factor_registry"]} == {
        "mom_20_v1",
        "carry_nf_v1",
        "curve_slope_v1",
        "oi_pressure_v1",
    }
    assert {row["factor_id"] for row in payload["option_proxy_registry"]} == {
        "option_atm_iv_proxy_v1",
        "option_iv_rank_proxy_v1",
        "option_pcr_volume_v1",
        "option_pcr_oi_v1",
        "option_skew_proxy_v1",
        "option_liquidity_score_v1",
    }

    csv_rows = pd.read_csv(result.factor_csv_path)
    assert len(csv_rows) == 10
    assert not csv_rows["required_inputs"].astype(str).str.contains("raw_").any()

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "CF 产品配置与因子注册快照 R50" in markdown
    assert "R50 只固化 CF，不启动多品种扩展" in markdown


def test_cli_build_cf_product_research_registry(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-product-research-registry",
            "--output-dir",
            str(tmp_path / "registry"),
            "--report-output-dir",
            str(tmp_path / "reports"),
            "--run-id",
            "r50_cli",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["status"] == "COMPLETED"
    assert output["futures_factor_count"] == 4
    assert output["option_proxy_factor_count"] == 6
    assert Path(output["json_path"]).exists()
