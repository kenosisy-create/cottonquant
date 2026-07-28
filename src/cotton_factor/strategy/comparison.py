"""R89 fixed candidate-versus-baseline promotion decision."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import StrategyError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.strategy.spec import PromotionRuleSpec, StrategySpec, load_strategy_spec

COMPARISON_RULE_VERSION = "V5.1_R89_strategy_promotion_v1"


@dataclass(frozen=True)
class StrategyComparisonResult:
    """Automatic PASS/FROZEN decision and traceable evidence."""

    run_id: str
    baseline_key: str
    candidate_key: str
    decision: str
    year_win_count: int
    eligible_year_count: int
    full_delta_sharpe: float
    conservative_net_return: float
    drawdown_deterioration_pp: float
    comparison_path: Path
    json_path: Path
    markdown_path: Path
    manifest_path: Path

    @property
    def passed(self) -> bool:
        """Return whether the candidate clears every fixed gate."""
        return self.decision == "PASS"

    def to_summary(self) -> dict[str, object]:
        """Return a machine-readable decision summary."""
        return {
            "run_id": self.run_id,
            "baseline_key": self.baseline_key,
            "candidate_key": self.candidate_key,
            "decision": self.decision,
            "passed": self.passed,
            "year_win_count": self.year_win_count,
            "eligible_year_count": self.eligible_year_count,
            "full_delta_sharpe": self.full_delta_sharpe,
            "conservative_net_return": self.conservative_net_return,
            "drawdown_deterioration_pp": self.drawdown_deterioration_pp,
            "comparison_path": str(self.comparison_path),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "manifest_path": str(self.manifest_path),
        }


def compare_cf_strategies(
    *,
    baseline_spec_path: Path,
    candidate_spec_path: Path,
    baseline_evaluation_path: Path | None = None,
    candidate_evaluation_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> StrategyComparisonResult:
    """Apply the ex-ante non-overlapping-year promotion rule once."""
    baseline = load_strategy_spec(baseline_spec_path)
    candidate = load_strategy_spec(candidate_spec_path)
    if baseline.status != "baseline":
        raise StrategyError("comparison spec-a must be the baseline")
    if candidate.promotion_rule is None:
        raise StrategyError("candidate spec must define promotion_rule")
    base_path = baseline_evaluation_path or _latest_evaluation_path(baseline)
    candidate_path = candidate_evaluation_path or _latest_evaluation_path(candidate)
    base_frame = pd.read_parquet(base_path)
    candidate_frame = pd.read_parquet(candidate_path)
    comparison_rows, decision_metrics = promotion_decision(
        baseline=base_frame,
        candidate=candidate_frame,
        rule=candidate.promotion_rule,
    )
    active_run_id = run_id or _default_run_id(candidate)
    paths = _output_paths(
        baseline=baseline,
        candidate=candidate,
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    paths["comparison"].parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(comparison_rows).to_parquet(paths["comparison"], index=False)
    result = StrategyComparisonResult(
        run_id=active_run_id,
        baseline_key=baseline.spec_key,
        candidate_key=candidate.spec_key,
        decision=str(decision_metrics["decision"]),
        year_win_count=int(decision_metrics["year_win_count"]),
        eligible_year_count=int(decision_metrics["eligible_year_count"]),
        full_delta_sharpe=float(decision_metrics["full_delta_sharpe"]),
        conservative_net_return=float(decision_metrics["conservative_net_return"]),
        drawdown_deterioration_pp=float(decision_metrics["drawdown_deterioration_pp"]),
        comparison_path=paths["comparison"],
        json_path=paths["json"],
        markdown_path=paths["markdown"],
        manifest_path=paths["manifest"],
    )
    _write_outputs(
        result=result,
        rows=comparison_rows,
        decision_metrics=decision_metrics,
        input_paths=(baseline_spec_path, candidate_spec_path, base_path, candidate_path),
    )
    return result


def promotion_decision(
    *,
    baseline: pd.DataFrame,
    candidate: pd.DataFrame,
    rule: PromotionRuleSpec,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Return yearly comparisons and one deterministic promotion result."""
    required = {
        "window_id",
        "window_type",
        "cost_scenario",
        "sharpe",
        "max_drawdown",
        "net_return",
        "active_days",
        "completed_trades",
    }
    for name, frame in (("baseline", baseline), ("candidate", candidate)):
        missing = required - set(frame.columns)
        if missing:
            raise StrategyError(f"{name} evaluation missing columns: {sorted(missing)}")
    rows: list[dict[str, object]] = []
    eligible_year_count = 0
    year_win_count = 0
    for year in rule.evaluation_years:
        window_id = f"YEAR_{year}"
        base = _one_row(baseline, window_id=window_id)
        cand = _one_row(candidate, window_id=window_id)
        eligible = (
            int(cand["active_days"]) >= rule.min_active_days
            and int(cand["completed_trades"]) >= rule.min_completed_trades
        )
        win = eligible and float(cand["sharpe"]) >= float(base["sharpe"])
        eligible_year_count += int(eligible)
        year_win_count += int(win)
        rows.append(
            {
                "year": year,
                "window_id": window_id,
                "eligible": eligible,
                "win": win,
                "baseline_sharpe": float(base["sharpe"]),
                "candidate_sharpe": float(cand["sharpe"]),
                "delta_sharpe": float(cand["sharpe"]) - float(base["sharpe"]),
                "candidate_active_days": int(cand["active_days"]),
                "candidate_completed_trades": int(cand["completed_trades"]),
            }
        )
    base_full = _full_row(baseline)
    candidate_full = _full_row(candidate)
    delta_sharpe = float(candidate_full["sharpe"]) - float(base_full["sharpe"])
    conservative_net_return = float(candidate_full["net_return"])
    drawdown_deterioration_pp = max(
        0.0,
        (abs(float(candidate_full["max_drawdown"])) - abs(float(base_full["max_drawdown"])))
        * 100.0,
    )
    conditions = {
        "eligible_years": eligible_year_count >= rule.required_year_wins,
        "year_wins": year_win_count >= rule.required_year_wins,
        "full_delta_sharpe": delta_sharpe >= rule.min_full_period_delta_sharpe,
        "positive_conservative_return": (
            conservative_net_return > 0
            if rule.require_positive_conservative_return
            else True
        ),
        "drawdown_guard": (
            drawdown_deterioration_pp <= rule.max_drawdown_deterioration_pp
        ),
    }
    decision = "PASS" if all(conditions.values()) else "FROZEN"
    return rows, {
        "decision": decision,
        "eligible_year_count": eligible_year_count,
        "year_win_count": year_win_count,
        "full_delta_sharpe": delta_sharpe,
        "conservative_net_return": conservative_net_return,
        "drawdown_deterioration_pp": drawdown_deterioration_pp,
        "conditions": conditions,
    }


