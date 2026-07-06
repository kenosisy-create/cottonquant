from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from cotton_factor.cli.main import app
from cotton_factor.research_workbench import build_cf_publish_pack


def test_build_cf_publish_pack_writes_charts_and_publish_files(tmp_path: Path) -> None:
    paths = _write_r45_inputs(tmp_path)

    result = build_cf_publish_pack(
        latest_signal_json_path=paths["latest"],
        validated_brief_path=paths["validated"],
        core_quote_path=paths["core"],
        signal_matrix_path=paths["matrix"],
        historical_evidence_decay_path=paths["decay"],
        event_summary_path=paths["events"],
        output_root=tmp_path / "daily",
        run_id="r45_unit",
        price_lookback=5,
    )

    assert result.output_dir == tmp_path / "daily" / "CF" / "2026-07-01"
    assert len(result.chart_paths) == 6
    for chart_path in result.chart_paths:
        assert chart_path.exists()
        assert chart_path.stat().st_size > 100
        assert chart_path.read_text(encoding="utf-8").startswith("<svg")

    assert result.wechat_article_path.exists()
    assert result.wechat_summary_path.exists()
    assert result.data_asof_json_path.exists()
    assert result.chart_pack_zip_path.exists()
    assert result.manifest_path.exists()

    article = result.wechat_article_path.read_text(encoding="utf-8")
    assert "数据截至" in article
    assert "forward-return" in article
    assert "基本面事件解释链" in article
    assert "R55 历史事件明细" in article
    assert "不构成交易指令" in article
    assert "人工复核" in article

    summary = result.wechat_summary_path.read_text(encoding="utf-8")
    assert "R56 已覆盖 2/2 条 R55 事件上下文" in summary

    data_asof = json.loads(result.data_asof_json_path.read_text(encoding="utf-8"))
    assert data_asof["data_asof"] == "2026-07-01"
    assert data_asof["contains_historical_forward_return_validation"] is True
    assert data_asof["latest_signal_only_contains_forward_return_validation"] is False
    assert data_asof["validated_event_context"]["r56_event_context_connected"] is True
    assert data_asof["validated_event_context"]["r55_event_count"] == 2

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["report_type"] == "publish_pack"
    assert manifest["chart_pack_zip_path"] == str(result.chart_pack_zip_path)
    assert manifest["validated_event_context"]["r55_context_available_count"] == 2

    with zipfile.ZipFile(result.chart_pack_zip_path) as archive:
        names = set(archive.namelist())
    assert "charts/price_oi_main.svg" in names
    assert "charts/term_structure.svg" in names
    assert "charts/signal_matrix_heatmap.svg" in names
    assert "charts/factor_hit_rate.svg" in names
    assert "charts/trend_phase_timeline.svg" in names
    assert "charts/event_distribution.svg" in names
    assert "publish/wechat_article.md" in names
    assert "publish/data_asof.json" in names


