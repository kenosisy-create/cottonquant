#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CF 最新交易日研究观察 - 单文件 HTML 仪表盘生成器。

用法（在项目根目录 D:\\Cottonquant 下）：

    py -3.12 scripts\\build_dashboard.py                 # 自动选择 runs/daily/CF 下最新交易日
    py -3.12 scripts\\build_dashboard.py --date 2026-07-20
    py -3.12 scripts\\build_dashboard.py --open          # 生成后用默认浏览器打开

输入（只读，不修改任何研究产物）：
    runs/daily/CF/<date>/latest_signal_brief.json        # 必需
    runs/daily/CF/<date>/current_watch_window.md         # 可选（R77 观察窗口）
    runs/daily/CF/<date>/data_continuity_audit.json      # 可选（R63 审计状态条）
    runs/daily/CF/<date>/strategy_shadow.json             # 可选（R90 影子摘要）
    data/strategy/CF/*_shadow_ledger.parquet              # 可选（R90 物化视图）

输出：
    reports/dashboard/CF_dashboard_<date>.html
    reports/dashboard/CF_dashboard_latest.html           # 最新一份的稳定副本

设计边界：
    - 展示层只读；影子曲线复用项目已有 pandas，不引入新依赖；
    - 只读展示 latest signal-only 与前向影子产物，不读取任何 forward-return 标签；
    - 页面自带研究边界声明，不构成交易指令或投资建议。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import re
import sys
from pathlib import Path

try:
    import pandas as pd
except ImportError:  # pragma: no cover - 无 pandas 时按可选分区降级
    pd = None

RULE_VERSION = "dashboard_strategy_shadow_v3"
FORBIDDEN_DATA_TOKENS = ("forward_return", "fwd_ret")


# ---------------------------------------------------------------------------
# 数据读取
# ---------------------------------------------------------------------------

def _read_json(path: Path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def find_latest_date_dir(daily_root: Path) -> Path:
    """在 runs/daily/<product>/ 下找最新的、含 latest_signal_brief.json 的日期目录。"""
    if not daily_root.is_dir():
        raise SystemExit(f"[ERROR] daily runs dir not found: {daily_root}")
    candidates = []
    for child in daily_root.iterdir():
        if child.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", child.name):
            if (child / "latest_signal_brief.json").is_file():
                candidates.append(child)
    if not candidates:
        raise SystemExit(
            f"[ERROR] no date folder with latest_signal_brief.json under: {daily_root}"
        )
    return sorted(candidates, key=lambda p: p.name)[-1]


def parse_watch_window(md_text: str):
    """从 current_watch_window.md 提取关键数值；解析失败的字段保持 None。

    只做宽松的正则提取 + 分节保留原文，产物格式变化时页面仍可渲染原文。
    """
    watch = {
        "sections": [],
        "v2_phase": None,
        "levels": {},
        "review_dates": None,
        "avg_resolution_days": None,
        "states": {},
    }
    # 分节保留原文
    current = None
    for line in md_text.splitlines():
        if line.startswith("## "):
            current = {"title": line[3:].strip(), "lines": []}
            watch["sections"].append(current)
        elif line.startswith("# "):
            continue
        elif current is not None and line.strip():
            current["lines"].append(line.rstrip())

    def _search(pattern):
        m = re.search(pattern, md_text)
        return m.groups() if m else None

    g = _search(r"v2 阶段：`(S\d)`\s*([^/\s]+)\s*/\s*`([^`]+)`")
    if g:
        watch["v2_phase"] = {"code": g[0], "label": g[1], "strength": g[2]}
    for key, pat in [
        ("confirm", r"确认参考位：`([\d.]+)`"),
        ("ma_invalid", r"均线失效参考位：`([\d.]+)`"),
        ("strong_invalid", r"强失效参考位：`([\d.]+)`"),
    ]:
        g = _search(pat)
        if g:
            try:
                watch["levels"][key] = float(g[0])
            except ValueError:
                pass
    g = _search(r"T\+1 / T\+3 / T\+5 暂定复核日：`([\d-]+)`\s*/\s*`([\d-]+)`\s*/\s*`([\d-]+)`")
    if g:
        watch["review_dates"] = list(g)
    g = _search(r"历史平均解决周期：`([\d.]+)`")
    if g:
        try:
            watch["avg_resolution_days"] = float(g[0])
        except ValueError:
            pass
    for key, pat in [
        ("dual_price", r"双价格状态：`(\w+)`\s*/\s*`(\w+)`"),
        ("chain_oi", r"全链持仓：`(\w+)`"),
        ("roll", r"多日移仓：`(\w+)`"),
        ("option", r"期权结构：`(\w+)`\s*/\s*`?(\w+)`?"),
        ("vol_state", r"波动状态\s*`(\w+)`"),
    ]:
        g = _search(pat)
        if g:
            watch["states"][key] = list(g)
    return watch


def summarize_audit(audit: dict):
    return {
        "status": audit.get("continuity_status"),
        "passed": audit.get("passed"),
        "warning_count": audit.get("warning_count"),
        "error_count": audit.get("error_count"),
        "futures_latest": audit.get("core_latest_trade_date"),
        "option_latest": audit.get("option_latest_trade_date"),
        "rule_version": audit.get("rule_version"),
    }


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def _assert_no_forward_keys(value, *, context: str):
    """策略展示输入不得携带历史后验标签。"""
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in FORBIDDEN_DATA_TOKENS) or lowered.startswith(
                "future_"
            ):
                raise ValueError(f"{context} contains forbidden field: {key}")
            _assert_no_forward_keys(item, context=context)
    elif isinstance(value, list):
        for item in value:
            _assert_no_forward_keys(item, context=context)


def _resolve_ledger_path(item: dict, *, root: Path, product: str):
    strategy_root = (root / "data" / "strategy" / product).resolve()
    raw_path = str(item.get("ledger_path") or "").strip()
    if raw_path:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = root / candidate
    else:
        key = str(item.get("strategy_key") or "")
        if "/" not in key:
            return None
        strategy_id, version = key.split("/", 1)
        candidate = strategy_root / f"{strategy_id}_{version}_shadow_ledger.parquet"
    resolved = candidate.resolve()
    try:
        resolved.relative_to(strategy_root)
    except ValueError as exc:
        raise ValueError(f"shadow ledger escapes strategy root: {resolved}") from exc
    return resolved if resolved.is_file() else None


def _optional_value(value):
    if value is None:
        return None
    try:
        if pd is not None and pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def load_strategy_shadow(run_dir: Path, product: str, root: Path):
    """读取影子摘要和最多 60 行 NAV；没有可核对台账时返回 None。"""
    summary_path = run_dir / "strategy_shadow.json"
    if not summary_path.is_file() or pd is None:
        return None
    summary = _read_json(summary_path)
    _assert_no_forward_keys(summary, context="strategy_shadow.json")
    statuses = summary.get("strategies")
    if not isinstance(statuses, list):
        return None
    trade_date = str(summary.get("trade_date") or run_dir.name)
    strategies = []
    for status in statuses:
        if not isinstance(status, dict):
            continue
        ledger_path = _resolve_ledger_path(status, root=root, product=product)
        if ledger_path is None:
            continue
        frame = pd.read_parquet(ledger_path)
        forbidden = [
            column
            for column in frame.columns
            if any(token in column.lower() for token in FORBIDDEN_DATA_TOKENS)
            or column.lower().startswith("future_")
        ]
        if forbidden:
            raise ValueError(f"shadow ledger contains forbidden columns: {sorted(forbidden)}")
        required = {
            "trade_date",
            "strategy_key",
            "record_mode",
            "target_lots",
            "target_contract",
            "nav",
            "drawdown",
            "entry_date",
            "holding_days",
        }
        missing = required.difference(frame.columns)
        if missing or frame.empty:
            continue
        selected = frame.copy()
        selected["_trade_date"] = pd.to_datetime(
            selected["trade_date"], errors="coerce"
        ).dt.date
        if selected["_trade_date"].isna().any():
            raise ValueError(f"shadow ledger has invalid trade_date: {ledger_path}")
        selected = selected.loc[selected["_trade_date"] <= pd.Timestamp(trade_date).date()]
        if selected.empty:
            continue
        selected = selected.sort_values("_trade_date")
        if selected["_trade_date"].duplicated().any():
            raise ValueError(f"shadow ledger contains duplicate dates: {ledger_path}")
        numeric_nav = pd.to_numeric(selected["nav"], errors="coerce")
        numeric_drawdown = pd.to_numeric(selected["drawdown"], errors="coerce")
        if not numeric_nav.map(math.isfinite).all() or not numeric_drawdown.map(
            math.isfinite
        ).all():
            raise ValueError(f"shadow ledger contains invalid NAV or drawdown: {ledger_path}")
        latest = selected.iloc[-1]
        nav_points = [
            {"trade_date": row["_trade_date"].isoformat(), "nav": float(row["nav"])}
            for row in selected.tail(60).to_dict(orient="records")
        ]
        target_lots = int(latest["target_lots"])
        strategies.append(
            {
                "strategy_key": str(latest["strategy_key"]),
                "status": str(status.get("status") or "UNKNOWN"),
                "record_mode": str(latest["record_mode"]),
                "latest_date": latest["_trade_date"].isoformat(),
                "target_lots": target_lots,
                "target_contract": str(_optional_value(latest["target_contract"]) or ""),
                "direction": "long" if target_lots > 0 else "short" if target_lots < 0 else "neutral",
                "held_lots": int(_optional_value(latest.get("held_lots_after", 0)) or 0),
                "held_contract": str(
                    _optional_value(latest.get("held_contract_after", "")) or ""
                ),
                "nav": float(latest["nav"]),
                "drawdown": float(latest["drawdown"]),
                "entry_date": _optional_value(latest["entry_date"]),
                "holding_days": int(latest["holding_days"]),
                "warning_count": int(status.get("warning_count") or 0),
                "forward_capture_days": int(
                    selected.loc[
                        selected["record_mode"].eq("FORWARD_CAPTURE"), "_trade_date"
                    ].nunique()
                ),
                "historical_replay_days": int(
                    selected.loc[
                        selected["record_mode"].eq("HISTORICAL_REPLAY"), "_trade_date"
                    ].nunique()
                ),
                "nav_series": nav_points,
                "ledger_path": _relpath(ledger_path, root),
            }
        )
    if not strategies:
        return None
    baseline_nav = next(
        (
            item["nav"]
            for item in strategies
            if item["strategy_key"].startswith("CF_tsmom/")
        ),
        None,
    )
    for item in strategies:
        item["nav_difference_vs_baseline"] = (
            item["nav"] - baseline_nav if baseline_nav is not None else None
        )
    return {
        "trade_date": trade_date,
        "record_mode": str(summary.get("record_mode") or "UNKNOWN"),
        "run_id": str(summary.get("run_id") or ""),
        "research_boundary": str(summary.get("research_boundary") or ""),
        "strategies": strategies,
        "source_json": _relpath(summary_path, root),
    }


def build_payload(run_dir: Path, product: str, root: Path):
    brief_path = run_dir / "latest_signal_brief.json"
    brief = _read_json(brief_path)

    watch = None
    watch_path = run_dir / "current_watch_window.md"
    if watch_path.is_file():
        try:
            watch = parse_watch_window(watch_path.read_text(encoding="utf-8"))
        except Exception as exc:  # 展示层容错：观察窗口解析失败不阻断整页
            print(f"[WARN] failed to parse current_watch_window.md: {exc}")
            watch = None

    audit = None
    audit_path = run_dir / "data_continuity_audit.json"
    if audit_path.is_file():
        try:
            audit = summarize_audit(_read_json(audit_path))
        except Exception as exc:
            print(f"[WARN] failed to read data_continuity_audit.json: {exc}")
            audit = None

    strategy_shadow = None
    try:
        strategy_shadow = load_strategy_shadow(run_dir, product, root)
    except Exception as exc:  # 展示层容错：策略分区失败时隐藏，不影响研究简报
        print(f"[WARN] failed to read strategy shadow: {exc}")
        strategy_shadow = None

    return {
        "rule_version": RULE_VERSION,
        "generated_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "product": product,
        "trade_date": brief.get("trade_date"),
        "brief": brief,
        "watch": watch,
        "audit": audit,
        "strategy_shadow": strategy_shadow,
        "source": {
            "brief": _relpath(brief_path, root),
            "watch": _relpath(watch_path, root) if watch else None,
            "audit": _relpath(audit_path, root) if audit else None,
            "strategy": strategy_shadow.get("source_json") if strategy_shadow else None,
        },
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main(argv=None):
    try:  # Windows 控制台编码兜底
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Build CF latest-signal dashboard HTML")
    parser.add_argument("--root", default=None, help="project root (default: parent of scripts/)")
    parser.add_argument("--product", default="CF")
    parser.add_argument("--date", default=None, help="trade date folder name, e.g. 2026-07-20")
    parser.add_argument("--output", default=None, help="explicit output html path")
    parser.add_argument("--no-latest-copy", action="store_true",
                        help="do not write the *_latest.html stable copy")
    parser.add_argument("--open", action="store_true", help="open result in default browser")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    daily_root = root / "runs" / "daily" / args.product
    run_dir = (daily_root / args.date) if args.date else find_latest_date_dir(daily_root)
    if not (run_dir / "latest_signal_brief.json").is_file():
        raise SystemExit(f"[ERROR] latest_signal_brief.json not found in: {run_dir}")

    payload = build_payload(run_dir, args.product, root)
    trade_date = payload.get("trade_date") or run_dir.name

    payload_js = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html_text = TEMPLATE.replace("__PAYLOAD__", payload_js)

    if args.output:
        out_paths = [Path(args.output)]
    else:
        out_dir = root / "reports" / "dashboard"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_paths = [out_dir / f"{args.product}_dashboard_{trade_date}.html"]
        if not args.no_latest_copy:
            out_paths.append(out_dir / f"{args.product}_dashboard_latest.html")

    for path in out_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html_text, encoding="utf-8")
        print(f"[OK] wrote {path}")

    print(f"[OK] trade_date={trade_date} source={run_dir}")
    if args.open:
        import webbrowser
        webbrowser.open(out_paths[0].resolve().as_uri())
    return 0


# ---------------------------------------------------------------------------
# HTML 模板（单文件，内联全部 CSS/JS，无外部依赖）
# ---------------------------------------------------------------------------

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CF 最新交易日研究观察</title>
<style>
:root{
  color-scheme: light;
  --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --baseline:#c3c2b7; --border:rgba(11,11,11,.10);
  --blue:#2a78d6; --violet:#4a3aa7; --up:#d03b3b; --down:#006300; --down-mark:#0ca30c;
  --warn:#fab219; --serious:#ec835a; --crit:#d03b3b; --good:#0ca30c;
  --tint-blue:rgba(42,120,214,.09); --tint-up:rgba(208,59,59,.09); --tint-down:rgba(12,163,12,.10);
  --tint-warn:rgba(250,178,25,.14); --tint-muted:rgba(137,135,129,.12); --tint-violet:rgba(74,58,167,.09);
}
:root[data-theme="dark"]{
  color-scheme: dark;
  --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --baseline:#383835; --border:rgba(255,255,255,.10);
  --blue:#3987e5; --violet:#9085e9; --up:#e66767; --down:#0ca30c; --down-mark:#0ca30c;
  --tint-blue:rgba(57,135,229,.14); --tint-up:rgba(230,103,103,.14); --tint-down:rgba(12,163,12,.14);
  --tint-warn:rgba(250,178,25,.14); --tint-muted:rgba(137,135,129,.18); --tint-violet:rgba(144,133,233,.16);
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{background:var(--page);color:var(--ink);
  font:14px/1.55 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;}
.wrap{max-width:1200px;margin:0 auto;padding:20px 20px 48px}
a{color:var(--blue)}
h1{font-size:21px;margin:0;font-weight:700;letter-spacing:.2px}
h2{font-size:15px;margin:0 0 12px;font-weight:700}
h3{font-size:13px;margin:0 0 8px;font-weight:600;color:var(--ink2)}
.sub{color:var(--ink2);font-size:12.5px;margin-top:3px}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
.hdr-right{display:flex;gap:8px;align-items:center}
.datepill{font-size:16px;font-weight:700;background:var(--surface);border:1px solid var(--border);
  border-radius:8px;padding:6px 12px}
.themebtn{cursor:pointer;font-size:12px;color:var(--ink2);background:var(--surface);
  border:1px solid var(--border);border-radius:8px;padding:6px 10px}
.badges{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0 18px}
.badge{font-size:11.5px;padding:2.5px 9px;border-radius:999px;border:1px solid var(--border);
  color:var(--ink2);background:var(--surface)}
.badge.b-blue{color:var(--blue);background:var(--tint-blue);border-color:transparent}
.badge.b-warn{background:var(--tint-warn);border-color:transparent}
.badge.b-good{color:var(--down);background:var(--tint-down);border-color:transparent}
.badge.b-crit{color:var(--crit);background:var(--tint-up);border-color:transparent}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px 18px}
section.card{margin-bottom:16px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:16px}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:13px 15px}
.kpi .k-label{font-size:12px;color:var(--ink2)}
.kpi .k-value{font-size:24px;font-weight:700;margin-top:3px;letter-spacing:.2px}
.kpi .k-sub{font-size:12px;color:var(--muted);margin-top:4px}
.chip{display:inline-flex;align-items:center;gap:4px;font-size:12px;font-weight:600;
  border-radius:999px;padding:2px 10px;white-space:nowrap}
.chip.small{font-size:11px;padding:1.5px 8px}
.c-up{color:var(--up);background:var(--tint-up)}
.c-down{color:var(--down);background:var(--tint-down)}
.c-neutral{color:var(--ink2);background:var(--tint-muted)}
.c-blue{color:var(--blue);background:var(--tint-blue)}
.c-violet{color:var(--violet);background:var(--tint-violet)}
.c-warn{color:var(--ink);background:var(--tint-warn)}
.c-crit{color:var(--crit);background:var(--tint-up)}
.grid2{display:grid;grid-template-columns:1.25fr 1fr;gap:16px}
@media(max-width:900px){.grid2{grid-template-columns:1fr}}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th{font-size:11.5px;color:var(--muted);font-weight:600;text-align:right;
  padding:5px 8px;border-bottom:1px solid var(--grid);white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th.tl,td.tl{text-align:left}
td{font-size:12.5px;padding:6.5px 8px;border-bottom:1px solid var(--grid);text-align:right;white-space:nowrap}
tr:last-child td{border-bottom:none}
tr.main-row td{background:var(--tint-blue)}
tr.primary-row td{background:var(--tint-violet)}
.num-up{color:var(--up);font-weight:600}
.num-down{color:var(--down);font-weight:600}
.cellbar{display:inline-block;height:8px;border-radius:4px;background:var(--blue);
  vertical-align:middle;margin-right:6px;min-width:2px}
.meter{display:inline-flex;align-items:center;gap:7px}
.meter .track{width:72px;height:7px;border-radius:4px;background:var(--tint-muted);overflow:hidden}
.meter .fill{height:100%;border-radius:4px;background:var(--blue)}
.factor-chips{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px}
.fchip{border:1px solid var(--border);border-radius:10px;padding:8px 13px;min-width:120px}
.fchip .f-name{font-size:11.5px;color:var(--muted)}
.fchip .f-val{margin-top:3px}
.stepper{display:flex;gap:6px;margin:10px 0 6px;flex-wrap:wrap}
.step{flex:1;min-width:96px;border:1px solid var(--border);border-radius:9px;
  padding:7px 10px;font-size:12px;color:var(--muted);position:relative}
.step .s-code{font-weight:700;font-size:12.5px}
.step.active{border-color:transparent;color:var(--ink)}
.step .s-mark{position:absolute;top:7px;right:9px;font-size:10.5px;font-weight:700}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11.5px;color:var(--ink2);margin-top:8px}
.legend .sw{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.mdlist{margin:6px 0 0;padding-left:18px}
.mdlist li{margin:3px 0;font-size:12.8px;color:var(--ink2)}
.mdlist code,.inlinecode{font:12px ui-monospace,Consolas,monospace;background:var(--tint-muted);
  border-radius:4px;padding:0 5px;color:var(--ink)}
.cond-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}
@media(max-width:900px){.cond-grid{grid-template-columns:1fr}}
.cond{border-radius:10px;padding:11px 14px;border:1px solid var(--border)}
.cond.ok{background:var(--tint-blue)}
.cond.bad{background:var(--tint-warn)}
.watchitems li{margin:5px 0;font-size:13px}
.footer{color:var(--muted);font-size:11.5px;margin-top:22px;line-height:1.8}
.footer code{font-size:10.5px}
.sharebtn{cursor:pointer;font-size:12px;font-weight:600;color:#fff;background:#07C160;
  border:none;border-radius:8px;padding:6px 12px}
.sharebtn:hover{filter:brightness(1.06)}
#share-overlay{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:60;display:none;
  align-items:center;justify-content:center;padding:20px}
#share-overlay.show{display:flex}
.share-panel{background:var(--surface);border:1px solid var(--border);border-radius:14px;
  width:min(480px,94vw);max-height:92vh;display:flex;flex-direction:column;overflow:hidden}
.share-head{display:flex;justify-content:space-between;align-items:center;padding:13px 16px;
  border-bottom:1px solid var(--grid)}
.share-head h3{margin:0;font-size:14px;color:var(--ink)}
.share-close{cursor:pointer;border:none;background:none;color:var(--muted);font-size:17px;line-height:1}
.share-body{overflow:auto;padding:14px 16px;background:var(--page);text-align:center}
.share-body img{max-width:100%;border:1px solid var(--border);border-radius:10px;
  box-shadow:0 6px 22px rgba(0,0,0,.12)}
.share-foot{padding:12px 16px;border-top:1px solid var(--grid)}
.share-actions{display:flex;gap:8px;flex-wrap:wrap}
.share-actions button{cursor:pointer;font-size:12.5px;font-weight:600;border-radius:8px;
  padding:8px 14px;border:1px solid var(--border);background:var(--surface);color:var(--ink)}
.share-actions .primary{background:#07C160;border-color:#07C160;color:#fff}
.share-hint{font-size:11.5px;color:var(--muted);margin-top:8px}
#share-toast{font-size:12px;margin-top:8px;display:none}
svg text{font-family:inherit}
#tooltip{position:fixed;display:none;pointer-events:none;z-index:99;background:var(--surface);
  border:1px solid var(--border);border-radius:8px;padding:7px 11px;font-size:12px;
  box-shadow:0 4px 14px rgba(0,0,0,.13);color:var(--ink);line-height:1.5}
.hr-chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.section-note{font-size:11.5px;color:var(--muted);margin-top:10px}
.table-scroll{overflow-x:auto;overscroll-behavior-inline:contain}
.strategy-key{font-weight:700;color:var(--ink)}
.strategy-sub{display:block;color:var(--muted);font-size:10.5px;margin-top:2px}
.sparkline{display:block;width:150px;height:38px;min-width:150px}
.mode-forward{color:var(--good);background:var(--tint-down)}
.mode-replay{color:var(--warn);background:var(--tint-warn)}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1 id="page-title">CF 最新交易日研究观察</h1>
      <div class="sub" id="page-sub"></div>
    </div>
    <div class="hdr-right">
      <div class="datepill" id="datepill"></div>
      <button class="sharebtn" id="sharebtn" type="button">分享图 · 微信</button>
      <button class="themebtn" id="themebtn" type="button">🌗 暗色</button>
    </div>
  </header>
  <div class="badges" id="badges"></div>
  <div class="kpis" id="kpis"></div>

  <section class="card" id="sec-strategy" style="display:none">
    <h2>策略影子 · V5.1 研究记账</h2>
    <div class="table-scroll" id="strategy-table"></div>
    <div class="section-note" id="strategy-note"></div>
  </section>

  <section class="card" id="sec-market">
    <h2>一、市场事实 · 合约活跃度</h2>
    <div class="grid2">
      <div id="activity-table"></div>
      <div>
        <h3>期限结构（结算价，按合约月份）</h3>
        <div id="term-chart"></div>
        <div id="term-meta" class="section-note"></div>
      </div>
    </div>
  </section>

  <section class="card" id="sec-factors">
    <h2>二、因子信号与主力收益</h2>
    <div class="grid2">
      <div>
        <div class="factor-chips" id="factor-chips"></div>
        <div id="multifactor"></div>
      </div>
      <div>
        <h3>主力合约区间收益（1/3/5/10/20 日）</h3>
        <div id="returns-chart"></div>
      </div>
    </div>
  </section>

  <section class="card" id="sec-matrix">
    <h2>三、多周期信号矩阵（R35/R38）</h2>
    <div id="matrix-table"></div>
    <div class="section-note" id="matrix-note"></div>
  </section>

  <section class="card" id="sec-phase">
    <h2>四、趋势阶段</h2>
    <div id="phase-block"></div>
  </section>

  <section class="card" id="sec-watch" style="display:none">
    <h2>五、当前观察窗口（R77）</h2>
    <div class="grid2">
      <div id="watch-left"></div>
      <div>
        <h3>价格窗口</h3>
        <div id="ladder"></div>
      </div>
    </div>
    <div class="cond-grid" id="watch-conds"></div>
    <div id="watch-review" class="section-note"></div>
  </section>

  <section class="card" id="sec-warn">
    <h2 id="warn-title">六、明日观察清单 · 警告 · 人工复核</h2>
    <div id="watch-list"></div>
    <div id="warn-table"></div>
    <div id="human-review"></div>
  </section>

  <div class="footer" id="footer"></div>
</div>
<div id="share-overlay">
  <div class="share-panel">
    <div class="share-head">
      <h3>微信分享图（长图规格 750px）</h3>
      <button class="share-close" id="share-close" type="button" aria-label="关闭">✕</button>
    </div>
    <div class="share-body"><img id="share-preview" alt="分享图预览"></div>
    <div class="share-foot">
      <div class="share-actions">
        <button class="primary" id="share-copy" type="button">复制图片</button>
        <button id="share-download" type="button">下载 PNG</button>
      </div>
      <div class="share-hint">复制后切到微信聊天窗口 Ctrl+V 即可发送；朋友圈请先下载再从相册选择。图片自带研究边界声明。</div>
      <div id="share-toast"></div>
    </div>
  </div>
</div>
<div id="tooltip"></div>
<script>
const DATA = __PAYLOAD__;
(function(){
"use strict";
const $ = id => document.getElementById(id);
const brief = DATA.brief || {};
const S = brief.summary || {};
const facts = S.market_facts || {};
const activity = facts.contract_activity || [];
const factors = S.factor_signals || {};
const term = S.term_structure || {};
const matrixCtx = brief.signal_matrix_context || S.signal_matrix_context || {};
const phase = brief.trend_phase || S.trend_phase || {};
const watch = DATA.watch;
const audit = DATA.audit;
const strategy = DATA.strategy_shadow;

/* ---------- 主题切换 ---------- */
const btn = $("themebtn");
function applyTheme(t){
  document.documentElement.setAttribute("data-theme", t);
  btn.textContent = t === "dark" ? "☀️ 亮色" : "🌗 暗色";
  renderCharts(); // 图表用当前 CSS 变量重绘
}
let theme = (window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light";
btn.addEventListener("click", () => { theme = theme === "dark" ? "light" : "dark"; applyTheme(theme); });

/* ---------- 工具 ---------- */
const fmt = {
  num(v, d){ if(v==null||isNaN(v)) return "—";
    return Number(v).toLocaleString("zh-CN",{minimumFractionDigits:d||0,maximumFractionDigits:d||0}); },
  signed(v, d){ if(v==null||isNaN(v)) return "—";
    const s = fmt.num(Math.abs(v), d); return (v>0?"+":v<0?"−":"") + s; },
  pct(v, d){ if(v==null||isNaN(v)) return "—";
    const x=v*100, s=Math.abs(x).toFixed(d==null?2:d); return (x>0?"+":x<0?"−":"")+s+"%"; }
};
function cls(v){ return v>0 ? "num-up" : (v<0 ? "num-down" : ""); }
function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g,
  c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
function mdInline(s){ // 仅处理 `code` 与 **bold**
  return esc(s).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
}
function cssVar(name){ return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

const DIR = {
  long:{t:"偏多",c:"c-up",a:"▲"}, short:{t:"偏空",c:"c-down",a:"▼"},
  neutral:{t:"中性",c:"c-neutral",a:"—"}, unknown:{t:"未知",c:"c-neutral",a:"?"}
};
function dirChip(d, extra){ const m = DIR[d]||DIR.unknown;
  return '<span class="chip '+m.c+'">'+m.a+" "+m.t+(extra?(" "+esc(extra)):"")+"</span>"; }
const OPT = {
  confirm_long:{t:"确认偏多",c:"c-up"}, confirm_short:{t:"确认偏空",c:"c-down"},
  diverge_long:{t:"背离偏多",c:"c-warn"}, diverge_short:{t:"背离偏空",c:"c-warn"},
  volatility_risk:{t:"波动风险",c:"c-warn"}, watch:{t:"观察",c:"c-neutral"},
  not_connected:{t:"未接入",c:"c-neutral"}
};
function optChip(v){ const m = OPT[v]||{t:v||"—",c:"c-neutral"};
  return '<span class="chip small '+m.c+'">'+esc(m.t)+"</span>"; }
const CONF = {low:"低",medium:"中",high:"高"};
const EVID = {weak:"弱",moderate:"中",strong:"强"};
const FLAG = {option_divergence:"期权背离",low_confidence:"低置信",main_switch:"主力切换",
  roll_risk:"换月风险",thin_liquidity:"流动性弱"};
const PHASES = [["S0","未确认"],["S1","起点观察"],["S2","趋势中"],["S3","衰竭观察"],["S4","终点确认"]];
const PHCOLOR = {S0:"--muted",S1:"--blue",S2:"--violet",S3:"--warn",S4:"--crit"};
const STATE_CN = {
  BOTH_ABOVE:"收盘/结算同在20日线上", BOTH_BELOW:"收盘/结算同破20日线",
  SETTLE_STRONGER:"结算相对更强", CLOSE_STRONGER:"收盘相对更强", MIXED:"分化",
  SHORT_COVER_OR_EXIT:"空头回补或资金退出", LONG_BUILD:"多头增仓", SHORT_BUILD:"空头增仓",
  LONG_LIQUIDATION:"多头减仓", ROLL_DOMINANT:"移仓主导", ROLL_WITH_NET_EXIT:"移仓伴净退出",
  EXIT_DOMINANT:"资金退出主导", CONFIRM_LONG:"期权确认偏多", CONFIRM_SHORT:"期权确认偏空",
  LOW_VOL_UNPRICED:"低波动未定价", EXHAUSTION_OR_FAILURE_WATCH:"衰竭/失效观察"
};
function stateCN(code){ return STATE_CN[code] || code; }

/* ---------- 头部 ---------- */
$("page-title").textContent = (DATA.product||"CF") + " 最新交易日研究观察";
$("page-sub").textContent = "研究级生产数据决策工作台 · latest signal-only · 主力合约 " + (brief.main_contract||"—");
$("datepill").textContent = DATA.trade_date || "—";

(function badges(){
  const b = [];
  b.push('<span class="badge b-blue">Run: '+esc(brief.run_id||"—")+'</span>');
  const rb = S.research_boundary || {};
  if (rb.no_future_return_labels !== false) b.push('<span class="badge">不含未来收益标签</span>');
  b.push('<span class="badge">'+esc(rb.forward_return_validation||"未完成 forward-return 验证")+'</span>');
  b.push('<span class="badge">'+esc(rb.trading_instruction||"不构成交易指令")+'</span>');
  if (audit){
    const ok = audit.passed && (audit.error_count||0)===0;
    b.push('<span class="badge '+(ok?"b-good":"b-crit")+'">R63 数据审计 '+esc(audit.status||"—")
      +(ok?" ✓":" ✗")+' · 警告 '+(audit.warning_count==null?"—":audit.warning_count)+'</span>');
    if (audit.futures_latest) b.push('<span class="badge">期货核心表至 '+esc(audit.futures_latest)+'</span>');
    if (audit.option_latest) b.push('<span class="badge">期权核心表至 '+esc(audit.option_latest)+'</span>');
  }
  if (strategy && (strategy.strategies||[]).length){
    const first = strategy.strategies[0];
    const isForward = strategy.record_mode === "FORWARD_CAPTURE";
    b.push('<span class="badge '+(isForward?"b-good":"b-warn")+'">策略影子 '
      +esc(strategy.record_mode||"—")+' · 前向 '+(first.forward_capture_days||0)+' 日</span>');
  }
  const warnsAll = brief.warnings || [];
  const wcnt = warnsAll.filter(w=>/WARN|ERROR/i.test(w.severity||"")).length;
  if (warnsAll.length)
    b.push('<span class="badge'+(wcnt?" b-warn":"")+'">Brief 警告 '+wcnt+' · 提示 '+(warnsAll.length-wcnt)+'</span>');
  $("badges").innerHTML = b.join("");
})();

/* ---------- 策略影子 ---------- */
function navSparkline(points){
  if (!points || !points.length) return "—";
  const W=150,H=38,P=3, vals=points.map(p=>Number(p.nav)).filter(Number.isFinite);
  if (!vals.length) return "—";
  let lo=Math.min(...vals), hi=Math.max(...vals);
  if (hi===lo){ hi+=1; lo-=1; }
  const x=i=>P+(W-2*P)*(points.length===1?0.5:i/(points.length-1));
  const y=v=>P+(H-2*P)*(1-(v-lo)/(hi-lo));
  const coords=points.map((p,i)=>x(i)+","+y(Number(p.nav))).join(" ");
  return '<svg class="sparkline" viewBox="0 0 '+W+' '+H+'" role="img" aria-label="近60日NAV">'
    +'<line x1="'+P+'" y1="'+(H-P)+'" x2="'+(W-P)+'" y2="'+(H-P)+'" stroke="var(--grid)"/>'
    +(points.length>1?'<polyline fill="none" stroke="var(--blue)" stroke-width="2" points="'+coords+'"/>'
      :'<circle cx="'+x(0)+'" cy="'+y(vals[0])+'" r="3" fill="var(--blue)"/>')
    +'</svg>';
}
(function strategyBlock(){
  const rows = strategy && strategy.strategies || [];
  if (!rows.length) return;
  $("sec-strategy").style.display = "";
  const body = rows.map(r=>{
    const modeForward = r.record_mode === "FORWARD_CAPTURE";
    const target = (r.target_lots>0?"+":"")+String(r.target_lots)+" 手";
    const entry = r.entry_date || "—";
    const navDiff = r.nav_difference_vs_baseline==null ? "—" : fmt.signed(r.nav_difference_vs_baseline,2);
    return '<tr><td class="tl"><span class="strategy-key">'+esc(r.strategy_key)+'</span>'
      +'<span class="strategy-sub">'+esc(r.status)+' · '+esc(r.latest_date)+'</span></td>'
      +'<td class="tl"><span class="chip small '+(modeForward?"mode-forward":"mode-replay")+'">'
      +esc(r.record_mode)+'</span></td>'
      +'<td><strong>'+esc(target)+'</strong><span class="strategy-sub">'+esc(r.target_contract||"—")+'</span></td>'
      +'<td class="tl">'+dirChip(r.direction)+'</td>'
      +'<td>'+fmt.num(r.nav,2)+'</td><td class="'+cls(r.drawdown)+'">'+fmt.pct(r.drawdown)+'</td>'
      +'<td>'+esc(entry)+'</td><td>'+fmt.num(r.holding_days)+'</td><td>'+esc(navDiff)+'</td>'
      +'<td>'+navSparkline(r.nav_series)+'</td></tr>';
  }).join("");
  $("strategy-table").innerHTML = '<table><thead><tr><th class="tl">策略</th><th class="tl">记录模式</th>'
    +'<th>当前目标</th><th class="tl">方向</th><th>NAV</th><th>回撤</th><th>入场日</th>'
    +'<th>持仓日</th><th>相对基准</th><th>近60日NAV</th></tr></thead><tbody>'+body+'</tbody></table>';
  $("strategy-note").textContent = strategy.research_boundary || "策略影子为研究记账，不构成交易指令。";
})();

/* ---------- KPI ---------- */
(function kpis(){
  const main = activity[0] || {};
  const mf = factors.multi_factor || {};
  const rows = matrixCtx.rows || [];
  const ph = matrixCtx.primary_horizon;
  const prow = rows.find(r=>r.horizon===ph) || rows[0] || {};
  const k = [];
  k.push({label:"主力结算价 · "+(facts.main_contract||"—"),
    value:fmt.num(facts.main_settle),
    sub:'<span class="'+cls(main.settle_change)+'">'+fmt.signed(main.settle_change)
      +" ("+fmt.pct(main.settle_return)+")</span> · 持仓 "+fmt.num(facts.main_open_interest)
      +' <span class="'+cls(facts.main_oi_change)+'">'+fmt.signed(facts.main_oi_change)+"</span>"});
  k.push({label:"多因子方向（4 因子）",
    value:dirChip(mf.direction, "分数 "+(mf.score==null?"—":mf.score)),
    sub:"置信度 "+(CONF[mf.confidence]||mf.confidence||"—")+" · 可用信号 "+(mf.available_signal_count==null?"—":mf.available_signal_count)+"/4"});
  const phName = (PHASES.find(p=>p[0]===phase.phase_code)||[])[1] || phase.phase_label || "—";
  k.push({label:"趋势阶段（R24 主流程）",
    value:'<span class="chip" style="color:var('+(PHCOLOR[phase.phase_code]||"--muted")+');background:var(--tint-muted)">'
      +esc(phase.phase_code||"—")+" "+esc(phName)+"</span>",
    sub:"方向 "+(DIR[phase.direction]?DIR[phase.direction].t:"—")+" · 置信度 "+(CONF[phase.confidence]||phase.confidence||"—")
      + (watch && watch.v2_phase ? " · v2: "+esc(watch.v2_phase.code)+" "+esc(watch.v2_phase.label) : "")});
  k.push({label:"期权过滤（主周期 "+(ph||"—")+"D）",
    value:optChip(prow.option_signal),
    sub:"PCR OI "+(prow.option_pcr_oi==null?"—":Number(prow.option_pcr_oi).toFixed(3))
      +" · PCR Vol "+(prow.option_pcr_volume==null?"—":Number(prow.option_pcr_volume).toFixed(3))
      +" · IV rank "+(prow.option_atm_iv_rank==null?"—":(prow.option_atm_iv_rank*100).toFixed(1)+"%")});
  k.push({label:"期限结构 proxy",
    value:'<span style="font-size:19px">'+fmt.pct(term.carry_annualized)+'</span>',
    sub:"年化 carry · 曲线斜率 "+fmt.pct(term.curve_slope)
      +" · 远月价差 "+fmt.signed(term.far_minus_main)});
  $("kpis").innerHTML = k.map(x=>'<div class="kpi"><div class="k-label">'+x.label
    +'</div><div class="k-value">'+x.value+'</div><div class="k-sub">'+x.sub+"</div></div>").join("");
})();

/* ---------- 市场事实表 ---------- */
(function activityTable(){
  if (!activity.length){ $("activity-table").innerHTML = '<div class="section-note">无合约活跃度数据</div>'; return; }
  const maxVol = Math.max(...activity.map(r=>r.volume||0), 1);
  const maxOI = Math.max(...activity.map(r=>r.open_interest||0), 1);
  const rows = activity.map(r=>{
    const isMain = r.contract_code === facts.main_contract;
    return '<tr class="'+(isMain?"main-row":"")+'">'
      +'<td class="tl"><strong>'+esc(r.contract_code)+'</strong>'+(isMain?' <span class="chip small c-blue">主力</span>':"")+'</td>'
      +'<td>'+fmt.num(r.settle)+'</td>'
      +'<td class="'+cls(r.settle_change)+'">'+fmt.signed(r.settle_change)+'</td>'
      +'<td class="'+cls(r.settle_return)+'">'+fmt.pct(r.settle_return)+'</td>'
      +'<td><span class="cellbar" style="width:'+Math.round(56*(r.volume||0)/maxVol)+'px"></span>'+fmt.num(r.volume)+'</td>'
      +'<td><span class="cellbar" style="width:'+Math.round(56*(r.open_interest||0)/maxOI)+'px;opacity:.55"></span>'+fmt.num(r.open_interest)+'</td>'
      +'<td class="'+cls(r.oi_change)+'">'+fmt.signed(r.oi_change)+'</td></tr>';
  }).join("");
  $("activity-table").innerHTML = '<table><thead><tr><th class="tl">合约</th><th>结算价</th>'
    +'<th>涨跌</th><th>涨跌幅</th><th>成交量</th><th>持仓量</th><th>持仓变化</th></tr></thead><tbody>'
    +rows+"</tbody></table>";
})();

/* ---------- 图表 ---------- */
const tooltip = $("tooltip");
function showTip(e, html){ tooltip.innerHTML = html; tooltip.style.display="block"; moveTip(e); }
function moveTip(e){ const pad=14; let x=e.clientX+pad, y=e.clientY+pad;
  const r=tooltip.getBoundingClientRect();
  if(x+r.width>innerWidth-8) x=e.clientX-r.width-pad;
  if(y+r.height>innerHeight-8) y=e.clientY-r.height-pad;
  tooltip.style.left=x+"px"; tooltip.style.top=y+"px"; }
function hideTip(){ tooltip.style.display="none"; }

function termChart(){
  const el = $("term-chart"); el.innerHTML = "";
  const data = activity.slice().filter(r=>r.settle!=null)
    .sort((a,b)=>String(a.contract_code).localeCompare(String(b.contract_code)));
  if (data.length < 2){ el.innerHTML = '<div class="section-note">合约数不足，无法绘制曲线</div>'; return; }
  const W = el.clientWidth || 460, H = 218, m = {t:24,r:18,b:26,l:46};
  const xs = i => m.l + (W-m.l-m.r) * (data.length===1?0.5:i/(data.length-1));
  const vals = data.map(d=>d.settle);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = Math.max((hi-lo)*0.18, 20); lo-=pad; hi+=pad;
  const ys = v => m.t + (H-m.t-m.b) * (1-(v-lo)/(hi-lo));
  const blue = cssVar("--blue"), gridc = cssVar("--grid"), mutedc = cssVar("--muted"),
        ink = cssVar("--ink"), base = cssVar("--baseline"), surface = cssVar("--surface");
  let s = '<svg width="'+W+'" height="'+H+'" role="img" aria-label="期限结构曲线">';
  for(let g=0; g<4; g++){ const v = lo + (hi-lo)*g/3, y = ys(v);
    s += '<line x1="'+m.l+'" y1="'+y+'" x2="'+(W-m.r)+'" y2="'+y+'" stroke="'+gridc+'" stroke-width="1"/>'
      + '<text x="'+(m.l-7)+'" y="'+(y+3.5)+'" text-anchor="end" font-size="10.5" fill="'+mutedc+'">'+Math.round(v).toLocaleString()+'</text>'; }
  s += '<polyline fill="none" stroke="'+blue+'" stroke-width="2" points="'
    + data.map((d,i)=>xs(i)+","+ys(d.settle)).join(" ") + '"/>';
  data.forEach((d,i)=>{
    const isMain = d.contract_code===facts.main_contract;
    s += '<circle cx="'+xs(i)+'" cy="'+ys(d.settle)+'" r="'+(isMain?5:4)+'" fill="'+blue
      +'" stroke="'+surface+'" stroke-width="2" data-i="'+i+'" style="cursor:default"/>';
    s += '<text x="'+xs(i)+'" y="'+(ys(d.settle)-9)+'" text-anchor="middle" font-size="10.5" fill="'
      +(isMain?ink:mutedc)+'" font-weight="'+(isMain?"700":"400")+'">'+Math.round(d.settle).toLocaleString()+'</text>';
    s += '<text x="'+xs(i)+'" y="'+(H-8)+'" text-anchor="middle" font-size="10.5" fill="'
      +(isMain?ink:mutedc)+'" font-weight="'+(isMain?"700":"400")+'">'+esc(d.contract_code)+'</text>';
  });
  s += '<line x1="'+m.l+'" y1="'+(H-m.b)+'" x2="'+(W-m.r)+'" y2="'+(H-m.b)+'" stroke="'+base+'" stroke-width="1"/></svg>';
  el.innerHTML = s;
  el.querySelectorAll("circle").forEach(c=>{
    const d = data[+c.dataset.i];
    c.addEventListener("mousemove", e=>showTip(e,
      "<strong>"+esc(d.contract_code)+"</strong><br>结算 "+fmt.num(d.settle)
      +" ("+fmt.pct(d.settle_return)+")<br>持仓 "+fmt.num(d.open_interest)
      +" <span class='"+cls(d.oi_change)+"'>"+fmt.signed(d.oi_change)+"</span>"));
    c.addEventListener("mouseleave", hideTip);
  });
  $("term-meta").innerHTML = "近月 "+esc(term.near_contract||"—")+" · 远月 "+esc(term.far_contract||"—")
    +" · 主力交割参考日 "+esc(term.main_delivery_date||"—")+" · tenor "+(term.tenor_days==null?"—":term.tenor_days+" 天");
}

function returnsChart(){
  const el = $("returns-chart"); el.innerHTML = "";
  const mr = factors.main_returns || {};
  const hs = ["1","3","5","10","20"].filter(h=>mr[h]!=null);
  if (!hs.length){ el.innerHTML = '<div class="section-note">无区间收益数据</div>'; return; }
  const W = el.clientWidth || 460, H = 205, m = {t:20,r:12,b:24,l:46};
  const vals = hs.map(h=>mr[h]);
  let hi = Math.max(...vals,0), lo = Math.min(...vals,0);
  const span = Math.max(hi-lo, 0.005), padv = span*0.22; hi+=padv; lo-=padv;
  const ys = v => m.t + (H-m.t-m.b)*(1-(v-lo)/(hi-lo));
  const bw = Math.min(46, (W-m.l-m.r)/hs.length*0.52);
  const up = cssVar("--up"), down = cssVar("--down-mark"), gridc = cssVar("--grid"),
        mutedc = cssVar("--muted"), base = cssVar("--baseline"), ink = cssVar("--ink");
  let s = '<svg width="'+W+'" height="'+H+'" role="img" aria-label="主力区间收益">';
  for(let g=0; g<4; g++){ const v = lo+(hi-lo)*g/3, y=ys(v);
    s += '<line x1="'+m.l+'" y1="'+y+'" x2="'+(W-m.r)+'" y2="'+y+'" stroke="'+gridc+'"/>'
      +'<text x="'+(m.l-7)+'" y="'+(y+3.5)+'" text-anchor="end" font-size="10.5" fill="'+mutedc+'">'+(v*100).toFixed(1)+'%</text>'; }
  const y0 = ys(0);
  hs.forEach((h,i)=>{
    const v = mr[h];
    const x = m.l + (W-m.l-m.r)*(i+0.5)/hs.length - bw/2;
    const y = ys(Math.max(v,0)), hgt = Math.abs(ys(v)-y0);
    const col = v>=0 ? up : down;
    s += '<rect x="'+x+'" y="'+(v>=0?y:y0)+'" width="'+bw+'" height="'+Math.max(hgt,1.5)
      +'" rx="4" fill="'+col+'" data-h="'+h+'"/>';
    s += '<text x="'+(x+bw/2)+'" y="'+(v>=0?y-6:y0+hgt+13)+'" text-anchor="middle" font-size="10.5" fill="'
      +ink+'" font-weight="600">'+fmt.pct(v)+'</text>';
    s += '<text x="'+(x+bw/2)+'" y="'+(H-7)+'" text-anchor="middle" font-size="11" fill="'+mutedc+'">'+h+'D</text>';
  });
  s += '<line x1="'+m.l+'" y1="'+y0+'" x2="'+(W-m.r)+'" y2="'+y0+'" stroke="'+base+'" stroke-width="1"/></svg>';
  el.innerHTML = s;
  el.querySelectorAll("rect").forEach(r=>{
    const h = r.dataset.h;
    r.addEventListener("mousemove", e=>showTip(e,"<strong>"+h+" 日区间收益</strong><br>"+fmt.pct(mr[h],3)));
    r.addEventListener("mouseleave", hideTip);
  });
}

function ladder(){
  const el = $("ladder"); if(!el) return; el.innerHTML = "";
  const lv = (watch && watch.levels) || {};
  const cur = facts.main_settle, ma20 = factors.ma20;
  const items = [];
  if (lv.confirm!=null) items.push({v:lv.confirm, t:"确认参考位", c:cssVar("--blue")});
  if (ma20!=null) items.push({v:ma20, t:"MA20", c:cssVar("--muted"), dash:1});
  if (lv.ma_invalid!=null) items.push({v:lv.ma_invalid, t:"均线失效参考位", c:cssVar("--warn")});
  if (lv.strong_invalid!=null) items.push({v:lv.strong_invalid, t:"强失效参考位", c:cssVar("--serious")});
  if (!items.length || cur==null){ el.innerHTML = '<div class="section-note">无价格窗口数据</div>'; return; }
  const all = items.map(i=>i.v).concat([cur]);
  let lo = Math.min(...all), hi = Math.max(...all);
  const pad = Math.max((hi-lo)*0.14, 30); lo-=pad; hi+=pad;
  const W = el.clientWidth || 460, H = 232, m = {t:14,r:88,b:12,l:118};
  const ys = v => m.t + (H-m.t-m.b)*(1-(v-lo)/(hi-lo));
  const ink = cssVar("--ink"), surface = cssVar("--surface");
  let s = '<svg width="'+W+'" height="'+H+'" role="img" aria-label="价格窗口">';
  items.sort((a,b)=>b.v-a.v);
  // 标签防重叠：线保持真实位置，文字过近时向下让位
  let prevLabelY = -1e9;
  items.forEach(it=>{
    it.y = ys(it.v);
    it.ly = Math.max(it.y, prevLabelY + 13);
    prevLabelY = it.ly;
  });
  items.forEach(it=>{
    s += '<line x1="'+m.l+'" y1="'+it.y+'" x2="'+(W-m.r)+'" y2="'+it.y+'" stroke="'+it.c
      +'" stroke-width="2"'+(it.dash?' stroke-dasharray="5,4" stroke-width="1.5"':"")+'/>';
    s += '<text x="'+(m.l-8)+'" y="'+(it.ly+3.5)+'" text-anchor="end" font-size="11" fill="'+it.c+'" font-weight="600">'+esc(it.t)+'</text>';
    s += '<text x="'+(W-m.r+8)+'" y="'+(it.ly+3.5)+'" font-size="11" fill="'+it.c+'" font-weight="600">'+fmt.num(it.v, it.v%1?2:0)+'</text>';
  });
  const cy = ys(cur);
  const nearLine = items.some(it=>Math.abs(it.y-cy)<11);
  s += '<circle cx="'+((m.l+W-m.r)/2)+'" cy="'+cy+'" r="6" fill="'+ink+'" stroke="'+surface+'" stroke-width="2.5"/>';
  s += '<text x="'+((m.l+W-m.r)/2+12)+'" y="'+(cy+(nearLine?16:4))+'" font-size="11.5" fill="'+ink+'" font-weight="700">最新结算 '+fmt.num(cur)+'</text>';
  s += '</svg>';
  el.innerHTML = s;
}

function renderCharts(){ termChart(); returnsChart(); ladder(); }

/* ---------- 因子信号 ---------- */
(function factorBlock(){
  const st = factors.states || {};
  const names = {momentum:"动量 momentum", carry:"持有成本 carry", curve:"曲线 curve", oi_pressure:"持仓压力 OI"};
  $("factor-chips").innerHTML = Object.keys(names).map(k=>{
    return '<div class="fchip"><div class="f-name">'+names[k]+'</div><div class="f-val">'+dirChip(st[k])+"</div></div>";
  }).join("");
  const mf = factors.multi_factor || {};
  $("multifactor").innerHTML = '<h3>多因子合成</h3><div>'
    + dirChip(mf.direction, "score "+(mf.score==null?"—":mf.score))
    + ' <span class="chip small c-neutral">置信度 '+(CONF[mf.confidence]||mf.confidence||"—")+"</span>"
    + ' <span class="chip small c-neutral">MA20 '+fmt.num(factors.ma20,2)+"</span></div>"
    + '<div class="section-note">等权 4 因子方向投票；期权信号仅作过滤，不进入 composite score。</div>';
})();

/* ---------- 多周期矩阵 ---------- */
(function matrixTable(){
  const rows = matrixCtx.rows || [];
  if (!rows.length){ $("matrix-table").innerHTML = '<div class="section-note">未提供信号矩阵（status: '
    +esc(matrixCtx.status||"NOT_PROVIDED")+'）</div>'; return; }
  const ph = matrixCtx.primary_horizon;
  const body = rows.map(r=>{
    const flags = String(r.warning_flags||"").split(";").filter(Boolean)
      .map(f=>'<span class="chip small c-warn">'+esc(FLAG[f]||f)+"</span>").join(" ");
    const phName = (PHASES.find(p=>p[0]===r.trend_phase)||[])[1] || r.trend_phase_label || r.trend_phase || "—";
    return '<tr class="'+(r.horizon===ph?"primary-row":"")+'">'
      +'<td class="tl"><strong>'+r.horizon+"D</strong>"+(r.horizon===ph?' <span class="chip small c-violet">主周期</span>':"")+"</td>"
      +'<td class="tl">'+dirChip(r.direction)+"</td>"
      +'<td class="tl">'+optChip(r.option_signal)+"</td>"
      +'<td class="tl"><span class="meter"><span class="track"><span class="fill" style="width:'
        +Math.max(0,Math.min(100,r.confidence_score||0))+'%"></span></span>'
        +(r.confidence_score==null?"—":Math.round(r.confidence_score))+"</span></td>"
      +'<td class="tl">'+esc(r.trend_phase||"—")+" "+esc(phName)+"</td>"
      +"<td>"+esc(EVID[r.evidence_level]||r.evidence_level||"—")+"</td>"
      +'<td class="tl">'+esc(r.action_type||"—")+"</td>"
      +'<td class="tl">'+(flags||'<span class="chip small c-neutral">无</span>')+"</td></tr>";
  }).join("");
  $("matrix-table").innerHTML = '<table><thead><tr><th class="tl">周期</th><th class="tl">方向</th>'
    +'<th class="tl">期权过滤</th><th class="tl">置信分</th><th class="tl">趋势阶段</th>'
    +'<th>证据</th><th class="tl">操作类型</th><th class="tl">风险标签</th></tr></thead><tbody>'+body+"</tbody></table>";
  $("matrix-note").textContent = (matrixCtx.research_boundary||"") + "（主观察周期 "
    + (ph||"—") + "D，方向 " + (DIR[matrixCtx.primary_direction]?DIR[matrixCtx.primary_direction].t:"—")
    + "，置信度 " + (CONF[matrixCtx.primary_confidence]||"—") + "）";
})();

/* ---------- 趋势阶段 ---------- */
(function phaseBlock(){
  const v2 = watch && watch.v2_phase;
  function stepper(code, tag){
    return '<div class="stepper">'+PHASES.map(p=>{
      const active = p[0]===code;
      const cvar = PHCOLOR[p[0]]||"--muted";
      return '<div class="step'+(active?" active":"")+'"'
        +(active?' style="background:color-mix(in srgb,var('+cvar+') 12%,var(--surface));border-color:var('+cvar+')"':"")
        +'><div class="s-code"'+(active?' style="color:var('+cvar+')"':"")+'>'+p[0]+"</div>"
        +'<div>'+p[1]+"</div>"+(active?'<div class="s-mark" style="color:var('+cvar+')">'+tag+"</div>":"")+"</div>";
    }).join("")+"</div>";
  }
  let html = '<h3>R24 主流程判定</h3>' + stepper(phase.phase_code, "●");
  html += '<div class="section-note">'+esc(phase.reason||"")+" · 支持信号 "
    +(phase.support_count==null?"—":phase.support_count)+"/"+(phase.available_signal_count==null?"—":phase.available_signal_count)
    +" · 置信度 "+(CONF[phase.confidence]||phase.confidence||"—")+"</div>";
  if (v2){
    html += '<h3 style="margin-top:14px">R76 v2 判定（含双价格 / 全链持仓 / 期权证据）</h3>'
      + stepper(v2.code, "◆")
      + '<div class="section-note">强度 '+esc(v2.strength||"—");
    const stz = (watch && watch.states) || {};
    const chips = [];
    if (stz.dual_price) chips.push(stateCN(stz.dual_price[0])+" / "+stateCN(stz.dual_price[1]));
    if (stz.chain_oi) chips.push(stateCN(stz.chain_oi[0]));
    if (stz.roll) chips.push(stateCN(stz.roll[0]));
    if (stz.option) chips.push(stateCN(stz.option[0])+"("+esc(stz.option[1]||"")+")");
    if (stz.vol_state) chips.push(stateCN(stz.vol_state[0]));
    if (chips.length) html += " · 证据：" + chips.map(esc).join("；");
    html += "</div>";
    if (phase.phase_code && v2.code && phase.phase_code !== v2.code){
      html += '<div class="section-note" style="color:var(--ink2)">⚠ 两套判定不一致（R24 '
        +esc(phase.phase_code)+" vs v2 "+esc(v2.code)+"）：v2 纳入了期权与全链持仓证据，口径更严格，阅读时以版本标注区分。</div>";
    }
  }
  $("phase-block").innerHTML = html;
})();

/* ---------- 观察窗口 ---------- */
(function watchBlock(){
  if (!watch){ return; }
  $("sec-watch").style.display = "";
  const secs = watch.sections || [];
  const judge = secs.find(s=>s.title.indexOf("当前判断")>=0);
  let left = "";
  if (judge){
    left += '<h3>当前判断</h3><ul class="mdlist">'
      + judge.lines.map(l=>"<li>"+mdInline(l.replace(/^-\s*/,""))+"</li>").join("") + "</ul>";
  }
  $("watch-left").innerHTML = left || '<div class="section-note">无当前判断内容</div>';
  const conf = secs.find(s=>s.title.indexOf("确认条件")>=0);
  const fail = secs.find(s=>s.title.indexOf("失效条件")>=0);
  let conds = "";
  if (conf) conds += '<div class="cond ok"><h3>结构确认条件</h3><ul class="mdlist">'
    + conf.lines.map(l=>"<li>"+mdInline(l.replace(/^-\s*/,""))+"</li>").join("")+"</ul></div>";
  if (fail) conds += '<div class="cond bad"><h3>结构失效条件</h3><ul class="mdlist">'
    + fail.lines.map(l=>"<li>"+mdInline(l.replace(/^-\s*/,""))+"</li>").join("")+"</ul></div>";
  $("watch-conds").innerHTML = conds;
  let rv = "";
  if (watch.review_dates) rv += "T+1 / T+3 / T+5 暂定复核日：<strong>"
    + watch.review_dates.map(esc).join(" / ")+"</strong>（按工作日暂定，须用官方交易日历复核）";
  if (watch.avg_resolution_days!=null) rv += " · 历史平均解决周期 "+watch.avg_resolution_days+" 个交易日";
  $("watch-review").innerHTML = rv;
})();

/* ---------- 警告 / 人工复核 ---------- */
(function warnBlock(){
  const items = S.watch_items || [];
  let html = "";
  if (items.length){
    html += '<h3>明日观察清单</h3><ul class="mdlist watchitems">'
      + items.map(x=>"<li>"+esc(x)+"</li>").join("") + "</ul>";
  }
  $("watch-list").innerHTML = html;
  const warns = brief.warnings || [];
  if (warns.length){
    const rows = warns.map(w=>{
      const sev = String(w.severity||"INFO").toUpperCase();
      const c = sev==="WARN"||sev==="WARNING" ? "c-warn" : (sev==="ERROR"?"c-crit":"c-neutral");
      return '<tr><td class="tl"><span class="chip small '+c+'">'+esc(sev)+"</span></td>"
        +'<td class="tl"><code class="inlinecode">'+esc(w.warning_code||"—")+"</code></td>"
        +'<td class="tl" style="white-space:normal">'+esc(w.warning_message||"")+"</td>"
        +'<td class="tl">'+esc(w.section||"")+"</td></tr>";
    }).join("");
    $("warn-table").innerHTML = '<h3 style="margin-top:14px">运行警告（'+warns.length+'）</h3>'
      +'<table><thead><tr><th class="tl">级别</th><th class="tl">代码</th><th class="tl">说明</th>'
      +'<th class="tl">来源</th></tr></thead><tbody>'+rows+"</tbody></table>";
  }
  const hr = brief.human_review_required || [];
  if (hr.length){
    $("human-review").innerHTML = '<h3 style="margin-top:14px">人工复核项（'+hr.length+'）</h3>'
      +'<div class="hr-chips">'+hr.map(x=>'<span class="badge b-warn">'+esc(x)+"</span>").join("")+"</div>";
  }
})();

/* ---------- 页脚 ---------- */
(function footer(){
  const ds = (S.data_status||{});
  const snaps = (ds.input_snapshot_ids||[]).join("; ");
  $("footer").innerHTML =
    "报告类型 latest_signal_only（规则 "+esc(S.rule_version||"—")+"） · 数据截至 <strong>"+esc(ds.data_asof||DATA.trade_date||"—")
    +"</strong> · 最新日行数 "+(ds.latest_row_count==null?"—":ds.latest_row_count)
    +"<br>输入快照：<code>"+esc(snaps||"—")+"</code>"
    +"<br>数据源：<code>"+esc(DATA.source.brief||"")+"</code>"
    +(DATA.source.watch?" · <code>"+esc(DATA.source.watch)+"</code>":"")
    +(DATA.source.audit?" · <code>"+esc(DATA.source.audit)+"</code>":"")
    +(DATA.source.strategy?" · <code>"+esc(DATA.source.strategy)+"</code>":"")
    +"<br>页面生成于 "+esc(DATA.generated_at)+"（"+esc(DATA.rule_version)+"）"
    +" · 本页面为研究观察展示，未包含未来收益标签，未完成 forward-return 验证，不构成投资建议或交易指令。";
})();

/* ==================== 微信分享图 ==================== */
(function shareModule(){
  const FONT = 'system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif';
  const C = { bg:"#f5f5f2", card:"#ffffff", border:"#e6e5df", ink:"#141412", ink2:"#52514e",
    muted:"#8b8983", grid:"#ecebe6", blue:"#2a78d6", violet:"#4a3aa7", up:"#d03b3b",
    down:"#0a7a0a", warnT:"#a06c00", serious:"#c2542d", wechat:"#07C160",
    tintBlue:"#eaf2fc", tintUp:"#fbeaea", tintDown:"#eaf6ea", tintWarn:"#fdf3dd", tintMuted:"#f0efeb" };
  const ctxM = document.createElement("canvas").getContext("2d");
  function mw(s, font){ ctxM.font = font; return ctxM.measureText(s).width; }
  function wrapText(s, font, maxW){
    ctxM.font = font; const lines = []; let cur = "";
    for (const ch of String(s)){
      if (cur && ctxM.measureText(cur+ch).width > maxW){ lines.push(cur); cur = ch; }
      else cur += ch;
    }
    if (cur) lines.push(cur); return lines;
  }
  function xml(s){ return String(s==null?"":s).replace(/[&<>"']/g,
    c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
  function dirColor(d){ return d==="long"?C.up : d==="short"?C.down : C.muted; }
  function dirBg(d){ return d==="long"?C.tintUp : d==="short"?C.tintDown : C.tintMuted; }
  function dirText(d){ const m = DIR[d]||DIR.unknown; return m.a+" "+m.t; }

  function buildShareCard(){
    const W = 750, M = 28, CP = 22, IW = W - 2*M - 2*CP; // 卡片内容宽 650
    const B = [];
    function R2(x,y,w,h,r,fill,stroke,sw,dash){
      B.push('<rect x="'+x+'" y="'+y+'" width="'+w+'" height="'+h+'" rx="'+r+'" fill="'+fill+'"'
        +(stroke?' stroke="'+stroke+'" stroke-width="'+(sw||1)+'"':"")
        +(dash?' stroke-dasharray="'+dash+'"':"")+'/>');
    }
    function T2(x,y,s,size,color,weight,anchor){
      B.push('<text x="'+x+'" y="'+y+'" font-size="'+size+'" fill="'+color
        +'" font-weight="'+(weight||400)+'"'+(anchor?' text-anchor="'+anchor+'"':"")+'>'+xml(s)+"</text>");
    }
    function L2(x1,y1,x2,y2,color,swd,dash){
      B.push('<line x1="'+x1+'" y1="'+y1+'" x2="'+x2+'" y2="'+y2+'" stroke="'+color
        +'" stroke-width="'+(swd||1)+'"'+(dash?' stroke-dasharray="'+dash+'"':"")+'/>');
    }
    function chip(x, yMid, label, color, bg, size){
      size = size || 13; const f = "600 "+size+"px "+FONT;
      const w = mw(label, f) + 20, h = size + 11;
      R2(x, yMid-h/2, w, h, h/2, bg);
      B.push('<text x="'+(x+w/2)+'" y="'+(yMid+size*0.36)+'" font-size="'+size+'" fill="'+color
        +'" font-weight="600" text-anchor="middle">'+xml(label)+"</text>");
      return w;
    }
    function cardStart(title){ // 返回卡片起始 y，正文由调用方绘制，最后 cardEnd 收口
      const y0 = y;
      cardMeta = { y0: y0 };
      y += CP + 6;
      if (title){ T2(M+CP, y+8, title, 17, C.ink, 700); y += 26; }
      return y;
    }
    let cardMeta = null;
    const cardRects = [];
    function cardEnd(){
      y += CP - 4;
      cardRects.push([cardMeta.y0, y]);
      y += 14;
    }

    const main = activity[0] || {};
    const mf = factors.multi_factor || {};
    const rowsM = matrixCtx.rows || [];
    const ph = matrixCtx.primary_horizon;
    const v2 = watch && watch.v2_phase;
    let y = 0;

    // ---- 顶部
    y = 22;
    T2(M, y+22, (DATA.product||"CF")+" 郑棉 · 最新交易日研究观察", 27, C.ink, 800);
    const dtf = "700 16px "+FONT, dts = DATA.trade_date||"—";
    const dw = mw(dts, dtf)+24;
    R2(W-M-dw, y, dw, 32, 8, C.card, C.border, 1);
    T2(W-M-dw/2, y+21.5, dts, 16, C.ink, 700, "middle");
    y += 46;
    T2(M, y+8, "主力合约 "+(brief.main_contract||"—")+" · latest signal-only · "+(brief.run_id||""), 12.5, C.muted);
    y += 26;

    // ---- 主力行情卡
    cardStart(null);
    const hx = M+CP;
    T2(hx, y+12, "主力结算价（"+(facts.main_contract||"—")+"）", 13, C.ink2); y += 22;
    const settleStr = fmt.num(facts.main_settle);
    T2(hx, y+42, settleStr, 48, C.ink, 800);
    const sw2 = mw(settleStr, "800 48px "+FONT);
    chip(hx+sw2+14, y+26, fmt.signed(main.settle_change)+" ("+fmt.pct(main.settle_return)+")",
      (main.settle_change||0) >= 0 ? C.up : C.down,
      (main.settle_change||0) >= 0 ? C.tintUp : C.tintDown, 15);
    // 右侧两行
    T2(W-M-CP, y+8, "成交量 "+fmt.num(facts.main_volume), 13, C.ink2, 400, "end");
    T2(W-M-CP, y+30, "持仓 "+fmt.num(facts.main_open_interest)+"（"+fmt.signed(facts.main_oi_change)+"）", 13,
      (facts.main_oi_change||0) < 0 ? C.down : C.up, 600, "end");
    y += 56;
    T2(hx, y+10, "年化 carry "+fmt.pct(term.carry_annualized)+" · 曲线斜率 "+fmt.pct(term.curve_slope)
      +" · 远月价差 "+fmt.signed(term.far_minus_main)+"（"+(term.far_contract||"—")+"）", 12.5, C.muted);
    y += 14;
    cardEnd();

    // ---- 策略影子卡
    const strategyRows = strategy && strategy.strategies || [];
    if (strategyRows.length){
      cardStart("策略影子（研究记账）");
      strategyRows.slice(0,3).forEach((r,i)=>{
        if (i) L2(M+CP, y, M+CP+IW, y, C.grid);
        const targetText = (r.target_lots>0?"+":"")+r.target_lots+" 手 · "+(r.target_contract||"—");
        T2(M+CP, y+21, r.strategy_key, 14, C.ink, 700);
        T2(M+CP+180, y+21, targetText, 13.5, dirColor(r.direction), 700);
        T2(M+CP+390, y+21, "NAV "+fmt.num(r.nav,2), 13.5, C.ink2, 600);
        T2(M+CP+IW, y+21, "回撤 "+fmt.pct(r.drawdown), 13, r.drawdown<0?C.warnT:C.muted, 600, "end");
        T2(M+CP, y+42, (r.record_mode||"—")+" · 前向 "+(r.forward_capture_days||0)
          +" 日 · 持仓 "+(r.holding_days||0)+" 日", 11.5, C.muted);
        y += 50;
      });
      cardEnd();
    }

    // ---- 因子信号卡
    cardStart("因子信号");
    const st = factors.states || {};
    const fnames = [["momentum","动量"],["carry","持有成本"],["curve","曲线"],["oi_pressure","持仓压力"]];
    const bw2 = (IW - 3*10) / 4;
    fnames.forEach((f,i)=>{
      const x = M+CP + i*(bw2+10);
      R2(x, y, bw2, 58, 9, C.bg, C.border, 1);
      T2(x+12, y+22, f[1], 12, C.muted);
      T2(x+12, y+45, dirText(st[f[0]]), 15, dirColor(st[f[0]]), 700);
    });
    y += 70;
    T2(M+CP, y+12, "多因子合成：", 13.5, C.ink2);
    const mfx = M+CP + mw("多因子合成：", "400 13.5px "+FONT) + 6;
    chip(mfx, y+7, dirText(mf.direction)+" score "+(mf.score==null?"—":mf.score), dirColor(mf.direction), dirBg(mf.direction), 13);
    T2(mfx+150, y+12, "置信度 "+(CONF[mf.confidence]||mf.confidence||"—")+" · MA20 "+fmt.num(factors.ma20,2), 13, C.muted);
    y += 24;
    cardEnd();

    // ---- 趋势阶段卡
    cardStart("趋势阶段");
    const pw = (IW - 4*8) / 5;
    PHASES.forEach((p,i)=>{
      const x = M+CP + i*(pw+8);
      const isR24 = phase.phase_code===p[0], isV2 = v2 && v2.code===p[0];
      R2(x, y, pw, 46, 8, isR24?C.tintBlue:(isV2?C.tintWarn:C.bg),
        isR24?C.blue:(isV2?C.warnT:C.border), (isR24||isV2)?2:1);
      T2(x+10, y+19, p[0], 13, isR24?C.blue:(isV2?C.warnT:C.muted), 800);
      T2(x+10, y+37, p[1], 11.5, isR24||isV2?C.ink:C.muted);
      if (isR24) T2(x+pw-10, y+19, "●", 11, C.blue, 700, "end");
      if (isV2) T2(x+pw-10, y+(isR24?37:19), "◆", 11, C.warnT, 700, "end");
    });
    y += 58;
    T2(M+CP, y+12, "● R24 主流程："+(phase.phase_code||"—")+" "
      +((PHASES.find(p=>p[0]===phase.phase_code)||[])[1]||"")+"（"+(DIR[phase.direction]?DIR[phase.direction].t:"—")
      +" / 置信度 "+(CONF[phase.confidence]||"—")+"）", 12.5, C.ink2);
    y += 20;
    if (v2){
      T2(M+CP, y+12, "◆ R76 v2（含双价格/全链持仓/期权证据）："+v2.code+" "+v2.label+" / "+(v2.strength||"—")
        +(phase.phase_code!==v2.code ? "，与 R24 口径不一致，以版本标注区分" : ""), 12.5, C.warnT);
      y += 20;
    }
    cardEnd();

    // ---- 多周期矩阵卡
    if (rowsM.length){
      cardStart("多周期信号矩阵（R35）");
      const cols = [0, 70, 190, 330, 480];
      T2(M+CP+cols[0], y+8, "周期", 11.5, C.muted);
      T2(M+CP+cols[1], y+8, "方向", 11.5, C.muted);
      T2(M+CP+cols[2], y+8, "期权过滤", 11.5, C.muted);
      T2(M+CP+cols[3], y+8, "置信分", 11.5, C.muted);
      T2(M+CP+cols[4], y+8, "趋势阶段", 11.5, C.muted);
      y += 16;
      rowsM.forEach(r=>{
        const rowY = y, isP = r.horizon===ph;
        if (isP) R2(M+CP-8, rowY+2, IW+16, 30, 6, "#f1eefc");
        L2(M+CP, rowY, M+CP+IW, rowY, C.grid);
        T2(M+CP+cols[0], rowY+22, r.horizon+"D"+(isP?" ★":""), 13.5, isP?C.violet:C.ink, 700);
        T2(M+CP+cols[1], rowY+22, dirText(r.direction), 13, dirColor(r.direction), 700);
        const om = OPT[r.option_signal]||{t:r.option_signal||"—"};
        const oc = /^confirm_long/.test(r.option_signal||"")?C.up
          :/^confirm_short/.test(r.option_signal||"")?C.down
          :/diverge|volatility/.test(r.option_signal||"")?C.warnT:C.muted;
        T2(M+CP+cols[2], rowY+22, om.t, 13, oc, 600);
        const cs = Math.max(0, Math.min(100, r.confidence_score||0));
        R2(M+CP+cols[3], rowY+13, 90, 8, 4, C.tintMuted);
        R2(M+CP+cols[3], rowY+13, 90*cs/100, 8, 4, C.blue);
        T2(M+CP+cols[3]+98, rowY+22, String(Math.round(r.confidence_score||0)), 12.5, C.ink2);
        T2(M+CP+cols[4], rowY+22, (r.trend_phase||"—")+" "+(r.trend_phase_label||""), 12.5, C.ink2);
        y += 32;
      });
      T2(M+CP, y+14, "主观察周期 "+(ph||"—")+"D · 期权信号仅作过滤，不进入 composite score", 11.5, C.muted);
      y += 20;
      cardEnd();
    }

    // ---- 期限结构卡
    const tdata = activity.slice().filter(r=>r.settle!=null)
      .sort((a,b)=>String(a.contract_code).localeCompare(String(b.contract_code)));
    if (tdata.length >= 2){
      cardStart("期限结构（结算价）");
      const chH = 120, chY = y + 14;
      const vals = tdata.map(d=>d.settle);
      let lo = Math.min(...vals), hi = Math.max(...vals);
      const padv = Math.max((hi-lo)*0.22, 25); lo-=padv; hi+=padv;
      const xs2 = i => M+CP+18 + (IW-36) * (i/(tdata.length-1));
      const ys2 = v => chY + chH * (1-(v-lo)/(hi-lo));
      B.push('<polyline fill="none" stroke="'+C.blue+'" stroke-width="2.5" points="'
        +tdata.map((d,i)=>xs2(i)+","+ys2(d.settle)).join(" ")+'"/>');
      tdata.forEach((d,i)=>{
        const isMain = d.contract_code===facts.main_contract;
        B.push('<circle cx="'+xs2(i)+'" cy="'+ys2(d.settle)+'" r="'+(isMain?5.5:4)
          +'" fill="'+C.blue+'" stroke="#fff" stroke-width="2"/>');
        T2(xs2(i), ys2(d.settle)-10, Math.round(d.settle).toLocaleString(), 11.5, isMain?C.ink:C.muted, isMain?800:400, "middle");
        T2(xs2(i), chY+chH+20, d.contract_code, 11.5, isMain?C.ink:C.muted, isMain?800:400, "middle");
        if (isMain) T2(xs2(i), chY+chH+36, "主力", 10.5, C.blue, 700, "middle");
      });
      y = chY + chH + 44;
      cardEnd();
    }

    // ---- 价格窗口卡
    const lv = (watch && watch.levels) || {};
    if (Object.keys(lv).length){
      cardStart("价格窗口（R77 观察窗口）");
      const items = [];
      if (lv.confirm!=null) items.push({t:"确认参考位", v:lv.confirm, c:C.blue});
      if (factors.ma20!=null) items.push({t:"MA20", v:factors.ma20, c:C.muted});
      if (lv.ma_invalid!=null) items.push({t:"均线失效参考位", v:lv.ma_invalid, c:C.warnT});
      if (facts.main_settle!=null) items.push({t:"最新结算价", v:facts.main_settle, c:C.ink, cur:1});
      if (lv.strong_invalid!=null) items.push({t:"强失效参考位", v:lv.strong_invalid, c:C.serious});
      items.sort((a,b)=>b.v-a.v);
      items.forEach(it=>{
        if (it.cur) R2(M+CP-8, y, IW+16, 30, 6, C.tintMuted);
        B.push('<circle cx="'+(M+CP+7)+'" cy="'+(y+15)+'" r="5" fill="'+it.c+'"/>');
        T2(M+CP+22, y+20, it.t, 13.5, it.cur?C.ink:C.ink2, it.cur?800:400);
        T2(M+CP+IW, y+20, fmt.num(it.v, it.v%1?2:0), 15, it.c, 800, "end");
        y += 30;
      });
      if (watch.review_dates)
        { T2(M+CP, y+16, "T+1/T+3/T+5 暂定复核日 "+watch.review_dates.join(" / ")+"（须按官方交易日历复核）", 11.5, C.muted); y += 22; }
      cardEnd();
    }

    // ---- 明日观察卡
    const items2 = (S.watch_items||[]).slice(0,3);
    if (items2.length){
      cardStart("明日观察清单");
      items2.forEach(it=>{
        const lines = wrapText(it, "400 13.5px "+FONT, IW-24);
        lines.forEach((ln,j)=>{
          if (j===0) B.push('<circle cx="'+(M+CP+6)+'" cy="'+(y+11)+'" r="3" fill="'+C.blue+'"/>');
          T2(M+CP+20, y+16, ln, 13.5, C.ink2);
          y += 22;
        });
        y += 4;
      });
      cardEnd();
    }

    // ---- 底部声明
    y += 4;
    L2(M, y, W-M, y, C.border); y += 20;
    T2(M, y, "研究边界：不含未来收益标签 · 影子 NAV 非真实资金 · 不构成投资建议或交易指令", 12, C.ink2, 600);
    y += 20;
    T2(M, y, "最新日信号、因子阈值与趋势阶段仍需人工复核 · 数据截至 "+(DATA.trade_date||"—")
      +" · 生成于 "+DATA.generated_at, 11.5, C.muted);
    y += 20;
    T2(M, y, "Cottonquant · CF 研究级生产数据决策工作台", 11.5, C.muted);
    T2(W-M, y, "latest signal-only", 11.5, C.muted, 400, "end");
    y += 26;

    const H = Math.ceil(y);
    // 组装：背景 → 卡片底 → 内容 → 顶部色条
    const head = '<svg xmlns="http://www.w3.org/2000/svg" width="'+W+'" height="'+H
      +'" viewBox="0 0 '+W+" "+H+'" font-family=\''+FONT+"'>"
      +'<defs><linearGradient id="acc" x1="0" y1="0" x2="1" y2="0">'
      +'<stop offset="0" stop-color="'+C.blue+'"/><stop offset="1" stop-color="'+C.violet+'"/>'
      +"</linearGradient></defs>"
      +'<rect width="'+W+'" height="'+H+'" fill="'+C.bg+'"/>'
      +cardRects.map(cr=>'<rect x="'+M+'" y="'+cr[0]+'" width="'+(W-2*M)+'" height="'+(cr[1]-cr[0])
        +'" rx="14" fill="'+C.card+'" stroke="'+C.border+'" stroke-width="1"/>').join("")
      +'<rect width="'+W+'" height="6" fill="url(#acc)"/>';
    return { svg: head + B.join("") + "</svg>", w: W, h: H };
  }

  function svgToPng(svg, w, h, scale){
    return new Promise(function(resolve, reject){
      const img = new Image();
      img.onload = function(){
        const c = document.createElement("canvas");
        c.width = Math.round(w*scale); c.height = Math.round(h*scale);
        const g = c.getContext("2d");
        g.scale(scale, scale); g.drawImage(img, 0, 0, w, h);
        c.toBlob(function(b){ b ? resolve({blob:b, canvas:c}) : reject(new Error("toBlob failed")); }, "image/png");
      };
      img.onerror = function(){ reject(new Error("SVG 渲染失败")); };
      img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
    });
  }

  const overlay = $("share-overlay");
  let last = null;
  function toast(msg, ok){
    const t = $("share-toast");
    t.style.display = "block"; t.style.color = ok ? "#0a7a0a" : "#c2542d";
    t.textContent = msg;
  }
  $("sharebtn").addEventListener("click", function(){
    try {
      last = buildShareCard();
      window.__shareSVG = last.svg; window.__shareH = last.h;
      $("share-preview").src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(last.svg);
      $("share-toast").style.display = "none";
      overlay.classList.add("show");
    } catch(e){ alert("生成分享图失败：" + e.message); }
  });
  $("share-close").addEventListener("click", function(){ overlay.classList.remove("show"); });
  overlay.addEventListener("click", function(e){ if (e.target === overlay) overlay.classList.remove("show"); });
  function fileName(){ return (DATA.product||"CF")+"_研究观察_"+(DATA.trade_date||"")+".png"; }
  function download(blob){
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = fileName();
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function(){ URL.revokeObjectURL(url); }, 4000);
  }
  $("share-download").addEventListener("click", function(){
    if (!last) return;
    svgToPng(last.svg, last.w, last.h, 2)
      .then(function(r){ download(r.blob); toast("已下载 "+fileName()+"，微信里从相册/文件发送即可。", true); })
      .catch(function(e){ toast("导出失败："+e.message, false); });
  });
  $("share-copy").addEventListener("click", function(){
    if (!last) return;
    svgToPng(last.svg, last.w, last.h, 2).then(function(r){
      if (navigator.clipboard && window.ClipboardItem){
        return navigator.clipboard.write([new ClipboardItem({"image/png": r.blob})])
          .then(function(){ toast("图片已复制，切到微信聊天窗口 Ctrl+V 发送。", true); })
          .catch(function(){ download(r.blob); toast("剪贴板不可用，已改为下载 PNG。", false); });
      }
      download(r.blob); toast("当前浏览器不支持复制图片，已改为下载 PNG。", false);
    }).catch(function(e){ toast("导出失败："+e.message, false); });
  });
})();

applyTheme(theme);
window.addEventListener("resize", (function(){ let t; return function(){ clearTimeout(t); t=setTimeout(renderCharts,150); };})());
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
