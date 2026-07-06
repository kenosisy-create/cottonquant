from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.core.schemas import (
    CoreChainMapDailyRow,
    CoreTradeMappingDailyRow,
    ResearchFactorDiagnosticDailyRow,
    ResearchFactorEvaluationRow,
    ResearchMultifactorScoreDailyRow,
)
from cotton_factor.research_workbench import build_cf_daily_brief


def test_build_cf_daily_brief_writes_markdown_json_and_warnings(tmp_path: Path) -> None:
    paths = _write_daily_brief_inputs(tmp_path)

    result = build_cf_daily_brief(
        trade_date=date(2024, 1, 9),
        start=date(2024, 1, 9),
        end=date(2024, 1, 12),
        quality_csv_path=paths["quality"],
        chain_map_path=paths["chain"],
        trade_mapping_path=paths["trade"],
        diagnostic_path=paths["diagnostic"],
        single_factor_evaluation_path=paths["evaluation"],
        multifactor_score_path=paths["score"],
        cost_sensitivity_path=paths["cost"],
        report_output_dir=tmp_path / "briefs",
        run_id="r19_brief_test",
    )

    assert result.brief_status == "WATCH_REQUIRED"
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.warning_csv_path.exists()
    assert "daily_brief_interpretation" in result.human_review_required
    assert "oi_pressure_v1" in result.summary["watch_items"][0]

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["brief_status"] == "WATCH_REQUIRED"
    assert payload["summary"]["market_structure"]["mapped_contract"] == "CF401"
    assert payload["summary"]["multifactor_score"]["direction"] == "long"
    warning_codes = pd.read_csv(result.warning_csv_path)["warning_code"].to_list()
    assert "DAILY_BRIEF_UNKNOWN_FACTOR_STATE" in warning_codes
    assert "DAILY_BRIEF_COST_ASSUMPTION_REQUIRES_REVIEW" in warning_codes


def test_build_cf_daily_brief_requires_inputs(tmp_path: Path) -> None:
    with pytest.raises(ResearchWorkbenchError, match="required inputs are missing"):
        build_cf_daily_brief(
            trade_date=date(2024, 1, 9),
            start=date(2024, 1, 9),
            end=date(2024, 1, 12),
            report_output_dir=tmp_path / "briefs",
        )


def _write_daily_brief_inputs(tmp_path: Path) -> dict[str, Path]:
    return {
        "quality": _write_quality_csv(tmp_path),
        "chain": _write_parquet(
            tmp_path / "mapping" / "CF_2024-01-09_2024-01-12_chain_map_daily.parquet",
            [
                CoreChainMapDailyRow(
                    source_snapshot_id="chain_snap",
                    exchange="CZCE",
                    product_code="CF",
                    signal_object_id="CF.C1",
                    trade_date=date(2024, 1, 9),
                    mapped_contract="CF401",
                    chain_rank=1,
                    switch_reason="highest_open_interest",
                    roll_rule_version="roll_fixture_v1",
                )
            ],
        ),
        "trade": _write_parquet(
            tmp_path / "mapping" / "CF_2024-01-09_2024-01-12_trade_mapping_daily.parquet",
            [
                CoreTradeMappingDailyRow(
                    source_snapshot_id="trade_snap",
                    exchange="CZCE",
                    product_code="CF",
                    signal_object_id="CF.C1",
                    trade_date=date(2024, 1, 9),
                    execution_date=date(2024, 1, 10),
                    target_contract="CF401",
                    is_blocked=False,
                    execution_eligible=True,
                    mapping_rule_version="trade_mapping_fixture_v1",
                )
            ],
        ),
        "diagnostic": _write_parquet(
            tmp_path / "factors" / "CF_2024-01-09_2024-01-12_factor_diagnostic_daily.parquet",
            [
                _diagnostic("mom_20_v1", "long", 0.2, []),
                _diagnostic("carry_nf_v1", "short", -0.1, []),
                _diagnostic("curve_slope_v1", "neutral", 0.0, []),
                _diagnostic("oi_pressure_v1", "unknown", None, ["R14_MISSING_FACTOR_VALUE"]),
            ],
        ),
        "evaluation": _write_parquet(
            tmp_path / "backtests" / "CF_2024-01-09_2024-01-12_single_factor_evaluation.parquet",
            [
                ResearchFactorEvaluationRow(
                    run_id="r16_eval",
                    factor_id="mom_20_v1",
                    factor_version="v1",
                    product_code="CF",
                    universe="CF_MAIN",
                    horizon=1,
                    metric_name="directional_accuracy",
                    metric_value=1.0,
                    observation_count=3,
                    evaluation_rule_version="single_factor_eval_fixture_v1",
                    input_snapshot_ids=["eval_snap"],
                )
            ],
        ),
        "score": _write_parquet(
            tmp_path / "multifactor" / "CF_2024-01-09_2024-01-12_multifactor_score_daily.parquet",
            [
                ResearchMultifactorScoreDailyRow(
                    run_id="r17_score",
                    score_id="cf_equal_weight_v1",
                    score_version="v1",
                    product_code="CF",
                    universe="CF_MAIN",
                    signal_object_id="CF.C1",
                    trade_date=date(2024, 1, 9),
                    raw_score=0.1,
                    processed_score=None,
                    factor_count=3,
                    input_factor_ids=["mom_20_v1", "carry_nf_v1", "curve_slope_v1"],
                    score_rule_version="equal_weight_multifactor_v1",
                    input_snapshot_ids=["score_snap"],
                )
            ],
        ),
        "cost": _write_cost_summary(tmp_path),
    }


