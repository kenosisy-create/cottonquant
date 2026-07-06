from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.core.schemas import ResearchFactorValueDailyRow
from cotton_factor.research_workbench import build_cf_factor_diagnostics
from cotton_factor.research_workbench.factor_artifacts import WARNING_COLUMNS


def test_build_cf_factor_diagnostics_writes_states_and_missing_unknown(
    tmp_path: Path,
) -> None:
    factor_path = _write_factor_rows(
        tmp_path,
        [
            _factor_row("mom_20_v1", date(2024, 1, 9), 0.02, "mom_snap"),
            _factor_row("carry_nf_v1", date(2024, 1, 9), -0.01, "carry_snap"),
            _factor_row("curve_slope_v1", date(2024, 1, 9), 0.0, "curve_snap"),
        ],
    )
    warning_path = _write_warning_rows(
        tmp_path,
        [
            {
                "run_id": "r12_carry_test",
                "factor_id": "carry_nf_v1",
                "trade_date": "",
                "severity": "WARN",
                "warning_code": "CARRY_HUMAN_REVIEW_REQUIRED",
                "warning_message": "carry rule needs review",
                "human_review_required": "carry_tenor_rule",
                "input_snapshot_ids": "carry_snap",
            }
        ],
    )

    result = build_cf_factor_diagnostics(
        start=date(2024, 1, 9),
        end=date(2024, 1, 9),
        factor_value_path=factor_path,
        warning_csv_path=warning_path,
        output_dir=tmp_path / "diagnostics",
        report_output_dir=tmp_path / "reports",
        run_id="r14_diagnostics_test",
    )

    assert len(result.rows) == 4
    state_by_factor = {row.factor_id: row.signal_state for row in result.rows}
    assert state_by_factor == {
        "mom_20_v1": "long",
        "carry_nf_v1": "short",
        "curve_slope_v1": "neutral",
        "oi_pressure_v1": "unknown",
    }
    carry_row = next(row for row in result.rows if row.factor_id == "carry_nf_v1")
    assert "factor_thresholds" in carry_row.human_review_required
    assert "carry_tenor_rule" in carry_row.human_review_required
    assert "CARRY_HUMAN_REVIEW_REQUIRED" in carry_row.warning_flags

    assert result.state_counts["unknown"] == 1
    assert result.missing_factor_count == 1
    assert result.diagnostic_parquet_path.exists()
    assert result.diagnostic_csv_path.exists()
    assert result.markdown_path.exists()

    written = pd.read_parquet(result.diagnostic_parquet_path)
    assert set(written["signal_state"]) == {"long", "short", "neutral", "unknown"}
    warning_codes = pd.read_csv(result.warning_csv_path)["warning_code"].to_list()
    assert "R14_MISSING_FACTOR_VALUE" in warning_codes


def test_build_cf_factor_diagnostics_requires_factor_values(tmp_path: Path) -> None:
    factor_path = tmp_path / "missing.parquet"

    with pytest.raises(ResearchWorkbenchError, match="factor value parquet not found"):
        build_cf_factor_diagnostics(
            start=date(2024, 1, 9),
            end=date(2024, 1, 9),
            factor_value_path=factor_path,
            output_dir=tmp_path / "diagnostics",
            report_output_dir=tmp_path / "reports",
        )


def _write_factor_rows(tmp_path: Path, rows: list[ResearchFactorValueDailyRow]) -> Path:
    path = tmp_path / "factors" / "CF_2024-01-09_2024-01-09_factor_value_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _write_warning_rows(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    path = tmp_path / "factors" / "CF_2024-01-09_2024-01-09_factor_warnings.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _factor_row(
    factor_id: str,
    trade_date: date,
    raw_value: float,
    snapshot_id: str,
) -> ResearchFactorValueDailyRow:
    return ResearchFactorValueDailyRow(
        run_id=f"{factor_id}_run",
        factor_id=factor_id,
        factor_version="v1",
        product_code="CF",
        universe="CF_MAIN",
        signal_object_id="CF.C1",
        trade_date=trade_date,
        raw_value=raw_value,
        processed_value=None,
        input_snapshot_ids=[snapshot_id],
    )
