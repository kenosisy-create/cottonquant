"""Research-mode CF core quote data quality checks."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.core.trading_calendar import official_calendar_path
from cotton_factor.research_workbench.core_quotes import CORE_QUOTE_FILE_NAME

PRODUCT_CODE = "CF"
EXCHANGE = "CZCE"
QUALITY_REPORT_DIR = "data_quality"
Severity = Literal["CRITICAL", "WARNING", "INFO"]
Status = Literal["PASS", "FAIL", "WARN", "INFO"]
REQUIRED_COLUMNS = (
    "source_snapshot_id",
    "exchange",
    "product_code",
    "contract_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "settle",
    "volume",
    "open_interest",
)
PRICE_COLUMNS = ("open", "high", "low", "close", "settle")
OPTIONAL_RISK_COLUMNS = ("limit_up", "limit_down", "margin_rate", "trading_status")


@dataclass(frozen=True)
class DataQualityIssue:
    """One machine-readable quality check row."""

    severity: Severity
    check_id: str
    status: Status
    message: str
    field_name: str | None = None
    contract_code: str | None = None
    observed_value: str | None = None
    threshold: str | None = None

    def to_row(self) -> dict[str, str]:
        """Return a CSV-safe row."""
        return {
            "severity": self.severity,
            "check_id": self.check_id,
            "status": self.status,
            "field_name": self.field_name or "",
            "contract_code": self.contract_code or "",
            "observed_value": self.observed_value or "",
            "threshold": self.threshold or "",
            "message": self.message,
        }


@dataclass(frozen=True)
class CfDataQualityResult:
    """Result of an R06 CF data quality run."""

    trade_date: date
    product_code: str
    input_path: Path
    csv_path: Path
    markdown_path: Path
    row_count: int
    issues: tuple[DataQualityIssue, ...]

    @property
    def passed(self) -> bool:
        """Return whether no critical check failed."""
        return not any(
            issue.severity == "CRITICAL" and issue.status == "FAIL"
            for issue in self.issues
        )

    def severity_counts(self) -> dict[str, int]:
        """Count non-passing rows by severity for summaries."""
        counts = {"CRITICAL": 0, "WARNING": 0, "INFO": 0}
        for issue in self.issues:
            if issue.status != "PASS":
                counts[issue.severity] += 1
        return counts

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable CLI summary."""
        return {
            "trade_date": self.trade_date.isoformat(),
            "product_code": self.product_code,
            "input_path": str(self.input_path),
            "csv_path": str(self.csv_path),
            "markdown_path": str(self.markdown_path),
            "row_count": self.row_count,
            "passed": self.passed,
            "severity_counts": self.severity_counts(),
        }


