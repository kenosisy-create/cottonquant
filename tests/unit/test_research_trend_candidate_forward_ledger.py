from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench.trend_candidate_forward_ledger import (
    build_cf_trend_candidate_forward_ledger,
)


def test_forward_ledger_captures_before_outcome_and_is_idempotent(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(tmp_path, include_future_event=True)
    ledger_root = tmp_path / "ledger"
    first = _build(paths, ledger_root=ledger_root, as_of_date=date(2026, 7, 29))

    assert first.status == "FORWARD_LEDGER_APPENDED"
    assert first.capture_appended_count == 2
    assert first.outcome_appended_count == 0
    assert first.strict_forward_count == 2
    assert first.pending_outcome_count == 2
    first_ledger = pd.read_parquet(first.ledger_path).sort_values("hypothesis_id")
    capture_hashes = first_ledger["capture_event_sha256"].tolist()
    for path_value in first_ledger["capture_event_path"]:
        payload = json.loads(Path(path_value).read_text(encoding="utf-8"))
        assert payload["event_type"] == "CAPTURE"
        assert not {
            "exit_date",
            "outcome",
            "raw_return",
            "directional_return",
            "label_available",
        }.intersection(payload["event_business"])

    _resolve_outcomes(paths["breakout"])
    second = _build(paths, ledger_root=ledger_root, as_of_date=date(2026, 8, 31))
    assert second.capture_appended_count == 0
    assert second.outcome_appended_count == 2
    assert second.resolved_outcome_count == 2
    second_ledger = pd.read_parquet(second.ledger_path).sort_values("hypothesis_id")
    assert second_ledger["capture_event_sha256"].tolist() == capture_hashes
    assert second_ledger["outcome_status"].eq("RESOLVED").all()
    for row in second_ledger.itertuples(index=False):
        payload = json.loads(Path(row.outcome_event_path).read_text(encoding="utf-8"))
        assert payload["event_type"] == "OUTCOME"
        assert payload["capture_event_sha256"] == row.capture_event_sha256

    event_count = len(list((ledger_root / "events").rglob("*.json")))
    third = _build(paths, ledger_root=ledger_root, as_of_date=date(2026, 8, 31))
    assert third.status == "FORWARD_LEDGER_NO_CHANGES"
    assert third.no_change_count == 2
    assert len(list((ledger_root / "events").rglob("*.json"))) == event_count


def test_forward_ledger_rejects_capture_feature_rewrite(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path, include_future_event=True)
    ledger_root = tmp_path / "ledger"
    _build(paths, ledger_root=ledger_root, as_of_date=date(2026, 7, 29))
    events = pd.read_parquet(paths["breakout"])
    events.loc[events["horizon"].eq(20), "participation_alignment"] = (
        "NEUTRAL_OR_EXIT"
    )
    events.to_parquet(paths["breakout"], index=False)

    with pytest.raises(ResearchWorkbenchError, match="immutable capture"):
        _build(paths, ledger_root=ledger_root, as_of_date=date(2026, 7, 29))


def test_forward_ledger_outcome_correction_requires_reason(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path, include_future_event=True)
    ledger_root = tmp_path / "ledger"
    _build(paths, ledger_root=ledger_root, as_of_date=date(2026, 7, 29))
    _resolve_outcomes(paths["breakout"])
    _build(paths, ledger_root=ledger_root, as_of_date=date(2026, 8, 31))
    events = pd.read_parquet(paths["breakout"])
    events.loc[events["horizon"].eq(5), "directional_return"] = -0.03
    events.loc[events["horizon"].eq(5), "raw_return"] = -0.03
    events.loc[events["horizon"].eq(5), "outcome"] = "FAILED_BREAKOUT"
    events.to_parquet(paths["breakout"], index=False)

    with pytest.raises(ResearchWorkbenchError, match="correction_reason"):
        _build(paths, ledger_root=ledger_root, as_of_date=date(2026, 8, 31))
    corrected = build_cf_trend_candidate_forward_ledger(
        symmetric_trend_daily_path=paths["daily"],
        breakout_event_path=paths["breakout"],
        candidate_evaluation_path=paths["evaluation"],
        spec_path=paths["spec"],
        as_of_date=date(2026, 8, 31),
        ledger_root=ledger_root,
        report_output_dir=tmp_path / "reports_corrected",
        run_id="r93d_corrected",
        correction_reason="fixture official outcome correction",
    )
    assert corrected.correction_appended_count == 1
    ledger = pd.read_parquet(corrected.ledger_path)
    corrected_row = ledger.loc[ledger["horizon"].eq(5)].iloc[0]
    assert corrected_row["correction_count"] == 1
    assert corrected_row["last_correction_reason"] == (
        "fixture official outcome correction"
    )


def test_forward_ledger_marks_late_capture_non_strict(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path, include_future_event=True)
    result = _build(
        paths,
        ledger_root=tmp_path / "late_ledger",
        as_of_date=date(2026, 7, 30),
    )
    ledger = pd.read_parquet(result.ledger_path)

    assert result.capture_appended_count == 2
    assert result.strict_forward_count == 0
    assert ledger["capture_mode"].eq("LATE_BACKFILL_CAPTURE").all()
    assert ledger["historical_result_is_oos"].eq(False).all()  # noqa: E712
    assert any(
        warning.warning_code == "R93D_LATE_CAPTURE_EXCLUDED"
        for warning in result.warning_records
    )


def test_forward_ledger_rejects_tampered_event_file(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path, include_future_event=True)
    ledger_root = tmp_path / "ledger"
    result = _build(paths, ledger_root=ledger_root, as_of_date=date(2026, 7, 29))
    ledger = pd.read_parquet(result.ledger_path)
    capture_path = Path(ledger.iloc[0]["capture_event_path"])
    capture_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ResearchWorkbenchError, match="checksum"):
        _build(paths, ledger_root=ledger_root, as_of_date=date(2026, 7, 29))