def _write_quality_csv(tmp_path: Path) -> Path:
    path = tmp_path / "quality" / "CF_2024-01-09_quality.csv"
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "severity",
                "check_id",
                "status",
                "field_name",
                "contract_code",
                "observed_value",
                "threshold",
                "message",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "severity": "CRITICAL",
                "check_id": "required_fields_not_null",
                "status": "PASS",
                "field_name": "settle",
                "contract_code": "",
                "observed_value": "",
                "threshold": "",
                "message": "settle is complete",
            }
        )
    return path


def _write_cost_summary(tmp_path: Path) -> Path:
    path = tmp_path / "cost" / "CF_2024-01-09_2024-01-12_cost_sensitivity_summary.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "run_id": "r18_cost",
                "scenario_id": "normal_cost",
                "product_code": "CF",
                "universe": "CF_MAIN",
                "signal_object_id": "CF.C1",
                "horizon": 1,
                "observation_count": 3,
                "signal_count": 2,
                "long_count": 1,
                "short_count": 1,
                "flat_count": 1,
                "round_turn_cost_bps": 5.0,
                "gross_mean_return": 0.01,
                "net_mean_return": 0.0095,
                "gross_hit_rate": 1.0,
                "net_hit_rate": 1.0,
                "average_abs_score": 0.2,
                "sensitivity_rule_version": "cost_sensitivity_round_turn_bps_v1",
                "input_snapshot_ids": "score_snap;return_snap",
            }
        ]
    ).to_parquet(path, index=False)
    return path


def _write_parquet(path: Path, rows: list[object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _diagnostic(
    factor_id: str,
    state: str,
    raw_value: float | None,
    warning_flags: list[str],
) -> ResearchFactorDiagnosticDailyRow:
    return ResearchFactorDiagnosticDailyRow(
        run_id="r14_diag",
        factor_id=factor_id,
        factor_version="v1",
        product_code="CF",
        universe="CF_MAIN",
        signal_object_id="CF.C1",
        trade_date=date(2024, 1, 9),
        raw_value=raw_value,
        processed_value=None,
        signal_state=state,  # type: ignore[arg-type]
        diagnostic_reason=f"fixture {state}",
        warning_flags=warning_flags,
        human_review_required=["factor_thresholds"],
        diagnostic_rule_version="r14_sign_state_heuristic_v1",
        input_snapshot_ids=[f"{factor_id}_snap"],
    )