def _one_row(frame: pd.DataFrame, *, window_id: str) -> pd.Series:
    selected = frame.loc[
        frame["window_id"].eq(window_id)
        & frame["cost_scenario"].eq("conservative_cost")
    ]
    if len(selected) != 1:
        raise StrategyError(f"expected one conservative row for {window_id}, got {len(selected)}")
    return selected.iloc[0]


def _full_row(frame: pd.DataFrame) -> pd.Series:
    selected = frame.loc[
        frame["window_type"].eq("full_period")
        & frame["cost_scenario"].eq("conservative_cost")
    ]
    if len(selected) != 1:
        raise StrategyError(f"expected one conservative full-period row, got {len(selected)}")
    return selected.iloc[0]


def _latest_evaluation_path(spec: StrategySpec) -> Path:
    path = (
        data_dir()
        / "strategy"
        / "CF"
        / spec.strategy_id
        / f"{spec.strategy_id}_{spec.version}_evaluation_window.parquet"
    )
    if not path.exists():
        raise StrategyError(f"strategy evaluation artifact not found: {path}")
    return path


def _output_paths(
    *,
    baseline: StrategySpec,
    candidate: StrategySpec,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    root = output_dir or data_dir() / "strategy" / "CF" / candidate.strategy_id
    report_root = report_output_dir or reports_dir() / "strategy"
    stem = (
        f"{candidate.strategy_id}_{candidate.version}_vs_"
        f"{baseline.strategy_id}_{baseline.version}"
    )
    return {
        "comparison": root / f"{stem}_comparison.parquet",
        "manifest": root / f"{stem}_manifest.json",
        "json": report_root / f"{stem}.json",
        "markdown": report_root / f"{stem}.md",
    }


def _write_outputs(
    *,
    result: StrategyComparisonResult,
    rows: list[dict[str, object]],
    decision_metrics: dict[str, object],
    input_paths: tuple[Path, ...],
) -> None:
    payload = {
        **result.to_summary(),
        "rule_version": COMPARISON_RULE_VERSION,
        "yearly_comparison": rows,
        "conditions": decision_metrics["conditions"],
        "research_boundary": "固定历史比较只授予候选资格，不构成交易指令。",
    }
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        f"# CF 候选策略晋级判定：{result.candidate_key}",
        "",
        f"- 基准：`{result.baseline_key}`",
        f"- 结论：`{result.decision}`",
        f"- 合格年度：`{result.eligible_year_count}/5`",
        f"- 年度胜出：`{result.year_win_count}/5`",
        f"- 全历史 conservative cost Delta Sharpe：`{result.full_delta_sharpe:.3f}`",
        f"- conservative cost 净收益：`{result.conservative_net_return:.2%}`",
        f"- 最大回撤恶化：`{result.drawdown_deterioration_pp:.2f}` 个百分点",
        "",
        "| 年度 | 合格 | 胜出 | 基准Sharpe | 候选Sharpe | Delta Sharpe | 在场日 | 完成事件 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['year']} | {row['eligible']} | {row['win']} | "
            f"{row['baseline_sharpe']:.3f} | {row['candidate_sharpe']:.3f} | "
            f"{row['delta_sharpe']:.3f} | {row['candidate_active_days']} | "
            f"{row['candidate_completed_trades']} |"
        )
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "- 两年滚动窗口未进入晋级计数。",
            "- 历史判定不自动修改策略方向，不构成交易指令。",
        ]
    )
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    artifacts = (result.comparison_path, result.json_path, result.markdown_path)
    manifest = {
        **result.to_summary(),
        "rule_version": COMPARISON_RULE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "input_sha256": {str(path): _sha256(path) for path in input_paths},
        "artifact_sha256": {str(path): _sha256(path) for path in artifacts},
    }
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_run_id(spec: StrategySpec) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{spec.strategy_id}_{spec.version}_compare_{stamp}_{uuid.uuid4().hex[:8]}"