def test_forward_ledger_cli_writes_empty_registered_ledger(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path, include_future_event=False)
    ledger_root = tmp_path / "cli_ledger"
    report_dir = tmp_path / "cli_reports"
    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-trend-candidate-forward-ledger",
            "--symmetric-trend-daily-path",
            str(paths["daily"]),
            "--breakout-event-path",
            str(paths["breakout"]),
            "--candidate-evaluation-path",
            str(paths["evaluation"]),
            "--spec-path",
            str(paths["spec"]),
            "--as-of-date",
            "2026-07-29",
            "--ledger-root",
            str(ledger_root),
            "--report-output-dir",
            str(report_dir),
            "--run-id",
            "r93d_cli_fixture",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "FORWARD_LEDGER_READY_NO_EVENTS"
    assert payload["ledger_row_count"] == 0
    for key in (
        "ledger_path",
        "summary_path",
        "warning_csv_path",
        "json_path",
        "markdown_path",
        "manifest_path",
    ):
        assert Path(payload[key]).exists()


def _build(
    paths: dict[str, Path],
    *,
    ledger_root: Path,
    as_of_date: date,
):
    return build_cf_trend_candidate_forward_ledger(
        symmetric_trend_daily_path=paths["daily"],
        breakout_event_path=paths["breakout"],
        candidate_evaluation_path=paths["evaluation"],
        spec_path=paths["spec"],
        as_of_date=as_of_date,
        ledger_root=ledger_root,
        report_output_dir=ledger_root / "reports",
        run_id=f"r93d_fixture_{as_of_date:%Y%m%d}",
    )


