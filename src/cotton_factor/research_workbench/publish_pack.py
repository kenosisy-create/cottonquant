"""R45 publish pack for CF validated research outputs."""

from __future__ import annotations

import html
import json
import re
import uuid
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, project_root
from cotton_factor.common.time import utc_now
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME

PRODUCT_CODE = "CF"
PUBLISH_PACK_VERSION = "R45_cf_publish_pack_v1"
PUBLISH_PACK_EVENT_CONTEXT_VERSION = "R57_publish_pack_event_context_v1"
DEFAULT_PRICE_LOOKBACK = 120
HUMAN_REVIEW_REQUIRED = (
    "publish_wording",
    "historical_evidence_interpretation",
    "historical_event_interpretation",
    "factor_thresholds",
    "chart_readability",
)


@dataclass(frozen=True)
class ResearchPublishPackResult:
    """Result of building the R45 publish pack."""

    product_code: str
    run_id: str
    data_asof: date
    output_dir: Path
    chart_paths: tuple[Path, ...]
    wechat_article_path: Path
    wechat_summary_path: Path
    data_asof_json_path: Path
    chart_pack_zip_path: Path
    manifest_path: Path
    latest_signal_json_path: Path
    validated_brief_path: Path
    core_quote_path: Path
    validated_event_context: dict[str, object]
    human_review_required: tuple[str, ...]

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI summary."""
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "data_asof": self.data_asof.isoformat(),
            "output_dir": str(self.output_dir),
            "chart_paths": [str(path) for path in self.chart_paths],
            "wechat_article_path": str(self.wechat_article_path),
            "wechat_summary_path": str(self.wechat_summary_path),
            "data_asof_json_path": str(self.data_asof_json_path),
            "chart_pack_zip_path": str(self.chart_pack_zip_path),
            "manifest_path": str(self.manifest_path),
            "latest_signal_json_path": str(self.latest_signal_json_path),
            "validated_brief_path": str(self.validated_brief_path),
            "core_quote_path": str(self.core_quote_path),
            "validated_event_context": self.validated_event_context,
            "human_review_required": list(self.human_review_required),
        }


def build_cf_publish_pack(
    *,
    latest_signal_json_path: Path | None = None,
    validated_brief_path: Path | None = None,
    core_quote_path: Path | None = None,
    signal_matrix_path: Path | None = None,
    historical_evidence_decay_path: Path | None = None,
    event_summary_path: Path | None = None,
    output_root: Path | None = None,
    run_id: str | None = None,
    price_lookback: int = DEFAULT_PRICE_LOOKBACK,
) -> ResearchPublishPackResult:
    """Build R45 charts and WeChat-ready publish materials."""
    # 发布包只整合已落地的研究产物，不直接读取交易所原始文件，避免绕开 raw/core 边界。
    latest_path = latest_signal_json_path or _default_latest_signal_json_path()
    latest = _load_latest_signal(latest_path)
    data_asof = _parse_date(str(latest["data_asof"]))
    brief_path = validated_brief_path or _default_validated_brief_path(data_asof=data_asof)
    quote_path = core_quote_path or data_dir() / "core" / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
    matrix_path = signal_matrix_path or _default_signal_matrix_path()
    decay_path = historical_evidence_decay_path or _default_historical_decay_path()
    event_path = event_summary_path or _default_event_summary_path()
    quotes = _load_core_quotes(quote_path)
    matrix = _load_signal_matrix(matrix_path)
    decay = _load_table(decay_path, required={"horizon", "directional_hit_rate"})
    event_summary = _load_table(event_path, required={"event_type", "event_count"})
    validated_markdown = _load_validated_brief(brief_path)
    validated_event_context = _validated_brief_publish_context(validated_markdown)
    publish_run_id = run_id or _default_run_id(data_asof=data_asof)
    output_dir = (
        (output_root or project_root() / "runs" / "daily")
        / PRODUCT_CODE
        / data_asof.isoformat()
    )
    charts_dir = output_dir / "charts"
    publish_dir = output_dir / "publish"
    charts_dir.mkdir(parents=True, exist_ok=True)
    publish_dir.mkdir(parents=True, exist_ok=True)

    main_contract = str(latest.get("main_contract") or _latest_main_contract(quotes, data_asof))
    # 图表只使用 T 日及以前可观察信息；历史 forward-return 只在验证型摘要中作为后验标签出现。
    chart_paths = (
        _write_price_oi_chart(
            quotes=quotes,
            data_asof=data_asof,
            main_contract=main_contract,
            output_path=charts_dir / "price_oi_main.svg",
            lookback=price_lookback,
        ),
        _write_term_structure_chart(
            quotes=quotes,
            data_asof=data_asof,
            main_contract=main_contract,
            output_path=charts_dir / "term_structure.svg",
        ),
        _write_signal_matrix_chart(
            latest=latest,
            output_path=charts_dir / "signal_matrix_heatmap.svg",
        ),
        _write_factor_hit_rate_chart(
            decay=decay,
            output_path=charts_dir / "factor_hit_rate.svg",
        ),
        _write_trend_phase_chart(
            matrix=matrix,
            output_path=charts_dir / "trend_phase_timeline.svg",
            lookback=price_lookback,
        ),
        _write_event_distribution_chart(
            event_summary=event_summary,
            output_path=charts_dir / "event_distribution.svg",
        ),
    )
    article = _render_wechat_article(
        latest=latest,
        validated_markdown=validated_markdown,
        validated_event_context=validated_event_context,
        chart_paths=chart_paths,
        output_dir=output_dir,
    )
    summary_text = _render_wechat_summary(
        latest=latest,
        decay=decay,
        event_summary=event_summary,
        validated_event_context=validated_event_context,
    )
    wechat_article_path = publish_dir / "wechat_article.md"
    wechat_summary_path = publish_dir / "wechat_summary.txt"
    data_asof_json_path = publish_dir / "data_asof.json"
    chart_pack_zip_path = publish_dir / "chart_pack.zip"
    manifest_path = publish_dir / "manifest.json"
    wechat_article_path.write_text(article, encoding="utf-8")
    wechat_summary_path.write_text(summary_text, encoding="utf-8")
    _write_data_asof_json(
        path=data_asof_json_path,
        result_context={
            "run_id": publish_run_id,
            "data_asof": data_asof.isoformat(),
            "latest_signal_json_path": str(latest_path),
            "validated_brief_path": str(brief_path),
            "contains_historical_forward_return_validation": True,
            "latest_signal_only_contains_forward_return_validation": False,
            "validated_event_context": validated_event_context,
            "human_review_required": list(HUMAN_REVIEW_REQUIRED),
        },
    )
    _write_chart_pack_zip(
        zip_path=chart_pack_zip_path,
        chart_paths=chart_paths,
        extra_paths=(wechat_article_path, wechat_summary_path, data_asof_json_path),
        root=output_dir,
    )
    result = ResearchPublishPackResult(
        product_code=PRODUCT_CODE,
        run_id=publish_run_id,
        data_asof=data_asof,
        output_dir=output_dir,
        chart_paths=chart_paths,
        wechat_article_path=wechat_article_path,
        wechat_summary_path=wechat_summary_path,
        data_asof_json_path=data_asof_json_path,
        chart_pack_zip_path=chart_pack_zip_path,
        manifest_path=manifest_path,
        latest_signal_json_path=latest_path,
        validated_brief_path=brief_path,
        core_quote_path=quote_path,
        validated_event_context=validated_event_context,
        human_review_required=HUMAN_REVIEW_REQUIRED,
    )
    _write_manifest(
        result=result,
        signal_matrix_path=matrix_path,
        decay_path=decay_path,
        event_path=event_path,
    )
    return result


def _load_latest_signal(path: Path) -> dict[str, object]:
    if not path.exists():
        raise ResearchWorkbenchError(f"latest signal JSON not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    # latest signal-only 输入必须保持无未来收益标签，发布层不能把观察报告升级成交易结论。
    if _contains_forward_return_label(payload):
        raise ResearchWorkbenchError("publish pack latest signal input must not contain labels")
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise ResearchWorkbenchError("latest signal JSON missing summary object")
    data_asof = payload.get("data_asof") or summary.get("data_status", {}).get("data_asof")
    if data_asof is None:
        raise ResearchWorkbenchError("latest signal JSON missing data_asof")
    return {
        "data_asof": data_asof,
        "main_contract": payload.get("main_contract"),
        "signal_direction": payload.get("signal_direction"),
        "trend_phase": payload.get("trend_phase") or summary.get("trend_phase"),
        "signal_matrix_context": payload.get("signal_matrix_context")
        or summary.get("signal_matrix_context"),
        "signal_threshold_context": payload.get("signal_threshold_context")
        or summary.get("signal_threshold_context"),
    }


def _load_core_quotes(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"core quote table not found: {path}")
    frame = pd.read_parquet(path)
    required = {"trade_date", "contract_code", "settle", "open_interest"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"core quote table missing columns: {missing}")
    working = frame.copy()
    working["trade_date"] = pd.to_datetime(working["trade_date"]).dt.date
    working["settle"] = pd.to_numeric(working["settle"], errors="coerce")
    working["open_interest"] = pd.to_numeric(working["open_interest"], errors="coerce")
    if "volume" in working.columns:
        working["volume"] = pd.to_numeric(working["volume"], errors="coerce")
    return working.dropna(subset=["trade_date", "contract_code"]).reset_index(drop=True)


def _load_signal_matrix(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"signal matrix table not found: {path}")
    frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
    required = {"trade_date", "horizon", "trend_phase"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"signal matrix table missing columns: {missing}")
    working = frame.copy()
    working["trade_date"] = pd.to_datetime(working["trade_date"]).dt.date
    working["horizon"] = pd.to_numeric(working["horizon"], errors="coerce")
    return working.dropna(subset=["trade_date", "horizon"]).reset_index(drop=True)


def _load_table(path: Path, *, required: set[str]) -> pd.DataFrame:
    if not path.exists():
        raise ResearchWorkbenchError(f"publish pack input table not found: {path}")
    frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"publish pack input table missing columns: {missing}")
    return frame.copy()


def _load_validated_brief(path: Path) -> str:
    if not path.exists():
        raise ResearchWorkbenchError(f"validated research brief not found: {path}")
    text = path.read_text(encoding="utf-8")
    if "不构成交易指令" not in text:
        raise ResearchWorkbenchError("validated research brief missing trading boundary")
    return text


def _validated_brief_publish_context(validated_markdown: str) -> dict[str, object]:
    """从 R56 验证型报告中提取可发布的事件基本面解释链状态。"""
    connected = "基本面事件解释链" in validated_markdown
    event_count = _extract_markdown_count(validated_markdown, "R55 事件明细数")
    context_count = _extract_markdown_count(validated_markdown, "已匹配事件日前基本面上下文")
    return {
        "rule_version": PUBLISH_PACK_EVENT_CONTEXT_VERSION,
        "r56_event_context_connected": connected,
        "r55_event_count": event_count,
        "r55_context_available_count": context_count,
        "publish_boundary": (
            "R56 基本面事件解释链只作为历史复盘上下文，不构成交易指令"
            if connected
            else "未接入 R56 基本面事件解释链"
        ),
    }


def _extract_markdown_count(markdown: str, label: str) -> int | None:
    pattern = rf"{re.escape(label)}：`(\d+)`"
    match = re.search(pattern, markdown)
    if match is None:
        return None
    return int(match.group(1))


def _write_price_oi_chart(
    *,
    quotes: pd.DataFrame,
    data_asof: date,
    main_contract: str,
    output_path: Path,
    lookback: int,
) -> Path:
    series = quotes.loc[quotes["contract_code"].astype(str).eq(main_contract)].copy()
    series = series.loc[series["trade_date"] <= data_asof].sort_values("trade_date").tail(lookback)
    if series.empty:
        raise ResearchWorkbenchError(f"no quote rows for main contract {main_contract}")
    price = series["settle"].astype(float).tolist()
    oi = series["open_interest"].astype(float).tolist()
    labels = [item.isoformat()[5:] for item in series["trade_date"]]
    svg = _line_dual_axis_svg(
        title=f"{main_contract} 主力价格与持仓",
        labels=labels,
        left_values=price,
        right_values=oi,
        left_label="结算价",
        right_label="持仓量",
    )
    return _write_svg(output_path, svg)


def _write_term_structure_chart(
    *,
    quotes: pd.DataFrame,
    data_asof: date,
    main_contract: str,
    output_path: Path,
) -> Path:
    latest = quotes.loc[quotes["trade_date"].eq(data_asof)].copy()
    if latest.empty:
        raise ResearchWorkbenchError(f"no quote rows for {data_asof.isoformat()}")
    latest = latest.sort_values("contract_code")
    labels = latest["contract_code"].astype(str).tolist()
    values = latest["settle"].astype(float).tolist()
    colors = ["#2563eb" if label == main_contract else "#64748b" for label in labels]
    svg = _bar_svg(title="期限结构", labels=labels, values=values, colors=colors, value_suffix="")
    return _write_svg(output_path, svg)


def _write_signal_matrix_chart(*, latest: dict[str, object], output_path: Path) -> Path:
    context = latest.get("signal_matrix_context")
    if not isinstance(context, dict):
        raise ResearchWorkbenchError("latest signal JSON missing signal matrix context")
    rows = context.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ResearchWorkbenchError("latest signal matrix context has no rows")
    labels = [f"{row.get('horizon')}D" for row in rows if isinstance(row, dict)]
    values = [
        _score_for_signal(row.get("direction"), row.get("confidence"))
        for row in rows
        if isinstance(row, dict)
    ]
    svg = _heatmap_row_svg(title="多周期信号矩阵", labels=labels, values=values)
    return _write_svg(output_path, svg)


def _write_factor_hit_rate_chart(*, decay: pd.DataFrame, output_path: Path) -> Path:
    working = decay.copy()
    working["horizon"] = pd.to_numeric(working["horizon"], errors="coerce")
    working["directional_hit_rate"] = pd.to_numeric(
        working["directional_hit_rate"],
        errors="coerce",
    )
    working = working.dropna(subset=["horizon", "directional_hit_rate"]).sort_values("horizon")
    svg = _bar_svg(
        title="历史方向命中率",
        labels=[f"{int(row.horizon)}D" for row in working.itertuples()],
        values=[float(row.directional_hit_rate) * 100 for row in working.itertuples()],
        colors=["#0f766e" for _ in range(len(working))],
        value_suffix="%",
        baseline=50.0,
    )
    return _write_svg(output_path, svg)


def _write_trend_phase_chart(
    *,
    matrix: pd.DataFrame,
    output_path: Path,
    lookback: int,
) -> Path:
    working = matrix.loc[matrix["horizon"].eq(20)].copy()
    if working.empty:
        working = matrix.copy()
    working = working.sort_values("trade_date").tail(lookback)
    labels = [item.isoformat()[5:] for item in working["trade_date"]]
    values = [_phase_score(value) for value in working["trend_phase"]]
    svg = _step_svg(title="趋势阶段时间线", labels=labels, values=values)
    return _write_svg(output_path, svg)


def _write_event_distribution_chart(*, event_summary: pd.DataFrame, output_path: Path) -> Path:
    working = event_summary.copy()
    working["event_count"] = pd.to_numeric(working["event_count"], errors="coerce")
    counts = working.groupby("event_type", as_index=False)["event_count"].max()
    counts = counts.sort_values("event_count", ascending=False)
    svg = _bar_svg(
        title="历史事件分布",
        labels=counts["event_type"].astype(str).tolist(),
        values=counts["event_count"].astype(float).tolist(),
        colors=["#7c3aed" for _ in range(len(counts))],
        value_suffix="",
    )
    return _write_svg(output_path, svg)


def _render_wechat_article(
    *,
    latest: dict[str, object],
    validated_markdown: str,
    validated_event_context: dict[str, object],
    chart_paths: tuple[Path, ...],
    output_dir: Path,
) -> str:
    data_asof = str(latest["data_asof"])
    trend = latest.get("trend_phase") if isinstance(latest.get("trend_phase"), dict) else {}
    chart_lines = [
        f"![{path.stem}]({_relative_path(path=path, root=output_dir)})" for path in chart_paths
    ]
    event_context_lines = _wechat_event_context_lines(validated_event_context)
    evidence_excerpt = "\n".join(validated_markdown.splitlines()[0:80])
    return "\n".join(
        [
            f"# 郑棉 CF 日度研究：{data_asof} 结构观察与历史证据",
            "",
            f"- 数据截至：`{data_asof}`",
            "- 研究品种：`CF`",
            "- 报告类型：`validated publish pack`",
            "- latest signal-only 是否包含 forward-return 验证：`否`",
            "- 历史证据是否包含 forward-return 后验验证：`是，仅用于历史验证`",
            "- R56 基本面事件解释链："
            + (
                "`已接入`"
                if validated_event_context.get("r56_event_context_connected")
                else "`未接入`"
            ),
            "- 是否存在人工复核项：`是`",
            "- 研究边界：`不构成交易指令`",
            "",
            "## 摘要",
            "",
            f"当前主力合约为 `{latest.get('main_contract')}`，最新方向为 "
            f"`{latest.get('signal_direction')}`，趋势阶段为 "
            f"`{trend.get('phase_code')}` {trend.get('phase_label')}。",
            "",
            "## 图表包",
            "",
            *chart_lines,
            "",
            "## 基本面事件解释链",
            "",
            *event_context_lines,
            "",
            "## 验证型研究摘要",
            "",
            evidence_excerpt,
            "",
            "## 研究边界",
            "",
            "- 图表和文字用于研究复盘与发布素材准备。",
            "- 历史 forward-return 只作为后验验证标签。",
            "- 本文不构成交易指令。",
            "",
        ]
    )


def _render_wechat_summary(
    *,
    latest: dict[str, object],
    decay: pd.DataFrame,
    event_summary: pd.DataFrame,
    validated_event_context: dict[str, object],
) -> str:
    data_asof = str(latest["data_asof"])
    best = decay.sort_values("directional_hit_rate", ascending=False).head(1)
    best_text = "历史证据不足"
    if not best.empty:
        row = best.iloc[0]
        best_text = f"{int(row['horizon'])}D 命中率约 {_fmt_percent(row['directional_hit_rate'])}"
    top_event = event_summary.sort_values("event_count", ascending=False).head(1)
    event_text = "事件样本不足"
    if not top_event.empty:
        row = top_event.iloc[0]
        event_text = f"{row['event_type']} 样本 {int(row['event_count'])}"
    event_context_text = "R56 基本面事件解释链未接入"
    if validated_event_context.get("r56_event_context_connected"):
        event_count = validated_event_context.get("r55_event_count")
        context_count = validated_event_context.get("r55_context_available_count")
        event_context_text = f"R56 已覆盖 {context_count}/{event_count} 条 R55 事件上下文"
    return (
        f"数据截至 {data_asof}。CF 当前方向 {latest.get('signal_direction')}，"
        f"主力 {latest.get('main_contract')}。历史证据中 {best_text}；"
        f"历史事件中 {event_text}；{event_context_text}。"
        "本摘要仅供研究发布准备，不构成交易指令。\n"
    )


def _wechat_event_context_lines(context: dict[str, object]) -> list[str]:
    if not context.get("r56_event_context_connected"):
        return [
            "- 本次发布包未接入 R56 基本面事件解释链。",
            "- 发布文本仍以最新观察、历史证据和 R42 事件汇总为主。",
        ]
    return [
        f"- R55 历史事件明细：`{context.get('r55_event_count')}` 条。",
        f"- 匹配事件日前基本面上下文：`{context.get('r55_context_available_count')}` 条。",
        "- R56 基本面事件解释链只用于历史复盘与解释，不生成 `fundamental_signal`。",
        "- 该内容不构成交易指令，仍需要 HUMAN_REVIEW_REQUIRED。",
    ]


def _write_data_asof_json(*, path: Path, result_context: dict[str, object]) -> None:
    payload = {
        "report_type": "publish_pack_data_asof",
        "rule_version": PUBLISH_PACK_VERSION,
        "generated_at": utc_now().isoformat(),
        **result_context,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_chart_pack_zip(
    *,
    zip_path: Path,
    chart_paths: tuple[Path, ...],
    extra_paths: tuple[Path, ...],
    root: Path,
) -> None:
    # 压缩包保留相对路径，便于公众号素材目录整体迁移和人工复核。
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in (*chart_paths, *extra_paths):
            archive.write(path, arcname=str(path.relative_to(root)).replace("\\", "/"))


def _write_manifest(
    *,
    result: ResearchPublishPackResult,
    signal_matrix_path: Path,
    decay_path: Path,
    event_path: Path,
) -> None:
    payload = {
        "run_id": result.run_id,
        "product_code": PRODUCT_CODE,
        "report_type": "publish_pack",
        "rule_version": PUBLISH_PACK_VERSION,
        "data_asof": result.data_asof.isoformat(),
        "generated_at": utc_now().isoformat(),
        "latest_signal_json_path": str(result.latest_signal_json_path),
        "validated_brief_path": str(result.validated_brief_path),
        "core_quote_path": str(result.core_quote_path),
        "signal_matrix_path": str(signal_matrix_path),
        "historical_evidence_decay_path": str(decay_path),
        "event_summary_path": str(event_path),
        "validated_event_context": result.validated_event_context,
        "publish_pack_event_context_rule_version": PUBLISH_PACK_EVENT_CONTEXT_VERSION,
        "chart_paths": [str(path) for path in result.chart_paths],
        "wechat_article_path": str(result.wechat_article_path),
        "wechat_summary_path": str(result.wechat_summary_path),
        "data_asof_json_path": str(result.data_asof_json_path),
        "chart_pack_zip_path": str(result.chart_pack_zip_path),
        "human_review_required": list(result.human_review_required),
    }
    result.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _line_dual_axis_svg(
    *,
    title: str,
    labels: list[str],
    left_values: list[float],
    right_values: list[float],
    left_label: str,
    right_label: str,
) -> str:
    width, height = 900, 420
    plot = _plot_box(width=width, height=height)
    x_values = _x_positions(count=len(left_values), plot=plot)
    left_points = _points(x_values=x_values, values=left_values, plot=plot)
    right_points = _points(x_values=x_values, values=right_values, plot=plot)
    bottom_labels = _sparse_labels(labels, x_values, plot["bottom"])
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" \
viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="#ffffff"/>
{_svg_title(title)}
{_svg_axes(plot)}
<polyline fill="none" stroke="#2563eb" stroke-width="3" points="{left_points}"/>
<polyline fill="none" stroke="#f97316" stroke-width="3" points="{right_points}"/>
<text x="70" y="78" font-size="14" fill="#2563eb">{html.escape(left_label)}</text>
<text x="760" y="78" font-size="14" fill="#f97316">{html.escape(right_label)}</text>
{bottom_labels}
</svg>
"""


