from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.research_workbench import build_cf_latest_signal_brief, build_cf_signal_matrix


def test_build_cf_latest_signal_brief_uses_latest_date_and_writes_outputs(
    tmp_path: Path,
) -> None:
    core_path, trade_dates = _write_latest_signal_core_quotes(tmp_path)
    latest_date = trade_dates[-1]

    result = build_cf_latest_signal_brief(
        core_quote_path=core_path,
        output_root=tmp_path / "runs" / "daily",
        run_id="r23_unit_latest",
    )

    assert result.trade_date == latest_date
    assert result.main_contract == "CF405"
    assert result.signal_direction == "long"
    assert result.trend_phase.phase_code == "S2"
    assert result.markdown_path.parent == tmp_path / "runs" / "daily" / "CF" / "2024-02-05"
    assert result.markdown_path.exists()
    assert result.json_path.exists()
    assert result.warning_csv_path.exists()
    assert result.manifest_path.exists()

    market = result.summary["market_facts"]
    factors = result.summary["factor_signals"]
    term = result.summary["term_structure"]
    assert market["main_contract"] == "CF405"
    assert market["contract_activity"][0]["contract_code"] == "CF405"  # type: ignore[index]
    assert factors["main_returns"]["1"] == pytest.approx(124 / 123 - 1)  # type: ignore[index]
    assert factors["main_returns"]["3"] == pytest.approx(124 / 121 - 1)  # type: ignore[index]
    assert factors["main_returns"]["5"] == pytest.approx(124 / 119 - 1)  # type: ignore[index]
    assert factors["main_returns"]["10"] == pytest.approx(124 / 114 - 1)  # type: ignore[index]
    assert factors["main_returns"]["20"] == pytest.approx(124 / 104 - 1)  # type: ignore[index]
    assert market["main_oi_pressure"] == pytest.approx(100 / 12_300)  # type: ignore[index]
    assert term["near_contract"] == "CF403"
    assert term["main_minus_near"] == pytest.approx(2)
    assert term["far_contract"] == "CF409"
    assert term["far_minus_main"] == pytest.approx(4)
    assert term["curve_slope"] == pytest.approx(128 / 124 - 1)

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["data_status"]["contains_forward_return_validation"] is False
    assert payload["summary"]["research_boundary"]["no_future_return_labels"] is True
    assert payload["trend_phase"]["phase_code"] == "S2"

    markdown = result.markdown_path.read_text(encoding="utf-8")
    for section in (
        "## 一、数据状态",
        "## 二、市场事实",
        "## 三、期限结构",
        "## 四、因子信号",
        "## 五、趋势阶段",
        "## 六、明日观察清单",
        "## 七、研究边界",
    ):
        assert section in markdown
    assert "未包含未来收益标签" in markdown
    assert "未完成 forward-return 验证" in markdown
    assert "不构成交易指令" in markdown
    assert "backtest" not in markdown.lower()
    assert "cost sensitivity" not in markdown.lower()


def test_build_cf_latest_signal_brief_connects_trend_rule_candidate_context(
    tmp_path: Path,
) -> None:
    core_path, _ = _write_latest_signal_transition_core_quotes(tmp_path)
    candidate_path = _write_trend_rule_candidate_fixture(tmp_path)

    result = build_cf_latest_signal_brief(
        core_quote_path=core_path,
        output_root=tmp_path / "daily",
        run_id="r28_unit_latest",
        trend_rule_candidate_path=candidate_path,
    )

    context = result.summary["trend_rule_context"]
    assert context["previous_phase_code"] == "S1"  # type: ignore[index]
    assert context["current_phase_code"] == "S2"  # type: ignore[index]
    assert context["transition_code"] == "S1_TO_S2"  # type: ignore[index]
    assert context["candidate_status"] == "READY_CANDIDATE"  # type: ignore[index]
    assert context["daily_brief_action"] == "ALLOW_DAILY_EXPLANATION_CANDIDATE"  # type: ignore[index]
    assert context["selected_horizon"] == 10  # type: ignore[index]
    assert result.to_summary()["trend_rule_candidate_path"] == str(candidate_path)

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["trend_rule_context"]["transition_code"] == "S1_TO_S2"
    assert payload["summary"]["trend_rule_context"]["candidate_status"] == "READY_CANDIDATE"

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "历史候选解释" in markdown
    assert "S1_TO_S2" in markdown
    assert "R27 候选只用于解释，不构成交易指令" in markdown
    assert "forward_return_" not in markdown
    assert "backtest" not in markdown.lower()


