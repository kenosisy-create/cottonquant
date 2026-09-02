from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.operations.daily_update import CfDailyUpdateConfig, run_cf_daily_update


class FakeExecutor:
    def __init__(self, *, fail_command: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_command = fail_command

    def run(self, args: list[str] | tuple[str, ...]) -> dict[str, Any]:
        command = list(args)
        self.calls.append(command)
        command_name = command[1]
        if command_name == self.fail_command:
            raise ResearchWorkbenchError(f"fixture failure: {command_name}")
        return _summary(command_name)


def test_daily_update_runs_light_steps_in_dependency_order(tmp_path: Path) -> None:
    _write_core(tmp_path, latest_date=date(2026, 8, 27))
    executor = FakeExecutor()
    result = run_cf_daily_update(
        _config(
            tmp_path,
            include_options=False,
            run_state_upgrade=False,
            run_daily_operation_audit=True,
        ),
        executor=executor,
    )

    assert result.passed is True
    assert result.status == "COMPLETED_WITH_WARNINGS"
    assert result.data_asof == date(2026, 8, 27)
    assert "signal_matrix" in result.to_summary()["warning_steps"]
    assert [call[1] for call in executor.calls] == [
        "connect-cf-official-history",
        "build-cf-data-continuity-audit",
        "build-cf-signal-matrix",
        "build-cf-latest-signal-brief",
        "build-cf-fundamental-data-status",
        "build-cf-trend-continuity-board",
        "build-cf-daily-operation-audit",
    ]
    studio = next(step for step in result.steps if step.step_id == "studio_dashboard")
    assert studio.status in {"COMPLETED", "WARNING"}
    assert (Path(__file__).parents[2] / "scripts/build_cf_studio_dashboard.py").is_file()
    assert result.json_path.exists()
    assert result.markdown_path.exists()
    calendar = pd.read_csv(tmp_path / "configs/calendars/CZCE_2026_OFFICIAL.csv")
    latest_row = calendar.loc[calendar["trade_date"] == "2026-08-27"].iloc[0]
    assert bool(latest_row["is_trading_day"]) is True


def test_daily_update_download_path_refreshes_option_sidecar(tmp_path: Path) -> None:
    _write_core(tmp_path, latest_date=date(2026, 8, 27))
    executor = FakeExecutor()
    result = run_cf_daily_update(
        _config(
            tmp_path,
            download_official=True,
            include_options=True,
            run_state_upgrade=True,
        ),
        executor=executor,
    )

    assert result.passed is True
    assert [call[1] for call in executor.calls] == [
        "fetch-cf-official-daily-files",
        "connect-cf-official-history",
        "connect-cf-option-history",
        "build-cf-data-continuity-audit",
        "build-cf-option-factor-proxy",
        "build-cf-signal-matrix",
        "build-cf-dual-price-state",
        "build-cf-chain-oi-structure",
        "build-cf-option-structure-research",
        "build-cf-trend-phase-v2",
        "build-cf-latest-signal-brief",
        "build-cf-fundamental-data-status",
        "build-cf-trend-continuity-board",
    ]
    studio = next(step for step in result.steps if step.step_id == "studio_dashboard")
    assert studio.status in {"COMPLETED", "WARNING"}
    option_factor_call = next(
        call for call in executor.calls if call[1] == "build-cf-option-factor-proxy"
    )
    assert "--incremental" in option_factor_call


def test_nonblocking_status_failure_keeps_daily_update_usable(tmp_path: Path) -> None:
    _write_core(tmp_path, latest_date=date(2026, 8, 27))
    result = run_cf_daily_update(
        _config(tmp_path, include_options=False, run_state_upgrade=False),
        executor=FakeExecutor(fail_command="build-cf-fundamental-data-status"),
    )

    assert result.passed is True
    assert result.status == "COMPLETED_WITH_WARNINGS"
    warning = next(step for step in result.steps if step.step_id == "fundamental_data_status")
    assert warning.status == "WARNING"


def test_blocking_failure_stops_later_steps_and_writes_summary(tmp_path: Path) -> None:
    _write_core(tmp_path, latest_date=date(2026, 8, 27))
    result = run_cf_daily_update(
        _config(tmp_path, include_options=False, run_state_upgrade=False),
        executor=FakeExecutor(fail_command="build-cf-signal-matrix"),
    )

    assert result.passed is False
    assert result.status == "FAILED"
    failed = next(step for step in result.steps if step.step_id == "signal_matrix")
    latest = next(step for step in result.steps if step.step_id == "latest_signal_brief")
    assert failed.status == "FAILED"
    assert latest.status == "SKIPPED_BLOCKED"
    assert result.json_path.exists()


def test_public_daily_update_cli_wires_options_into_config(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    class FakeResult:
        passed = True

        def to_summary(self) -> dict[str, Any]:
            return {"status": "COMPLETED", "passed": True}

    def fake_run(config: CfDailyUpdateConfig) -> FakeResult:
        captured["config"] = config
        return FakeResult()

    monkeypatch.setattr("cotton_factor.operations.run_cf_daily_update", fake_run)
    result = CliRunner().invoke(
        app,
        [
            "operations",
            "run-cf-daily-update",
            "--date",
            "2026-08-27",
            "--skip-options",
            "--skip-continuity-audit",
            "--skip-state-upgrade",
            "--run-id",
            "r02_cli_wiring",
        ],
    )

    assert result.exit_code == 0, result.output
    config = captured["config"]
    assert config.trade_date == date(2026, 8, 27)
    assert config.include_options is False
    assert config.run_continuity_audit is False
    assert config.run_state_upgrade is False
    assert config.run_id == "r02_cli_wiring"


def test_studio_dashboard_step_is_skippable_and_nonblocking(tmp_path: Path) -> None:
    _write_core(tmp_path, latest_date=date(2026, 8, 27))
    result = run_cf_daily_update(
        _config(tmp_path, include_options=False, run_state_upgrade=False, build_studio_dashboard=False),
        executor=FakeExecutor(),
    )
    studio = next(step for step in result.steps if step.step_id == "studio_dashboard")
    assert studio.status == "SKIPPED"

    # scripts 目录缺失时 studio 步骤失败但不阻断整条流水线
    missing_repo = tmp_path / "missing_scripts_repo"
    _write_core(missing_repo, latest_date=date(2026, 8, 27))
    failed = run_cf_daily_update(
        _config(missing_repo, include_options=False, run_state_upgrade=False),
        executor=FakeExecutor(),
    )
    studio_failed = next(step for step in failed.steps if step.step_id == "studio_dashboard")
    assert studio_failed.status == "WARNING"
    assert failed.passed is True


def _config(repo_root: Path, **overrides: Any) -> CfDailyUpdateConfig:
    values: dict[str, Any] = {
        "trade_date": date(2026, 8, 27),
        "year": 2026,
        "run_id": "daily_update_unit",
        "repo_root": repo_root,
        "include_options": False,
        "run_state_upgrade": False,
    }
    values.update(overrides)
    return CfDailyUpdateConfig(**values)


def _write_core(repo_root: Path, *, latest_date: date) -> None:
    path = repo_root / "data/core/CF/core_quote_daily.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "trade_date": [date(2026, 8, 25), date(2026, 8, 26), latest_date],
        }
    ).to_parquet(path, index=False)


