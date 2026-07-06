from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench import build_cf_trend_continuity_board


def test_build_cf_trend_continuity_board_writes_latest_window_outputs(
    tmp_path: Path,
) -> None:
    core_path, trade_dates = _write_trend_continuity_core_quotes(tmp_path)
    candidate_path = _write_trend_rule_candidate_fixture(tmp_path)

    result = build_cf_trend_continuity_board(
        core_quote_path=core_path,
        output_root=tmp_path / "runs" / "daily",
        run_id="r29_unit_board",
        lookback_trading_days=3,
        trend_rule_candidate_path=candidate_path,
    )

    assert result.trade_date == trade_dates[-1]
    assert result.row_count == 3
    assert result.latest_main_contract == "CF405"
    assert result.latest_phase_code == "S2"
    assert result.latest_transition_code == "S1_TO_S2"
    assert result.latest_observation_marker == "趋势起点观察"
    assert result.latest_trend_quality_score >= 60
    assert result.latest_trend_quality_label in {"趋势质量改善", "强趋势质量"}
    assert result.board_csv_path.exists()
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.warning_csv_path.exists()
    assert result.manifest_path.exists()

    board = pd.read_csv(result.board_csv_path)
    latest = board.iloc[-1]
    assert latest["transition_code"] == "S1_TO_S2"
    assert latest["candidate_status"] == "READY_CANDIDATE"
    assert latest["daily_brief_action"] == "ALLOW_DAILY_EXPLANATION_CANDIDATE"
    assert latest["phase_run_length"] == 1
    assert latest["trend_quality_score"] >= 60
    assert latest["trend_quality_label"] in {"趋势质量改善", "强趋势质量"}
    assert "R27 候选状态调整" in latest["trend_quality_reason"]

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["no_future_return_labels"] is True
    assert payload["rows"][-1]["transition_code"] == "S1_TO_S2"
    assert payload["latest_trend_quality_score"] >= 60
    assert payload["trend_quality_rule_version"] == "R31_trend_quality_score_v1"
    assert "forward_return_h" not in result.json_path.read_text(encoding="utf-8")

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "CF 趋势连续性观察板" in markdown
    assert "趋势起点观察" in markdown
    assert "趋势质量" in markdown
    assert "R31 趋势质量评分是研究解释启发式" in markdown
    assert "本观察板未包含未来收益标签" in markdown
    assert "R27 候选规则只用于解释阶段切换" in markdown
    assert "不构成交易指令" in markdown

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["no_lookahead"] is True
    assert manifest["contains_forward_return_validation"] is False
    assert manifest["trend_quality_rule_version"] == "R31_trend_quality_score_v1"


def test_build_cf_trend_continuity_board_validates_lookback(tmp_path: Path) -> None:
    core_path, _ = _write_trend_continuity_core_quotes(tmp_path)

    with pytest.raises(ResearchWorkbenchError, match="lookback_trading_days must be positive"):
        build_cf_trend_continuity_board(
            core_quote_path=core_path,
            output_root=tmp_path / "daily",
            lookback_trading_days=0,
        )


def test_build_cf_trend_continuity_board_connects_trend_quality_calibration(
    tmp_path: Path,
) -> None:
    core_path, trade_dates = _write_trend_continuity_core_quotes(tmp_path)
    baseline = build_cf_trend_continuity_board(
        core_quote_path=core_path,
        output_root=tmp_path / "baseline_daily",
        run_id="r29_unit_baseline",
        lookback_trading_days=3,
    )
    manifest_path = _write_trend_quality_calibration_manifest(
        tmp_path=tmp_path,
        trade_date=trade_dates[-1],
        latest_score=baseline.latest_trend_quality_score,
        latest_label=baseline.latest_trend_quality_label,
    )

    result = build_cf_trend_continuity_board(
        core_quote_path=core_path,
        output_root=tmp_path / "runs" / "daily",
        run_id="r33_unit_board",
        lookback_trading_days=3,
        trend_quality_calibration_manifest_path=manifest_path,
    )

    context = result.trend_quality_calibration_context
    assert context["context_status"] == "PROVIDED"
    assert context["alignment_status"] == "MATCHED"
    assert context["latest_score_context_label"] == "历史中位"
    assert "R32 校准显示" in str(context["interpretation_cn"])
    assert result.to_summary()["trend_quality_calibration_manifest_path"] == str(manifest_path)

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["contains_aggregated_trend_quality_calibration"] is True
    assert payload["trend_quality_calibration_context"]["alignment_status"] == "MATCHED"
    assert "forward_return_h" not in result.json_path.read_text(encoding="utf-8")

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "## 三、趋势质量历史校准" in markdown
    assert "R32 校准显示" in markdown
    assert "只读取 manifest 和分数段聚合校准表" in markdown