def test_build_cf_latest_signal_brief_connects_signal_matrix_context(
    tmp_path: Path,
) -> None:
    core_path, trade_dates = _write_latest_signal_core_quotes(tmp_path)
    matrix = build_cf_signal_matrix(
        start=trade_dates[0],
        end=trade_dates[-1],
        horizons=(1, 5, 20),
        core_quote_path=core_path,
        output_dir=tmp_path / "matrix",
        report_output_dir=tmp_path / "matrix_reports",
        run_id="r35_for_r38",
    )

    result = build_cf_latest_signal_brief(
        core_quote_path=core_path,
        output_root=tmp_path / "daily",
        run_id="r38_unit_latest",
        signal_matrix_path=matrix.latest_snapshot_json_path,
    )

    context = result.summary["signal_matrix_context"]
    assert context["status"] == "PROVIDED"  # type: ignore[index]
    assert context["primary_horizon"] == 20  # type: ignore[index]
    assert len(context["rows"]) == 3  # type: ignore[index]
    assert result.to_summary()["signal_matrix_path"] == str(matrix.latest_snapshot_json_path)

    payload_text = result.json_path.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    assert payload["summary"]["signal_matrix_context"]["status"] == "PROVIDED"
    assert "forward_return_h" not in payload_text

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "## 六、多周期信号矩阵" in markdown
    assert "主观察 horizon" in markdown
    assert "R35 矩阵只使用 T 日及以前可观察数据" in markdown
    assert "forward_return_" not in markdown


def test_build_cf_latest_signal_brief_connects_threshold_research_context(
    tmp_path: Path,
) -> None:
    core_path, trade_dates = _write_latest_signal_core_quotes(tmp_path)
    matrix = build_cf_signal_matrix(
        start=trade_dates[0],
        end=trade_dates[-1],
        horizons=(1, 5, 20),
        core_quote_path=core_path,
        output_dir=tmp_path / "matrix",
        report_output_dir=tmp_path / "matrix_reports",
        run_id="r35_for_r39",
    )
    threshold_path = _write_signal_threshold_weighting_fixture(tmp_path)

    result = build_cf_latest_signal_brief(
        core_quote_path=core_path,
        output_root=tmp_path / "daily",
        run_id="r39_unit_latest",
        signal_matrix_path=matrix.latest_snapshot_json_path,
        signal_threshold_research_path=threshold_path,
    )

    context = result.summary["signal_threshold_context"]
    assert context["status"] == "PROVIDED"  # type: ignore[index]
    assert context["primary_candidate"]["scheme_id"] == "confidence_ge_70"  # type: ignore[index]
    assert result.to_summary()["signal_threshold_research_path"] == str(threshold_path)

    payload_text = result.json_path.read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    assert payload["summary"]["signal_threshold_context"]["status"] == "PROVIDED"
    assert "R37 候选显示" in payload["summary"]["signal_threshold_context"]["explanation_cn"]
    assert "forward_return_h" not in payload_text

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "## 七、阈值与权重候选" in markdown
    assert "置信度 >=70" in markdown
    assert "R37 候选只用于历史解释和人工复核" in markdown


