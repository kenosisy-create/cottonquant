"""R86 unified cross-year strategy input preparation."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import (
    ChainMapError,
    ContinuousPriceError,
    StrategyError,
    TradeMappingError,
)
from cotton_factor.common.paths import data_dir, project_root, reports_dir
from cotton_factor.core import (
    CF_MAIN_CYCLE_MONTHS,
    CF_MAIN_CYCLE_ROLL_RULE_VERSION,
    TradingCalendar,
    build_chain_map,
    build_contract_master,
    build_trade_mapping,
    load_trading_calendar_csv,
)
from cotton_factor.core.schemas import (
    CoreChainMapDailyRow,
    CoreContractMasterRow,
    CoreQuoteDailyRow,
    CoreTradingCalendarRow,
)
from cotton_factor.research import build_continuous_price

PRODUCT_CODE = "CF"
EXCHANGE = "CZCE"
SIGNAL_OBJECT_ID = "CF.C1"
INPUT_RULE_VERSION = "V5.1_R86_strategy_inputs_v2_main_cycle"
UNIFIED_CALENDAR_VERSION = "CZCE_OFFICIAL_CF_HISTORY_UNIFIED_V1"


@dataclass(frozen=True)
class StrategyInputBuildResult:
    """Artifacts needed by every historical strategy run."""

    run_id: str
    start: date
    end: date
    core_quote_path: Path
    chain_map_path: Path
    trade_mapping_path: Path
    continuous_price_path: Path
    calendar_validation_path: Path
    warning_csv_path: Path
    manifest_path: Path
    markdown_path: Path
    chain_row_count: int
    trade_mapping_row_count: int
    continuous_row_count: int
    pending_signal_dates: tuple[date, ...]
    warning_count: int

    def to_summary(self) -> dict[str, object]:
        """Return a CLI-safe summary."""
        return {
            "run_id": self.run_id,
            "product_code": PRODUCT_CODE,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "core_quote_path": str(self.core_quote_path),
            "chain_map_path": str(self.chain_map_path),
            "trade_mapping_path": str(self.trade_mapping_path),
            "continuous_price_path": str(self.continuous_price_path),
            "calendar_validation_path": str(self.calendar_validation_path),
            "warning_csv_path": str(self.warning_csv_path),
            "manifest_path": str(self.manifest_path),
            "markdown_path": str(self.markdown_path),
            "chain_row_count": self.chain_row_count,
            "trade_mapping_row_count": self.trade_mapping_row_count,
            "continuous_row_count": self.continuous_row_count,
            "pending_signal_dates": [value.isoformat() for value in self.pending_signal_dates],
            "warning_count": self.warning_count,
        }


def prepare_cf_strategy_inputs(
    *,
    start: date | None = None,
    end: date | None = None,
    core_quote_path: Path | None = None,
    calendar_dir: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> StrategyInputBuildResult:
    """Build one canonical CF chain, T+1 mapping and continuous-price history."""
    quote_path = core_quote_path or data_dir() / "core" / PRODUCT_CODE / "core_quote_daily.parquet"
    quotes = _load_core_quotes(quote_path)
    all_dates = sorted({row.trade_date for row in quotes})
    selected_start = start or all_dates[0]
    selected_end = end or all_dates[-1]
    if selected_start > selected_end:
        raise StrategyError("strategy input start must be <= end")
    if selected_start < all_dates[0] or selected_end > all_dates[-1]:
        raise StrategyError(
            "strategy input range must stay inside core quote coverage "
            f"{all_dates[0]} to {all_dates[-1]}"
        )

    calendar_root = calendar_dir or project_root() / "configs" / "calendars"
    calendar, calendar_validation = _validated_unified_calendar(
        quotes=quotes,
        calendar_dir=calendar_root,
        end=selected_end,
    )
    build_quotes = [row for row in quotes if row.trade_date <= selected_end]
    contracts, contract_warnings = _contract_master_for_quotes(
        quotes=build_quotes,
        calendar=calendar,
    )
    try:
        chain_result = build_chain_map(
            quotes=build_quotes,
            contracts=contracts,
            calendar=calendar,
            product_code=PRODUCT_CODE,
            signal_object_id=SIGNAL_OBJECT_ID,
            roll_rule_version=CF_MAIN_CYCLE_ROLL_RULE_VERSION,
            eligible_delivery_months=CF_MAIN_CYCLE_MONTHS,
        )
        continuous_result = build_continuous_price(
            quotes=build_quotes,
            chain_rows=chain_result.rows,
            product_code=PRODUCT_CODE,
            signal_object_id=SIGNAL_OBJECT_ID,
            price_field="settle",
        )
        resolvable_chain, pending_dates = _resolvable_chain_rows(
            chain_rows=chain_result.rows,
            calendar=calendar,
        )
        trade_result = build_trade_mapping(
            chain_rows=resolvable_chain,
            contracts=contracts,
            calendar=calendar,
            product_code=PRODUCT_CODE,
            signal_object_id=SIGNAL_OBJECT_ID,
        )
    except (ChainMapError, ContinuousPriceError, TradeMappingError) as exc:
        raise StrategyError(f"cannot prepare strategy inputs: {exc}") from exc

    chain_rows = tuple(row for row in chain_result.rows if row.trade_date >= selected_start)
    trade_rows = tuple(row for row in trade_result.rows if row.trade_date >= selected_start)
    continuous_rows = tuple(
        row for row in continuous_result.rows if row.trade_date >= selected_start
    )
    warnings = sorted(
        set(
            [
                *contract_warnings,
                *chain_result.warnings,
                *continuous_result.warnings,
                *trade_result.warnings,
            ]
            + [
                f"{value.isoformat()}: PENDING_NEXT_OFFICIAL_SESSION"
                for value in pending_dates
                if value >= selected_start
            ]
        )
    )

    active_run_id = run_id or _default_run_id()
    paths = _output_paths(
        start=selected_start,
        end=selected_end,
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    _write_rows(paths["chain"], chain_rows)
    _write_rows(paths["trade"], trade_rows)
    _write_rows(paths["continuous"], continuous_rows)
    _write_calendar_validation(paths["calendar_validation"], calendar_validation)
    _write_warnings(paths["warnings"], warnings=warnings, run_id=active_run_id)

    result = StrategyInputBuildResult(
        run_id=active_run_id,
        start=selected_start,
        end=selected_end,
        core_quote_path=quote_path,
        chain_map_path=paths["chain"],
        trade_mapping_path=paths["trade"],
        continuous_price_path=paths["continuous"],
        calendar_validation_path=paths["calendar_validation"],
        warning_csv_path=paths["warnings"],
        manifest_path=paths["manifest"],
        markdown_path=paths["markdown"],
        chain_row_count=len(chain_rows),
        trade_mapping_row_count=len(trade_rows),
        continuous_row_count=len(continuous_rows),
        pending_signal_dates=tuple(
            value for value in pending_dates if value >= selected_start
        ),
        warning_count=len(warnings),
    )
    _write_manifest(result=result, calendar_dir=calendar_root)
    _write_markdown(result=result, warnings=warnings)
    return result


def _load_core_quotes(path: Path) -> list[CoreQuoteDailyRow]:
    if not path.exists() or not path.is_file():
        raise StrategyError(f"core quote parquet not found: {path}")
    frame = pd.read_parquet(path)
    required = {"product_code", "contract_code", "trade_date", "settle"}
    missing = required - set(frame.columns)
    if missing:
        raise StrategyError(f"core quote parquet missing columns: {sorted(missing)}")
    rows: list[CoreQuoteDailyRow] = []
    for record in frame.to_dict(orient="records"):
        cleaned = _clean_record(record)
        if str(cleaned.get("product_code", "")).upper() == PRODUCT_CODE:
            rows.append(CoreQuoteDailyRow.model_validate(cleaned))
    if not rows:
        raise StrategyError("core quote parquet contains no CF rows")
    return sorted(rows, key=lambda row: (row.trade_date, row.contract_code))


def _validated_unified_calendar(
    *,
    quotes: list[CoreQuoteDailyRow],
    calendar_dir: Path,
    end: date,
) -> tuple[TradingCalendar, list[dict[str, object]]]:
    core_dates = sorted({row.trade_date for row in quotes if row.trade_date <= end})
    core_by_year = {
        year: {value for value in core_dates if value.year == year}
        for year in range(core_dates[0].year, end.year + 1)
    }
    unified_rows: list[CoreTradingCalendarRow] = []
    validation_rows: list[dict[str, object]] = []
    for year, expected_dates in core_by_year.items():
        path = calendar_dir / f"{EXCHANGE}_{year}_OFFICIAL.csv"
        if not path.exists():
            raise StrategyError(f"official calendar missing for strategy history: {path}")
        loaded = load_trading_calendar_csv(fixture_path=path, exchange=EXCHANGE)
        observed_dates = {
            row.trade_date
            for row in loaded
            if row.is_trading_day and row.trade_date <= max(expected_dates)
        }
        missing_dates = sorted(expected_dates - observed_dates)
        extra_dates = sorted(observed_dates - expected_dates)
        status = "PASS" if not missing_dates and not extra_dates else "FAIL"
        validation_rows.append(
            {
                "year": year,
                "status": status,
                "core_trading_days": len(expected_dates),
                "calendar_trading_days": len(observed_dates),
                "missing_dates": ";".join(value.isoformat() for value in missing_dates),
                "extra_dates": ";".join(value.isoformat() for value in extra_dates),
                "calendar_path": str(path),
            }
        )
        if status != "PASS":
            raise StrategyError(
                f"official calendar does not match core quote dates for {year}: "
                f"missing={missing_dates[:5]}, extra={extra_dates[:5]}"
            )
        for row in loaded:
            if row.is_trading_day and row.trade_date <= end:
                unified_rows.append(
                    CoreTradingCalendarRow(
                        exchange=EXCHANGE,
                        trade_date=row.trade_date,
                        is_trading_day=True,
                        calendar_version=UNIFIED_CALENDAR_VERSION,
                        source_snapshot_id=row.source_snapshot_id,
                    )
                )
    return TradingCalendar(unified_rows), validation_rows


def _contract_master_for_quotes(
    *,
    quotes: list[CoreQuoteDailyRow],
    calendar: TradingCalendar,
) -> tuple[list[CoreContractMasterRow], list[str]]:
    delivery_years = sorted({_infer_delivery_year(row) for row in quotes})
    contracts: list[CoreContractMasterRow] = []
    warnings: list[str] = []
    for delivery_year in delivery_years:
        result = build_contract_master(
            product_code=PRODUCT_CODE,
            year=delivery_year,
            trading_dates=None,
        )
        for contract in result.contracts:
            month_dates = [
                value
                for value in calendar.trading_dates
                if value.year == delivery_year and value.month == contract.delivery_month
            ]
            last_trade_date = month_dates[9] if len(month_dates) >= 10 else None
            contracts.append(contract.model_copy(update={"last_trade_date": last_trade_date}))
            if last_trade_date is None:
                warnings.append(
                    f"{contract.contract_code}: last_trade_date unavailable in to-date calendar; "
                    "HUMAN_REVIEW_REQUIRED"
                )
    known_codes = {row.contract_code for row in contracts}
    missing_codes = sorted({row.contract_code for row in quotes} - known_codes)
    if missing_codes:
        raise StrategyError(f"contract master missing quote contracts: {missing_codes[:10]}")
    return contracts, warnings


def _infer_delivery_year(quote: CoreQuoteDailyRow) -> int:
    match = re.fullmatch(r"CF([0-9])([0-9]{2})", quote.contract_code.upper())
    if match is None:
        raise StrategyError(f"unsupported CF contract code: {quote.contract_code}")
    year_digit = int(match.group(1))
    candidates = [
        year
        for year in range(quote.trade_date.year - 1, quote.trade_date.year + 3)
        if year % 10 == year_digit
    ]
    if not candidates:
        raise StrategyError(f"cannot infer delivery year for {quote.contract_code}")
    non_past = [year for year in candidates if year >= quote.trade_date.year]
    return min(non_past) if non_past else max(candidates)


def _resolvable_chain_rows(
    *,
    chain_rows: list[CoreChainMapDailyRow],
    calendar: TradingCalendar,
) -> tuple[list[CoreChainMapDailyRow], list[date]]:
    resolvable: list[CoreChainMapDailyRow] = []
    pending: list[date] = []
    for row in chain_rows:
        try:
            calendar.next_trade_date(row.trade_date)
        except Exception:
            pending.append(row.trade_date)
        else:
            resolvable.append(row)
    return resolvable, pending


def _clean_record(record: dict[str, object]) -> dict[str, object]:
    cleaned: dict[str, object] = {}
    for key, value in record.items():
        if pd.isna(value):
            cleaned[key] = None
        elif key == "trade_date":
            cleaned[key] = pd.to_datetime(value).date()
        else:
            cleaned[key] = value
    return cleaned


def _output_paths(
    *,
    start: date,
    end: date,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    root = output_dir or data_dir() / "strategy" / PRODUCT_CODE / "inputs"
    report_root = report_output_dir or reports_dir() / "strategy" / "inputs"
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return {
        "chain": root / f"{stem}_chain_map_daily.parquet",
        "trade": root / f"{stem}_trade_mapping_daily.parquet",
        "continuous": root / f"{stem}_continuous_price_daily.parquet",
        "calendar_validation": root / f"{stem}_calendar_validation.csv",
        "warnings": root / f"{stem}_strategy_input_warnings.csv",
        "manifest": root / f"{stem}_strategy_input_manifest.json",
        "markdown": report_root / f"{stem}_strategy_inputs.md",
    }


def _write_rows(path: Path, rows: tuple[object, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [row.model_dump(mode="json") for row in rows]
    pd.DataFrame(records).to_parquet(path, index=False)


def _write_calendar_validation(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8")


def _write_warnings(path: Path, *, warnings: list[str], run_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("run_id", "warning_code", "message"))
        writer.writeheader()
        for message in warnings:
            writer.writerow(
                {
                    "run_id": run_id,
                    "warning_code": message.split(":", 1)[-1].strip().split(" ", 1)[0],
                    "message": message,
                }
            )


def _write_manifest(*, result: StrategyInputBuildResult, calendar_dir: Path) -> None:
    payload = {
        **result.to_summary(),
        "rule_version": INPUT_RULE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "calendar_dir": str(calendar_dir),
        "input_sha256": {"core_quote": _sha256(result.core_quote_path)},
        "artifact_sha256": {
            "chain_map": _sha256(result.chain_map_path),
            "trade_mapping": _sha256(result.trade_mapping_path),
            "continuous_price": _sha256(result.continuous_price_path),
            "calendar_validation": _sha256(result.calendar_validation_path),
            "warnings": _sha256(result.warning_csv_path),
        },
        "research_boundary": [
            "连续价格仅用于信号；真实执行使用trade mapping中的可交易合约",
            "T日结算后信号最早在T+1结算成交",
            "不构成交易指令",
        ],
    }
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    result.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_markdown(*, result: StrategyInputBuildResult, warnings: list[str]) -> None:
    lines = [
        "# CF V5.1 策略输入包",
        "",
        f"- 数据区间：`{result.start}` 至 `{result.end}`",
        f"- chain map 行数：`{result.chain_row_count}`",
        f"- T+1 trade mapping 行数：`{result.trade_mapping_row_count}`",
        f"- 连续结算价行数：`{result.continuous_row_count}`",
        f"- 待下一官方交易日确认：`{len(result.pending_signal_dates)}`",
        f"- manifest：`{result.manifest_path}`",
        "",
        "## 研究边界",
        "",
        "- 连续价格仅用于信号，订单和损益必须落到真实可交易合约。",
        "- T 日结算后目标只允许在 T+1 结算成交，新仓位不获得 T 到 T+1 收益。",
        "- 本输入包不包含 forward return，不构成交易指令。",
        "",
        "## 警告",
        "",
    ]
    lines.extend(f"- {message}" for message in warnings)
    if not warnings:
        lines.append("- 无")
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"cf_strategy_inputs_{stamp}_{uuid.uuid4().hex[:8]}"
