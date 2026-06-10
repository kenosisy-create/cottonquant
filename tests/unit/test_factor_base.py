from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from cotton_factor.common.exceptions import (
    FactorDependencyError,
    FactorRegistryError,
)
from cotton_factor.core.schemas import (
    CoreQuoteDailyRow,
    ResearchContinuousPriceDailyRow,
)
from cotton_factor.research import (
    FactorDefinition,
    FactorInputBundle,
    FactorObservation,
    build_factor_rows,
    load_factor_registry,
    validate_factor_dependencies,
)


def _continuous_price_row() -> ResearchContinuousPriceDailyRow:
    return ResearchContinuousPriceDailyRow(
        product_code="CF",
        signal_object_id="CF.C1",
        trade_date=date(2024, 1, 9),
        mapped_contract="CF401",
        price_field="settle",
        raw_price=15540,
        adjusted_price=15540,
        adjustment=0,
        cumulative_adjustment=0,
        is_roll=False,
        chain_switch_reason="initial_highest_open_interest",
        continuous_rule_version="continuous_back_adjust_additive_v1",
        input_snapshot_ids=["raw_quote_1"],
    )


def _quote_row() -> CoreQuoteDailyRow:
    return CoreQuoteDailyRow(
        source_snapshot_id="raw_quote_1",
        exchange="CZCE",
        product_code="CF",
        contract_code="CF401",
        trade_date=date(2024, 1, 9),
        settle=15540,
        volume=100,
        open_interest=200,
    )


def test_factor_registry_loads_all_mvp_factor_definitions() -> None:
    registry = load_factor_registry()

    assert set(registry.factors) == {
        "carry_nf_v1",
        "mom_20_v1",
        "curve_slope_v1",
        "oi_pressure_v1",
    }
    momentum = registry.get("mom_20_v1")
    assert momentum.required_inputs == ("research_continuous_price_daily",)
    assert momentum.human_review_required == ("owner",)


def test_factor_registry_rejects_unknown_input_tables(tmp_path: Path) -> None:
    registry_path = tmp_path / "factor_registry.yaml"
    registry_path.write_text(
        "\n".join(
            [
                "factors:",
                "  bad_factor_v1:",
                "    family: bad",
                "    version: v1",
                "    owner: TODO_REQUIRES_HUMAN_REVIEW",
                "    status: planned",
                "    required_inputs:",
                "      - continuous_price_daily",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(FactorRegistryError, match="unknown required input tables"):
        load_factor_registry(registry_path)


def test_factor_dependency_validation_fails_on_missing_or_wrong_inputs() -> None:
    definition = load_factor_registry().get("mom_20_v1")

    with pytest.raises(FactorDependencyError, match="missing required input tables"):
        validate_factor_dependencies(
            definition,
            FactorInputBundle(tables={"core_quote_daily": [_quote_row()]}),
        )

    with pytest.raises(FactorDependencyError, match="schema type check"):
        validate_factor_dependencies(
            definition,
            FactorInputBundle(tables={"research_continuous_price_daily": [_quote_row()]}),
        )


def test_factor_dependency_validation_accepts_declared_normalized_inputs() -> None:
    definition = load_factor_registry().get("mom_20_v1")

    validate_factor_dependencies(
        definition,
        FactorInputBundle(
            tables={"research_continuous_price_daily": [_continuous_price_row()]}
        ),
    )


def test_build_factor_rows_requires_non_empty_lineage() -> None:
    definition = FactorDefinition(
        factor_id="mom_20_v1",
        family="momentum",
        version="v1",
        owner="research",
        status="test",
        required_inputs=("research_continuous_price_daily",),
    )

    with pytest.raises(FactorDependencyError, match="row validation"):
        build_factor_rows(
            definition=definition,
            run_id="factor_run_1",
            product_code="CF",
            universe="CF_MAIN",
            observations=[
                FactorObservation(
                    signal_object_id="CF.C1",
                    trade_date=date(2024, 1, 9),
                    raw_value=0.01,
                    input_snapshot_ids=(),
                )
            ],
        )

    rows = build_factor_rows(
        definition=definition,
        run_id="factor_run_1",
        product_code="cf",
        universe="CF_MAIN",
        observations=[
            FactorObservation(
                signal_object_id="CF.C1",
                trade_date=date(2024, 1, 9),
                raw_value=0.01,
                processed_value=1.0,
                input_snapshot_ids=("raw_quote_1",),
            )
        ],
    )

    assert rows[0].product_code == "CF"
    assert rows[0].input_snapshot_ids == ["raw_quote_1"]