def _write_trend_continuity_core_quotes(tmp_path: Path) -> tuple[Path, list[date]]:
    path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True)
    trade_dates = _business_dates(date(2024, 1, 2), count=25)
    rows: list[dict[str, object]] = []
    for offset, trade_date in enumerate(trade_dates):
        main_settle = 100 + offset
        if offset == len(trade_dates) - 3:
            main_open_interest = 12_200
        elif offset == len(trade_dates) - 2:
            main_open_interest = 12_100
        elif offset == len(trade_dates) - 1:
            main_open_interest = 12_300
        else:
            main_open_interest = 10_000 + offset * 100
        rows.extend(
            [
                _quote(
                    contract_code="CF403",
                    trade_date=trade_date,
                    settle=main_settle - 2,
                    volume=800 + offset,
                    open_interest=7_000 + offset,
                ),
                _quote(
                    contract_code="CF405",
                    trade_date=trade_date,
                    settle=main_settle,
                    volume=1_000 + offset,
                    open_interest=main_open_interest,
                ),
                _quote(
                    contract_code="CF409",
                    trade_date=trade_date,
                    settle=main_settle + 4,
                    volume=700 + offset,
                    open_interest=6_000 + offset,
                ),
            ]
        )
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path, trade_dates


def _write_trend_rule_candidate_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "trend_rule_candidates" / "candidates.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "run_id": "r27_unit_candidates",
                "product_code": "CF",
                "transition_code": "S1_TO_S2",
                "event_type": "趋势起点确认",
                "candidate_status": "READY_CANDIDATE",
                "daily_brief_action": "ALLOW_DAILY_EXPLANATION_CANDIDATE",
                "selected_horizon": 10,
                "event_count": 4,
                "observation_count": 4,
                "new_phase_direction": "long",
                "mean_forward_return": 0.0125,
                "median_forward_return": 0.011,
                "directional_hit_rate": 0.75,
                "positive_rate": 0.75,
                "negative_rate": 0.25,
                "latest_event_date": "2024-02-01",
                "evidence_score": 0.8,
                "rule_text_cn": "S1_TO_S2 可作为日报趋势解释候选，参考 h10。",
                "caveat_cn": "样本仍有限，仅用于研究解释。",
                "candidate_rule_version": "R27_trend_rule_candidates_v1",
                "source_event_rule_version": "R26_trend_phase_transition_events_v1",
            }
        ]
    ).to_parquet(path, index=False)
    return path


def _write_trend_quality_calibration_manifest(
    *,
    tmp_path: Path,
    trade_date: date,
    latest_score: int,
    latest_label: str,
) -> Path:
    root = tmp_path / "trend_quality_calibration"
    root.mkdir(parents=True)
    bucket_summary_path = root / "bucket_summary.parquet"
    pd.DataFrame(
        [
            {
                "score_bucket": "B3_60_74",
                "score_bucket_label": "60-74 趋势质量改善",
                "horizon": 5,
                "signal_day_count": 8,
                "observation_count": 7,
                "mean_forward_return": 0.012,
                "directional_hit_rate": 0.71,
            },
            {
                "score_bucket": "B3_60_74",
                "score_bucket_label": "60-74 趋势质量改善",
                "horizon": 10,
                "signal_day_count": 8,
                "observation_count": 6,
                "mean_forward_return": 0.018,
                "directional_hit_rate": 0.67,
            },
        ]
    ).to_parquet(bucket_summary_path, index=False)
    manifest_path = root / "manifest.json"
    manifest = {
        "report_type": "trend_quality_calibration",
        "rule_version": "R32_trend_quality_calibration_v1",
        "forward_returns_are_validation_labels": True,
        "start": "2024-01-02",
        "end": trade_date.isoformat(),
        "daily_row_count": 25,
        "latest_trade_date": trade_date.isoformat(),
        "latest_main_contract": "CF405",
        "latest_trend_quality_score": latest_score,
        "latest_trend_quality_label": latest_label,
        "latest_score_bucket": "B3_60_74",
        "latest_score_bucket_label": "60-74 趋势质量改善",
        "latest_score_percentile": 0.62,
        "latest_score_context_label": "历史中位",
        "bucket_summary_parquet_path": str(bucket_summary_path),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _business_dates(start: date, *, count: int) -> list[date]:
    values: list[date] = []
    current = start
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current += timedelta(days=1)
    return values


def _quote(
    *,
    contract_code: str,
    trade_date: date,
    settle: float,
    volume: int,
    open_interest: int,
) -> dict[str, object]:
    return {
        "source_snapshot_id": f"r29_fixture_{contract_code}_{trade_date:%Y%m%d}",
        "exchange": "CZCE",
        "product_code": "CF",
        "contract_code": contract_code,
        "trade_date": trade_date,
        "settle": settle,
        "volume": volume,
        "open_interest": open_interest,
    }