def check_cf_data_quality(
    *,
    trade_date: date,
    core_output_dir: Path | None = None,
    core_quote_path: Path | None = None,
    report_output_dir: Path | None = None,
    volume_spike_ratio_threshold: float = 5.0,
    oi_spike_ratio_threshold: float = 5.0,
) -> CfDataQualityResult:
    """Check one CF core quote table and write CSV/Markdown quality reports."""
    if volume_spike_ratio_threshold <= 0 or oi_spike_ratio_threshold <= 0:
        raise ResearchWorkbenchError("spike ratio thresholds must be positive")

    input_path = core_quote_path or _default_core_quote_path(core_output_dir)
    if not input_path.exists():
        raise ResearchWorkbenchError(f"core quote parquet not found: {input_path}")

    frame = pd.read_parquet(input_path)
    issues: list[DataQualityIssue] = []
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing_columns:
        issues.append(
            DataQualityIssue(
                severity="CRITICAL",
                check_id="required_columns_present",
                status="FAIL",
                field_name=",".join(missing_columns),
                message=f"core_quote_daily is missing required columns: {missing_columns}",
            )
        )

    selected = _selected_trade_date_frame(frame, trade_date=trade_date, issues=issues)
    if selected is not None:
        issues.extend(_check_required_values(selected))
        issues.extend(_check_primary_key(selected))
        issues.extend(_check_positive_prices(selected))
        issues.extend(_check_high_low_order(selected))
        issues.extend(_check_non_negative_numeric(selected, "volume"))
        issues.extend(_check_non_negative_numeric(selected, "open_interest"))
        issues.extend(_check_settle_exists(selected))
        issues.extend(_check_active_cf_contract(selected))
        issues.extend(_check_trading_calendar(trade_date))
        issues.extend(
            _check_volume_oi_spikes(
                frame,
                selected,
                trade_date=trade_date,
                volume_threshold=volume_spike_ratio_threshold,
                oi_threshold=oi_spike_ratio_threshold,
            )
        )
        issues.extend(_check_optional_risk_fields(frame))

    row_count = 0 if selected is None else len(selected)
    csv_path, markdown_path = _report_paths(
        trade_date=trade_date,
        report_output_dir=report_output_dir,
    )
    result = CfDataQualityResult(
        trade_date=trade_date,
        product_code=PRODUCT_CODE,
        input_path=input_path,
        csv_path=csv_path,
        markdown_path=markdown_path,
        row_count=row_count,
        issues=tuple(issues),
    )
    _write_quality_csv(csv_path=csv_path, issues=result.issues)
    _write_quality_markdown(markdown_path=markdown_path, result=result)
    return result


def _selected_trade_date_frame(
    frame: pd.DataFrame,
    *,
    trade_date: date,
    issues: list[DataQualityIssue],
) -> pd.DataFrame | None:
    if "trade_date" not in frame.columns:
        return None

    working = frame.copy()
    working["trade_date"] = working["trade_date"].astype(str)
    selected = working.loc[working["trade_date"] == trade_date.isoformat()].copy()
    if selected.empty:
        issues.append(
            DataQualityIssue(
                severity="CRITICAL",
                check_id="active_cf_contract_exists",
                status="FAIL",
                message=(
                    f"no core_quote_daily rows found for "
                    f"{PRODUCT_CODE} {trade_date.isoformat()}"
                ),
            )
        )
    return selected


def _check_required_values(frame: pd.DataFrame) -> list[DataQualityIssue]:
    issues: list[DataQualityIssue] = []
    for column in REQUIRED_COLUMNS:
        if column not in frame.columns:
            continue
        missing_count = int(
            frame[column].isna().sum()
            + (frame[column].astype(str).str.len() == 0).sum()
        )
        if missing_count:
            issues.append(
                DataQualityIssue(
                    severity="CRITICAL",
                    check_id="required_fields_not_null",
                    status="FAIL",
                    field_name=column,
                    observed_value=str(missing_count),
                    message=f"{column} has {missing_count} missing values",
                )
            )
        else:
            issues.append(
                DataQualityIssue(
                    severity="CRITICAL",
                    check_id="required_fields_not_null",
                    status="PASS",
                    field_name=column,
                    message=f"{column} is complete",
                )
            )
    return issues


def _check_primary_key(frame: pd.DataFrame) -> list[DataQualityIssue]:
    key_columns = ["trade_date", "contract_code"]
    if any(column not in frame.columns for column in key_columns):
        return []
    duplicates = frame.loc[frame.duplicated(subset=key_columns, keep=False), key_columns]
    if duplicates.empty:
        return [
            DataQualityIssue(
                severity="CRITICAL",
                check_id="primary_key_unique",
                status="PASS",
                message="trade_date + contract_code is unique",
            )
        ]
    duplicate_keys = sorted(
        f"{row.trade_date}/{row.contract_code}"
        for row in duplicates.itertuples(index=False)
    )
    return [
        DataQualityIssue(
            severity="CRITICAL",
            check_id="primary_key_unique",
            status="FAIL",
            observed_value=";".join(duplicate_keys),
            message="duplicate trade_date + contract_code keys found",
        )
    ]