def _bar_svg(
    *,
    title: str,
    labels: list[str],
    values: list[float],
    colors: list[str],
    value_suffix: str,
    baseline: float | None = None,
) -> str:
    width, height = 900, 420
    plot = _plot_box(width=width, height=height)
    if not labels:
        raise ResearchWorkbenchError(f"chart has no labels: {title}")
    minimum = min(values + ([baseline] if baseline is not None else []))
    maximum = max(values + ([baseline] if baseline is not None else []))
    span = maximum - minimum or 1.0
    bar_width = max(18, int((plot["right"] - plot["left"]) / max(len(labels), 1) * 0.58))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        _svg_title(title),
        _svg_axes(plot),
    ]
    if baseline is not None:
        y = _scale(value=baseline, minimum=minimum, span=span, plot=plot)
        parts.append(
            f'<line x1="{plot["left"]}" x2="{plot["right"]}" y1="{y}" y2="{y}" '
            'stroke="#94a3b8" stroke-dasharray="4 4"/>'
        )
    for index, (label, value) in enumerate(zip(labels, values, strict=False)):
        x = plot["left"] + (index + 0.5) * (plot["right"] - plot["left"]) / len(labels)
        y = _scale(value=value, minimum=minimum, span=span, plot=plot)
        height_value = plot["bottom"] - y
        color = colors[index % len(colors)]
        parts.append(
            f'<rect x="{x - bar_width / 2:.1f}" y="{y:.1f}" width="{bar_width}" '
            f'height="{height_value:.1f}" fill="{color}" rx="3"/>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{y - 7:.1f}" text-anchor="middle" font-size="12" '
            f'fill="#0f172a">{value:.2f}{html.escape(value_suffix)}</text>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{plot["bottom"] + 24}" text-anchor="middle" '
            f'font-size="12" fill="#334155">{html.escape(str(label))}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def _heatmap_row_svg(*, title: str, labels: list[str], values: list[float]) -> str:
    width, height = 900, 240
    cell_width = 110
    start_x = 90
    y = 95
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        _svg_title(title),
    ]
    for index, (label, value) in enumerate(zip(labels, values, strict=False)):
        x = start_x + index * cell_width
        parts.append(
            f'<rect x="{x}" y="{y}" width="92" height="58" fill="{_heat_color(value)}" rx="4"/>'
        )
        parts.append(
            f'<text x="{x + 46}" y="{y + 34}" text-anchor="middle" font-size="16" '
            f'fill="#ffffff">{html.escape(label)}</text>'
        )
    parts.append(
        '<text x="90" y="190" font-size="13" fill="#475569">'
        "蓝色偏多，灰色中性，红色偏空；深浅代表置信度。"
        "</text>"
    )
    parts.append("</svg>")
    return "\n".join(parts)


