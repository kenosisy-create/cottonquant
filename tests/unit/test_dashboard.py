from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


def test_dashboard_loads_auditable_shadow_ledger(tmp_path: Path) -> None:
    dashboard = _load_dashboard_module()
    run_dir, ledger_path = _dashboard_fixture(tmp_path)

    payload = dashboard.build_payload(run_dir, "CF", tmp_path)

    shadow = payload["strategy_shadow"]
    assert shadow["record_mode"] == "FORWARD_CAPTURE"
    assert shadow["strategies"][0]["strategy_key"] == "CF_tsmom/v0"
    assert shadow["strategies"][0]["target_lots"] == -3
    assert shadow["strategies"][0]["forward_capture_days"] == 1
    assert shadow["strategies"][0]["historical_replay_days"] == 1
    assert len(shadow["strategies"][0]["nav_series"]) == 2
    assert shadow["strategies"][0]["ledger_path"].endswith(ledger_path.name)


def test_dashboard_hides_strategy_section_without_ledger(tmp_path: Path) -> None:
    dashboard = _load_dashboard_module()
    run_dir = _brief_fixture(tmp_path)
    (run_dir / "strategy_shadow.json").write_text(
        json.dumps(
            {
                "trade_date": "2024-01-03",
                "record_mode": "FORWARD_CAPTURE",
                "strategies": [
                    {
                        "strategy_key": "CF_tsmom/v0",
                        "ledger_path": str(tmp_path / "data/strategy/CF/missing.parquet"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = dashboard.build_payload(run_dir, "CF", tmp_path)

    assert payload["strategy_shadow"] is None


def test_dashboard_rejects_forward_return_columns(tmp_path: Path) -> None:
    dashboard = _load_dashboard_module()
    run_dir, ledger_path = _dashboard_fixture(tmp_path)
    frame = pd.read_parquet(ledger_path)
    frame["forward_return_20d"] = 0.01
    frame.to_parquet(ledger_path, index=False)

    with pytest.raises(ValueError, match="forbidden columns"):
        dashboard.load_strategy_shadow(run_dir, "CF", tmp_path)


def test_dashboard_main_writes_single_file_with_strategy_payload(tmp_path: Path) -> None:
    dashboard = _load_dashboard_module()
    _dashboard_fixture(tmp_path)
    output_path = tmp_path / "dashboard.html"

    result = dashboard.main(
        [
            "--root",
            str(tmp_path),
            "--product",
            "CF",
            "--date",
            "2024-01-03",
            "--output",
            str(output_path),
        ]
    )

    html = output_path.read_text(encoding="utf-8")
    assert result == 0
    assert output_path.stat().st_size > 10_000
    assert "__PAYLOAD__" not in html
    assert 'id="sec-strategy"' in html
    assert "CF_tsmom/v0" in html
    assert "不含未来收益标签" in html


def _load_dashboard_module():
    path = Path(__file__).resolve().parents[2] / "scripts/build_dashboard.py"
    spec = importlib.util.spec_from_file_location("cottonquant_dashboard", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dashboard_fixture(tmp_path: Path) -> tuple[Path, Path]:
    run_dir = _brief_fixture(tmp_path)
    ledger_path = tmp_path / "data/strategy/CF/CF_tsmom_v0_shadow_ledger.parquet"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            _ledger_row("2024-01-02", mode="HISTORICAL_REPLAY", nav=1_000_000.0),
            _ledger_row("2024-01-03", mode="FORWARD_CAPTURE", nav=1_000_125.0),
        ]
    ).to_parquet(ledger_path, index=False)
    (run_dir / "strategy_shadow.json").write_text(
        json.dumps(
            {
                "trade_date": "2024-01-03",
                "record_mode": "FORWARD_CAPTURE",
                "run_id": "shadow_fixture",
                "research_boundary": "研究仿真，不构成交易指令；NAV 非真实资金。",
                "strategies": [
                    {
                        "strategy_key": "CF_tsmom/v0",
                        "status": "APPENDED",
                        "ledger_path": str(ledger_path),
                        "warning_count": 0,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return run_dir, ledger_path


def _brief_fixture(tmp_path: Path) -> Path:
    run_dir = tmp_path / "runs/daily/CF/2024-01-03"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "latest_signal_brief.json").write_text(
        json.dumps(
            {
                "trade_date": "2024-01-03",
                "main_contract": "CF405",
                "summary": {"research_boundary": {"no_future_return_labels": True}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return run_dir


def _ledger_row(trade_date: str, *, mode: str, nav: float) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "strategy_key": "CF_tsmom/v0",
        "record_mode": mode,
        "target_lots": -3,
        "target_contract": "CF405",
        "held_lots_after": -2,
        "held_contract_after": "CF405",
        "nav": nav,
        "drawdown": min(0.0, nav / 1_000_125.0 - 1.0),
        "entry_date": "2024-01-02",
        "holding_days": 2,
    }