def _check_positive_prices(frame: pd.DataFrame) -> list[DataQualityIssue]:
    issues: list[DataQualityIssue] = []
    for column in PRICE_COLUMNS:
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        bad_rows = frame.loc[values.isna() | (values <= 0)]
        if bad_rows.empty:
            issues.append(
                DataQualityIssue(
                    severity="CRITICAL",
                    check_id="positive_prices",
                    status="PASS",
                    field_name=column,
                    threshold=">0",
                    message=f"{column} prices are positive",
                )
            )
            continue
        for row in bad_rows.itertuples(index=False):
            issues.append(
                DataQualityIssue(
                    severity="CRITICAL",
                    check_id="positive_prices",
                    status="FAIL",
                    field_name=column,
                    contract_code=str(getattr(row, "contract_code", "")),
                    observed_value=str(getattr(row, column)),
                    threshold=">0",
                    message=f"{column} must be positive",
                )
            )
    return issues


def _check_high_low_order(frame: pd.DataFrame) -> list[DataQualityIssue]:
    if "high" not in frame.columns or "low" not in frame.columns:
        return []
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    bad_rows = frame.loc[high < low]
    if bad_rows.empty:
        return [
            DataQualityIssue(
                severity="CRITICAL",
                check_id="high_low_order",
                status="PASS",
                message="high >= low for all rows",
            )
        ]
    return [
        DataQualityIssue(
            severity="CRITICAL",
            check_id="high_low_order",
            status="FAIL",
            contract_code=str(row.contract_code),
            observed_value=f"high={row.high},low={row.low}",
            message="high must be >= low",
        )
        for row in bad_rows.itertuples(index=False)
    ]


def _check_non_negative_numeric(frame: pd.DataFrame, column: str) -> list[DataQualityIssue]:
    if column not in frame.columns:
        return []
    values = pd.to_numeric(frame[column], errors="coerce")
    bad_rows = frame.loc[values.isna() | (values < 0)]
    if bad_rows.empty:
        return [
            DataQualityIssue(
                severity="CRITICAL",
                check_id=f"{column}_non_negative",
                status="PASS",
                field_name=column,
                threshold=">=0",
                message=f"{column} is non-negative",
            )
        ]
    return [
        DataQualityIssue(
            severity="CRITICAL",
            check_id=f"{column}_non_negative",
            status="FAIL",
            field_name=column,
            contract_code=str(getattr(row, "contract_code", "")),
            observed_value=str(getattr(row, column)),
            threshold=">=0",
            message=f"{column} must be non-negative",
        )
        for row in bad_rows.itertuples(index=False)
    ]


def _check_settle_exists(frame: pd.DataFrame) -> list[DataQualityIssue]:
    if "settle" not in frame.columns:
        return []
    missing_count = int(frame["settle"].isna().sum())
    if missing_count:
        return [
            DataQualityIssue(
                severity="CRITICAL",
                check_id="settle_exists",
                status="FAIL",
                field_name="settle",
                observed_value=str(missing_count),
                message="post-settlement research requires settle values",
            )
        ]
    return [
        DataQualityIssue(
            severity="CRITICAL",
            check_id="settle_exists",
            status="PASS",
            field_name="settle",
            message="settle values are available",
        )
    ]


def _check_active_cf_contract(frame: pd.DataFrame) -> list[DataQualityIssue]:
    if "product_code" not in frame.columns:
        return []
    cf_rows = frame.loc[frame["product_code"].astype(str).str.upper() == PRODUCT_CODE]
    if cf_rows.empty:
        return [
            DataQualityIssue(
                severity="CRITICAL",
                check_id="active_cf_contract_exists",
                status="FAIL",
                message=f"no active {PRODUCT_CODE} contract rows found for the date",
            )
        ]
    return [
        DataQualityIssue(
            severity="CRITICAL",
            check_id="active_cf_contract_exists",
            status="PASS",
            observed_value=str(len(cf_rows)),
            message=f"{len(cf_rows)} {PRODUCT_CODE} contract rows available",
        )
    ]