def test_build_cf_latest_signal_brief_shows_alternate_threshold_horizons(
    tmp_path: Path,
) -> None:
    core_path, trade_dates = _write_latest_signal_core_quotes(tmp_path)
    matrix = build_cf_signal_matrix(
        start=trade_dates[0],
        end=trade_dates[-1],
        horizons=(1, 5, 10, 20),
        core_quote_path=core_path,
        output_dir=tmp_path / "matrix",
        report_output_dir=tmp_path / "matrix_reports",
        run_id="r35_for_r40",
    )
    threshold_path = _write_signal_threshold_alternate_only_fixture(tmp_path)

    result = build_cf_latest_signal_brief(
        core_quote_path=core_path,
        output_root=tmp_path / "daily",
        run_id="r40_unit_latest",
        signal_matrix_path=matrix.latest_snapshot_json_path,
        signal_threshold_research_path=threshold_path,
    )

    context = result.summary["signal_threshold_context"]
    assert context["primary_horizon"] == 20  # type: ignore[index]
    assert context["horizon_alignment_status"] == "ALTERNATE_ONLY"  # type: ignore[index]
    assert context["matched_candidates"] == []  # type: ignore[index]
    alternate = context["alternate_candidates"]  # type: ignore[index]
    assert alternate[0]["horizon"] == 10
    assert alternate[0]["scheme_id"] == "confidence_ge_70"

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "非主周期参考候选" in markdown
    assert "不能替代主周期确认" in markdown
    assert "10 | 置信度 >=70" in markdown

    warning_text = result.warning_csv_path.read_text(encoding="utf-8")
    assert "R40_THRESHOLD_ALTERNATE_HORIZON_REFERENCE" in warning_text


def test_build_cf_latest_signal_brief_rejects_daily_validation_as_threshold_context(
    tmp_path: Path,
) -> None:
    core_path, trade_dates = _write_latest_signal_core_quotes(tmp_path)
    matrix = build_cf_signal_matrix(
        start=trade_dates[0],
        end=trade_dates[-1],
        horizons=(1, 5, 20),
        core_quote_path=core_path,
        output_dir=tmp_path / "matrix",
        report_output_dir=tmp_path / "matrix_reports",
        run_id="r35_for_r39_reject",
    )
    bad_path = tmp_path / "validation_daily.parquet"
    pd.DataFrame(
        [
            {
                "trade_date": trade_dates[-1],
                "horizon": 20,
                "direction": "long",
                "forward_return": 0.01,
                "forward_label_available": True,
            }
        ]
    ).to_parquet(bad_path, index=False)

    with pytest.raises(ResearchWorkbenchError, match="forbidden validation columns"):
        build_cf_latest_signal_brief(
            core_quote_path=core_path,
            output_root=tmp_path / "daily",
            run_id="r39_unit_reject_validation",
            signal_matrix_path=matrix.latest_snapshot_json_path,
            signal_threshold_research_path=bad_path,
        )


def test_build_cf_latest_signal_brief_rejects_forward_return_matrix_input(
    tmp_path: Path,
) -> None:
    core_path, trade_dates = _write_latest_signal_core_quotes(tmp_path)
    bad_path = tmp_path / "bad_signal_matrix.parquet"
    pd.DataFrame(
        [
            {
                "trade_date": trade_dates[-1],
                "horizon": 1,
                "direction": "long",
                "confidence_score": 60,
                "confidence": "medium",
                "trend_phase": "S2",
                "evidence_level": "moderate",
                "action_type": "验证",
                "warning_flags": "",
                "forward_return": 0.01,
            }
        ]
    ).to_parquet(bad_path, index=False)

    with pytest.raises(ResearchWorkbenchError, match="must not contain forward_return"):
        build_cf_latest_signal_brief(
            core_quote_path=core_path,
            output_root=tmp_path / "daily",
            run_id="r38_unit_reject_forward",
            signal_matrix_path=bad_path,
        )


def test_build_cf_latest_signal_brief_accepts_explicit_date(tmp_path: Path) -> None:
    core_path, trade_dates = _write_latest_signal_core_quotes(tmp_path)

    result = build_cf_latest_signal_brief(
        trade_date=trade_dates[-2],
        core_quote_path=core_path,
        output_root=tmp_path / "daily",
        run_id="r23_unit_explicit",
    )

    assert result.trade_date == trade_dates[-2]
    assert result.data_asof == trade_dates[-2]
    assert result.markdown_path.parent == tmp_path / "daily" / "CF" / "2024-02-02"


def test_build_cf_latest_signal_brief_rejects_missing_date(tmp_path: Path) -> None:
    core_path, _ = _write_latest_signal_core_quotes(tmp_path)

    with pytest.raises(ResearchWorkbenchError, match="no CF core rows for 2024-12-31"):
        build_cf_latest_signal_brief(
            trade_date=date(2024, 12, 31),
            core_quote_path=core_path,
            output_root=tmp_path / "daily",
            run_id="r23_unit_missing",
        )


