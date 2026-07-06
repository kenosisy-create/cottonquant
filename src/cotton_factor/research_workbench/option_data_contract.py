"""R46 option data contract and incoming-path check for CF."""

from __future__ import annotations

import csv
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.common.time import utc_now
from cotton_factor.core.schemas import CoreOptionQuoteDailyRow, validate_rows

PRODUCT_CODE = "CF"
EXCHANGE = "CZCE"
OPTION_CONTRACT_VERSION = "R46_option_data_contract_v1"
CORE_OPTION_QUOTE_FILE_NAME = "core_option_quote_daily.parquet"
REPORT_DIR = "option_data_contract"
EXPECTED_FILE_PATTERNS = (
    "CFOPTIONS{year}.xlsx",
    "CFOPTIONS{year}.xls",
    "ALLOPTIONS{year}.zip",
    "CZCE_CF_OPTIONS_*.csv",
)
HUMAN_REVIEW_REQUIRED = (
    "official_option_field_interpretation",
    "option_symbol_format",
    "underlying_contract_mapping",
    "moneyness_definition",
    "liquidity_thresholds",
    "deep_otm_and_near_expiry_filters",
)
OPTION_CORE_COLUMNS = tuple(CoreOptionQuoteDailyRow.model_fields)


@dataclass(frozen=True)
class OptionDataContractWarningRecord:
    """R46 warning row."""

    severity: str
    warning_code: str
    message: str
    human_review_required: tuple[str, ...] = ()

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable warning row."""
        return {
            "severity": self.severity,
            "warning_code": self.warning_code,
            "message": self.message,
            "human_review_required": list(self.human_review_required),
        }


@dataclass(frozen=True)
class ResearchOptionDataContractResult:
    """Result of building R46 option data contract artifacts."""

    product_code: str
    exchange: str
    run_id: str
    status: str
    incoming_dir: Path
    core_option_quote_path: Path
    core_row_count: int
    incoming_file_count: int
    expected_file_patterns: tuple[str, ...]
    schema_table: str
    schema_columns: tuple[str, ...]
    json_path: Path
    markdown_path: Path
    warning_csv_path: Path
    manifest_path: Path
    warnings: tuple[OptionDataContractWarningRecord, ...]
    human_review_required: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """R46 passes when contract artifacts are visible, even if option data is absent."""
        return self.status in {"MISSING_OPTION_HISTORY", "OPTION_HISTORY_PRESENT_CONTRACT_ONLY"}

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI summary."""
        return {
            "product_code": self.product_code,
            "exchange": self.exchange,
            "run_id": self.run_id,
            "status": self.status,
            "passed": self.passed,
            "incoming_dir": str(self.incoming_dir),
            "core_option_quote_path": str(self.core_option_quote_path),
            "core_row_count": self.core_row_count,
            "incoming_file_count": self.incoming_file_count,
            "expected_file_patterns": list(self.expected_file_patterns),
            "schema_table": self.schema_table,
            "schema_columns": list(self.schema_columns),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "warning_csv_path": str(self.warning_csv_path),
            "manifest_path": str(self.manifest_path),
            "warning_count": len(self.warnings),
            "warnings": [warning.to_summary() for warning in self.warnings],
            "human_review_required": list(self.human_review_required),
            "option_signal_status": "not_connected",
        }


def build_cf_option_data_contract(
    *,
    source_dir: Path | None = None,
    core_output_dir: Path | None = None,
    output_path: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    create_dirs: bool = True,
) -> ResearchOptionDataContractResult:
    """Build the R46 option data contract and make missing option files explicit."""
    option_run_id = run_id or _default_run_id()
    incoming_dir = source_dir or data_dir() / "incoming" / PRODUCT_CODE / "options" / "history"
    core_path = output_path or _default_core_output_path(core_output_dir)
    if create_dirs:
        incoming_dir.mkdir(parents=True, exist_ok=True)
        core_path.parent.mkdir(parents=True, exist_ok=True)

    incoming_files = _option_history_files(incoming_dir)
    warnings = _warnings_for_files(incoming_dir=incoming_dir, incoming_files=incoming_files)
    core_row_count = _ensure_core_option_table(core_path)

    result = ResearchOptionDataContractResult(
        product_code=PRODUCT_CODE,
        exchange=EXCHANGE,
        run_id=option_run_id,
        status=_status(incoming_files),
        incoming_dir=incoming_dir,
        core_option_quote_path=core_path,
        core_row_count=core_row_count,
        incoming_file_count=len(incoming_files),
        expected_file_patterns=EXPECTED_FILE_PATTERNS,
        schema_table=CoreOptionQuoteDailyRow.table_name,
        schema_columns=OPTION_CORE_COLUMNS,
        json_path=_json_path(report_output_dir),
        markdown_path=_markdown_path(report_output_dir),
        warning_csv_path=_warning_csv_path(report_output_dir),
        manifest_path=_manifest_path(report_output_dir),
        warnings=tuple(warnings),
        human_review_required=HUMAN_REVIEW_REQUIRED,
    )
    _write_outputs(result=result, incoming_files=incoming_files)
    return result


