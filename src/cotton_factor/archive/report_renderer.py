"""HTML report renderer for archive artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined, select_autoescape

from cotton_factor.common.exceptions import ReportRenderError
from cotton_factor.common.paths import reports_dir
from cotton_factor.core.schemas import (
    ResearchFactorEvaluationRow,
    ResearchFactorValueDailyRow,
    ResearchForwardReturnDailyRow,
)

DEFAULT_REPORT_RENDER_VERSION = "html_report_renderer_v1"


@dataclass(frozen=True)
class ReportRenderResult:
    """Rendered report artifact summary."""

    report_type: str
    run_id: str
    title: str
    output_path: Path
    row_count: int
    warnings: list[str]
    input_snapshot_ids: list[str]
    render_version: str


def render_single_factor_report(
    *,
    evaluation_rows: Sequence[ResearchFactorEvaluationRow],
    factor_rows: Sequence[ResearchFactorValueDailyRow] = (),
    forward_return_rows: Sequence[ResearchForwardReturnDailyRow] = (),
    output_path: Path | None = None,
    title: str | None = None,
    warnings: Sequence[str] = (),
    render_version: str = DEFAULT_REPORT_RENDER_VERSION,
) -> ReportRenderResult:
    """Render a single factor evaluation report as static HTML."""
    if not evaluation_rows:
        raise ReportRenderError("single factor report requires evaluation_rows")

    run_id = _single_value([row.run_id for row in evaluation_rows], field_name="run_id")
    factor_id = _single_value([row.factor_id for row in evaluation_rows], field_name="factor_id")
    product_code = _single_value(
        [row.product_code for row in evaluation_rows],
        field_name="product_code",
    )
    horizon = _single_value([row.horizon for row in evaluation_rows], field_name="horizon")
    report_title = title or f"{product_code} {factor_id} Single Factor Report"
    artifact_path = output_path or _default_report_path(
        run_id=run_id,
        report_slug=f"single_factor_{factor_id}_h{horizon}",
    )

    metrics = [
        {"name": row.metric_name, "value": _format_number(row.metric_value)}
        for row in sorted(evaluation_rows, key=lambda item: item.metric_name)
    ]
    context = {
        "title": report_title,
        "report_type": "single_factor",
        "run_id": run_id,
        "rendered_at_utc": _utc_now_text(),
        "summary": [
            ("Product", product_code),
            ("Factor", factor_id),
            ("Horizon", horizon),
            ("Evaluation rows", len(evaluation_rows)),
            ("Factor rows", len(factor_rows)),
            ("Forward return rows", len(forward_return_rows)),
        ],
        "sections": [
            {
                "title": "Metrics",
                "headers": ["Metric", "Value"],
                "rows": [[metric["name"], metric["value"]] for metric in metrics],
            },
            {
                "title": "Lineage",
                "headers": ["Input Snapshot ID"],
                "rows": [[snapshot_id] for snapshot_id in _single_factor_lineage(
                    evaluation_rows=evaluation_rows,
                    factor_rows=factor_rows,
                    forward_return_rows=forward_return_rows,
                )],
            },
        ],
        "warnings": _unique_warnings(warnings),
        "render_version": render_version,
    }
    return _render_report(
        context=context,
        output_path=artifact_path,
        report_type="single_factor",
        run_id=run_id,
        title=report_title,
        row_count=len(evaluation_rows),
        warnings=_unique_warnings(warnings),
        input_snapshot_ids=_single_factor_lineage(
            evaluation_rows=evaluation_rows,
            factor_rows=factor_rows,
            forward_return_rows=forward_return_rows,
        ),
        render_version=render_version,
    )


def render_backtest_report(
    *,
    run_id: str,
    summary: Mapping[str, object],
    equity_curve: Sequence[Mapping[str, object]] = (),
    trades: Sequence[Mapping[str, object]] = (),
    output_path: Path | None = None,
    title: str | None = None,
    warnings: Sequence[str] = (),
    input_snapshot_ids: Sequence[str] = (),
    render_version: str = DEFAULT_REPORT_RENDER_VERSION,
) -> ReportRenderResult:
    """Render a backtest summary report as static HTML."""
    if not run_id:
        raise ReportRenderError("backtest report requires run_id")
    if not summary:
        raise ReportRenderError("backtest report requires non-empty summary")

    report_title = title or f"{run_id} Backtest Report"
    artifact_path = output_path or _default_report_path(
        run_id=run_id,
        report_slug="backtest",
    )
    context = {
        "title": report_title,
        "report_type": "backtest",
        "run_id": run_id,
        "rendered_at_utc": _utc_now_text(),
        "summary": [(key, _display_value(value)) for key, value in sorted(summary.items())],
        "sections": [
            _mapping_table_section("Equity Curve", equity_curve),
            _mapping_table_section("Trades", trades),
            {
                "title": "Lineage",
                "headers": ["Input Snapshot ID"],
                "rows": [[snapshot_id] for snapshot_id in _unique_snapshot_ids(input_snapshot_ids)],
            },
        ],
        "warnings": _unique_warnings(warnings),
        "render_version": render_version,
    }
    # D15 只负责报告渲染；回测的订单、成交、成本和持仓规则仍由 D16 引擎产生。
    return _render_report(
        context=context,
        output_path=artifact_path,
        report_type="backtest",
        run_id=run_id,
        title=report_title,
        row_count=len(equity_curve) + len(trades),
        warnings=_unique_warnings(warnings),
        input_snapshot_ids=_unique_snapshot_ids(input_snapshot_ids),
        render_version=render_version,
    )


def _render_report(
    *,
    context: Mapping[str, object],
    output_path: Path,
    report_type: str,
    run_id: str,
    title: str,
    row_count: int,
    warnings: Sequence[str],
    input_snapshot_ids: Sequence[str],
    render_version: str,
) -> ReportRenderResult:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    html = _jinja_env().from_string(_REPORT_TEMPLATE).render(**context)
    output_path.write_text(html, encoding="utf-8")
    return ReportRenderResult(
        report_type=report_type,
        run_id=run_id,
        title=title,
        output_path=output_path,
        row_count=row_count,
        warnings=list(warnings),
        input_snapshot_ids=list(input_snapshot_ids),
        render_version=render_version,
    )


def _mapping_table_section(
    title: str,
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    headers = sorted({key for row in rows for key in row})
    return {
        "title": title,
        "headers": headers,
        "rows": [
            [_display_value(row.get(header, "")) for header in headers]
            for row in rows
        ],
    }


def _single_factor_lineage(
    *,
    evaluation_rows: Sequence[ResearchFactorEvaluationRow],
    factor_rows: Sequence[ResearchFactorValueDailyRow],
    forward_return_rows: Sequence[ResearchForwardReturnDailyRow],
) -> list[str]:
    snapshot_groups: list[Sequence[str]] = []
    snapshot_groups.extend(row.input_snapshot_ids for row in evaluation_rows)
    snapshot_groups.extend(row.input_snapshot_ids for row in factor_rows)
    snapshot_groups.extend(row.input_snapshot_ids for row in forward_return_rows)
    return _unique_snapshot_ids(*snapshot_groups)


def _single_value(values: Sequence[Any], *, field_name: str) -> Any:
    unique_values = []
    for value in values:
        if value not in unique_values:
            unique_values.append(value)
    if len(unique_values) != 1:
        raise ReportRenderError(f"single factor report has mixed {field_name}: {unique_values}")
    return unique_values[0]


def _default_report_path(*, run_id: str, report_slug: str) -> Path:
    safe_run_id = _safe_slug(run_id)
    safe_report_slug = _safe_slug(report_slug)
    return reports_dir() / f"{safe_run_id}_{safe_report_slug}.html"


def _safe_slug(value: str) -> str:
    cleaned = "".join(character if character.isalnum() else "_" for character in value)
    return cleaned.strip("_") or "report"


def _display_value(value: object) -> str:
    if isinstance(value, float):
        return _format_number(value)
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _format_number(value: float) -> str:
    return f"{value:.6g}"


def _utc_now_text() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _unique_snapshot_ids(*snapshot_groups: Sequence[str]) -> list[str]:
    values: list[str] = []
    for group in snapshot_groups:
        for snapshot_id in group:
            if snapshot_id not in values:
                values.append(snapshot_id)
    return values


def _unique_warnings(warnings: Sequence[str]) -> list[str]:
    values: list[str] = []
    for warning in warnings:
        if warning not in values:
            values.append(warning)
    return values


def _jinja_env() -> Environment:
    return Environment(
        autoescape=select_autoescape(enabled_extensions=("html",)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


_REPORT_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }}</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #1f2937;
      --muted: #667085;
      --line: #d0d5dd;
      --band: #f7f9fc;
      --accent: #0f766e;
      --warn: #b42318;
    }
    body {
      margin: 0;
      color: var(--ink);
      background: #ffffff;
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.45;
    }
    main {
      max-width: 1120px;
      margin: 0 auto;
      padding: 32px 24px 48px;
    }
    header {
      border-bottom: 2px solid var(--accent);
      padding-bottom: 16px;
      margin-bottom: 24px;
    }
    h1 {
      font-size: 28px;
      margin: 0 0 8px;
      letter-spacing: 0;
    }
    h2 {
      font-size: 18px;
      margin: 28px 0 10px;
      letter-spacing: 0;
    }
    .meta {
      color: var(--muted);
      font-size: 13px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
      margin-bottom: 12px;
    }
    th, td {
      text-align: left;
      border-bottom: 1px solid var(--line);
      padding: 8px 10px;
      vertical-align: top;
    }
    th {
      background: var(--band);
      font-weight: 700;
    }
    .warnings {
      border-left: 4px solid var(--warn);
      background: #fff7f5;
      padding: 10px 14px;
      margin: 18px 0;
    }
    .warnings p {
      color: var(--warn);
      margin: 0 0 6px;
      font-weight: 700;
    }
    .empty {
      color: var(--muted);
      font-style: italic;
    }
    footer {
      margin-top: 32px;
      color: var(--muted);
      font-size: 12px;
    }
  </style>
</head>
<body>
<main>
  <header>
    <h1>{{ title }}</h1>
    <div class="meta">
      {{ report_type }} | run_id={{ run_id }} | rendered={{ rendered_at_utc }}
    </div>
  </header>

  {% if warnings %}
  <section class="warnings">
    <p>Warnings</p>
    <ul>
    {% for warning in warnings %}
      <li>{{ warning }}</li>
    {% endfor %}
    </ul>
  </section>
  {% endif %}

  <section>
    <h2>Summary</h2>
    <table>
      <tbody>
      {% for key, value in summary %}
        <tr><th>{{ key }}</th><td>{{ value }}</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </section>

  {% for section in sections %}
  <section>
    <h2>{{ section.title }}</h2>
    {% if section.rows %}
    <table>
      <thead>
        <tr>
        {% for header in section.headers %}
          <th>{{ header }}</th>
        {% endfor %}
        </tr>
      </thead>
      <tbody>
      {% for row in section.rows %}
        <tr>
        {% for cell in row %}
          <td>{{ cell }}</td>
        {% endfor %}
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p class="empty">No rows.</p>
    {% endif %}
  </section>
  {% endfor %}

  <footer>
    Render version: {{ render_version }}
  </footer>
</main>
</body>
</html>
"""
