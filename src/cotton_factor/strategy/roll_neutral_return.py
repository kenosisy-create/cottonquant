"""R93F roll-neutral return index and TSMOM measurement comparison."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import StrategyError
from cotton_factor.common.paths import data_dir, project_root, reports_dir
from cotton_factor.core.contract_master import load_product_config
from cotton_factor.core.schemas import CoreQuoteDailyRow, ResearchContinuousPriceDailyRow
from cotton_factor.strategy.io import (
    default_core_quote_path,
    latest_strategy_input_paths,
    load_core_quotes,
    load_typed_parquet,
)
from cotton_factor.strategy.spec import StrategySpec, load_strategy_spec

PRODUCT_CODE = "CF"
SIGNAL_OBJECT_ID = "CF.C1"
ROLL_NEUTRAL_RULE_VERSION = "V5.1_R93F_roll_neutral_return_v1"
RESEARCH_BOUNDARY = (
    "研究仿真、无未来函数，不构成交易指令；本模块只比较价格收益测量口径，"
    "不修改现有策略、影子账本或历史结果。"
)


@dataclass(frozen=True)
class RollNeutralReturnDailyRow:
    """One auditable daily return observation built from tradable contracts."""

    product_code: str
    signal_object_id: str
    trade_date: date
    prior_trade_date: date | None
    mapped_contract: str
    previous_mapped_contract: str | None
    return_contract: str
    return_method: str
    is_roll: bool
    roll_from_contract: str | None
    roll_to_contract: str | None
    roll_gap: float | None
    mapped_contract_settle: float
    return_contract_prior_settle: float | None
    return_contract_current_settle: float
    daily_return: float
    return_index: float
    rule_version: str
    input_snapshot_ids: tuple[str, ...]

    def to_record(self) -> dict[str, object]:
        """Return a Parquet-friendly record."""
        record = asdict(self)
        record["input_snapshot_ids"] = list(self.input_snapshot_ids)
        return record


@dataclass(frozen=True)
class RollNeutralReturnResearchResult:
    """R93F artifact paths and high-level measurement findings."""

    run_id: str
    start: date
    end: date
    continuous_price_path: Path
    core_quote_path: Path
    strategy_spec_path: Path
    return_index_path: Path
    comparison_path: Path
    warning_csv_path: Path
    json_path: Path
    manifest_path: Path
    markdown_path: Path
    row_count: int
    eligible_row_count: int
    roll_count: int
    direction_disagreement_count: int
    target_lot_disagreement_count: int
    latest_contract: str
    latest_additive_direction: int
    latest_roll_neutral_direction: int
    latest_additive_target_lots: int
    latest_roll_neutral_target_lots: int
    warning_count: int

    def to_summary(self) -> dict[str, object]:
        """Return a stable CLI JSON payload."""
        return {
            "run_id": self.run_id,
            "product_code": PRODUCT_CODE,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "continuous_price_path": str(self.continuous_price_path),
            "core_quote_path": str(self.core_quote_path),
            "strategy_spec_path": str(self.strategy_spec_path),
            "return_index_path": str(self.return_index_path),
            "comparison_path": str(self.comparison_path),
            "warning_csv_path": str(self.warning_csv_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "markdown_path": str(self.markdown_path),
            "row_count": self.row_count,
            "eligible_row_count": self.eligible_row_count,
            "roll_count": self.roll_count,
            "direction_disagreement_count": self.direction_disagreement_count,
            "target_lot_disagreement_count": self.target_lot_disagreement_count,
            "latest_contract": self.latest_contract,
            "latest_additive_direction": self.latest_additive_direction,
            "latest_roll_neutral_direction": self.latest_roll_neutral_direction,
            "latest_additive_target_lots": self.latest_additive_target_lots,
            "latest_roll_neutral_target_lots": self.latest_roll_neutral_target_lots,
            "warning_count": self.warning_count,
        }


def build_cf_roll_neutral_return_research(
    *,
    continuous_price_path: Path | None = None,
    core_quote_path: Path | None = None,
    strategy_spec_path: Path | None = None,
    input_dir: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> RollNeutralReturnResearchResult:
    """Build the R93F return index and compare it with additive continuity."""
    resolved_continuous_path = continuous_price_path
    if resolved_continuous_path is None:
        resolved_continuous_path = latest_strategy_input_paths(input_dir)["continuous"]
    resolved_core_path = core_quote_path or default_core_quote_path()
    resolved_spec_path = strategy_spec_path or (
        project_root() / "configs" / "strategy" / "CF_tsmom_v0.yaml"
    )

    continuous_rows = load_typed_parquet(
        resolved_continuous_path,
        ResearchContinuousPriceDailyRow,
    )
    quotes = load_core_quotes(resolved_core_path)
    spec = load_strategy_spec(resolved_spec_path)
    _validate_inputs(continuous_rows=continuous_rows, spec=spec)
    multiplier = _confirmed_multiplier()

    return_rows = build_roll_neutral_return_index(
        continuous_rows=continuous_rows,
        quotes=quotes,
    )
    comparison_rows = build_tsmom_measurement_comparison(
        continuous_rows=continuous_rows,
        return_rows=return_rows,
        spec=spec,
        multiplier=multiplier,
    )
    warnings = _research_warnings(
        return_rows=return_rows,
        comparison_rows=comparison_rows,
    )
    active_run_id = run_id or _default_run_id()
    paths = _output_paths(
        start=return_rows[0].trade_date,
        end=return_rows[-1].trade_date,
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    _write_parquet(paths["return_index"], [row.to_record() for row in return_rows])
    _write_parquet(paths["comparison"], comparison_rows)
    _write_warnings(paths["warnings"], run_id=active_run_id, warnings=warnings)

    eligible = [row for row in comparison_rows if not row["warning_code"]]
    latest = comparison_rows[-1]
    result = RollNeutralReturnResearchResult(
        run_id=active_run_id,
        start=return_rows[0].trade_date,
        end=return_rows[-1].trade_date,
        continuous_price_path=resolved_continuous_path,
        core_quote_path=resolved_core_path,
        strategy_spec_path=resolved_spec_path,
        return_index_path=paths["return_index"],
        comparison_path=paths["comparison"],
        warning_csv_path=paths["warnings"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
        markdown_path=paths["markdown"],
        row_count=len(return_rows),
        eligible_row_count=len(eligible),
        roll_count=sum(row.is_roll for row in return_rows),
        direction_disagreement_count=sum(
            bool(row["direction_disagreement"]) for row in eligible
        ),
        target_lot_disagreement_count=sum(
            bool(row["target_lot_disagreement"]) for row in eligible
        ),
        latest_contract=str(latest["mapped_contract"]),
        latest_additive_direction=int(latest["additive_direction"]),
        latest_roll_neutral_direction=int(latest["roll_neutral_direction"]),
        latest_additive_target_lots=int(latest["additive_target_lots"]),
        latest_roll_neutral_target_lots=int(latest["roll_neutral_target_lots"]),
        warning_count=len(warnings),
    )
    statistics_payload = _comparison_statistics(comparison_rows)
    _write_json(
        path=result.json_path,
        result=result,
        statistics_payload=statistics_payload,
        warnings=warnings,
    )
    _write_markdown(
        result=result,
        return_rows=return_rows,
        comparison_rows=comparison_rows,
        statistics_payload=statistics_payload,
        warnings=warnings,
    )
    _write_manifest(result=result)
    return result


def build_roll_neutral_return_index(
    *,
    continuous_rows: list[ResearchContinuousPriceDailyRow],
    quotes: list[CoreQuoteDailyRow],
) -> list[RollNeutralReturnDailyRow]:
    """Create a base-100 return index without injecting same-day roll gaps."""
    rows = sorted(continuous_rows, key=lambda row: row.trade_date)
    if not rows:
        raise StrategyError("continuous price contains no rows")
    if len({row.trade_date for row in rows}) != len(rows):
        raise StrategyError("continuous price contains duplicate trade dates")
    quote_by_key = _quote_index(quotes)
    output: list[RollNeutralReturnDailyRow] = []
    return_index = 100.0

    for index, current in enumerate(rows):
        mapped_quote = _settlement_quote(
            quote_by_key,
            contract=current.mapped_contract,
            trade_date=current.trade_date,
        )
        _assert_raw_price_matches(current=current, mapped_quote=mapped_quote)
        if index == 0:
            daily_return = 0.0
            return_contract = current.mapped_contract
            prior_date = None
            previous_contract = None
            prior_settle = None
            current_settle = float(mapped_quote.settle)
            method = "BASE_100"
            lineage = _unique_ids(
                current.input_snapshot_ids,
                [mapped_quote.source_snapshot_id],
            )
        else:
            previous = rows[index - 1]
            prior_date = previous.trade_date
            previous_contract = previous.mapped_contract
            if current.is_roll:
                _validate_roll_row(current=current, previous=previous)
                # 换月日继续使用旧合约的当日收益，只剔除新旧合约同日价差。
                return_contract = previous.mapped_contract
                method = "OLD_CONTRACT_ON_ROLL_DATE"
            else:
                if current.mapped_contract != previous.mapped_contract:
                    raise StrategyError(
                        f"{current.trade_date}: mapped contract changed without is_roll"
                    )
                return_contract = current.mapped_contract
                method = "SAME_CONTRACT"
            prior_quote = _settlement_quote(
                quote_by_key,
                contract=return_contract,
                trade_date=prior_date,
            )
            current_return_quote = _settlement_quote(
                quote_by_key,
                contract=return_contract,
                trade_date=current.trade_date,
            )
            prior_settle = float(prior_quote.settle)
            current_settle = float(current_return_quote.settle)
            if prior_settle <= 0 or current_settle <= 0:
                raise StrategyError(
                    f"{current.trade_date}: settlement must be positive for return calculation"
                )
            daily_return = current_settle / prior_settle - 1.0
            return_index *= 1.0 + daily_return
            lineage = _unique_ids(
                previous.input_snapshot_ids,
                current.input_snapshot_ids,
                [
                    prior_quote.source_snapshot_id,
                    current_return_quote.source_snapshot_id,
                    mapped_quote.source_snapshot_id,
                ],
            )
        output.append(
            RollNeutralReturnDailyRow(
                product_code=PRODUCT_CODE,
                signal_object_id=SIGNAL_OBJECT_ID,
                trade_date=current.trade_date,
                prior_trade_date=prior_date,
                mapped_contract=current.mapped_contract,
                previous_mapped_contract=previous_contract,
                return_contract=return_contract,
                return_method=method,
                is_roll=current.is_roll,
                roll_from_contract=current.roll_from_contract,
                roll_to_contract=current.roll_to_contract,
                roll_gap=current.roll_gap,
                mapped_contract_settle=float(mapped_quote.settle),
                return_contract_prior_settle=prior_settle,
                return_contract_current_settle=current_settle,
                daily_return=daily_return,
                return_index=return_index,
                rule_version=ROLL_NEUTRAL_RULE_VERSION,
                input_snapshot_ids=tuple(lineage),
            )
        )
    return output


def build_tsmom_measurement_comparison(
    *,
    continuous_rows: list[ResearchContinuousPriceDailyRow],
    return_rows: list[RollNeutralReturnDailyRow],
    spec: StrategySpec,
    multiplier: float,
) -> list[dict[str, object]]:
    """Apply identical TSMOM parameters to the two price measurement series."""
    continuous = sorted(continuous_rows, key=lambda row: row.trade_date)
    neutral = sorted(return_rows, key=lambda row: row.trade_date)
    if [row.trade_date for row in continuous] != [row.trade_date for row in neutral]:
        raise StrategyError("continuous price and roll-neutral index dates do not align")
    if multiplier <= 0:
        raise StrategyError("contract multiplier must be positive")
    momentum_days = int(spec.signal_windows["momentum_days"])
    volatility_returns = int(spec.signal_windows["volatility_returns"])
    if momentum_days < 1 or volatility_returns < 2:
        raise StrategyError("TSMOM windows must include momentum>=1 and volatility>=2")

    additive_prices = [float(row.adjusted_price) for row in continuous]
    neutral_prices = [row.return_index for row in neutral]
    additive_previous_direction = 0
    neutral_previous_direction = 0
    output: list[dict[str, object]] = []

    for index, current in enumerate(continuous):
        enough_history = index >= max(momentum_days, volatility_returns)
        additive_daily_return = (
            0.0
            if index == 0
            else additive_prices[index] / additive_prices[index - 1] - 1.0
        )
        neutral_daily_return = neutral[index].daily_return
        additive_momentum = 0.0
        neutral_momentum = 0.0
        additive_sigma: float | None = None
        neutral_sigma: float | None = None
        additive_direction = 0
        neutral_direction = 0
        additive_lots = 0
        neutral_lots = 0
        warning_code = "INSUFFICIENT_LOOKBACK"

        if enough_history:
            warning_code = ""
            additive_momentum = (
                additive_prices[index] / additive_prices[index - momentum_days] - 1.0
            )
            neutral_momentum = (
                neutral_prices[index] / neutral_prices[index - momentum_days] - 1.0
            )
            additive_direction = _direction(additive_momentum, additive_previous_direction)
            neutral_direction = _direction(neutral_momentum, neutral_previous_direction)
            additive_previous_direction = additive_direction or additive_previous_direction
            neutral_previous_direction = neutral_direction or neutral_previous_direction
            additive_sigma = _annualized_sigma(
                additive_prices,
                end_index=index,
                return_count=volatility_returns,
            )
            neutral_sigma = _annualized_sigma(
                neutral_prices,
                end_index=index,
                return_count=volatility_returns,
            )
            actual_settle = neutral[index].mapped_contract_settle
            additive_lots = _target_lots(
                direction=additive_direction,
                sigma=additive_sigma,
                actual_settle=actual_settle,
                multiplier=multiplier,
                spec=spec,
            )
            neutral_lots = _target_lots(
                direction=neutral_direction,
                sigma=neutral_sigma,
                actual_settle=actual_settle,
                multiplier=multiplier,
                spec=spec,
            )

        output.append(
            {
                "product_code": PRODUCT_CODE,
                "signal_object_id": SIGNAL_OBJECT_ID,
                "trade_date": current.trade_date,
                "mapped_contract": current.mapped_contract,
                "is_roll": current.is_roll,
                "roll_from_contract": current.roll_from_contract,
                "roll_to_contract": current.roll_to_contract,
                "raw_settle": neutral[index].mapped_contract_settle,
                "additive_adjusted_settle": additive_prices[index],
                "roll_neutral_return_index": neutral_prices[index],
                "additive_daily_return": additive_daily_return,
                "roll_neutral_daily_return": neutral_daily_return,
                "daily_return_difference_bps": (
                    additive_daily_return - neutral_daily_return
                )
                * 10_000.0,
                "additive_momentum": additive_momentum,
                "roll_neutral_momentum": neutral_momentum,
                "momentum_difference_bps": (
                    additive_momentum - neutral_momentum
                )
                * 10_000.0,
                "additive_annualized_sigma": additive_sigma,
                "roll_neutral_annualized_sigma": neutral_sigma,
                "sigma_difference": (
                    None
                    if additive_sigma is None or neutral_sigma is None
                    else additive_sigma - neutral_sigma
                ),
                "additive_direction": additive_direction,
                "roll_neutral_direction": neutral_direction,
                "direction_disagreement": (
                    enough_history and additive_direction != neutral_direction
                ),
                "additive_target_lots": additive_lots,
                "roll_neutral_target_lots": neutral_lots,
                "target_lot_difference": additive_lots - neutral_lots,
                "target_lot_disagreement": enough_history and additive_lots != neutral_lots,
                "warning_code": warning_code,
                "rule_version": ROLL_NEUTRAL_RULE_VERSION,
            }
        )
    return output


def _validate_inputs(
    *,
    continuous_rows: list[ResearchContinuousPriceDailyRow],
    spec: StrategySpec,
) -> None:
    if spec.strategy_type != "baseline_tsmom":
        raise StrategyError("R93F requires the baseline_tsmom strategy specification")
    invalid = [
        row
        for row in continuous_rows
        if row.product_code != PRODUCT_CODE
        or row.signal_object_id != SIGNAL_OBJECT_ID
        or row.price_field != "settle"
    ]
    if invalid:
        raise StrategyError("R93F requires CF.C1 continuous settlement rows only")


def _quote_index(
    quotes: list[CoreQuoteDailyRow],
) -> dict[tuple[str, date], CoreQuoteDailyRow]:
    selected = [row for row in quotes if row.product_code == PRODUCT_CODE]
    quote_by_key = {(row.contract_code, row.trade_date): row for row in selected}
    if len(quote_by_key) != len(selected):
        raise StrategyError("core quote contains duplicate CF contract-date rows")
    return quote_by_key


def _settlement_quote(
    quote_by_key: dict[tuple[str, date], CoreQuoteDailyRow],
    *,
    contract: str,
    trade_date: date,
) -> CoreQuoteDailyRow:
    quote = quote_by_key.get((contract, trade_date))
    if quote is None or quote.settle is None:
        raise StrategyError(f"{trade_date}: settlement missing for {contract}")
    if float(quote.settle) <= 0:
        raise StrategyError(f"{trade_date}: settlement must be positive for {contract}")
    return quote


def _assert_raw_price_matches(
    *,
    current: ResearchContinuousPriceDailyRow,
    mapped_quote: CoreQuoteDailyRow,
) -> None:
    if not math.isclose(
        float(current.raw_price),
        float(mapped_quote.settle),
        rel_tol=1e-12,
        abs_tol=1e-9,
    ):
        raise StrategyError(
            f"{current.trade_date}: continuous raw settle does not match core quote for "
            f"{current.mapped_contract}"
        )


def _validate_roll_row(
    *,
    current: ResearchContinuousPriceDailyRow,
    previous: ResearchContinuousPriceDailyRow,
) -> None:
    if current.roll_from_contract != previous.mapped_contract:
        raise StrategyError(
            f"{current.trade_date}: roll_from_contract does not match prior mapping"
        )
    if current.roll_to_contract != current.mapped_contract:
        raise StrategyError(
            f"{current.trade_date}: roll_to_contract does not match current mapping"
        )


def _annualized_sigma(
    prices: list[float],
    *,
    end_index: int,
    return_count: int,
) -> float:
    log_returns = [
        math.log(prices[offset] / prices[offset - 1])
        for offset in range(end_index - return_count + 1, end_index + 1)
    ]
    return statistics.stdev(log_returns) * math.sqrt(252)


def _direction(momentum: float, previous_direction: int) -> int:
    if momentum > 0:
        return 1
    if momentum < 0:
        return -1
    return previous_direction


def _target_lots(
    *,
    direction: int,
    sigma: float,
    actual_settle: float,
    multiplier: float,
    spec: StrategySpec,
) -> int:
    sigma_effective = max(sigma, spec.sizing.vol_floor)
    unsigned_lots = math.floor(
        spec.sizing.capital_base
        * spec.sizing.target_vol
        / sigma_effective
        / (actual_settle * multiplier)
    )
    return direction * min(unsigned_lots, spec.sizing.max_lots)


def _confirmed_multiplier() -> float:
    config = load_product_config(PRODUCT_CODE)
    if not isinstance(config.multiplier, int | float) or float(config.multiplier) <= 0:
        raise StrategyError("CF multiplier is not confirmed in product config")
    return float(config.multiplier)


def _research_warnings(
    *,
    return_rows: list[RollNeutralReturnDailyRow],
    comparison_rows: list[dict[str, object]],
) -> list[str]:
    warnings: list[str] = []
    if not any(row.is_roll for row in return_rows):
        warnings.append("NO_ROLL_EVENT_IN_INPUT_RANGE: 当前区间无法检验换月日口径")
    if not any(not row["warning_code"] for row in comparison_rows):
        warnings.append("INSUFFICIENT_TSMOM_LOOKBACK_FOR_COMPARISON: 当前区间不足完整窗口")
    return warnings


def _comparison_statistics(rows: list[dict[str, object]]) -> dict[str, object]:
    eligible = [row for row in rows if not row["warning_code"]]
    if not eligible:
        return {
            "eligible_row_count": 0,
            "mean_abs_daily_return_difference_bps": None,
            "median_sigma_ratio_roll_neutral_to_additive": None,
            "mean_abs_target_lot_difference": None,
            "max_abs_target_lot_difference": None,
            "direction_disagreement_rate": None,
            "target_lot_disagreement_rate": None,
        }
    sigma_ratios = [
        float(row["roll_neutral_annualized_sigma"])
        / float(row["additive_annualized_sigma"])
        for row in eligible
        if row["additive_annualized_sigma"] is not None
        and float(row["additive_annualized_sigma"]) > 0
        and row["roll_neutral_annualized_sigma"] is not None
    ]
    lot_differences = [abs(int(row["target_lot_difference"])) for row in eligible]
    return {
        "eligible_row_count": len(eligible),
        "mean_abs_daily_return_difference_bps": statistics.mean(
            abs(float(row["daily_return_difference_bps"])) for row in eligible
        ),
        "median_sigma_ratio_roll_neutral_to_additive": (
            statistics.median(sigma_ratios) if sigma_ratios else None
        ),
        "mean_abs_target_lot_difference": statistics.mean(lot_differences),
        "max_abs_target_lot_difference": max(lot_differences),
        "direction_disagreement_rate": statistics.mean(
            bool(row["direction_disagreement"]) for row in eligible
        ),
        "target_lot_disagreement_rate": statistics.mean(
            bool(row["target_lot_disagreement"]) for row in eligible
        ),
    }


def _output_paths(
    *,
    start: date,
    end: date,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    root = output_dir or data_dir() / "strategy" / PRODUCT_CODE / "return_index"
    report_root = report_output_dir or reports_dir() / "strategy" / "return_index"
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return {
        "return_index": root / f"{stem}_roll_neutral_return_daily.parquet",
        "comparison": root / f"{stem}_measurement_comparison_daily.parquet",
        "warnings": root / f"{stem}_roll_neutral_return_warnings.csv",
        "json": report_root / f"{stem}_roll_neutral_return_research.json",
        "manifest": root / f"{stem}_roll_neutral_return_manifest.json",
        "markdown": report_root / f"{stem}_roll_neutral_return_research.md",
    }


def _write_parquet(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records).to_parquet(path, index=False)


def _write_warnings(path: Path, *, run_id: str, warnings: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("run_id", "warning_code", "message"))
        writer.writeheader()
        for warning in warnings:
            code, _, message = warning.partition(":")
            writer.writerow(
                {
                    "run_id": run_id,
                    "warning_code": code,
                    "message": message.strip() or warning,
                }
            )


def _write_json(
    *,
    path: Path,
    result: RollNeutralReturnResearchResult,
    statistics_payload: dict[str, object],
    warnings: list[str],
) -> None:
    payload = {
        **result.to_summary(),
        "rule_version": ROLL_NEUTRAL_RULE_VERSION,
        "measurement_statistics": statistics_payload,
        "warnings": warnings,
        "research_boundary": RESEARCH_BOUNDARY,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_markdown(
    *,
    result: RollNeutralReturnResearchResult,
    return_rows: list[RollNeutralReturnDailyRow],
    comparison_rows: list[dict[str, object]],
    statistics_payload: dict[str, object],
    warnings: list[str],
) -> None:
    latest = comparison_rows[-1]
    roll_rows = [row for row in comparison_rows if row["is_roll"]]
    lines = [
        "# CF R93F 无换月跳空收益指数研究",
        "",
        "## 数据状态",
        "",
        f"- 数据区间：`{result.start}` 至 `{result.end}`",
        f"- 逐日样本：`{result.row_count}`，完整 TSMOM 窗口：`{result.eligible_row_count}`",
        f"- 主力换月：`{result.roll_count}` 次",
        f"- 现有加法连续价：`{result.continuous_price_path}`",
        f"- 真实合约结算价：`{result.core_quote_path}`",
        "",
        "## 研究定义",
        "",
        "- 非换月日：使用映射真实合约从上一交易日到当日的结算价收益。",
        "- 换月日：继续使用旧合约从上一交易日到当日的结算价收益；不把新旧合约同日价差计入收益。",
        "- 换月后的下一交易日起：使用新合约自身的相邻交易日收益。",
        "- 将上述收益复利为基准 100 指数，再使用与 `CF_tsmom_v0` 完全相同的 20 日参数。",
        "",
        "## 全历史测量差异",
        "",
        "| 指标 | 结果 |",
        "| --- | ---: |",
        f"| 方向分歧日 | {result.direction_disagreement_count} |",
        f"| 目标手数分歧日 | {result.target_lot_disagreement_count} |",
        "| 方向分歧率 | "
        f"{_fmt_pct(statistics_payload['direction_disagreement_rate'])} |",
        "| 目标手数分歧率 | "
        f"{_fmt_pct(statistics_payload['target_lot_disagreement_rate'])} |",
        "| 日收益绝对差均值 | "
        f"{_fmt_number(statistics_payload['mean_abs_daily_return_difference_bps'], 3)} bps |",
        "| 无跳空/加法连续价波动率中位比 | "
        f"{_fmt_number(statistics_payload['median_sigma_ratio_roll_neutral_to_additive'], 4)} |",
        "| 目标手数绝对差均值 | "
        f"{_fmt_number(statistics_payload['mean_abs_target_lot_difference'], 3)} |",
        "| 目标手数最大绝对差 | "
        f"{_fmt_number(statistics_payload['max_abs_target_lot_difference'], 0)} |",
        "",
        "## 最新日对照",
        "",
        f"- 日期/合约：`{latest['trade_date']}` / `{latest['mapped_contract']}`",
        f"- 真实结算价：`{float(latest['raw_settle']):,.2f}`",
        f"- 加法连续价：`{float(latest['additive_adjusted_settle']):,.2f}`",
        f"- 20 日动量：加法 `{_fmt_pct(latest['additive_momentum'])}`，"
        f"无跳空 `{_fmt_pct(latest['roll_neutral_momentum'])}`",
        f"- 年化波动率：加法 `{_fmt_pct(latest['additive_annualized_sigma'])}`，"
        f"无跳空 `{_fmt_pct(latest['roll_neutral_annualized_sigma'])}`",
        f"- 方向：加法 `{_direction_label(int(latest['additive_direction']))}`，"
        f"无跳空 `{_direction_label(int(latest['roll_neutral_direction']))}`",
        f"- 研究测量手数：加法 `{latest['additive_target_lots']}`，"
        f"无跳空 `{latest['roll_neutral_target_lots']}`",
        "",
        "## 换月日核对",
        "",
        "| 日期 | 换出/换入 | 加法日收益 | 旧合约日收益 | 差异(bps) |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in roll_rows[-12:]:
        lines.append(
            f"| {row['trade_date']} | {row['roll_from_contract']} / "
            f"{row['roll_to_contract']} | {_fmt_pct(row['additive_daily_return'])} | "
            f"{_fmt_pct(row['roll_neutral_daily_return'])} | "
            f"{float(row['daily_return_difference_bps']):.3f} |"
        )
    if not roll_rows:
        lines.append("| 无 | 无 | 无 | 无 | 无 |")
    lines.extend(
        [
            "",
            "## 研究判断",
            "",
            _research_judgement(result=result, statistics_payload=statistics_payload),
            "",
            "## 警告与人审项",
            "",
        ]
    )
    lines.extend(f"- {warning}" for warning in warnings)
    if not warnings:
        lines.append("- 无数据质量警告。")
    lines.extend(
        [
            "- 是否为无换月跳空口径建立新版本策略规格，必须在独立历史回测后人工审批。",
            "- 现有 `CF_tsmom_v0`、R90 影子台账和既有历史结果均未修改。",
            "",
            "## 研究边界",
            "",
            f"> {RESEARCH_BOUNDARY}",
            "",
            "本报告不包含 forward return，不评价未来收益，也不自动触发策略晋级。",
        ]
    )
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _research_judgement(
    *,
    result: RollNeutralReturnResearchResult,
    statistics_payload: dict[str, object],
) -> str:
    direction_rate = statistics_payload["direction_disagreement_rate"]
    target_rate = statistics_payload["target_lot_disagreement_rate"]
    if result.direction_disagreement_count:
        return (
            "- 测量口径已在部分历史日期改变方向，属于实质性模型输入差异。"
            "应先建立独立候选规格和完整 T+1 回测，不得静默替换现有策略。"
        )
    if target_rate is not None and float(target_rate) > 0:
        return (
            "- 当前未观察到方向改变，但波动率尺度导致部分日期目标手数不同。"
            "这说明修正主要影响仓位测量，仍需独立回测后才能决定是否升级。"
        )
    if direction_rate is None:
        return "- 历史长度不足以形成完整 TSMOM 对照，暂不能判断测量影响。"
    return "- 当前样本未观察到方向或目标手数差异，保留侧车监测即可。"


def _write_manifest(*, result: RollNeutralReturnResearchResult) -> None:
    input_paths = (
        result.continuous_price_path,
        result.core_quote_path,
        result.strategy_spec_path,
    )
    artifact_paths = (
        result.return_index_path,
        result.comparison_path,
        result.warning_csv_path,
        result.json_path,
        result.markdown_path,
    )
    payload = {
        **result.to_summary(),
        "rule_version": ROLL_NEUTRAL_RULE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "input_sha256": {str(path): _sha256(path) for path in input_paths},
        "artifact_sha256": {str(path): _sha256(path) for path in artifact_paths},
        "research_boundary": RESEARCH_BOUNDARY,
    }
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    result.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _unique_ids(*groups: list[str]) -> list[str]:
    values: list[str] = []
    for group in groups:
        for value in group:
            if value not in values:
                values.append(value)
    if not values:
        raise StrategyError("roll-neutral return row requires input snapshot lineage")
    return values


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fmt_pct(value: object) -> str:
    if value is None:
        return "不可用"
    return f"{float(value):.2%}"


def _fmt_number(value: object, digits: int) -> str:
    if value is None:
        return "不可用"
    return f"{float(value):.{digits}f}"


def _direction_label(value: int) -> str:
    return {1: "long", -1: "short", 0: "flat"}[value]


def _default_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"cf_r93f_roll_neutral_{stamp}_{uuid.uuid4().hex[:8]}"