def _summary(command_name: str) -> dict[str, Any]:
    summaries: dict[str, dict[str, Any]] = {
        "fetch-cf-official-daily-files": {
            "futures_connect_source_dir": "data/incoming/CF/history/daily/2026/20260827",
            "options_connect_source_dir": "data/incoming/CF/options/history/daily/2026/20260827",
            "json_path": "reports/research/official_daily_files/fetch.json",
        },
        "connect-cf-official-history": {"status": "COMPLETED"},
        "connect-cf-option-history": {
            "status": "COMPLETED",
            "core_option_quote_path": "data/core/CF/core_option_quote_daily.parquet",
        },
        "build-cf-data-continuity-audit": {
            "passed": True,
            "continuity_status": "READY",
        },
        "build-cf-option-factor-proxy": {
            "factor_parquet_path": "data/research/CF/option_factors/factor.parquet",
        },
        "build-cf-signal-matrix": {
            "matrix_parquet_path": "data/research/CF/signal_matrix/matrix.parquet",
            "latest_snapshot_json_path": "data/research/CF/signal_matrix/latest.json",
            "warning_count": 1,
        },
        "build-cf-dual-price-state": {"daily_parquet_path": "dual.parquet"},
        "build-cf-chain-oi-structure": {"daily_parquet_path": "chain.parquet"},
        "build-cf-option-structure-research": {"daily_parquet_path": "option.parquet"},
        "build-cf-trend-phase-v2": {"daily_parquet_path": "phase.parquet"},
        "build-cf-latest-signal-brief": {
            "json_path": "runs/daily/CF/2026-08-27/latest_signal_brief.json",
            "markdown_path": "runs/daily/CF/2026-08-27/latest_signal_brief.md",
        },
        "build-cf-fundamental-data-status": {"status": "COMPLETED"},
        "build-cf-trend-continuity-board": {
            "json_path": "runs/daily/CF/2026-08-27/trend_continuity_board.json",
            "markdown_path": "runs/daily/CF/2026-08-27/trend_continuity_board.md",
        },
        "build-cf-daily-operation-audit": {"operation_status": "READY"},
    }
    return summaries[command_name]