def _option_history_files(incoming_dir: Path) -> tuple[Path, ...]:
    if not incoming_dir.exists():
        return ()
    candidates = [
        path
        for path in incoming_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".csv", ".xlsx", ".xls", ".zip"}
    ]
    return tuple(sorted(candidates))


def _warnings_for_files(
    *,
    incoming_dir: Path,
    incoming_files: tuple[Path, ...],
) -> list[OptionDataContractWarningRecord]:
    if not incoming_files:
        return [
            OptionDataContractWarningRecord(
                severity="WARN",
                warning_code="MISSING_OPTION_HISTORY",
                message=(
                    "未发现 CF 期权历史行情文件；请先把官方期权历史文件放入 "
                    f"{incoming_dir}。R46 只建立契约，不静默跳过。"
                ),
                human_review_required=("official_option_field_interpretation",),
            )
        ]
    return [
        OptionDataContractWarningRecord(
            severity="INFO",
            warning_code="OPTION_HISTORY_PRESENT_NOT_PARSED_R47_REQUIRED",
            message=(
                "已发现期权历史文件，但 R46 不解析行情；需要在 R47 执行 raw/core 接入。"
            ),
            human_review_required=("official_option_field_interpretation",),
        )
    ]


def _ensure_core_option_table(path: Path) -> int:
    if not path.exists():
        # R46 先写 schema-only 空表，避免后续模块因为路径不存在而把期权状态静默吞掉。
        pd.DataFrame(columns=OPTION_CORE_COLUMNS).to_parquet(path, index=False)
        return 0

    frame = pd.read_parquet(path)
    missing = sorted(set(OPTION_CORE_COLUMNS) - set(frame.columns))
    if missing:
        raise ResearchWorkbenchError(f"core option quote table missing columns: {missing}")
    if not frame.empty:
        validate_rows(CoreOptionQuoteDailyRow.table_name, frame.to_dict("records"))
    return int(len(frame))


def _status(incoming_files: tuple[Path, ...]) -> str:
    if not incoming_files:
        return "MISSING_OPTION_HISTORY"
    return "OPTION_HISTORY_PRESENT_CONTRACT_ONLY"


