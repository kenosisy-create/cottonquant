from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench.forward_evidence_weekly import (
    CANDIDATE_REQUIRED_COLUMNS,
    build_cf_forward_evidence_weekly,
)


def test_forward_evidence_weekly_separates_strategy_days_and_candidate_events(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(tmp_path, candidate_mode="REALTIME_FORWARD_CAPTURE")

    result = build_cf_forward_evidence_weekly(
        as_of_date=date(2026, 7, 30),
        strategy_ledger_root=paths["strategy_root"],
        candidate_ledger_path=paths["candidate_ledger"],
        candidate_event_root=paths["event_root"],
        candidate_run_json_path=paths["candidate_run"],
        output_dir=tmp_path / "data_out",
        report_output_dir=tmp_path / "reports_out",
        run_id="r93e_fixture",
    )

    assert result.status == "FORWARD_COLLECTION_HEALTHY"
    assert result.strategy_forward_days == 2
    assert result.governance_target_days == 40
    assert result.governance_days_remaining == 38
    assert result.candidate_unique_event_count == 1
    assert result.candidate_capture_count == 2
    assert result.candidate_pending_count == 2
    assert result.candidate_resolved_count == 0
    assert result.warning_count == 0
    summary = pd.read_parquet(result.summary_path)
    assert set(summary["channel"]) == {"STRATEGY_SHADOW", "TREND_CANDIDATE"}
    report = result.markdown_path.read_text(encoding="utf-8")
    assert "40日与5D/20D是不同口径" in report
    assert "不构成交易指令" in report
    assert "未到期CAPTURE不得提前解释为成功或失败" in report
    for path in (
        result.summary_path,
        result.warning_csv_path,
        result.json_path,
        result.markdown_path,
        result.manifest_path,
    ):
        assert path.exists()


def test_forward_evidence_weekly_marks_late_capture_and_stale_refresh_watch(
    tmp_path: Path,
) -> None:
    paths = _write_fixture(tmp_path, candidate_mode="LATE_BACKFILL_CAPTURE")
    paths["candidate_run"].write_text(
        json.dumps(
            {"as_of_date": "2026-07-29", "status": "FORWARD_LEDGER_NO_CHANGES"}
        ),
        encoding="utf-8",
    )

    result = build_cf_forward_evidence_weekly(
        as_of_date=date(2026, 7, 30),
        strategy_ledger_root=paths["strategy_root"],
        candidate_ledger_path=paths["candidate_ledger"],
        candidate_event_root=paths["event_root"],
        candidate_run_json_path=paths["candidate_run"],
        output_dir=tmp_path / "watch_data",
        report_output_dir=tmp_path / "watch_reports",
        run_id="r93e_watch_fixture",
    )

    assert result.status == "FORWARD_COLLECTION_WATCH"
    assert result.candidate_late_capture_count == 2
    warning_codes = {item.warning_code for item in result.warning_records}
    assert "R93E_LATE_CAPTURE_EXCLUDED" in warning_codes
    assert "R93E_CANDIDATE_REFRESH_STALE" in warning_codes


def test_forward_evidence_weekly_cli_accepts_current_empty_candidate_ledger(
    tmp_path: Path,
) -> None:
    strategy_root = tmp_path / "strategy"
    _write_shadow_ledger(strategy_root / "CF_tsmom_v0_shadow_ledger.parquet")
    candidate_ledger = tmp_path / "empty_candidate.parquet"
    pd.DataFrame(columns=sorted(CANDIDATE_REQUIRED_COLUMNS)).to_parquet(
        candidate_ledger,
        index=False,
    )
    candidate_run = tmp_path / "candidate_run.json"
    candidate_run.write_text(
        json.dumps(
            {
                "as_of_date": "2026-07-30",
                "status": "FORWARD_LEDGER_READY_NO_EVENTS",
            }
        ),
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-forward-evidence-weekly",
            "--date",
            "2026-07-30",
            "--strategy-ledger-root",
            str(strategy_root),
            "--candidate-ledger-path",
            str(candidate_ledger),
            "--candidate-event-root",
            str(tmp_path / "empty_events"),
            "--candidate-run-json-path",
            str(candidate_run),
            "--output-dir",
            str(tmp_path / "cli_data"),
            "--report-output-dir",
            str(tmp_path / "cli_reports"),
            "--run-id",
            "r93e_cli_fixture",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "FORWARD_COLLECTION_HEALTHY_NO_CANDIDATE_EVENTS"
    assert payload["candidate_capture_count"] == 0
    assert Path(payload["markdown_path"]).exists()
    assert Path(payload["manifest_path"]).exists()


def _write_fixture(tmp_path: Path, *, candidate_mode: str) -> dict[str, Path]:
    strategy_root = tmp_path / "strategy"
    _write_shadow_ledger(strategy_root / "CF_tsmom_v0_shadow_ledger.parquet")
    candidate_ledger = tmp_path / "candidate_ledger.parquet"
    strict = candidate_mode == "REALTIME_FORWARD_CAPTURE"
    rows = []
    for hypothesis_id, horizon, decision in (
        ("H1_PARTICIPATION_CONFIRM_20D", 20, "READY_FOR_FORWARD_PREREGISTRATION"),
        ("H2_WEAK_OPTION_CONTEXT_VETO_5D", 5, "FORWARD_WATCH_SMALL_SAMPLE"),
    ):
        rows.append(
            {
                "hypothesis_id": hypothesis_id,
                "event_id": "20260730_short_0122",
                "event_date": date(2026, 7, 30),
                "capture_as_of_date": date(2026, 7, 30),
                "capture_mode": candidate_mode,
                "strict_forward_eligible": strict,
                "candidate_decision": decision,
                "treated": False,
                "direction": "short",
                "horizon": horizon,
                "outcome_status": "PENDING",
                "label_available": False,
                "outcome": None,
                "directional_return": None,
                "correction_count": 0,
                "historical_result_is_oos": strict,
                "strategy_change_allowed": False,
            }
        )
    pd.DataFrame(rows).to_parquet(candidate_ledger, index=False)
    event_root = tmp_path / "events"
    _write_event_chain(event_root, count=2)
    candidate_run = tmp_path / "candidate_run.json"
    candidate_run.write_text(
        json.dumps(
            {"as_of_date": "2026-07-30", "status": "FORWARD_LEDGER_APPENDED"}
        ),
        encoding="utf-8",
    )
    return {
        "strategy_root": strategy_root,
        "candidate_ledger": candidate_ledger,
        "event_root": event_root,
        "candidate_run": candidate_run,
    }


def _write_shadow_ledger(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    nav = 1_000_000.0
    for index, record_mode in enumerate(
        ("HISTORICAL_REPLAY", "FORWARD_CAPTURE", "FORWARD_CAPTURE")
    ):
        net_pnl = 0.0 if index == 0 else 100.0 * index
        nav = 1_000_000.0 + net_pnl if index == 1 else nav + net_pnl
        rows.append(
            {
                "trade_date": (date(2026, 7, 28) + timedelta(days=index)).isoformat(),
                "strategy_key": "CF_tsmom/v0",
                "record_mode": record_mode,
                "event_type": "SHADOW_DAILY",
                "net_pnl": net_pnl,
                "nav": nav,
                "drawdown": 0.0,
                "target_lots": -17,
                "target_contract": "CF609",
                "held_lots_after": -17 if index > 0 else 0,
                "overwrite_reason": None,
            }
        )
    pd.DataFrame(rows).to_parquet(path, index=False)


def _write_event_chain(root: Path, *, count: int) -> None:
    day_root = root / "2026-07-30"
    day_root.mkdir(parents=True, exist_ok=True)
    previous_sha: str | None = None
    for index in range(count):
        path = day_root / f"20260730T00000000000{index}Z_capture_{index}.json"
        payload = {
            "schema_version": "V5.1_R93D_trend_candidate_forward_ledger_v1",
            "event_type": "CAPTURE",
            "previous_event_sha256": previous_sha,
            "event_business": {"event_date": "2026-07-30"},
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        previous_sha = hashlib.sha256(path.read_bytes()).hexdigest()