def _write_latest_signal_core_quotes(tmp_path: Path) -> tuple[Path, list[date]]:
    path = tmp_path / "core" / "CF" / "core_quote_daily.parquet"
    path.parent.mkdir(parents=True)
    trade_dates = _business_dates(date(2024, 1, 2), count=25)
    rows: list[dict[str, object]] = []
    for offset, trade_date in enumerate(trade_dates):
        main_settle = 100 + offset
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
                    open_interest=10_000 + offset * 100,
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


def _write_latest_signal_transition_core_quotes(tmp_path: Path) -> tuple[Path, list[date]]:
    path = tmp_path / "core_transition" / "CF" / "core_quote_daily.parquet"
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


def _write_signal_threshold_weighting_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "signal_threshold" / "weighting.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "scheme_id": "confidence_ge_70",
                "scheme_label_cn": "置信度 >=70",
                "horizon": 20,
                "active_row_count": 18,
                "total_row_count": 60,
                "coverage_rate": 0.30,
                "observation_count": 18,
                "mean_forward_return": 0.012,
                "median_forward_return": 0.01,
                "directional_hit_rate": 0.67,
                "candidate_status": "READY_CANDIDATE",
                "threshold_rule_version": "R37_signal_threshold_weight_research_v1",
            },
            {
                "scheme_id": "matrix_all",
                "scheme_label_cn": "矩阵全样本",
                "horizon": 20,
                "active_row_count": 60,
                "total_row_count": 60,
                "coverage_rate": 1.0,
                "observation_count": 60,
                "mean_forward_return": 0.004,
                "median_forward_return": 0.002,
                "directional_hit_rate": 0.53,
                "candidate_status": "WEAK_OR_UNSTABLE",
                "threshold_rule_version": "R37_signal_threshold_weight_research_v1",
            },
        ]
    ).to_parquet(path, index=False)
    return path


def _write_signal_threshold_alternate_only_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "signal_threshold_alternate" / "weighting.parquet"
    path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "scheme_id": "matrix_all",
                "scheme_label_cn": "矩阵全样本",
                "horizon": 20,
                "active_row_count": 60,
                "total_row_count": 60,
                "coverage_rate": 1.0,
                "observation_count": 60,
                "mean_forward_return": -0.001,
                "median_forward_return": 0.0,
                "directional_hit_rate": 0.49,
                "candidate_status": "WEAK_OR_UNSTABLE",
                "threshold_rule_version": "R37_signal_threshold_weight_research_v1",
            },
            {
                "scheme_id": "confidence_ge_70",
                "scheme_label_cn": "置信度 >=70",
                "horizon": 10,
                "active_row_count": 24,
                "total_row_count": 60,
                "coverage_rate": 0.40,
                "observation_count": 24,
                "mean_forward_return": 0.018,
                "median_forward_return": 0.012,
                "directional_hit_rate": 0.71,
                "candidate_status": "READY_CANDIDATE",
                "threshold_rule_version": "R37_signal_threshold_weight_research_v1",
            },
            {
                "scheme_id": "confidence_ge_55",
                "scheme_label_cn": "置信度 >=55",
                "horizon": 5,
                "active_row_count": 28,
                "total_row_count": 60,
                "coverage_rate": 0.47,
                "observation_count": 28,
                "mean_forward_return": 0.009,
                "median_forward_return": 0.006,
                "directional_hit_rate": 0.62,
                "candidate_status": "WATCH_CANDIDATE",
                "threshold_rule_version": "R37_signal_threshold_weight_research_v1",
            },
        ]
    ).to_parquet(path, index=False)
    return path


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
        "source_snapshot_id": f"r23_fixture_{contract_code}_{trade_date:%Y%m%d}",
        "exchange": "CZCE",
        "product_code": "CF",
        "contract_code": contract_code,
        "trade_date": trade_date,
        "settle": settle,
        "volume": volume,
        "open_interest": open_interest,
    }
