from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import build_cf_futures_option_divergence_playbook


def test_build_cf_futures_option_divergence_playbook_maps_current_structure(
    tmp_path: Path,
) -> None:
    paths = _write_r71_inputs(tmp_path)

    result = build_cf_futures_option_divergence_playbook(
        event_path=paths["events"],
        node_summary_path=paths["nodes"],
        latest_signal_json_path=paths["latest"],
        output_dir=tmp_path / "research" / "playbook",
        report_output_dir=tmp_path / "reports" / "playbook",
        run_id="r71_unit",
        min_sample_size=30,
        edge_threshold=0.08,
    )

    assert result.node_table_parquet_path.exists()
    assert result.current_mapping_parquet_path.exists()
    assert result.warning_csv_path.exists()
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.manifest_path.exists()
    assert result.current_mapping_count == 1
    assert result.warning_count == 1

    node_table = pd.read_parquet(result.node_table_parquet_path)
    assert "期权方历史占优" in set(node_table["playbook_label_cn"])
    assert "期权同向确认" in set(node_table["playbook_label_cn"])

    current = pd.read_parquet(result.current_mapping_parquet_path)
    assert current.loc[0, "matched_playbook_label"] == "OPTIONS_SIDE_HISTORICALLY_VALIDATED"
    assert current.loc[0, "matched_sample_count"] == 53

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "期货-期权背离节点解释表 R71" in markdown
    assert "forward_return` 仅为历史后验验证标签" in markdown
    assert "不修改 `composite_score`" in markdown
    assert "不构成交易指令" in markdown

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "futures_option_divergence_playbook"
    assert payload["research_boundary"]["auto_reverse_allowed"] is False
    assert payload["current_mapping_rows"][0]["matched_node_id"].startswith("R71_NODE_")


def test_cli_build_cf_futures_option_divergence_playbook(tmp_path: Path) -> None:
    paths = _write_r71_inputs(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-futures-option-divergence-playbook",
            "--event-path",
            str(paths["events"]),
            "--node-summary-path",
            str(paths["nodes"]),
            "--latest-signal-json-path",
            str(paths["latest"]),
            "--output-dir",
            str(tmp_path / "research" / "playbook"),
            "--report-output-dir",
            str(tmp_path / "reports" / "playbook"),
            "--run-id",
            "r71_cli",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "r71_cli"
    assert Path(output["node_table_parquet_path"]).exists()
    assert Path(output["current_mapping_parquet_path"]).exists()


def _write_r71_inputs(tmp_path: Path) -> dict[str, Path]:
    event_path = tmp_path / "r69" / "events.parquet"
    node_path = tmp_path / "r69" / "nodes.parquet"
    latest_path = tmp_path / "daily" / "CF" / "2026-07-07" / "latest_signal_brief.json"
    for path in (event_path, node_path, latest_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {
                "trade_date": "2026-07-05",
                "horizon": 5,
                "main_contract": "CF609",
                "futures_direction": "long",
                "option_direction": "short",
                "divergence_type": "directional_divergence",
                "option_signal": "diverge_short",
                "trend_phase": "S4",
                "confidence": "low",
                "winner_label": "OPTIONS_WIN",
                "forward_label_available": True,
            },
            {
                "trade_date": "2026-07-06",
                "horizon": 10,
                "main_contract": "CF609",
                "futures_direction": "long",
                "option_direction": "long",
                "divergence_type": "option_confirmation",
                "option_signal": "confirm_long",
                "trend_phase": "S2",
                "confidence": "high",
                "winner_label": "FUTURES_FOLLOW_THROUGH",
                "forward_label_available": False,
            },
        ]
    ).to_parquet(event_path, index=False)

    pd.DataFrame(
        [
            {
                "divergence_type": "directional_divergence",
                "trend_phase": "S4",
                "confidence": "low",
                "option_signal": "diverge_short",
                "iv_rank_bucket": "iv_low_0_10",
                "skew_bucket": "skew_put_discount_or_call_rich",
                "pcr_bucket": "pcr_low",
                "oi_signal": "neutral",
                "sample_count": 53,
                "futures_win_rate": 0.377358,
                "options_win_rate": 0.584906,
                "avg_futures_directional_forward_return": -0.049516,
                "average_resolution_horizon": 13.47,
                "dominant_winner_label": "OPTIONS_WIN",
                "recent_stability": "STABLE",
                "evidence_level": "READY",
            },
            {
                "divergence_type": "option_confirmation",
                "trend_phase": "S2",
                "confidence": "high",
                "option_signal": "confirm_long",
                "iv_rank_bucket": "iv_low_0_10",
                "skew_bucket": "skew_neutral",
                "pcr_bucket": "pcr_low",
                "oi_signal": "neutral",
                "sample_count": 80,
                "futures_win_rate": 0.61,
                "options_win_rate": 0.0,
                "avg_futures_directional_forward_return": 0.01,
                "average_resolution_horizon": 5.0,
                "dominant_winner_label": "FUTURES_FOLLOW_THROUGH",
                "recent_stability": "STABLE",
                "evidence_level": "READY",
            },
        ]
    ).to_parquet(node_path, index=False)

    latest_path.write_text(
        json.dumps(
            {
                "data_asof": "2026-07-07",
                "signal_matrix_context": {
                    "rows": [
                        {
                            "horizon": 5,
                            "direction": "long",
                            "confidence": "low",
                            "trend_phase": "S4",
                            "option_signal": "diverge_short",
                            "option_signal_direction": "short",
                            "option_atm_iv_rank": 0.03,
                            "option_skew_proxy": -0.002,
                            "option_pcr_volume": 0.50,
                            "option_pcr_oi": 0.70,
                            "oi_signal": "neutral",
                        }
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {"events": event_path, "nodes": node_path, "latest": latest_path}