def _write_fixture(
    tmp_path: Path,
    *,
    include_future_event: bool,
) -> dict[str, Path]:
    paths = {
        "daily": tmp_path / "symmetric_daily.parquet",
        "breakout": tmp_path / "breakout.parquet",
        "evaluation": tmp_path / "evaluation.parquet",
        "spec": tmp_path / "spec.yaml",
    }
    pd.DataFrame(
        {
            "trade_date": [
                date(2026, 7, 28),
                date(2026, 7, 29),
                date(2026, 7, 30),
                date(2026, 8, 31),
            ]
        }
    ).to_parquet(paths["daily"], index=False)
    rows = _breakout_rows(
        event_date=date(2026, 7, 29) if include_future_event else date(2026, 7, 7)
    )
    pd.DataFrame(rows).to_parquet(paths["breakout"], index=False)
    pd.DataFrame(
        [
            {
                "hypothesis_id": "H1_PARTICIPATION_CONFIRM_20D",
                "decision_status": "READY_FOR_FORWARD_PREREGISTRATION",
                "strategy_change_allowed": False,
            },
            {
                "hypothesis_id": "H2_WEAK_OPTION_CONTEXT_VETO_5D",
                "decision_status": "FORWARD_WATCH_SMALL_SAMPLE",
                "strategy_change_allowed": False,
            },
            {
                "hypothesis_id": "H3_DIRECTIONAL_WALL_OI_BUILD_3D",
                "decision_status": "HISTORICAL_WATCH_ONLY",
                "strategy_change_allowed": False,
            },
        ]
    ).to_parquet(paths["evaluation"], index=False)
    paths["spec"].write_text(
        yaml.safe_dump(_spec_payload(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return paths


def _breakout_rows(*, event_date: date) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for horizon in (5, 20):
        rows.append(
            {
                "event_id": "20260729_long_0001",
                "event_date": event_date,
                "direction": "long",
                "direction_episode_id": "20260729_long_0001",
                "start_stage": "BREAKOUT",
                "start_strength": 0.65,
                "start_price": 15000.0,
                "main_contract": "CF701",
                "option_alignment": "WEAK_OPTION_CONTEXT",
                "participation_alignment": "CONFIRM",
                "horizon": horizon,
                "exit_date": None,
                "raw_return": None,
                "directional_return": None,
                "label_available": False,
                "outcome": "CURRENT_ONLY",
            }
        )
    return rows


def _resolve_outcomes(path: Path) -> None:
    events = pd.read_parquet(path)
    events["label_available"] = True
    events["outcome"] = "FOLLOW_THROUGH"
    events["raw_return"] = 0.02
    events["directional_return"] = 0.02
    events.loc[events["horizon"].eq(5), "exit_date"] = date(2026, 8, 5)
    events.loc[events["horizon"].eq(20), "exit_date"] = date(2026, 8, 26)
    events.to_parquet(path, index=False)


def _spec_payload() -> dict[str, object]:
    return {
        "spec_version": "R93D_TEST_SPEC",
        "product_code": "CF",
        "status": "frozen_for_forward_research",
        "registered_at": "2026-07-29",
        "effective_after_date": "2026-07-28",
        "selection_disclosure": "fixture retrospective selection",
        "strategy_actions_allowed": False,
        "evaluation_gate": {
            "minimum_historical_treated": 30,
            "minimum_historical_control": 10,
            "minimum_direction_each": 5,
            "minimum_year_each": 2,
            "minimum_evaluable_years": 3,
            "minimum_year_alignment_rate": 0.60,
            "practical_hit_delta": 0.05,
            "practical_return_delta": 0.001,
            "era_split_year": 2023,
            "bootstrap_samples": 100,
            "bootstrap_confidence": 0.95,
            "bootstrap_seed": 9303,
        },
        "hypotheses": [
            {
                "hypothesis_id": "H1_PARTICIPATION_CONFIRM_20D",
                "feature_column": "participation_alignment",
                "feature_value": "CONFIRM",
                "primary_horizon": 20,
                "desired_effect": "positive",
                "forward_role": "confirmation",
                "rationale": "fixture",
            },
            {
                "hypothesis_id": "H2_WEAK_OPTION_CONTEXT_VETO_5D",
                "feature_column": "option_alignment",
                "feature_value": "WEAK_OPTION_CONTEXT",
                "primary_horizon": 5,
                "desired_effect": "negative",
                "forward_role": "veto",
                "rationale": "fixture",
            },
            {
                "hypothesis_id": "H3_DIRECTIONAL_WALL_OI_BUILD_3D",
                "feature_column": "directional_wall_oi_state",
                "feature_value": "WALL_OI_BUILDING",
                "primary_horizon": 3,
                "desired_effect": "positive",
                "forward_role": "wall",
                "rationale": "fixture",
            },
        ],
        "diagnostic_horizons": [1, 3, 5, 10, 20],
        "forbidden_actions": ["modify_strategy"],
    }