def _write_outputs(
    *,
    result: ResearchOptionDataContractResult,
    incoming_files: tuple[Path, ...],
) -> None:
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    result.json_path.write_text(
        json.dumps(result.to_summary(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result.markdown_path.write_text(
        _render_markdown(result=result, incoming_files=incoming_files),
        encoding="utf-8",
    )
    _write_warning_csv(result)
    _write_manifest(result=result, incoming_files=incoming_files)


def _write_warning_csv(result: ResearchOptionDataContractResult) -> None:
    result.warning_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with result.warning_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["severity", "warning_code", "message", "human_review_required"],
        )
        writer.writeheader()
        for warning in result.warnings:
            writer.writerow(
                {
                    "severity": warning.severity,
                    "warning_code": warning.warning_code,
                    "message": warning.message,
                    "human_review_required": ";".join(warning.human_review_required),
                }
            )


def _write_manifest(
    *,
    result: ResearchOptionDataContractResult,
    incoming_files: tuple[Path, ...],
) -> None:
    payload = {
        "report_type": "option_data_contract",
        "rule_version": OPTION_CONTRACT_VERSION,
        "generated_at": utc_now().isoformat(),
        "run_id": result.run_id,
        "product_code": PRODUCT_CODE,
        "exchange": EXCHANGE,
        "status": result.status,
        "incoming_dir": str(result.incoming_dir),
        "incoming_files": [str(path) for path in incoming_files],
        "core_option_quote_path": str(result.core_option_quote_path),
        "core_row_count": result.core_row_count,
        "schema_table": result.schema_table,
        "schema_columns": list(result.schema_columns),
        "option_signal_status": "not_connected",
        "human_review_required": list(result.human_review_required),
    }
    result.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _render_markdown(
    *,
    result: ResearchOptionDataContractResult,
    incoming_files: tuple[Path, ...],
) -> str:
    lines = [
        "# CF 期权数据契约 R46",
        "",
        "## 数据状态",
        "",
        "- 报告类型：`option_data_contract`",
        f"- 状态：`{result.status}`",
        f"- incoming 路径：`{result.incoming_dir}`",
        f"- core 期权表：`{result.core_option_quote_path}`",
        f"- core 行数：`{result.core_row_count}`",
        "- 期权信号状态：`not_connected`",
        "",
        "## incoming 规范",
        "",
        "- 推荐路径：`data/incoming/CF/options/history/`",
        "- R46 只确认文件存在和契约，不解析行情。",
        "- R47 才允许从 preserved raw/snapshot 进入 core normalization。",
        "",
        "| 文件模式 | 用途 |",
        "| --- | --- |",
    ]
    for pattern in result.expected_file_patterns:
        lines.append(f"| `{pattern}` | CF 期权历史行情候选文件 |")

    lines.extend(
        [
            "",
            "## core_option_quote_daily schema",
            "",
            "| 字段 | 说明 |",
            "| --- | --- |",
        ]
    )
    for column in result.schema_columns:
        lines.append(f"| `{column}` | {_column_description(column)} |")

    lines.extend(
        [
            "",
            "## 已发现文件",
            "",
        ]
    )
    if incoming_files:
        lines.extend(f"- `{path}`" for path in incoming_files)
    else:
        lines.append("- 未发现期权历史行情文件，已输出 `MISSING_OPTION_HISTORY`。")

    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "- R46 不生成 IV、Greek、PCR、skew 或期货-期权联动信号。",
            "- 期权缺失必须显式记录为 `MISSING_OPTION_HISTORY`，不能静默回退。",
            "- 美式期权 IV/Greek 的模型口径进入 R48 前必须人工复核。",
            "- 本报告不构成交易指令。",
            "",
            "## Human Review Required",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    return "\n".join(lines) + "\n"


def _column_description(column: str) -> str:
    descriptions = {
        "schema_version": "schema 版本",
        "source_snapshot_id": "raw/core 血缘快照",
        "exchange": "交易所",
        "product_code": "品种代码",
        "trade_date": "交易日",
        "option_symbol": "期权合约代码",
        "underlying_contract": "标的期货合约",
        "option_type": "C/P",
        "strike": "行权价",
        "settle": "结算价",
        "volume": "成交量",
        "open_interest": "持仓量",
        "moneyness": "moneyness 研究口径，R47/R48 需复核",
        "liquidity_flag": "流动性标签",
        "data_quality_flag": "数据质量标签",
    }
    return descriptions.get(column, "")


def _json_path(report_output_dir: Path | None) -> Path:
    return _report_root(report_output_dir) / f"{PRODUCT_CODE}_option_data_contract.json"


def _markdown_path(report_output_dir: Path | None) -> Path:
    return _report_root(report_output_dir) / f"{PRODUCT_CODE}_option_data_contract.md"


def _warning_csv_path(report_output_dir: Path | None) -> Path:
    return _report_root(report_output_dir) / f"{PRODUCT_CODE}_option_data_contract_warnings.csv"


def _manifest_path(report_output_dir: Path | None) -> Path:
    return _report_root(report_output_dir) / f"{PRODUCT_CODE}_option_data_contract_manifest.json"


def _report_root(report_output_dir: Path | None) -> Path:
    return report_output_dir or reports_dir() / "research" / REPORT_DIR


def _default_core_output_path(core_output_dir: Path | None) -> Path:
    root = core_output_dir or data_dir() / "core"
    return root / PRODUCT_CODE / CORE_OPTION_QUOTE_FILE_NAME


def _default_run_id() -> str:
    return f"r46_option_contract_{PRODUCT_CODE}_{uuid.uuid4().hex[:8]}"
