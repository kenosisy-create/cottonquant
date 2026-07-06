"""R27 candidate rules from CF trend phase transition events."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.common.time import utc_now
from cotton_factor.research_workbench.trend_phase_events import (
    KEY_TRANSITIONS,
    PRODUCT_CODE,
    TREND_PHASE_EVENT_RULE_VERSION,
)
from cotton_factor.research_workbench.trend_phase_events import (
    OUTPUT_DIR as R26_OUTPUT_DIR,
)

TREND_RULE_CANDIDATE_VERSION = "R27_trend_rule_candidates_v2_r30_taxonomy"
OUTPUT_DIR = "trend_rule_candidates"
DEFAULT_MIN_EVENT_COUNT = 3
DEFAULT_MIN_OBSERVATION_COUNT = 3
DEFAULT_MIN_DIRECTIONAL_HIT_RATE = 0.60
WARNING_SEVERITY = "WARN"
INFO_SEVERITY = "INFO"
HUMAN_REVIEW_REQUIRED = (
    "trend_rule_candidate_thresholds",
    "trend_phase_transition_taxonomy",
    "daily_brief_wording",
    "event_outcome_horizon_set",
)

WARNING_COLUMNS = [
    "run_id",
    "section",
    "severity",
    "warning_code",
    "warning_message",
    "affected_count",
    "human_review_required",
]


@dataclass(frozen=True)
class TrendRuleCandidateWarningRecord:
    """Warning row for R27 trend rule candidate outputs."""

    run_id: str
    section: str
    severity: str
    warning_code: str
    warning_message: str
    affected_count: int
    human_review_required: tuple[str, ...]

    def to_csv_row(self) -> dict[str, str]:
        """Return a CSV-safe warning row."""
        return {
            "run_id": self.run_id,
            "section": self.section,
            "severity": self.severity,
            "warning_code": self.warning_code,
            "warning_message": self.warning_message,
            "affected_count": str(self.affected_count),
            "human_review_required": ";".join(self.human_review_required),
        }


@dataclass(frozen=True)
class ResearchTrendRuleCandidateResult:
    """Result of building R27 trend rule candidate artifacts."""

    product_code: str
    run_id: str
    start: date
    end: date
    min_event_count: int
    min_observation_count: int
    min_directional_hit_rate: float
    candidate_count: int
    ready_candidate_count: int
    watch_candidate_count: int
    insufficient_candidate_count: int
    warning_records: tuple[TrendRuleCandidateWarningRecord, ...]
    candidate_parquet_path: Path
    candidate_csv_path: Path
    warning_csv_path: Path
    markdown_path: Path
    manifest_path: Path
    event_summary_path: Path
    event_path: Path | None
    human_review_required: tuple[str, ...]

    @property
    def warning_count(self) -> int:
        """Return non-info warning count."""
        return sum(1 for warning in self.warning_records if warning.severity != INFO_SEVERITY)

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI summary."""
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "min_event_count": self.min_event_count,
            "min_observation_count": self.min_observation_count,
            "min_directional_hit_rate": self.min_directional_hit_rate,
            "candidate_count": self.candidate_count,
            "ready_candidate_count": self.ready_candidate_count,
            "watch_candidate_count": self.watch_candidate_count,
            "insufficient_candidate_count": self.insufficient_candidate_count,
            "warning_count": self.warning_count,
            "candidate_parquet_path": str(self.candidate_parquet_path),
            "candidate_csv_path": str(self.candidate_csv_path),
            "warning_csv_path": str(self.warning_csv_path),
            "markdown_path": str(self.markdown_path),
            "manifest_path": str(self.manifest_path),
            "event_summary_path": str(self.event_summary_path),
            "event_path": None if self.event_path is None else str(self.event_path),
            "human_review_required": list(self.human_review_required),
        }


