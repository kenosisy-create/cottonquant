from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench.futures_option_evidence_gate import (
    build_cf_futures_option_evidence_gate,
)


def test_evidence_gate_keeps_only_fully_validated_fixed_candidate(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(tmp_path)
    result = _build(paths, tmp_path, run_id="r93r_unit")

    assert result.expansion_decision == "KEEP_FIXED_CANDIDATE_VALIDATION"
    assert result.stop_option_factor_expansion is False
    assert result.promotable_candidate_count == 1
    assert result.reference_keep_count == 1
    assert result.predictive_keep_count == 1
    assert result.r94_unlocked is False
    assert result.markdown_path.exists()
    assert result.manifest_path.exists()

    evidence = pd.read_parquet(result.evidence_parquet_path)
    candidate = evidence.loc[
        evidence["source_module"].eq("R93O")
        & evidence["evidence_id"].eq("KEEP_GO")
    ].iloc[0]
    assert candidate["decision"] == "KEEP"
    assert bool(candidate["predictive_promotion_eligible"])

    no_fdr = evidence.loc[evidence["evidence_id"].eq("WATCH_NO_FDR")].iloc[0]
    assert no_fdr["decision"] == "WATCH"
    cost_fail = evidence.loc[evidence["evidence_id"].eq("REJECT_COST")].iloc[0]
    assert cost_fail["decision"] == "REJECT"
    assert set(evidence["decision"]) <= {"KEEP", "WATCH", "REJECT"}
    assert not evidence["enters_signal_matrix"].any()
    assert not evidence["enters_composite_score"].any()

    costs = pd.read_parquet(result.cost_sensitivity_parquet_path)
    keep_cost = costs.loc[
        costs["source_module"].eq("R93O")
        & costs["evidence_id"].eq("KEEP_GO")
        & costs["cost_bps_per_side"].eq(10)
    ].iloc[0]
    assert keep_cost["gross_mean_directional_return"] == pytest.approx(0.006)
    assert keep_cost["net_mean_directional_return"] == pytest.approx(0.004)

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "forward return仅作为历史后验验证标签" in markdown
    assert "解释性框架的KEEP不等于预测候选KEEP" in markdown
    assert "不构成交易指令" in markdown


def test_evidence_gate_stops_expansion_when_no_candidate_passes(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(tmp_path)
    evidence = pd.read_parquet(paths["r93o_evidence"])
    evidence.loc[evidence["candidate_id"].eq("KEEP_GO"), "fdr_q_value"] = 0.5
    evidence.loc[evidence["candidate_id"].eq("KEEP_GO"), "decision"] = "WATCH"
    evidence.to_parquet(paths["r93o_evidence"], index=False)

    result = _build(paths, tmp_path, run_id="r93r_stop")

    assert result.expansion_decision == "REJECT_STOP_OPTION_FACTOR_EXPANSION"
    assert result.stop_option_factor_expansion is True
    assert result.promotable_candidate_count == 0
    assert result.warning_count == 1
    modules = pd.read_parquet(result.module_summary_parquet_path)
    r93o = modules.loc[modules["source_module"].eq("R93O")].iloc[0]
    assert r93o["retention_decision"] == "REJECT"
    assert bool(r93o["stop_new_factor_expansion"])


def test_evidence_gate_rejects_non_t_plus_one_input(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    labels = pd.read_parquet(paths["r93n_label"])
    labels.loc[0, "execution_date"] = labels.loc[0, "trade_date"]
    labels.to_parquet(paths["r93n_label"], index=False)

    with pytest.raises(ResearchWorkbenchError, match=r"T\+1执行"):
        _build(paths, tmp_path, run_id="r93r_invalid")


def test_evidence_gate_cli_writes_bundle(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    invocation = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-futures-option-evidence-gate",
            "--r93n-label-path",
            str(paths["r93n_label"]),
            "--r93o-evidence-path",
            str(paths["r93o_evidence"]),
            "--r93o-posterior-path",
            str(paths["r93o_posterior"]),
            "--r93p-summary-path",
            str(paths["r93p_summary"]),
            "--r93p-resolution-path",
            str(paths["r93p_resolution"]),
            "--r93p-oos-path",
            str(paths["r93p_oos"]),
            "--r93q-main-effect-path",
            str(paths["r93q_main"]),
            "--r93q-primary-path",
            str(paths["r93q_primary"]),
            "--horizons",
            "1",
            "--cost-bps-per-side",
            "0,5,10",
            "--min-sample-size",
            "2",
            "--output-dir",
            str(tmp_path / "data" / "cli"),
            "--report-output-dir",
            str(tmp_path / "reports" / "cli"),
            "--run-id",
            "r93r_cli",
        ],
    )

    assert invocation.exit_code == 0, invocation.output
    payload = json.loads(invocation.stdout)
    assert payload["run_id"] == "r93r_cli"
    assert payload["promotable_candidate_count"] == 1
    assert payload["reference_keep_count"] == 1
    assert payload["predictive_keep_count"] == 1
    assert payload["enters_composite_score"] is False
    assert Path(payload["markdown_path"]).exists()


def _build(
    paths: dict[str, Path], tmp_path: Path, *, run_id: str
):
    return build_cf_futures_option_evidence_gate(
        r93n_label_path=paths["r93n_label"],
        r93o_evidence_path=paths["r93o_evidence"],
        r93o_posterior_path=paths["r93o_posterior"],
        r93p_summary_path=paths["r93p_summary"],
        r93p_resolution_path=paths["r93p_resolution"],
        r93p_oos_path=paths["r93p_oos"],
        r93q_main_effect_path=paths["r93q_main"],
        r93q_primary_path=paths["r93q_primary"],
        horizons=(1,),
        cost_bps_per_side=(0, 5, 10),
        min_sample_size=2,
        output_dir=tmp_path / "data" / run_id,
        report_output_dir=tmp_path / "reports" / run_id,
        run_id=run_id,
    )


def _write_fixture(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "r93n_label": tmp_path / "r93n_label.parquet",
        "r93o_evidence": tmp_path / "r93o_evidence.parquet",
        "r93o_posterior": tmp_path / "r93o_posterior.parquet",
        "r93p_summary": tmp_path / "r93p_summary.parquet",
        "r93p_resolution": tmp_path / "r93p_resolution.parquet",
        "r93p_oos": tmp_path / "r93p_oos.parquet",
        "r93q_main": tmp_path / "r93q_main.parquet",
        "r93q_primary": tmp_path / "r93q_primary.parquet",
    }
    dates = [
        date(2024, 1, 2),
        date(2024, 1, 3),
        date(2025, 1, 2),
        date(2025, 1, 3),
        date(2026, 1, 2),
        date(2026, 1, 5),
    ]
    labels = [_label_row(value, index) for index, value in enumerate(dates)]
    pd.DataFrame(labels).to_parquet(paths["r93n_label"], index=False)

    candidates = (
        ("KEEP_GO", "KEEP", 0.05, 0.006, 0.002),
        ("WATCH_NO_FDR", "WATCH", 0.50, 0.005, 0.001),
        ("REJECT_COST", "KEEP", 0.05, 0.001, 0.0005),
    )
    evidence_rows = [
        _candidate_evidence_row(*candidate, sample_count=len(dates))
        for candidate in candidates
    ]
    pd.DataFrame(evidence_rows).to_parquet(paths["r93o_evidence"], index=False)
    posterior_rows = []
    for candidate_id, _, _, mean_return, _ in candidates:
        posterior_rows.extend(
            _candidate_posterior_row(
                trade_date=value,
                index=index,
                candidate_id=candidate_id,
                directional_return=mean_return,
            )
            for index, value in enumerate(dates)
        )
    pd.DataFrame(posterior_rows).to_parquet(paths["r93o_posterior"], index=False)

    pd.DataFrame([_r93p_summary_row()]).to_parquet(
        paths["r93p_summary"], index=False
    )
    pd.DataFrame([_r93p_resolution_row()]).to_parquet(
        paths["r93p_resolution"], index=False
    )
    pd.DataFrame([_r93p_oos_row(2024), _r93p_oos_row(2025)]).to_parquet(
        paths["r93p_oos"], index=False
    )
    pd.DataFrame([_r93q_main_row()]).to_parquet(paths["r93q_main"], index=False)
    pd.DataFrame([_r93q_primary_row()]).to_parquet(
        paths["r93q_primary"], index=False
    )
    return paths


def _label_row(trade_date: date, index: int) -> dict[str, object]:
    execution_date = trade_date + timedelta(days=1)
    exit_date = trade_date + timedelta(days=2)
    return {
        "observation_id": f"obs_{index}",
        "trade_date": trade_date,
        "calendar_year": trade_date.year,
        "option_market_stage": "MATURE_ACTIVE",
        "horizon": 1,
        "execution_date": execution_date,
        "exit_date": exit_date,
        "long_mfe": 0.010,
        "long_mae": -0.002,
        "short_mfe": 0.002,
        "short_mae": -0.010,
        "futures_direction": "long",
        "futures_directional_return": 0.004,
        "futures_hit": True,
        "r48_option_direction": "long",
        "r48_directional_return": 0.005,
        "r48_hit": True,
        "dynamic_option_direction": "long",
        "dynamic_directional_return": 0.006,
        "dynamic_hit": True,
        "forward_label_available": True,
        "t_plus_one_execution": True,
        "forward_returns_are_historical_posterior_labels": True,
    }


def _candidate_evidence_row(
    candidate_id: str,
    decision: str,
    fdr_q_value: float,
    mean_return: float,
    incremental_return: float,
    *,
    sample_count: int,
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "candidate_family": "FIXTURE",
        "comparison_mode": "DIRECTIONAL_PAIR",
        "option_market_stage": "MATURE_ACTIVE",
        "horizon": 1,
        "candidate_sample_count": sample_count,
        "candidate_hit_rate": 0.60,
        "candidate_mean_directional_return": mean_return,
        "candidate_median_directional_return": mean_return,
        "candidate_mean_mfe": 0.010,
        "candidate_mean_mae": -0.002,
        "primary_incremental_mean_return": incremental_return,
        "fdr_q_value": fdr_q_value,
        "oos_test_years": 2,
        "oos_positive_years": 2,
        "oos_non_partial_positive": True,
        "decision": decision,
        "decision_reason": "FIXTURE",
    }


def _candidate_posterior_row(
    *,
    trade_date: date,
    index: int,
    candidate_id: str,
    directional_return: float,
) -> dict[str, object]:
    return {
        "observation_id": f"obs_{index}",
        "trade_date": trade_date,
        "calendar_year": trade_date.year,
        "option_market_stage": "MATURE_ACTIVE",
        "candidate_id": candidate_id,
        "candidate_family": "FIXTURE",
        "horizon": 1,
        "execution_date": trade_date + timedelta(days=1),
        "exit_date": trade_date + timedelta(days=2),
        "signal_active": True,
        "candidate_directional_return": directional_return,
        "candidate_hit": True,
        "candidate_mfe": 0.010,
        "candidate_mae": -0.002,
        "forward_label_available": True,
        "t_plus_one_execution": True,
        "forward_returns_are_historical_posterior_labels": True,
    }


def _r93p_summary_row() -> dict[str, object]:
    return {
        "event_family": "CALL_OI_CHANGE",
        "event_type": "LOCAL_CALL_BUILD",
        "horizon": 1,
        "sample_count": 40,
        "directional_count": 40,
        "continuation_rate": 0.52,
        "mean_directional_return": 0.001,
        "median_directional_return": 0.0005,
        "mean_mfe": 0.010,
        "mean_mae": -0.009,
        "fdr_q_value": 0.8,
        "predictive_evidence_status": "NO_STABLE_PREDICTIVE_EVIDENCE",
        "forward_returns_are_historical_posterior_labels": True,
    }


def _r93p_resolution_row() -> dict[str, object]:
    return {
        "event_family": "CALL_OI_CHANGE",
        "event_type": "LOCAL_CALL_BUILD",
        "option_market_stage": "MATURE_ACTIVE",
        "available_path_count": 40,
        "mean_first_resolution_horizon": 1.5,
        "median_first_resolution_horizon": 1.0,
        "forward_returns_are_historical_posterior_labels": True,
    }


def _r93p_oos_row(test_year: int) -> dict[str, object]:
    return {
        "event_family": "CALL_OI_CHANGE",
        "event_type": "LOCAL_CALL_BUILD",
        "horizon": 1,
        "test_year": test_year,
        "test_year_is_partial": False,
        "test_sample_count": 20,
        "oos_status": "SUPPORT",
        "forward_returns_are_historical_posterior_labels": True,
    }


def _r93q_main_row() -> dict[str, object]:
    return {
        "event_family": "CALL_OI_CHANGE",
        "event_direction": "long",
        "horizon": 1,
        "market_stage": "MATURE_ACTIVE",
        "stage_sample_count": 50,
        "stage_hit_rate": 0.52,
        "stage_mean_directional_return": 0.001,
        "fdr_q_value": 0.7,
        "evidence_status": "NO_STABLE_STAGE_MAIN_EFFECT",
        "forward_returns_are_historical_posterior_labels": True,
    }


def _r93q_primary_row() -> dict[str, object]:
    return {
        "interaction_id": "INT_FIXTURE",
        "base_value": "CALL_OI_CHANGE",
        "event_direction": "long",
        "horizon": 1,
        "market_stage": "MATURE_ACTIVE",
        "interaction_dimension": "contract_cycle",
        "interaction_level": "JAN_CYCLE",
        "target_stage_level_sample_count": 40,
        "target_stage_control_sample_count": 40,
        "target_stage_level_hit_rate": 0.55,
        "target_stage_level_mean_directional_return": 0.002,
        "target_stage_level_median_directional_return": 0.001,
        "interaction_delta_hit_rate": 0.03,
        "interaction_delta_mean_return": 0.001,
        "fisher_fdr_q_value": 0.5,
        "permutation_fdr_q_value": 0.5,
        "annual_comparable_years": 2,
        "annual_sign_consistency_rate": 0.5,
        "oos_support_count": 1,
        "oos_contradict_count": 1,
        "evidence_status": "INCONCLUSIVE",
        "forward_returns_are_historical_posterior_labels": True,
    }