def _step_svg(*, title: str, labels: list[str], values: list[int]) -> str:
    width, height = 900, 300
    plot = _plot_box(width=width, height=height)
    x_values = _x_positions(count=len(values), plot=plot)
    points = _points(x_values=x_values, values=[float(value) for value in values], plot=plot)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        _svg_title(title),
        _svg_axes(plot),
        f'<polyline fill="none" stroke="#16a34a" stroke-width="3" points="{points}"/>',
        _sparse_labels(labels, x_values, plot["bottom"]),
        '<text x="70" y="85" font-size="13" fill="#475569">S0=0, S1=1, S2=2, S3=3, S4=4</text>',
        "</svg>",
    ]
    return "\n".join(parts)


def _write_svg(path: Path, svg: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")
    return path


def _plot_box(*, width: int, height: int) -> dict[str, int]:
    return {"left": 70, "right": width - 45, "top": 80, "bottom": height - 55}


def _svg_title(title: str) -> str:
    return (
        '<text x="35" y="42" font-size="22" font-weight="700" fill="#0f172a">'
        f"{html.escape(title)}</text>"
    )


def _svg_axes(plot: dict[str, int]) -> str:
    return (
        f'<line x1="{plot["left"]}" y1="{plot["bottom"]}" x2="{plot["right"]}" '
        f'y2="{plot["bottom"]}" stroke="#cbd5e1"/>'
        f'<line x1="{plot["left"]}" y1="{plot["top"]}" x2="{plot["left"]}" '
        f'y2="{plot["bottom"]}" stroke="#cbd5e1"/>'
    )


def _x_positions(*, count: int, plot: dict[str, int]) -> list[float]:
    if count <= 1:
        return [(plot["left"] + plot["right"]) / 2]
    span = plot["right"] - plot["left"]
    return [plot["left"] + index * span / (count - 1) for index in range(count)]


def _points(*, x_values: list[float], values: list[float], plot: dict[str, int]) -> str:
    minimum = min(values)
    maximum = max(values)
    span = maximum - minimum or 1.0
    return " ".join(
        f"{x:.1f},{_scale(value=value, minimum=minimum, span=span, plot=plot):.1f}"
        for x, value in zip(x_values, values, strict=False)
    )


def _scale(*, value: float, minimum: float, span: float, plot: dict[str, int]) -> float:
    return plot["bottom"] - ((value - minimum) / span) * (plot["bottom"] - plot["top"])


def _sparse_labels(labels: list[str], x_values: list[float], y: int) -> str:
    if not labels:
        return ""
    step = max(1, len(labels) // 8)
    parts = []
    for index, (label, x) in enumerate(zip(labels, x_values, strict=False)):
        if index % step == 0 or index == len(labels) - 1:
            parts.append(
                f'<text x="{x:.1f}" y="{y + 24}" text-anchor="middle" font-size="11" '
                f'fill="#64748b">{html.escape(label)}</text>'
            )
    return "\n".join(parts)


def _score_for_signal(direction: object, confidence: object) -> float:
    base = {"long": 1.0, "short": -1.0, "neutral": 0.0}.get(str(direction), 0.0)
    weight = {"high": 1.0, "medium": 0.65, "low": 0.35}.get(str(confidence), 0.25)
    return base * weight


def _heat_color(value: float) -> str:
    if value > 0.66:
        return "#1d4ed8"
    if value > 0.1:
        return "#60a5fa"
    if value < -0.66:
        return "#b91c1c"
    if value < -0.1:
        return "#f87171"
    return "#64748b"


def _phase_score(value: object) -> int:
    return {"S0": 0, "S1": 1, "S2": 2, "S3": 3, "S4": 4}.get(str(value), 0)


def _latest_main_contract(quotes: pd.DataFrame, data_asof: date) -> str:
    latest = quotes.loc[quotes["trade_date"].eq(data_asof)].copy()
    if latest.empty:
        raise ResearchWorkbenchError(f"no core quote rows for {data_asof.isoformat()}")
    if "volume" not in latest.columns:
        latest["volume"] = 0
    latest = latest.sort_values(["open_interest", "volume"], ascending=[False, False])
    return str(latest.iloc[0]["contract_code"])


def _contains_forward_return_label(value: object) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            if key_text == "forward_return" or key_text.startswith("forward_return_h"):
                return True
            if _contains_forward_return_label(nested):
                return True
    if isinstance(value, list):
        return any(_contains_forward_return_label(item) for item in value)
    return False


def _relative_path(*, path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _parse_date(value: str) -> date:
    return date.fromisoformat(value[:10])


def _fmt_percent(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2%}"


def _default_latest_signal_json_path() -> Path:
    root = project_root() / "runs" / "daily" / PRODUCT_CODE
    candidates = sorted(root.glob("*/latest_signal_brief.json"))
    if not candidates:
        raise ResearchWorkbenchError(f"no latest signal JSON found under {root}")
    return candidates[-1]


def _default_validated_brief_path(*, data_asof: date) -> Path:
    root = project_root() / "runs" / "daily" / PRODUCT_CODE / data_asof.isoformat()
    daily_path = root / "validated_research_brief.md"
    if daily_path.exists():
        return daily_path
    report_path = (
        project_root()
        / "reports"
        / "research"
        / "validated_brief"
        / f"{PRODUCT_CODE}_{data_asof.isoformat()}_validated_research_brief.md"
    )
    if report_path.exists():
        return report_path
    raise ResearchWorkbenchError(f"validated research brief not found for {data_asof.isoformat()}")


def _default_signal_matrix_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "signal_matrix"
    candidates = sorted(root.glob(f"{PRODUCT_CODE}_*_signal_matrix_daily.parquet"))
    if not candidates:
        raise ResearchWorkbenchError(f"no R35 signal matrix parquet found under {root}")
    return candidates[-1]


def _default_historical_decay_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "historical_evidence"
    candidates = sorted(root.glob(f"{PRODUCT_CODE}_*_historical_evidence_decay.parquet"))
    if not candidates:
        raise ResearchWorkbenchError(f"no R41 decay parquet found under {root}")
    return candidates[-1]


def _default_event_summary_path() -> Path:
    root = data_dir() / "research" / PRODUCT_CODE / "event_explanation"
    candidates = sorted(root.glob(f"{PRODUCT_CODE}_*_event_explanation_summary.parquet"))
    if not candidates:
        raise ResearchWorkbenchError(f"no R42 event summary parquet found under {root}")
    return candidates[-1]


def _default_run_id(*, data_asof: date) -> str:
    return f"r45_publish_pack_{PRODUCT_CODE}_{data_asof.isoformat()}_{uuid.uuid4().hex[:8]}"
