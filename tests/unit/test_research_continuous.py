from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.core import load_core_quote_daily_csv
from cotton_factor.research_workbench import (
    build_cf_research_continuous,
    build_cf_research_mapping,
)

QUOTE_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "core_quote_daily_cf_chain_sample.csv"
)


def test_build_cf_research_continuous_writes_roll_diagnostics(tmp_path: Path) -> None:
    core_path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    _write_quote_parquet(core_path)
    mapping = build_cf_research_mapping(
        start=date(2024, 1, 9),
        end=date(2024, 1, 12),
        core_quote_path=core_path,
        output_dir=tmp_path / "mapping",
        report_output_dir=tmp_path / "mapping_report",
        ltd_buffer_days=2,
    )

    result = build_cf_research_continuous(
        start=date(2024, 1, 9),
        end=date(2024, 1, 12),
        core_quote_path=core_path,
        chain_map_path=mapping.chain_parquet_path,
        output_dir=tmp_path / "continuous",
        report_output_dir=tmp_path / "continuous_report",
    )

    assert len(result.rows) == 4
    assert result.roll_count == 1
    assert [row.adjusted_price for row in result.rows] == [15540, 15550, 15560, 15570]
    assert result.rows[2].roll_from_contract == "CF401"
    assert result.rows[2].roll_to_contract == "CF405"
    assert result.continuous_parquet_path.exists()
    assert result.continuous_csv_path.exists()
    assert result.roll_diagnostics_csv_path.exists()
    assert result.markdown_path.exists()
    assert "CF401" in result.roll_diagnostics_csv_path.read_text(encoding="utf-8")
    assert "signal objects only" in result.markdown_path.read_text(encoding="utf-8")


def test_build_cf_research_continuous_requires_chain_map(tmp_path: Path) -> None:
    core_path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    _write_quote_parquet(core_path)

    with pytest.raises(ResearchWorkbenchError, match="chain map parquet not found"):
        build_cf_research_continuous(
            start=date(2024, 1, 9),
            end=date(2024, 1, 12),
            core_quote_path=core_path,
            chain_map_path=tmp_path / "missing_chain.parquet",
        )


def _write_quote_parquet(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [row.model_dump(mode="json") for row in load_core_quote_daily_csv(QUOTE_FIXTURE)]
    pd.DataFrame(rows).to_parquet(path, index=False)
