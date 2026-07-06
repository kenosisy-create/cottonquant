from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.core.schemas import CoreQuoteDailyRow, CoreTradeMappingDailyRow
from cotton_factor.research_workbench import build_cf_forward_returns


def test_build_cf_forward_returns_writes_multi_horizon_labels(tmp_path: Path) -> None:
    trade_path = _write_trade_mapping_rows(
        tmp_path,
        [
            _mapping(date(2024, 1, 1), execution_date=date(2024, 1, 2)),
            _mapping(
                date(2024, 1, 2),
                execution_date=date(2024, 1, 3),
                is_blocked=True,
                target_contract=None,
            ),
        ],
    )
    quote_path = _write_quote_rows(
        tmp_path,
        [
            _quote(date(2024, 1, 2), settle=100, snapshot_id="entry_snap"),
            _quote(date(2024, 1, 3), settle=110, snapshot_id="exit_h1_snap"),
            _quote(date(2024, 1, 4), settle=121, snapshot_id="exit_h2_snap"),
        ],
    )

    result = build_cf_forward_returns(
        start=date(2024, 1, 1),
        end=date(2024, 1, 2),
        horizons=(1, 2),
        core_quote_path=quote_path,
        trade_mapping_path=trade_path,
        output_dir=tmp_path / "returns",
        report_output_dir=tmp_path / "reports",
        run_id="r15_forward_test",
    )

    assert len(result.rows) == 2
    assert result.row_count_by_horizon == {1: 1, 2: 1}
    returns = {row.horizon: row for row in result.rows}
    assert returns[1].trade_date == date(2024, 1, 1)
    assert returns[1].execution_date == date(2024, 1, 2)
    assert returns[1].exit_date == date(2024, 1, 3)
    assert returns[1].target_contract == "CF401"
    assert returns[1].forward_return == pytest.approx(0.1)
    assert returns[2].exit_date == date(2024, 1, 4)
    assert returns[2].forward_return == pytest.approx(0.21)
    assert result.forward_return_parquet_path.exists()
    assert result.forward_return_csv_path.exists()
    assert result.warning_csv_path.exists()
    assert result.markdown_path.exists()

    warning_codes = pd.read_csv(result.warning_csv_path)["warning_code"].to_list()
    assert warning_codes == [
        "FORWARD_RETURN_BLOCKED_MAPPING",
        "FORWARD_RETURN_BLOCKED_MAPPING",
    ]
    written = pd.read_parquet(result.forward_return_parquet_path)
    assert sorted(written["horizon"].to_list()) == [1, 2]


def test_build_cf_forward_returns_validates_horizons(tmp_path: Path) -> None:
    trade_path = _write_trade_mapping_rows(
        tmp_path,
        [_mapping(date(2024, 1, 1), execution_date=date(2024, 1, 2))],
    )
    quote_path = _write_quote_rows(
        tmp_path,
        [
            _quote(date(2024, 1, 2), settle=100),
            _quote(date(2024, 1, 3), settle=101),
        ],
    )

    with pytest.raises(ResearchWorkbenchError, match="positive integers"):
        build_cf_forward_returns(
            start=date(2024, 1, 1),
            end=date(2024, 1, 1),
            horizons=(0,),
            core_quote_path=quote_path,
            trade_mapping_path=trade_path,
            output_dir=tmp_path / "returns",
            report_output_dir=tmp_path / "reports",
        )


def _write_trade_mapping_rows(tmp_path: Path, rows: list[CoreTradeMappingDailyRow]) -> Path:
    path = tmp_path / "mapping" / "CF_2024-01-01_2024-01-02_trade_mapping_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _write_quote_rows(tmp_path: Path, rows: list[CoreQuoteDailyRow]) -> Path:
    path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame([row.model_dump(mode="json") for row in rows]).to_parquet(path, index=False)
    return path


def _mapping(
    trade_date: date,
    *,
    execution_date: date,
    is_blocked: bool = False,
    target_contract: str | None = "CF401",
) -> CoreTradeMappingDailyRow:
    return CoreTradeMappingDailyRow(
        source_snapshot_id=f"mapping_{trade_date:%Y%m%d}",
        exchange="CZCE",
        product_code="CF",
        signal_object_id="CF.C1",
        trade_date=trade_date,
        execution_date=execution_date,
        target_contract=target_contract,
        is_blocked=is_blocked,
        block_reason="r15_fixture_block" if is_blocked else None,
        execution_eligible=not is_blocked,
        mapping_rule_version="trade_mapping_v1",
    )


def _quote(
    trade_date: date,
    *,
    settle: float,
    snapshot_id: str | None = None,
) -> CoreQuoteDailyRow:
    return CoreQuoteDailyRow(
        source_snapshot_id=snapshot_id or f"quote_{trade_date:%Y%m%d}",
        exchange="CZCE",
        product_code="CF",
        contract_code="CF401",
        trade_date=trade_date,
        settle=settle,
        volume=100,
        open_interest=1000,
    )
