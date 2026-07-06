from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from cotton_factor.core.schemas import ResearchFactorDiagnosticDailyRow
from cotton_factor.research_workbench import build_cf_multifactor_diagnostics


def test_build_cf_multifactor_diagnostics_writes_equal_weight_scores(
    tmp_path: Path,
) -> None:
    diagnostic_path = _write_diagnostics(
        tmp_path,
        [
            _diagnostic("mom_20_v1", date(2024, 1, 1), raw_value=0.4, state="long"),
            _diagnostic("carry_nf_v1", date(2024, 1, 1), raw_value=0.2, state="long"),
            _diagnostic("mom_20_v1", date(2024, 1, 2), raw_value=0.6, state="long"),
            _diagnostic("carry_nf_v1", date(2024, 1, 2), raw_value=None, state="unknown"),
        ],
    )

    result = build_cf_multifactor_diagnostics(
        start=date(2024, 1, 1),
        end=date(2024, 1, 2),
        factor_ids=("mom_20_v1", "carry_nf_v1"),
        diagnostic_path=diagnostic_path,
        output_dir=tmp_path / "multifactor",
        report_output_dir=tmp_path / "reports",
        run_id="r17_multifactor_test",
    )

    assert len(result.rows) == 1
    assert result.rows[0].trade_date == date(2024, 1, 1)
    assert result.rows[0].raw_score == pytest.approx(0.3)
    assert result.rows[0].factor_count == 2
    assert result.factor_weights == {"mom_20_v1": 0.5, "carry_nf_v1": 0.5}
    assert result.score_parquet_path.exists()
    assert result.score_csv_path.exists()
    assert result.warning_csv_path.exists()
    assert result.markdown_path.exists()

    warning_codes = pd.read_csv(result.warning_csv_path)["warning_code"].to_list()
    assert "MULTIFACTOR_UNKNOWN_DIAGNOSTICS_SKIPPED" in warning_codes
    assert "MULTIFACTOR_MISSING_REQUIRED_FACTORS" in warning_codes
    written = pd.read_parquet(result.score_parquet_path)
    assert written["raw_score"].to_list() == pytest.approx([0.3])


def test_build_cf_multifactor_diagnostics_can_allow_missing_factors(
    tmp_path: Path,
) -> None:
    diagnostic_path = _write_diagnostics(
        tmp_path,
        [
            _diagnostic("mom_20_v1", date(2024, 1, 1), raw_value=0.4, state="long"),
        ],
    )

    result = build_cf_multifactor_diagnostics(
        start=date(2024, 1, 1),
        end=date(2024, 1, 1),
        factor_ids=("mom_20_v1", "carry_nf_v1"),
        diagnostic_path=diagnostic_path,
        output_dir=tmp_path / "multifactor",
        report_output_dir=tmp_path / "reports",
        run_id="r17_allow_missing_test",
        require_all_factors=False,
    )

    assert len(result.rows) == 1
    assert result.rows[0].factor_count == 1
    assert result.rows[0].raw_score == pytest.approx(0.4)
    assert pd.read_csv(result.warning_csv_path).empty


def _write_diagnostics(tmp_path: Path, rows: list[ResearchFactorDiagnosticDailyRow]) -> Path:
    path = tmp_path / "factors" / "CF_2024-01-01_2024-01-02_factor_diagnostic_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _diagnostic(
    factor_id: str,
    trade_date: date,
    *,
    raw_value: float | None,
    state: str,
) -> ResearchFactorDiagnosticDailyRow:
    return ResearchFactorDiagnosticDailyRow(
        run_id="r14_diag_test",
        factor_id=factor_id,
        factor_version="v1",
        product_code="CF",
        universe="CF_MAIN",
        signal_object_id="CF.C1",
        trade_date=trade_date,
        raw_value=raw_value,
        processed_value=None,
        signal_state=state,
        diagnostic_reason=f"fixture {state}",
        warning_flags=["unknown"] if state == "unknown" else [],
        human_review_required=["factor_thresholds"],
        diagnostic_rule_version="r14_sign_state_heuristic_v1",
        input_snapshot_ids=[f"{factor_id}_{trade_date:%Y%m%d}"],
    )
