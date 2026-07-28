from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.strategy.weekly_audit import build_cf_weekly_strategy_audit


def test_weekly_audit_separates_forward_capture_and_checks_accounting(
    tmp_path: Path,
) -> None:
    ledger_root = tmp_path / "ledgers"
    _write_ledger(
        ledger_root / "CF_tsmom_v0_shadow_ledger.parquet",
        modes=["HISTORICAL_REPLAY", "FORWARD_CAPTURE", "FORWARD_CAPTURE"],
        pnl=[0.0, 100.0, -25.0],
    )

    result = build_cf_weekly_strategy_audit(
        ledger_root=ledger_root,
        report_output_dir=tmp_path / "reports",
        run_id="weekly_fixture",
    )

    assert result.status == "PASS"
    assert result.forward_capture_days == 2
    assert result.anomaly_count == 0
    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    row = payload["strategies"][0]
    assert row["week_forward_capture_days"] == 2
    assert row["historical_replay_days"] == 1
    assert row["week_return_difference_vs_baseline"] == 0.0
    assert "HISTORICAL_REPLAY 仅用于工程验收" in result.markdown_path.read_text(
        encoding="utf-8"
    )
    assert result.manifest_path.exists()


def test_weekly_audit_cli_marks_no_forward_sample_as_watch(tmp_path: Path) -> None:
    ledger_root = tmp_path / "ledgers"
    _write_ledger(
        ledger_root / "CF_tsmom_v0_shadow_ledger.parquet",
        modes=["HISTORICAL_REPLAY"],
        pnl=[0.0],
    )
    report_root = tmp_path / "reports"

    result = CliRunner().invoke(
        app,
        [
            "strategy",
            "weekly-audit",
            "--date",
            "2024-01-01",
            "--ledger-root",
            str(ledger_root),
            "--report-output-dir",
            str(report_root),
            "--run-id",
            "weekly_cli_fixture",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "WATCH"
    assert payload["forward_capture_days"] == 0
    report = Path(payload["markdown_path"]).read_text(encoding="utf-8")
    assert "NO_FORWARD_CAPTURE" in report
    assert "NAV 为研究记账值，非真实资金" in report


def test_weekly_audit_fails_visible_nav_break(tmp_path: Path) -> None:
    ledger_root = tmp_path / "ledgers"
    path = ledger_root / "CF_tsmom_v0_shadow_ledger.parquet"
    _write_ledger(
        path,
        modes=["FORWARD_CAPTURE", "FORWARD_CAPTURE"],
        pnl=[0.0, 100.0],
    )
    frame = pd.read_parquet(path)
    frame.loc[1, "nav"] += 50.0
    frame.to_parquet(path, index=False)

    result = build_cf_weekly_strategy_audit(
        ledger_root=ledger_root,
        report_output_dir=tmp_path / "reports",
    )

    assert result.status == "FAIL"
    assert "NAV_ACCOUNTING_MISMATCH" in result.markdown_path.read_text(encoding="utf-8")


def _write_ledger(path: Path, *, modes: list[str], pnl: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    start = date(2024, 1, 1)
    nav = 1_000_000.0
    high_watermark = nav
    rows: list[dict[str, object]] = []
    for index, (record_mode, net_pnl) in enumerate(zip(modes, pnl, strict=True)):
        nav += net_pnl
        high_watermark = max(high_watermark, nav)
        rows.append(
            {
                "trade_date": (start + timedelta(days=index)).isoformat(),
                "strategy_key": "CF_tsmom/v0",
                "record_mode": record_mode,
                "event_type": "SHADOW_DAILY",
                "warnings_json": "[]",
                "net_pnl": net_pnl,
                "nav": nav,
                "drawdown": nav / high_watermark - 1.0,
                "turnover_lots": index,
            }
        )
    pd.DataFrame(rows).to_parquet(path, index=False)