def test_cli_build_cf_publish_pack(tmp_path: Path) -> None:
    paths = _write_r45_inputs(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "research",
            "build-cf-publish-pack",
            "--latest-signal-json-path",
            str(paths["latest"]),
            "--validated-brief-path",
            str(paths["validated"]),
            "--core-quote-path",
            str(paths["core"]),
            "--signal-matrix-path",
            str(paths["matrix"]),
            "--historical-evidence-decay-path",
            str(paths["decay"]),
            "--event-summary-path",
            str(paths["events"]),
            "--output-root",
            str(tmp_path / "daily"),
            "--run-id",
            "r45_cli",
            "--price-lookback",
            "5",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["run_id"] == "r45_cli"
    assert Path(output["wechat_article_path"]).exists()
    assert Path(output["chart_pack_zip_path"]).exists()


def _write_r45_inputs(tmp_path: Path) -> dict[str, Path]:
    latest_path = tmp_path / "daily" / "CF" / "2026-07-01" / "latest_signal_brief.json"
    validated_path = tmp_path / "daily" / "CF" / "2026-07-01" / "validated_research_brief.md"
    core_path = tmp_path / "core" / "core_quote_daily.parquet"
    matrix_path = tmp_path / "matrix" / "signal_matrix.parquet"
    decay_path = tmp_path / "historical" / "decay.parquet"
    events_path = tmp_path / "events" / "summary.parquet"
    for path in (latest_path, validated_path, core_path, matrix_path, decay_path, events_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    latest_path.write_text(
        json.dumps(
            {
                "data_asof": "2026-07-01",
                "main_contract": "CF609",
                "signal_direction": "long",
                "trend_phase": {
                    "phase_code": "S3",
                    "phase_label": "衰竭观察",
                },
                "signal_matrix_context": {
                    "status": "PROVIDED",
                    "rows": [
                        {"horizon": 1, "direction": "long", "confidence": "high"},
                        {"horizon": 3, "direction": "long", "confidence": "medium"},
                        {"horizon": 5, "direction": "neutral", "confidence": "low"},
                        {"horizon": 10, "direction": "short", "confidence": "low"},
                    ],
                },
                "summary": {
                    "research_boundary": {
                        "forward_return_validation": "未完成 forward-return 验证"
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    validated_path.write_text(
        "\n".join(
            [
                "# CF 验证型研究报告 - 2026-07-01",
                "",
                "## 历史窗口证据",
                "",
                "forward return 只作为历史后验验证标签。",
                "",
                "## 十、基本面事件解释链",
                "",
                "- R55 事件明细数：`2`",
                "- 已匹配事件日前基本面上下文：`2`",
                "- R56 规则版本：`R56_validated_brief_event_context_v1`",
                "- R56 基本面事件解释只作为历史复盘上下文，不构成自动交易信号。",
                "",
                "## 研究边界",
                "",
                "本报告不构成交易指令，HUMAN_REVIEW_REQUIRED。",
                "",
            ]
        ),
        encoding="utf-8",
    )

    quote_rows = []
    for index, trade_date in enumerate(pd.date_range("2026-06-25", "2026-07-01", freq="D")):
        quote_rows.append(
            {
                "trade_date": trade_date.date(),
                "contract_code": "CF609",
                "settle": 15000 + index * 20,
                "open_interest": 100000 + index * 1000,
                "volume": 50000 + index * 100,
            }
        )
        quote_rows.append(
            {
                "trade_date": trade_date.date(),
                "contract_code": "CF701",
                "settle": 15100 + index * 10,
                "open_interest": 20000 + index * 100,
                "volume": 15000 + index * 100,
            }
        )
    pd.DataFrame(quote_rows).to_parquet(core_path, index=False)

    pd.DataFrame(
        [
            {"trade_date": "2026-06-25", "horizon": 20, "trend_phase": "S1"},
            {"trade_date": "2026-06-26", "horizon": 20, "trend_phase": "S2"},
            {"trade_date": "2026-06-27", "horizon": 20, "trend_phase": "S2"},
            {"trade_date": "2026-06-28", "horizon": 20, "trend_phase": "S3"},
            {"trade_date": "2026-06-29", "horizon": 20, "trend_phase": "S4"},
            {"trade_date": "2026-07-01", "horizon": 20, "trend_phase": "S3"},
        ]
    ).to_parquet(matrix_path, index=False)
    pd.DataFrame(
        [
            {"horizon": 1, "directional_hit_rate": 0.52},
            {"horizon": 3, "directional_hit_rate": 0.54},
            {"horizon": 5, "directional_hit_rate": 0.49},
            {"horizon": 10, "directional_hit_rate": 0.58},
            {"horizon": 20, "directional_hit_rate": 0.47},
        ]
    ).to_parquet(decay_path, index=False)
    pd.DataFrame(
        [
            {"event_type": "趋势中继", "event_count": 20},
            {"event_type": "终点确认", "event_count": 12},
            {"event_type": "主力切换", "event_count": 6},
        ]
    ).to_parquet(events_path, index=False)
    return {
        "latest": latest_path,
        "validated": validated_path,
        "core": core_path,
        "matrix": matrix_path,
        "decay": decay_path,
        "events": events_path,
    }