def _check_trading_calendar(trade_date: date) -> list[DataQualityIssue]:
    path = official_calendar_path(exchange=EXCHANGE, year=trade_date.year)
    if not path.exists():
        return [
            DataQualityIssue(
                severity="INFO",
                check_id="trading_calendar_available",
                status="INFO",
                message=(
                    f"official calendar not available for "
                    f"{EXCHANGE} {trade_date.year}; skipped"
                ),
            )
        ]

    calendar = pd.read_csv(path)
    if "trade_date" not in calendar.columns or "is_trading_day" not in calendar.columns:
        return [
            DataQualityIssue(
                severity="WARNING",
                check_id="missing_trading_day",
                status="WARN",
                message=f"calendar file missing required columns: {path}",
            )
        ]
    matched = calendar.loc[calendar["trade_date"].astype(str) == trade_date.isoformat()]
    if matched.empty:
        return [
            DataQualityIssue(
                severity="WARNING",
                check_id="missing_trading_day",
                status="WARN",
                message=f"{trade_date.isoformat()} is absent from official calendar {path}",
            )
        ]
    is_trading_day = str(matched.iloc[0]["is_trading_day"]).strip().lower() in {"1", "true", "yes"}
    if not is_trading_day:
        return [
            DataQualityIssue(
                severity="WARNING",
                check_id="missing_trading_day",
                status="WARN",
                message=f"{trade_date.isoformat()} is marked non-trading in official calendar",
            )
        ]
    return [
        DataQualityIssue(
            severity="INFO",
            check_id="missing_trading_day",
            status="PASS",
            message=f"{trade_date.isoformat()} is present as trading day in official calendar",
        )
    ]


def _check_volume_oi_spikes(
    full_frame: pd.DataFrame,
    selected: pd.DataFrame,
    *,
    trade_date: date,
    volume_threshold: float,
    oi_threshold: float,
) -> list[DataQualityIssue]:
    required = {"trade_date", "product_code", "volume", "open_interest"}
    if not required.issubset(full_frame.columns):
        return []

    working = full_frame.copy()
    working["trade_date"] = working["trade_date"].astype(str)
    previous_dates = sorted(
        value
        for value in working["trade_date"].dropna().unique()
        if str(value) < trade_date.isoformat()
    )
    if not previous_dates:
        return [
            DataQualityIssue(
                severity="INFO",
                check_id="volume_oi_spike",
                status="INFO",
                message="no previous date available for volume/OI spike comparison",
            )
        ]

    previous = working.loc[
        (working["trade_date"] == previous_dates[-1])
        & (working["product_code"].astype(str).str.upper() == PRODUCT_CODE)
    ]
    if previous.empty:
        return [
            DataQualityIssue(
                severity="INFO",
                check_id="volume_oi_spike",
                status="INFO",
                message="previous date has no CF rows for volume/OI comparison",
            )
        ]

    return [
        _aggregate_spike_issue(
            selected=selected,
            previous=previous,
            column="volume",
            threshold=volume_threshold,
        ),
        _aggregate_spike_issue(
            selected=selected,
            previous=previous,
            column="open_interest",
            threshold=oi_threshold,
        ),
    ]


