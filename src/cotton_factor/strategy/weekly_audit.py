"""R91 weekly strategy shadow audit."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import StrategyError
from cotton_factor.common.paths import data_dir, reports_dir

WEEKLY_AUDIT_RULE_VERSION = "V5.1_R91_weekly_strategy_audit_v2"
RESEARCH_BOUNDARY = (
    "研究仿真、前向记录、无未来函数，不构成交易指令；"
    "NAV 为研究记账值，非真实资金。"
)
REQUIRED_LEDGER_COLUMNS = {
    "trade_date",
    "strategy_key",
    "record_mode",
    "event_type",
    "warnings_json",
    "net_pnl",
    "nav",
    "drawdown",
    "turnover_lots",
}
FATAL_ANOMALIES = {
    "DUPLICATE_TRADE_DATE",
    "INVALID_TRADE_DATE",
    "NAV_ACCOUNTING_MISMATCH",
    "NON_POSITIVE_NAV",
}


@dataclass(frozen=True)
class WeeklyStrategyAuditResult:
    """R91 weekly audit artifacts."""

    asof_date: date
    run_id: str
    status: str
    strategy_count: int
    forward_capture_days: int
    anomaly_count: int
    json_path: Path
    markdown_path: Path
    manifest_path: Path

    def to_summary(self) -> dict[str, object]:
        """Return a CLI-safe summary."""
        return {
            "asof_date": self.asof_date.isoformat(),
            "run_id": self.run_id,
            "status": self.status,
            "strategy_count": self.strategy_count,
            "forward_capture_days": self.forward_capture_days,
            "anomaly_count": self.anomaly_count,
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "manifest_path": str(self.manifest_path),
        }


def build_cf_weekly_strategy_audit(
    *,
    asof_date: date | None = None,
    ledger_root: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> WeeklyStrategyAuditResult:
    """Summarize the latest five ledger rows without rewriting shadow history."""
    root = ledger_root or data_dir() / "strategy" / "CF"
    ledger_paths = sorted(root.glob("*_shadow_ledger.parquet"))
    if not ledger_paths:
        raise StrategyError(f"no shadow ledger found under {root}")
    ledgers = {path: _load_ledger(path) for path in ledger_paths}
    all_dates = [
        pd.to_datetime(frame["trade_date"]).dt.date.max()
        for frame in ledgers.values()
        if not frame.empty
    ]
    if not all_dates:
        raise StrategyError("shadow ledgers contain no rows")
    target_date = asof_date or max(all_dates)
    summaries: list[dict[str, object]] = []
    total_forward_dates: set[date] = set()
    for path, frame in ledgers.items():
        selected = frame.loc[frame["_trade_date"] <= target_date].copy()
        if selected.empty:
            continue
        selected = selected.sort_values("_trade_date")
        forward = selected.loc[selected["record_mode"].eq("FORWARD_CAPTURE")]
        # 一旦已有真实前向样本，周收益只使用最近五个前向交易日，避免混入历史回放。
        week = forward.tail(5) if not forward.empty else selected.tail(5)
        week_forward = week.loc[week["record_mode"].eq("FORWARD_CAPTURE")]
        total_forward_dates.update(forward["_trade_date"].tolist())
        warning_count = sum(_json_list_length(value) for value in week["warnings_json"])
        anomalies = _accounting_anomalies(selected)
        if forward.empty:
            anomalies.append("NO_FORWARD_CAPTURE")
        if warning_count:
            anomalies.append("WEEK_HAS_WARNINGS")
        if week["event_type"].eq("CORRECTION").any():
            anomalies.append("CORRECTION_EVENT_PRESENT")
        if max(selected["_trade_date"]) < target_date:
            anomalies.append("STALE_LEDGER")
        anomalies = sorted(set(anomalies))
        start_nav = float(week.iloc[0]["nav"] - week.iloc[0]["net_pnl"])
        end_nav = float(week.iloc[-1]["nav"])
        week_return = end_nav / start_nav - 1.0 if start_nav > 0 else math.nan
        summaries.append(
            {
                "strategy_key": str(week.iloc[-1]["strategy_key"]),
                "ledger_path": str(path),
                "latest_date": week.iloc[-1]["_trade_date"].isoformat(),
                "week_start_date": week.iloc[0]["_trade_date"].isoformat(),
                "week_row_count": len(week),
                "latest_nav": end_nav,
                "week_net_pnl": float(week["net_pnl"].sum()),
                "week_return": week_return,
                "latest_drawdown": float(week.iloc[-1]["drawdown"]),
                "week_turnover_lots": int(week["turnover_lots"].sum()),
                "week_forward_capture_days": int(week_forward["_trade_date"].nunique()),
                "forward_capture_days": int(forward["_trade_date"].nunique()),
                "historical_replay_days": int(
                    selected.loc[
                        selected["record_mode"].eq("HISTORICAL_REPLAY"), "_trade_date"
                    ].nunique()
                ),
                "warning_count": warning_count,
                "correction_count": int(week["event_type"].eq("CORRECTION").sum()),
                "anomalies": anomalies,
            }
        )
    if not summaries:
        raise StrategyError(f"no shadow rows found on or before {target_date}")
    baseline_nav = next(
        (
            float(row["latest_nav"])
            for row in summaries
            if str(row["strategy_key"]).startswith("CF_tsmom/")
        ),
        None,
    )
    baseline_return = next(
        (
            float(row["week_return"])
            for row in summaries
            if str(row["strategy_key"]).startswith("CF_tsmom/")
        ),
        None,
    )
    baseline_drawdown = next(
        (
            float(row["latest_drawdown"])
            for row in summaries
            if str(row["strategy_key"]).startswith("CF_tsmom/")
        ),
        None,
    )
    for row in summaries:
        row["nav_difference_vs_baseline"] = (
            float(row["latest_nav"]) - baseline_nav if baseline_nav is not None else None
        )
        row["week_return_difference_vs_baseline"] = (
            float(row["week_return"]) - baseline_return
            if baseline_return is not None
            else None
        )
        row["drawdown_difference_vs_baseline"] = (
            float(row["latest_drawdown"]) - baseline_drawdown
            if baseline_drawdown is not None
            else None
        )
        if baseline_nav is None:
            row["anomalies"] = sorted({*row["anomalies"], "BASELINE_LEDGER_MISSING"})
    all_anomalies = [
        anomaly for row in summaries for anomaly in row["anomalies"]
    ]
    if any(anomaly in FATAL_ANOMALIES for anomaly in all_anomalies):
        status = "FAIL"
    elif all_anomalies:
        status = "WATCH"
    else:
        status = "PASS"
    active_run_id = run_id or _default_run_id(target_date)
    report_root = report_output_dir or reports_dir() / "strategy"
    stem = f"CF_{target_date}_weekly_strategy_audit"
    result = WeeklyStrategyAuditResult(
        asof_date=target_date,
        run_id=active_run_id,
        status=status,
        strategy_count=len(summaries),
        forward_capture_days=len(total_forward_dates),
        anomaly_count=len(all_anomalies),
        json_path=report_root / f"{stem}.json",
        markdown_path=report_root / f"{stem}.md",
        manifest_path=report_root / f"{stem}_manifest.json",
    )
    _write_outputs(result=result, summaries=summaries, input_paths=tuple(ledgers))
    return result


def _write_outputs(
    *,
    result: WeeklyStrategyAuditResult,
    summaries: list[dict[str, object]],
    input_paths: tuple[Path, ...],
) -> None:
    payload = {
        **result.to_summary(),
        "rule_version": WEEKLY_AUDIT_RULE_VERSION,
        "strategies": summaries,
        "research_boundary": RESEARCH_BOUNDARY,
    }
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        f"# CF 周度策略影子审计 - {result.asof_date}",
        "",
        f"- 状态：`{result.status}`",
        f"- 累计可计入前向门槛的交易日：`{result.forward_capture_days}`",
        f"- 异常项：`{result.anomaly_count}`",
        "",
        "| 策略 | 最近5行收益 | 相对基准 | NAV | 回撤 | 换手 | 周内前向日 | 累计前向日 | 异常 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in summaries:
        lines.append(
            f"| {row['strategy_key']} | {_format_percent(row['week_return'])} | "
            f"{_format_percent(row['week_return_difference_vs_baseline'])} | "
            f"{float(row['latest_nav']):.2f} | {float(row['latest_drawdown']):.2%} | "
            f"{row['week_turnover_lots']} | {row['week_forward_capture_days']} | "
            f"{row['forward_capture_days']} | "
            f"{', '.join(row['anomalies']) or '无'} |"
        )
    lines.extend(
        [
            "",
            "## 下周复核",
            "",
            "- 检查最新日是否形成连续 FORWARD_CAPTURE，历史回放不得计入 40 日门槛。",
            "- 检查 correction event 和输入警告是否已解释。",
            "",
            "## 研究边界",
            "",
            f"- {RESEARCH_BOUNDARY}",
            "- HISTORICAL_REPLAY 仅用于工程验收，不计入 40 个真实前向交易日门槛。",
        ]
    )
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest = {
        **result.to_summary(),
        "rule_version": WEEKLY_AUDIT_RULE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "input_sha256": {str(path): _sha256(path) for path in input_paths},
        "artifact_sha256": {
            str(result.json_path): _sha256(result.json_path),
            str(result.markdown_path): _sha256(result.markdown_path),
        },
    }
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_ledger(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    missing = REQUIRED_LEDGER_COLUMNS.difference(frame.columns)
    if missing:
        raise StrategyError(f"shadow ledger missing columns {sorted(missing)}: {path}")
    if frame.empty:
        return frame.assign(_trade_date=pd.Series(dtype="object"))
    parsed = pd.to_datetime(frame["trade_date"], errors="coerce").dt.date
    if parsed.isna().any():
        raise StrategyError(f"shadow ledger contains invalid trade_date: {path}")
    result = frame.copy()
    result["_trade_date"] = parsed
    if "accounting_segment_start" not in result.columns:
        result["accounting_segment_start"] = False
    else:
        result["accounting_segment_start"] = (
            result["accounting_segment_start"].fillna(False).astype(bool)
        )
    return result


def _accounting_anomalies(frame: pd.DataFrame) -> list[str]:
    """对物化账本做轻量账务核对，不改写不可变事件。"""
    anomalies: list[str] = []
    if frame["_trade_date"].duplicated().any():
        anomalies.append("DUPLICATE_TRADE_DATE")
    nav = pd.to_numeric(frame["nav"], errors="coerce")
    pnl = pd.to_numeric(frame["net_pnl"], errors="coerce")
    if nav.isna().any() or pnl.isna().any():
        anomalies.append("NAV_ACCOUNTING_MISMATCH")
        return anomalies
    if (nav <= 0).any():
        anomalies.append("NON_POSITIVE_NAV")
    if len(frame) > 1:
        expected = nav.shift(1) + pnl
        segment_start = frame["accounting_segment_start"].fillna(False).astype(bool)
        # 新账户段允许 NAV 从资本基数重新起算，段内仍须逐日严格勾稽。
        mismatched = (
            ((nav.iloc[1:] - expected.iloc[1:]).abs() > 1e-6)
            & ~segment_start.iloc[1:]
        )
        if mismatched.any():
            anomalies.append("NAV_ACCOUNTING_MISMATCH")
    return anomalies


def _json_list_length(value: object) -> int:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return 0
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError:
        return 1
    return len(payload) if isinstance(payload, list) else 1


def _format_percent(value: object) -> str:
    if value is None:
        return "N/A"
    number = float(value)
    return f"{number:.2%}" if math.isfinite(number) else "N/A"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_run_id(asof_date: date) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"cf_weekly_strategy_{asof_date:%Y%m%d}_{stamp}_{uuid.uuid4().hex[:8]}"