def build_cf_trend_rule_candidates(
    *,
    start: date,
    end: date,
    event_summary_path: Path | None = None,
    event_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    min_event_count: int = DEFAULT_MIN_EVENT_COUNT,
    min_observation_count: int = DEFAULT_MIN_OBSERVATION_COUNT,
    min_directional_hit_rate: float = DEFAULT_MIN_DIRECTIONAL_HIT_RATE,
) -> ResearchTrendRuleCandidateResult:
    """Build R27 daily-brief trend explanation rule candidates from R26 outputs."""
    if start > end:
        raise ResearchWorkbenchError("start must be <= end")
    _validate_thresholds(
        min_event_count=min_event_count,
        min_observation_count=min_observation_count,
        min_directional_hit_rate=min_directional_hit_rate,
    )
    summary_path = event_summary_path or _default_event_summary_path(start=start, end=end)
    if not summary_path.exists():
        raise ResearchWorkbenchError(f"trend phase event summary not found: {summary_path}")
    resolved_event_path = _resolve_event_path(event_path=event_path, start=start, end=end)
    event_summary = _load_event_summary(input_path=summary_path)
    latest_event_dates = _latest_event_dates(input_path=resolved_event_path)
    candidate_run_id = run_id or _default_run_id(start=start, end=end)
    candidates = _candidate_rows(
        event_summary=event_summary,
        latest_event_dates=latest_event_dates,
        run_id=candidate_run_id,
        min_event_count=min_event_count,
        min_observation_count=min_observation_count,
        min_directional_hit_rate=min_directional_hit_rate,
    )
    warnings = _warning_records(run_id=candidate_run_id, candidates=candidates)
    paths = _output_paths(start=start, end=end, output_dir=output_dir)
    markdown_path = _markdown_path(start=start, end=end, report_output_dir=report_output_dir)

    # R27 只产出日报解释候选，不把任何候选升级为交易规则或执行指令。
    _write_candidates(
        rows=candidates,
        parquet_path=paths["candidate_parquet"],
        csv_path=paths["candidate_csv"],
    )
    _write_warning_csv(warnings=warnings, csv_path=paths["warning_csv"])
    result = ResearchTrendRuleCandidateResult(
        product_code=PRODUCT_CODE,
        run_id=candidate_run_id,
        start=start,
        end=end,
        min_event_count=min_event_count,
        min_observation_count=min_observation_count,
        min_directional_hit_rate=min_directional_hit_rate,
        candidate_count=len(candidates),
        ready_candidate_count=sum(
            1 for row in candidates if row["candidate_status"] == "READY_CANDIDATE"
        ),
        watch_candidate_count=sum(
            1 for row in candidates if row["candidate_status"] == "WATCH_CANDIDATE"
        ),
        insufficient_candidate_count=sum(
            1
            for row in candidates
            if row["candidate_status"] in {"INSUFFICIENT_SAMPLE", "NO_SAMPLE"}
        ),
        warning_records=warnings,
        candidate_parquet_path=paths["candidate_parquet"],
        candidate_csv_path=paths["candidate_csv"],
        warning_csv_path=paths["warning_csv"],
        markdown_path=markdown_path,
        manifest_path=paths["manifest"],
        event_summary_path=summary_path,
        event_path=resolved_event_path,
        human_review_required=HUMAN_REVIEW_REQUIRED,
    )
    _write_markdown(result=result, candidates=candidates)
    _write_manifest(result=result)
    return result