def _aggregate_spike_issue(
    *,
    selected: pd.DataFrame,
    previous: pd.DataFrame,
    column: str,
    threshold: float,
) -> DataQualityIssue:
    current_value = float(pd.to_numeric(selected[column], errors="coerce").fillna(0).sum())
    previous_value = float(pd.to_numeric(previous[column], errors="coerce").fillna(0).sum())
    if previous_value == 0:
        if current_value > 0:
            return DataQualityIssue(
                severity="WARNING",
                check_id=f"{column}_spike",
                status="WARN",
                field_name=column,
                observed_value=f"previous=0,current={current_value:g}",
                threshold=f"ratio<={threshold:g}",
                message=f"{column} cannot compute stable ratio because previous value is zero",
            )
        return DataQualityIssue(
            severity="INFO",
            check_id=f"{column}_spike",
            status="INFO",
            field_name=column,
            message=f"{column} is zero on current and previous dates",
        )

    ratio = current_value / previous_value
    if ratio > threshold:
        return DataQualityIssue(
            severity="WARNING",
            check_id=f"{column}_spike",
            status="WARN",
            field_name=column,
            observed_value=f"{ratio:.6g}",
            threshold=f"<={threshold:g}",
            message=f"{column} aggregate ratio exceeded diagnostic threshold",
        )
    return DataQualityIssue(
        severity="WARNING",
        check_id=f"{column}_spike",
        status="PASS",
        field_name=column,
        observed_value=f"{ratio:.6g}",
        threshold=f"<={threshold:g}",
        message=f"{column} aggregate ratio is within diagnostic threshold",
    )


def _check_optional_risk_fields(frame: pd.DataFrame) -> list[DataQualityIssue]:
    missing = [column for column in OPTIONAL_RISK_COLUMNS if column not in frame.columns]
    if missing:
        return [
            DataQualityIssue(
                severity="INFO",
                check_id="optional_risk_fields_visible",
                status="INFO",
                field_name=",".join(missing),
                message=(
                    "optional risk fields are not present in core_quote_daily; "
                    "settlement/risk table is still required for full review"
                ),
            )
        ]

    null_columns = [
        column
        for column in OPTIONAL_RISK_COLUMNS
        if int(frame[column].isna().sum()) > 0
    ]
    if null_columns:
        return [
            DataQualityIssue(
                severity="INFO",
                check_id="optional_risk_fields_visible",
                status="INFO",
                field_name=",".join(null_columns),
                message="optional risk fields are present with null values",
            )
        ]
    return [
        DataQualityIssue(
            severity="INFO",
            check_id="optional_risk_fields_visible",
            status="PASS",
            message="optional risk fields are present",
        )
    ]


def _write_quality_csv(*, csv_path: Path, issues: tuple[DataQualityIssue, ...]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "severity",
            "check_id",
            "status",
            "field_name",
            "contract_code",
            "observed_value",
            "threshold",
            "message",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for issue in issues:
            writer.writerow(issue.to_row())


def _write_quality_markdown(*, markdown_path: Path, result: CfDataQualityResult) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    counts = result.severity_counts()
    lines = [
        f"# CF Data Quality Report - {result.trade_date.isoformat()}",
        "",
        f"- Product: `{result.product_code}`",
        f"- Input: `{result.input_path}`",
        f"- Rows for date: `{result.row_count}`",
        f"- Passed: `{str(result.passed).lower()}`",
        f"- Critical issues: `{counts['CRITICAL']}`",
        f"- Warnings: `{counts['WARNING']}`",
        f"- Info items: `{counts['INFO']}`",
        "",
        "## Issues",
        "",
        "| Severity | Status | Check | Field | Contract | Observed | Threshold | Message |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for issue in result.issues:
        lines.append(
            "| "
            + " | ".join(
                [
                    issue.severity,
                    issue.status,
                    issue.check_id,
                    issue.field_name or "",
                    issue.contract_code or "",
                    issue.observed_value or "",
                    issue.threshold or "",
                    issue.message.replace("|", "\\|"),
                ]
            )
            + " |"
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _report_paths(
    *,
    trade_date: date,
    report_output_dir: Path | None,
) -> tuple[Path, Path]:
    root = report_output_dir or reports_dir() / "research" / QUALITY_REPORT_DIR
    stem = f"{PRODUCT_CODE}_{trade_date.isoformat()}_quality"
    return root / f"{stem}.csv", root / f"{stem}.md"


def _default_core_quote_path(core_output_dir: Path | None) -> Path:
    root = core_output_dir or data_dir() / "core"
    return root / PRODUCT_CODE / CORE_QUOTE_FILE_NAME
