#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CF 研究证据工作台 Studio V2 仪表盘生成器。

用法(在项目根目录 D:\\Cottonquant 下):

    py -3.12 scripts\\build_cf_studio_dashboard.py
    py -3.12 scripts\\build_cf_studio_dashboard.py --date 2026-08-21 --open

输入(全部只读, 不修改任何研究产物):
    runs/daily/CF/<date>/latest_signal_brief.json            # 日更观察(缺该文件的日期跳过)
    runs/daily/CF/<date>/trend_continuity_board.json         # 20日看板
    runs/daily/CF/<date>/data_continuity_audit.json          # 数据审计
    configs/calendars/CZCE_2026_OFFICIAL.csv                 # 交易日历(运行覆盖分析)
    data/research/CF/futures_option_evidence_gate/*module_summary.csv   # R93R 统一证据门控
    data/research/CF/trend_candidate_forward_ledger/events/*/*.json     # R93D 候选前向账本
    reports/strategy/*_evaluation.json                       # R88 策略评估
    reports/research/validated_brief/*_validated_research_brief.json    # 综合验证简报

输出:
    reports/dashboard/CF_studio_<date>.html
    reports/dashboard/CF_studio_latest.html

设计边界:
    - 单文件 HTML, 内嵌提取数据, 无外部依赖, 离线可开;
    - 只读展示; 不读取任何 forward-return / fwd_ret 标签(生成时强制校验);
    - 历史回测与事件后验只作为历史证据, 不构成交易指令或投资建议;
    - 不覆盖现有 build_dashboard.py 的输出。
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAILY_ROOT = ROOT / "runs" / "daily" / "CF"
OUT_DIR = ROOT / "reports" / "dashboard"
CALENDAR = ROOT / "configs" / "calendars" / "CZCE_2026_OFFICIAL.csv"
GATE_DIR = ROOT / "data" / "research" / "CF" / "futures_option_evidence_gate"
LEDGER_EVENTS = ROOT / "data" / "research" / "CF" / "trend_candidate_forward_ledger" / "events"
STRATEGY_DIR = ROOT / "reports" / "strategy"
VALIDATED_DIR = ROOT / "reports" / "research" / "validated_brief"

RULE_VERSION = "cf_studio_dashboard_v2"
FORBIDDEN_DATA_TOKENS = ("forward_return", "fwd_ret")

STRATEGY_FILES = [
    ("CF_tsmom_v0", "基准 · 20日动量波动目标", "CF_tsmom_v0_evaluation.json"),
    ("CF_phase_gated_v0", "阶段门控(FROZEN)", "CF_phase_gated_v0_evaluation.json"),
    ("ovl_option_veto_v0", "期权否决 overlay · R92: WATCH", "ovl_option_veto_v0_evaluation.json"),
    ("ovl_member_position_v0", "会员持仓 overlay · R92: REJECT", "ovl_member_position_v0_evaluation.json"),
    ("ovl_strike_wall_v0", "OI 墙 overlay · R92: WATCH", "ovl_strike_wall_v0_evaluation.json"),
]

# R93C 预登记候选(任务书固定描述)
PREREGISTERED_CANDIDATES = [
    {"hypothesis": "H1_PARTICIPATION_CONFIRM_20D", "name": "持仓参与确认 · 20D", "status": "进入冻结后前向登记", "cls": "strong"},
    {"hypothesis": "H2_WEAK_OPTION_ENV_5D", "name": "弱期权环境失败观察 · 5D", "status": "仅小样本前向观察", "cls": "mid"},
    {"hypothesis": "H3_OI_WALL_3D", "name": "方向侧 OI 墙增仓 · 3D", "status": "仅历史观察, 不进前向账本", "cls": "unk"},
]


def _read_json(path: Path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _g(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def _assert_clean(obj):
    text = json.dumps(obj, ensure_ascii=False).lower()
    for token in FORBIDDEN_DATA_TOKENS:
        if token in text:
            raise SystemExit(f"[ERROR] forbidden token in extracted payload: {token}")


def _assert_clean_text(html: str):
    lowered = html.lower()
    for token in FORBIDDEN_DATA_TOKENS:
        if token in lowered:
            raise SystemExit(f"[ERROR] forbidden token in rendered html: {token}")


# ---------------------------------------------------------------------------
# 日更观察
# ---------------------------------------------------------------------------

def extract_day(date_dir: Path) -> dict | None:
    brief_path = date_dir / "latest_signal_brief.json"
    if not brief_path.is_file():
        return None
    brief = _read_json(brief_path)
    summary = brief.get("summary") or {}
    fs = summary.get("factor_signals") or {}
    ts = summary.get("term_structure") or {}
    tp = brief.get("trend_phase") or summary.get("trend_phase") or {}
    sm = brief.get("signal_matrix_context") or {}

    day = {
        "date": brief.get("trade_date") or date_dir.name,
        "data_asof": brief.get("data_asof"),
        "run_id": brief.get("run_id"),
        "main_contract": _g(summary, "market_facts", "main_contract") or brief.get("main_contract"),
        "main_settle": _g(summary, "market_facts", "main_settle"),
        "main_oi": _g(summary, "market_facts", "main_open_interest"),
        "main_oi_change": _g(summary, "market_facts", "main_oi_change"),
        "main_volume": _g(summary, "market_facts", "main_volume"),
        "returns": fs.get("main_returns") or {},
        "ma20": fs.get("ma20"),
        "factor_states": fs.get("states") or {},
        "multi_factor": fs.get("multi_factor") or {},
        "trend_phase": {
            "phase_code": tp.get("phase_code"),
            "phase_label": tp.get("phase_label"),
            "direction": tp.get("direction"),
            "confidence": tp.get("confidence"),
            "support_count": tp.get("support_count"),
            "available_signal_count": tp.get("available_signal_count"),
            "reason": tp.get("reason"),
        },
        "term_structure": {
            "near_contract": ts.get("near_contract"), "near_settle": ts.get("near_settle"),
            "main_contract": ts.get("main_contract"), "main_settle": ts.get("main_settle"),
            "far_contract": ts.get("far_contract"), "far_settle": ts.get("far_settle"),
            "main_minus_near": ts.get("main_minus_near"),
            "far_minus_main": ts.get("far_minus_main"),
            "curve_slope": ts.get("curve_slope"),
            "carry_annualized": ts.get("carry_annualized"),
            "tenor_days": ts.get("tenor_days"),
        },
        "signal_matrix": [
            {
                "direction": r.get("direction"),
                "confidence": r.get("confidence"),
                "confidence_score": r.get("confidence_score"),
                "composite_score": r.get("composite_score"),
                "evidence_level": r.get("evidence_level"),
                "horizon": r.get("horizon"),
                "action_type": r.get("action_type"),
                "trend_phase_label": r.get("trend_phase_label"),
                "option_signal": r.get("option_signal"),
                "warning_flags": r.get("warning_flags"),
                "option_pcr_oi": r.get("option_pcr_oi"),
                "option_pcr_volume": r.get("option_pcr_volume"),
                "option_atm_iv_rank": r.get("option_atm_iv_rank"),
                "option_skew_proxy": r.get("option_skew_proxy"),
            }
            for r in (sm.get("rows") or [])
        ],
        "watch_items": brief.get("watch_items") or _g(brief, "trend_rule_context", "watch_items", default=[]) or _g(brief, "summary", "watch_items", default=[]),
        "warning_count": brief.get("warning_count") or 0,
    }

    board_path = date_dir / "trend_continuity_board.json"
    if board_path.is_file():
        board = _read_json(board_path)
        day["trend_quality_score"] = board.get("latest_trend_quality_score")
        day["trend_quality_label"] = board.get("latest_trend_quality_label")
        day["observation_marker"] = board.get("latest_observation_marker")
        day["board_rows"] = [
            {
                "trade_date": r.get("trade_date"),
                "main_settle": r.get("main_settle"),
                "ma20": r.get("ma20"),
                "trend_quality_score": r.get("trend_quality_score"),
                "trend_phase_code": r.get("trend_phase_code"),
                "trend_phase_label": r.get("trend_phase_label"),
                "return_1d": r.get("return_1d"),
                "momentum_signal": r.get("momentum_signal"),
                "carry_signal": r.get("carry_signal"),
                "curve_signal": r.get("curve_signal"),
                "oi_pressure_signal": r.get("oi_pressure_signal"),
                "main_oi_change": r.get("main_oi_change"),
                "main_open_interest": r.get("main_open_interest"),
            }
            for r in (board.get("rows") or [])
        ]
    else:
        day["board_rows"] = []

    audit_path = date_dir / "data_continuity_audit.json"
    if audit_path.is_file():
        audit = _read_json(audit_path)
        day["audit"] = {
            "continuity_status": audit.get("continuity_status"),
            "error_count": audit.get("error_count"),
            "core_latest_trade_date": audit.get("core_latest_trade_date"),
        }
    return day


# ---------------------------------------------------------------------------
# 运行覆盖(跳日分析)
# ---------------------------------------------------------------------------

def collect_coverage(daily: dict) -> list[dict]:
    trading = set()
    if CALENDAR.is_file():
        with open(CALENDAR, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("is_trading_day") == "true":
                    trading.add(row["trade_date"])
    run_dirs = {}
    if DAILY_ROOT.is_dir():
        for p in DAILY_ROOT.iterdir():
            if p.is_dir():
                run_dirs[p.name] = sorted(f.name for f in p.iterdir() if f.is_file())
    if trading:
        start = min(trading)
        last_calendar_trade = max(trading)
        # 官方 2026 日历目前只维护到 08-21；展示范围必须延伸到生成日，
        # 否则会把后续工作日误藏为“没有日期”，掩盖日历未覆盖问题。
        today = _dt.date.today().isoformat()
        end = max(last_calendar_trade, max(daily.keys()) if daily else "0000-00-00", today)
    else:
        start = "2026-01-01"
        last_calendar_trade = max(daily.keys()) if daily else "2026-01-01"
        end = max(last_calendar_trade, _dt.date.today().isoformat())
    # 从 2026-07-01 起展示(近期覆盖)
    start = max(start, "2026-07-01")
    out = []
    cur = _dt.date.fromisoformat(start)
    end_d = _dt.date.fromisoformat(end)
    while cur <= end_d:
        ds = cur.isoformat()
        wd = cur.weekday()  # 0=Mon
        if ds in trading:
            if ds in daily:
                status = "full"       # 有研究产物
            elif ds in run_dirs:
                status = "partial"    # 有目录但缺研究产物(如仅 shadow)
            else:
                status = "missing"    # 交易日未运行
        else:
            # 最后已确认交易日之后：周末仍按休市；工作日标为“日历未覆盖”，
            # 不能根据缺少 true 记录推断为非交易日。
            status = "uncovered" if ds > last_calendar_trade and wd < 5 else "closed"
        out.append({"date": ds, "weekday": wd, "status": status})
        cur += _dt.timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# R93R 统一证据门控
# ---------------------------------------------------------------------------

def collect_gate() -> dict:
    files = sorted(GATE_DIR.glob("*_module_summary.csv")) if GATE_DIR.is_dir() else []
    if not files:
        return {"rows": [], "file": None}
    latest = files[-1]
    rows = []
    with open(latest, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            rows.append({
                "module": r.get("source_module"),
                "evidence_rows": r.get("evidence_row_count"),
                "distinct_evidence": r.get("distinct_evidence_count"),
                "keep": r.get("keep_count"),
                "watch": r.get("watch_count"),
                "reject": r.get("reject_count"),
                "sample_min": r.get("sample_count_min"),
                "sample_max": r.get("sample_count_max"),
                "best_dir_ret": r.get("best_mean_directional_return"),
                "best_incr_ret": r.get("best_primary_incremental_mean_return"),
                "predictive": r.get("predictive_decision"),
                "retention": r.get("retention_decision"),
                "reason": r.get("retention_reason"),
                "stop_expansion": r.get("stop_new_factor_expansion") == "True",
                "promotion_eligible": r.get("promotion_eligible") == "True",
            })
    m = __import__("re").search(r"(\d{4}-\d{2}-\d{2})", latest.name)
    return {"rows": rows, "file": latest.name, "asof": m.group(1) if m else None}


# ---------------------------------------------------------------------------
# 策略评估
# ---------------------------------------------------------------------------

def collect_strategies() -> list[dict]:
    out = []
    for key, label, fname in STRATEGY_FILES:
        path = STRATEGY_DIR / fname
        if not path.is_file():
            continue
        d = _read_json(path)
        windows = d.get("windows") or []
        cons = [w for w in windows if w.get("cost_scenario") == "conservative_cost"]
        full = next((w for w in cons if w.get("window_type") == "full_period"), None)
        years = sorted(
            (w for w in cons if w.get("window_type") == "calendar_year"),
            key=lambda w: w.get("start_year") or 0,
        )
        out.append({
            "strategy_key": key,
            "label": label,
            "full": full,
            "years": [{"year": w.get("start_year"), "sharpe": w.get("sharpe"), "ret": w.get("annualized_return"), "mdd": w.get("max_drawdown")} for w in years],
            "run_id": d.get("run_id"),
        })
    return out


# ---------------------------------------------------------------------------
# R93D 候选前向账本
# ---------------------------------------------------------------------------

def collect_ledger() -> dict:
    events = []
    if LEDGER_EVENTS.is_dir():
        for day_dir in sorted(LEDGER_EVENTS.iterdir()):
            if not day_dir.is_dir():
                continue
            for f in sorted(day_dir.glob("*.json")):
                try:
                    ev = _read_json(f)
                except Exception:
                    continue
                biz = ev.get("event_business") or {}
                events.append({
                    "event_type": ev.get("event_type"),
                    "event_date": biz.get("event_date"),
                    "hypothesis_id": biz.get("hypothesis_id"),
                    "direction": biz.get("direction"),
                    "main_contract": biz.get("main_contract"),
                    "start_price": biz.get("start_price"),
                    "start_stage": biz.get("start_stage"),
                    "start_strength": biz.get("start_strength"),
                    "horizon": biz.get("horizon"),
                    "feature_value": biz.get("feature_value"),
                    "recorded_at": ev.get("recorded_at"),
                })
    counts = Counter(e["event_type"] for e in events)
    return {
        "events": events,
        "capture_count": counts.get("CAPTURE", 0),
        "outcome_count": counts.get("OUTCOME", 0),
        "candidates": PREREGISTERED_CANDIDATES,
    }


# ---------------------------------------------------------------------------
# 综合验证简报(最新一份, 标注日期)
# ---------------------------------------------------------------------------

def collect_validated() -> dict:
    files = sorted(VALIDATED_DIR.glob("*_validated_research_brief.json")) if VALIDATED_DIR.is_dir() else []
    if not files:
        return {"available": False}
    latest = files[-1]
    d = _read_json(latest)
    summary = d.get("summary") or {}
    scalars = {k: v for k, v in summary.items() if isinstance(v, (str, int, float, bool))}
    m = __import__("re").search(r"(\d{4}-\d{2}-\d{2})", latest.name)
    return {
        "available": True,
        "asof": m.group(1) if m else None,
        "generated_at": d.get("generated_at"),
        "report_type": d.get("report_type"),
        "event_rows": len(d.get("event_summary_rows") or []),
        "decay_rows": len(d.get("decay_rows") or []),
        "scalars": scalars,
        "file": latest.name,
    }


# ---------------------------------------------------------------------------
# R93E 验证明细(V3 模板专用, 来自最新综合验证简报)
# ---------------------------------------------------------------------------

def collect_validated_detail() -> dict:
    files = sorted(VALIDATED_DIR.glob("*_validated_research_brief.json")) if VALIDATED_DIR.is_dir() else []
    if not files:
        return {"available": False}
    latest = files[-1]
    try:
        d = _read_json(latest)
    except Exception:
        return {"available": False}
    events = [
        {
            "event_type": e.get("event_type"),
            "horizon": e.get("horizon"),
            "event_count": e.get("event_count"),
            "hit": e.get("directional_hit_rate"),
            "explainable": e.get("explainable_rate"),
            "fund_aligned": e.get("fundamental_aligned_count"),
            "fund_divergent": e.get("fundamental_divergent_count"),
        }
        for e in (d.get("event_summary_rows") or [])
    ]
    return {
        "available": True,
        "asof": (d.get("summary") or {}).get("data_asof"),
        "generated_at": d.get("generated_at"),
        "events": events,
        "decay_count": len(d.get("decay_rows") or []),
        "file": latest.name,
    }


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------

def collect_payload(*, include_validated_detail: bool = False) -> dict:
    if not DAILY_ROOT.is_dir():
        raise SystemExit(f"[ERROR] daily runs dir not found: {DAILY_ROOT}")
    dates = sorted(p.name for p in DAILY_ROOT.iterdir() if p.is_dir())
    daily = {}
    for name in dates:
        try:
            day = extract_day(DAILY_ROOT / name)
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] skip {name}: {exc}", file=sys.stderr)
            continue
        if day:
            daily[name] = day
    if not daily:
        raise SystemExit("[ERROR] no usable daily brief found")
    payload = {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "rule_version": RULE_VERSION,
        "product": "CF",
        "dates": sorted(daily.keys()),
        "latest_date": max(daily.keys()),
        "daily": daily,
        "coverage": collect_coverage(daily),
        "gate": collect_gate(),
        "strategies": collect_strategies(),
        "ledger": collect_ledger(),
        "validated": collect_validated(),
    }
    if include_validated_detail:
        payload["validated_detail"] = collect_validated_detail()
    _assert_clean(payload)
    return payload


_TEMPLATE_PATH = Path(__file__).with_name("cf_studio_template.html")
_TEMPLATE_V3_PATH = Path(__file__).with_name("cf_studio_template_v3.html")
_RULE_VERSION_V3 = "cf_studio_dashboard_v3"


def render_html(payload: dict, *, v3: bool = False) -> str:
    template_path = _TEMPLATE_V3_PATH if v3 else _TEMPLATE_PATH
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    html = template_path.read_text(encoding="utf-8").replace("__DATA_JSON__", data_json)
    return html


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="锚定日期(文件名后缀), 默认最新")
    parser.add_argument("--open", action="store_true", help="生成后用默认浏览器打开")
    parser.add_argument(
        "--v3",
        action="store_true",
        help="使用 V3 模板(2360px 版心+验证摘要), 输出 CF_studio_v3_*.html",
    )
    args = parser.parse_args()

    payload = collect_payload(include_validated_detail=args.v3)
    if args.v3:
        payload["rule_version"] = _RULE_VERSION_V3
    html = render_html(payload, v3=args.v3)
    _assert_clean_text(html)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    anchor = args.date or payload["latest_date"]
    prefix = "CF_studio_v3" if args.v3 else "CF_studio"
    dated = OUT_DIR / f"{prefix}_{anchor}.html"
    latest = OUT_DIR / f"{prefix}_latest.html"
    dated.write_text(html, encoding="utf-8")
    latest.write_text(html, encoding="utf-8")
    print(f"[OK] {dated}")
    print(f"[OK] {latest}")
    print(f"[OK] dates={len(payload['dates'])} gate_rows={len(payload['gate']['rows'])} "
          f"strategies={len(payload['strategies'])} ledger_events={len(payload['ledger']['events'])} "
          f"bytes={len(html.encode('utf-8'))}")

    if args.open:
        import os
        os.startfile(str(latest))  # noqa: S606


if __name__ == "__main__":
    main()