def _candidate_rows(
    *,
    event_summary: pd.DataFrame,
    latest_event_dates: dict[str, str],
    run_id: str,
    min_event_count: int,
    min_observation_count: int,
    min_directional_hit_rate: float,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for transition_code, event_type in KEY_TRANSITIONS.items():
        selected = _select_best_horizon(
            event_summary=event_summary,
            transition_code=transition_code,
            min_event_count=min_event_count,
            min_observation_count=min_observation_count,
            min_directional_hit_rate=min_directional_hit_rate,
        )
        if selected is None:
            rows.append(
                _empty_candidate(
                    run_id=run_id,
                    transition_code=transition_code,
                    event_type=event_type,
                    latest_event_dates=latest_event_dates,
                )
            )
            continue
        event_count = int(selected["event_count"])
        observation_count = int(selected["observation_count"])
        hit_rate = _maybe_float(selected["directional_hit_rate"])
        mean_return = _maybe_float(selected["mean_forward_return"])
        phase_direction = str(selected["new_phase_direction"])
        sample_ready = (
            event_count >= min_event_count and observation_count >= min_observation_count
        )
        direction_ok = _directional_evidence_ok(
            phase_direction=phase_direction,
            mean_forward_return=mean_return,
            directional_hit_rate=hit_rate,
            min_directional_hit_rate=min_directional_hit_rate,
        )
        if not sample_ready:
            status = "INSUFFICIENT_SAMPLE"
            action = "WATCH_ONLY"
        elif direction_ok:
            status = "READY_CANDIDATE"
            action = "ALLOW_DAILY_EXPLANATION_CANDIDATE"
        else:
            status = "WATCH_CANDIDATE"
            action = "WATCH_ONLY"
        rows.append(
            {
                "run_id": run_id,
                "product_code": PRODUCT_CODE,
                "transition_code": transition_code,
                "event_type": event_type,
                "candidate_status": status,
                "daily_brief_action": action,
                "selected_horizon": int(selected["horizon"]),
                "event_count": event_count,
                "observation_count": observation_count,
                "new_phase_direction": phase_direction,
                "mean_forward_return": mean_return,
                "median_forward_return": _maybe_float(selected["median_forward_return"]),
                "directional_hit_rate": hit_rate,
                "positive_rate": _maybe_float(selected["positive_rate"]),
                "negative_rate": _maybe_float(selected["negative_rate"]),
                "latest_event_date": latest_event_dates.get(transition_code),
                "evidence_score": _evidence_score(
                    event_count=event_count,
                    observation_count=observation_count,
                    hit_rate=hit_rate,
                    mean_return=mean_return,
                    phase_direction=phase_direction,
                ),
                "rule_text_cn": _rule_text(
                    transition_code=transition_code,
                    status=status,
                    selected_horizon=int(selected["horizon"]),
                ),
                "caveat_cn": _caveat(
                    status=status,
                    event_count=event_count,
                    observation_count=observation_count,
                ),
                "candidate_rule_version": TREND_RULE_CANDIDATE_VERSION,
                "source_event_rule_version": selected["event_rule_version"],
            }
        )
    return rows


def _select_best_horizon(
    *,
    event_summary: pd.DataFrame,
    transition_code: str,
    min_event_count: int,
    min_observation_count: int,
    min_directional_hit_rate: float,
) -> pd.Series | None:
    selected = event_summary.loc[event_summary["transition_code"].astype(str) == transition_code]
    selected = selected.dropna(subset=["observation_count"])
    if selected.empty:
        return None
    working = selected.copy()
    working["_hit_rate"] = pd.to_numeric(working["directional_hit_rate"], errors="coerce")
    working["_observation_count"] = pd.to_numeric(
        working["observation_count"],
        errors="coerce",
    )
    working["_event_count"] = pd.to_numeric(working["event_count"], errors="coerce")
    working["_horizon"] = pd.to_numeric(working["horizon"], errors="coerce")
    # 优先选择证据最强的 horizon，而不是机械选择最短 horizon。
    working["_sample_ready"] = (
        (working["_event_count"] >= min_event_count)
        & (working["_observation_count"] >= min_observation_count)
    )
    working["_mean_component"] = [
        _directional_mean_component(
            phase_direction=str(row.new_phase_direction),
            mean_forward_return=_maybe_float(row.mean_forward_return),
        )
        for row in working.itertuples(index=False)
    ]
    working["_direction_ready"] = [
        bool(sample_ready)
        and _directional_evidence_ok(
            phase_direction=str(row.new_phase_direction),
            mean_forward_return=_maybe_float(row.mean_forward_return),
            directional_hit_rate=_maybe_float(row.directional_hit_rate),
            min_directional_hit_rate=min_directional_hit_rate,
        )
        for row, sample_ready in zip(
            working.itertuples(index=False),
            working["_sample_ready"],
            strict=True,
        )
    ]
    working = working.sort_values(
        [
            "_direction_ready",
            "_sample_ready",
            "_hit_rate",
            "_mean_component",
            "_observation_count",
            "_event_count",
            "_horizon",
        ],
        ascending=[False, False, False, False, False, False, True],
        na_position="last",
    )
    return working.iloc[0]


def _empty_candidate(
    *,
    run_id: str,
    transition_code: str,
    event_type: str,
    latest_event_dates: dict[str, str],
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "product_code": PRODUCT_CODE,
        "transition_code": transition_code,
        "event_type": event_type,
        "candidate_status": "NO_SAMPLE",
        "daily_brief_action": "ACCUMULATE_SAMPLE",
        "selected_horizon": None,
        "event_count": 0,
        "observation_count": 0,
        "new_phase_direction": None,
        "mean_forward_return": None,
        "median_forward_return": None,
        "directional_hit_rate": None,
        "positive_rate": None,
        "negative_rate": None,
        "latest_event_date": latest_event_dates.get(transition_code),
        "evidence_score": 0.0,
        "rule_text_cn": _rule_text(
            transition_code=transition_code,
            status="NO_SAMPLE",
            selected_horizon=None,
        ),
        "caveat_cn": "当前窗口没有该阶段切换样本，不能进入日报正式规则候选。",
        "candidate_rule_version": TREND_RULE_CANDIDATE_VERSION,
        "source_event_rule_version": TREND_PHASE_EVENT_RULE_VERSION,
    }


def _warning_records(
    *,
    run_id: str,
    candidates: list[dict[str, object]],
) -> tuple[TrendRuleCandidateWarningRecord, ...]:
    records = [
        _warning(
            run_id=run_id,
            section="research_boundary",
            severity=INFO_SEVERITY,
            warning_code="R27_RULES_ARE_CANDIDATES_ONLY",
            warning_message="R27 只输出日报解释候选，不构成交易规则或交易指令。",
            affected_count=len(candidates),
            human_review_required=(),
        )
    ]
    insufficient = [
        row
        for row in candidates
        if row["candidate_status"] in {"INSUFFICIENT_SAMPLE", "NO_SAMPLE"}
    ]
    if insufficient:
        records.append(
            _warning(
                run_id=run_id,
                section="samples",
                severity=WARNING_SEVERITY,
                warning_code="R27_RULE_CANDIDATE_SAMPLE_INSUFFICIENT",
                warning_message=f"有 {len(insufficient)} 个关键切换样本不足或无样本。",
                affected_count=len(insufficient),
                human_review_required=("event_outcome_horizon_set",),
            )
        )
    ready = [row for row in candidates if row["candidate_status"] == "READY_CANDIDATE"]
    if not ready:
        records.append(
            _warning(
                run_id=run_id,
                section="candidates",
                severity=WARNING_SEVERITY,
                warning_code="R27_NO_READY_DAILY_BRIEF_RULE",
                warning_message="当前窗口没有达到阈值的日报解释规则候选。",
                affected_count=0,
                human_review_required=("trend_rule_candidate_thresholds",),
            )
        )
    return tuple(records)


def _warning(
    *,
    run_id: str,
    section: str,
    severity: str,
    warning_code: str,
    warning_message: str,
    affected_count: int,
    human_review_required: tuple[str, ...],
) -> TrendRuleCandidateWarningRecord:
    return TrendRuleCandidateWarningRecord(
        run_id=run_id,
        section=section,
        severity=severity,
        warning_code=warning_code,
        warning_message=warning_message,
        affected_count=affected_count,
        human_review_required=human_review_required,
    )


def _load_event_summary(*, input_path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(input_path)
    required = {
        "transition_code",
        "event_type",
        "new_phase_direction",
        "horizon",
        "event_count",
        "observation_count",
        "mean_forward_return",
        "median_forward_return",
        "positive_rate",
        "negative_rate",
        "directional_hit_rate",
        "event_rule_version",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"trend phase event summary missing columns: {missing}")
    return frame.copy()


def _latest_event_dates(*, input_path: Path | None) -> dict[str, str]:
    if input_path is None or not input_path.exists():
        return {}
    frame = pd.read_parquet(input_path)
    if {"transition_code", "event_date"} - set(frame.columns):
        return {}
    working = frame.copy()
    working["_event_date"] = pd.to_datetime(working["event_date"]).dt.date
    latest = working.groupby("transition_code")["_event_date"].max()
    return {str(key): value.isoformat() for key, value in latest.items()}


def _resolve_event_path(
    *,
    event_path: Path | None,
    start: date,
    end: date,
) -> Path | None:
    if event_path is not None:
        if not event_path.exists():
            raise ResearchWorkbenchError(f"trend phase event parquet not found: {event_path}")
        return event_path
    default_path = _default_event_path(start=start, end=end)
    return default_path if default_path.exists() else None


def _write_candidates(
    *,
    rows: list[dict[str, object]],
    parquet_path: Path,
    csv_path: Path,
) -> None:
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    frame.to_parquet(parquet_path, index=False)
    frame.to_csv(csv_path, index=False, encoding="utf-8")


def _write_warning_csv(
    *,
    warnings: tuple[TrendRuleCandidateWarningRecord, ...],
    csv_path: Path,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WARNING_COLUMNS)
        writer.writeheader()
        writer.writerows([warning.to_csv_row() for warning in warnings])


def _write_markdown(
    *,
    result: ResearchTrendRuleCandidateResult,
    candidates: list[dict[str, object]],
) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# CF 趋势解释规则候选 - {result.start.isoformat()} 至 {result.end.isoformat()}",
        "",
        "## 一、筛选阈值",
        "",
        f"- 最小事件数：`{result.min_event_count}`",
        f"- 最小后验样本数：`{result.min_observation_count}`",
        f"- 最小方向命中率：`{result.min_directional_hit_rate:.0%}`",
        f"- R26 事件汇总：`{result.event_summary_path}`",
        "",
        "## 二、候选状态",
        "",
        "| 切换 | 事件类型 | 状态 | 日报动作 | Horizon | 样本数 | 方向命中率 | 平均后验收益 |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in candidates:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["transition_code"]),
                    str(row["event_type"]),
                    str(row["candidate_status"]),
                    str(row["daily_brief_action"]),
                    _fmt_optional_int(row["selected_horizon"]),
                    str(row["observation_count"]),
                    _fmt_percent(row["directional_hit_rate"]),
                    _fmt_percent(row["mean_forward_return"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 三、日报候选表述",
            "",
        ]
    )
    lines.extend(f"- {row['rule_text_cn']} {row['caveat_cn']}" for row in candidates)
    lines.extend(
        [
            "",
            "## 四、研究边界",
            "",
            "- R27 只输出日报解释候选，不构成交易规则。",
            "- 样本不足、无样本或未过阈值的切换只能作为观察项。",
            "- S3->S4 若无样本，不允许进入正式日报判断规则。",
            "- 本报告不构成交易指令。",
            "",
            "## 五、人工复核项",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_manifest(*, result: ResearchTrendRuleCandidateResult) -> None:
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **result.to_summary(),
        "report_type": "trend_rule_candidates",
        "rule_version": TREND_RULE_CANDIDATE_VERSION,
        "source_event_rule_version": TREND_PHASE_EVENT_RULE_VERSION,
        "generated_at": utc_now().isoformat(),
        "candidate_rules_only": True,
        "not_trading_instruction": True,
    }
    result.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _directional_evidence_ok(
    *,
    phase_direction: str,
    mean_forward_return: float | None,
    directional_hit_rate: float | None,
    min_directional_hit_rate: float,
) -> bool:
    if mean_forward_return is None or directional_hit_rate is None:
        return False
    if directional_hit_rate < min_directional_hit_rate:
        return False
    if phase_direction == "long":
        return mean_forward_return > 0
    if phase_direction == "short":
        return mean_forward_return < 0
    return False


def _directional_mean_component(
    *,
    phase_direction: str,
    mean_forward_return: float | None,
) -> float:
    if mean_forward_return is None:
        return 0.0
    if phase_direction == "long":
        return mean_forward_return
    if phase_direction == "short":
        return -mean_forward_return
    return 0.0


def _evidence_score(
    *,
    event_count: int,
    observation_count: int,
    hit_rate: float | None,
    mean_return: float | None,
    phase_direction: str,
) -> float:
    hit_component = 0.0 if hit_rate is None else hit_rate
    sample_component = min(event_count, observation_count) / 10
    mean_component = 0.0
    if mean_return is not None:
        if phase_direction == "long":
            mean_component = max(mean_return, 0)
        elif phase_direction == "short":
            mean_component = max(-mean_return, 0)
    return round(hit_component + sample_component + mean_component, 6)


def _rule_text(
    *,
    transition_code: str,
    status: str,
    selected_horizon: int | None,
) -> str:
    event_type = KEY_TRANSITIONS.get(transition_code, "阶段切换观察")
    if status == "READY_CANDIDATE":
        return (
            f"{transition_code}（{event_type}）可作为日报趋势解释候选，"
            f"参考 h{selected_horizon}。"
        )
    if status == "WATCH_CANDIDATE":
        return f"{transition_code}（{event_type}）有样本但证据未过阈值，仅作观察。"
    if status == "INSUFFICIENT_SAMPLE":
        return f"{transition_code}（{event_type}）样本不足，暂不进入日报正式规则。"
    return f"{transition_code}（{event_type}）当前无样本，继续积累。"


def _caveat(*, status: str, event_count: int, observation_count: int) -> str:
    if status == "READY_CANDIDATE":
        return "仍需人工复核措辞和阈值，不能表达为交易指令。"
    return f"当前事件数={event_count}，后验样本数={observation_count}。"


def _validate_thresholds(
    *,
    min_event_count: int,
    min_observation_count: int,
    min_directional_hit_rate: float,
) -> None:
    if min_event_count <= 0:
        raise ResearchWorkbenchError("min_event_count must be positive")
    if min_observation_count <= 0:
        raise ResearchWorkbenchError("min_observation_count must be positive")
    if not 0 <= min_directional_hit_rate <= 1:
        raise ResearchWorkbenchError("min_directional_hit_rate must be between 0 and 1")


def _default_event_summary_path(*, start: date, end: date) -> Path:
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_trend_phase_events"
    return data_dir() / "research" / PRODUCT_CODE / R26_OUTPUT_DIR / f"{stem}_summary.parquet"


def _default_event_path(*, start: date, end: date) -> Path:
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_trend_phase_events"
    return data_dir() / "research" / PRODUCT_CODE / R26_OUTPUT_DIR / f"{stem}_events.parquet"


def _output_paths(*, start: date, end: date, output_dir: Path | None) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_trend_rule_candidates"
    return {
        "candidate_parquet": root / f"{stem}.parquet",
        "candidate_csv": root / f"{stem}.csv",
        "warning_csv": root / f"{stem}_warnings.csv",
        "manifest": root / f"{stem}_manifest.json",
    }


def _markdown_path(*, start: date, end: date, report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}_trend_rule_candidates"
    return root / f"{stem}.md"


def _maybe_float(value: object) -> float | None:
    if value is None:
        return None
    if pd.isna(value):
        return None
    return float(value)


def _fmt_percent(value: object) -> str:
    numeric = _maybe_float(value)
    if numeric is None:
        return "NA"
    return f"{numeric:.2%}"


def _fmt_optional_int(value: object) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return str(int(value))


def _default_run_id(*, start: date, end: date) -> str:
    return f"r27_trend_rule_candidates_{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
