"""R51 CF fundamental manual-input data contract."""

from __future__ import annotations

import csv
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.common.time import utc_now

PRODUCT_CODE = "CF"
EXCHANGE = "CZCE"
FUNDAMENTAL_CONTRACT_VERSION = "R51_fundamental_data_contract_v1"
OUTPUT_DIR = "fundamentals"
REPORT_DIR = "fundamentals"
MANUAL_FILE_SUFFIXES = {".csv", ".xlsx", ".xls", ".json", ".parquet"}
HUMAN_REVIEW_REQUIRED = (
    "warehouse_receipt_source_and_units",
    "basis_region_and_spot_price_source",
    "inventory_source_and_unit",
    "import_period_and_unit",
    "textile_chain_indicator_definition",
    "official_fundamental_field_interpretation",
    "fundamental_signal_rule_before_use",
)


@dataclass(frozen=True)
class FundamentalDatasetContract:
    """Single R51 manual-input dataset contract."""

    dataset_type: str
    display_name: str
    frequency: str
    required_columns: tuple[str, ...]
    optional_columns: tuple[str, ...]
    sample_file_name: str
    source_status: str = "manual_input_only"
    signal_status: str = "not_connected"
    data_boundary: str = "HUMAN_REVIEW_REQUIRED"

    def to_summary(self) -> dict[str, object]:
        """Return a JSON-serializable schema row."""
        return {
            "dataset_type": self.dataset_type,
            "display_name": self.display_name,
            "frequency": self.frequency,
            "required_columns": list(self.required_columns),
            "optional_columns": list(self.optional_columns),
            "sample_file_name": self.sample_file_name,
            "source_status": self.source_status,
            "signal_status": self.signal_status,
            "data_boundary": self.data_boundary,
        }


@dataclass(frozen=True)
class FundamentalDataContractWarningRecord:
    """R51 warning row."""

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
class ResearchFundamentalDataContractResult:
    """Result of building R51 fundamental manual-input contract artifacts."""

    product_code: str
    exchange: str
    run_id: str
    status: str
    incoming_dir: Path
    incoming_file_count: int
    dataset_contracts: tuple[FundamentalDatasetContract, ...]
    schema_json_path: Path
    template_csv_path: Path
    json_path: Path
    markdown_path: Path
    warning_csv_path: Path
    manifest_path: Path
    warnings: tuple[FundamentalDataContractWarningRecord, ...]
    human_review_required: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """R51 passes when the contract is visible, even if manual data is absent."""
        return self.status in {
            "MISSING_FUNDAMENTAL_INPUT",
            "FUNDAMENTAL_INPUT_PRESENT_CONTRACT_ONLY",
        }

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI summary."""
        return {
            "product_code": self.product_code,
            "exchange": self.exchange,
            "run_id": self.run_id,
            "status": self.status,
            "passed": self.passed,
            "incoming_dir": str(self.incoming_dir),
            "incoming_file_count": self.incoming_file_count,
            "dataset_count": len(self.dataset_contracts),
            "dataset_types": [contract.dataset_type for contract in self.dataset_contracts],
            "schema_json_path": str(self.schema_json_path),
            "template_csv_path": str(self.template_csv_path),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "warning_csv_path": str(self.warning_csv_path),
            "manifest_path": str(self.manifest_path),
            "warning_count": len(self.warnings),
            "warnings": [warning.to_summary() for warning in self.warnings],
            "human_review_required": list(self.human_review_required),
            "fundamental_signal_status": "not_connected",
        }


def build_cf_fundamental_data_contract(
    *,
    source_dir: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
    create_dirs: bool = True,
) -> ResearchFundamentalDataContractResult:
    """Build the R51 fundamental manual-input contract and explicit warnings."""
    contract_run_id = run_id or _default_run_id()
    incoming_dir = source_dir or data_dir() / "incoming" / PRODUCT_CODE / "fundamentals" / "manual"
    if create_dirs:
        incoming_dir.mkdir(parents=True, exist_ok=True)
        _output_root(output_dir).mkdir(parents=True, exist_ok=True)
        _report_root(report_output_dir).mkdir(parents=True, exist_ok=True)

    incoming_files = _manual_input_files(incoming_dir)
    warnings = _warnings_for_files(incoming_dir=incoming_dir, incoming_files=incoming_files)
    contracts = _dataset_contracts()
    result = ResearchFundamentalDataContractResult(
        product_code=PRODUCT_CODE,
        exchange=EXCHANGE,
        run_id=contract_run_id,
        status=_status(incoming_files),
        incoming_dir=incoming_dir,
        incoming_file_count=len(incoming_files),
        dataset_contracts=contracts,
        schema_json_path=_schema_json_path(output_dir),
        template_csv_path=_template_csv_path(output_dir),
        json_path=_json_path(output_dir),
        markdown_path=_markdown_path(report_output_dir),
        warning_csv_path=_warning_csv_path(report_output_dir),
        manifest_path=_manifest_path(output_dir),
        warnings=tuple(warnings),
        human_review_required=HUMAN_REVIEW_REQUIRED,
    )
    _write_outputs(result=result, incoming_files=incoming_files)
    return result


def _dataset_contracts() -> tuple[FundamentalDatasetContract, ...]:
    # R51 只定义手工输入口径，不假设任何自动数据源或交易信号规则。
    return (
        FundamentalDatasetContract(
            dataset_type="warehouse_receipt",
            display_name="仓单",
            frequency="daily",
            required_columns=(
                "trade_date",
                "product_code",
                "warehouse_receipt",
                "change",
                "source_name",
                "data_quality_flag",
                "human_review_required",
            ),
            optional_columns=("source_url", "remark"),
            sample_file_name="CF_warehouse_receipt_manual.csv",
        ),
        FundamentalDatasetContract(
            dataset_type="basis",
            display_name="基差",
            frequency="daily",
            required_columns=(
                "trade_date",
                "product_code",
                "region",
                "spot_price",
                "futures_contract",
                "futures_settle",
                "basis",
                "source_name",
                "data_quality_flag",
                "human_review_required",
            ),
            optional_columns=("source_url", "remark"),
            sample_file_name="CF_basis_manual.csv",
        ),
        FundamentalDatasetContract(
            dataset_type="inventory",
            display_name="库存",
            frequency="daily_or_weekly",
            required_columns=(
                "trade_date",
                "product_code",
                "inventory_value",
                "unit",
                "source_name",
                "data_quality_flag",
                "human_review_required",
            ),
            optional_columns=("region", "source_url", "remark"),
            sample_file_name="CF_inventory_manual.csv",
        ),
        FundamentalDatasetContract(
            dataset_type="import",
            display_name="进口",
            frequency="monthly",
            required_columns=(
                "period",
                "product_code",
                "import_volume",
                "unit",
                "source_name",
                "data_quality_flag",
                "human_review_required",
            ),
            optional_columns=("source_url", "remark"),
            sample_file_name="CF_import_manual.csv",
        ),
        FundamentalDatasetContract(
            dataset_type="textile_chain",
            display_name="纺织链条",
            frequency="daily_or_weekly_or_monthly",
            required_columns=(
                "period",
                "indicator_name",
                "indicator_value",
                "unit",
                "source_name",
                "data_quality_flag",
                "human_review_required",
            ),
            optional_columns=("product_code", "region", "source_url", "remark"),
            sample_file_name="CF_textile_chain_manual.csv",
        ),
    )


def _manual_input_files(incoming_dir: Path) -> tuple[Path, ...]:
    if incoming_dir.exists() and not incoming_dir.is_dir():
        raise ResearchWorkbenchError(f"fundamental source path is not a directory: {incoming_dir}")
    if not incoming_dir.exists():
        return ()
    candidates = [
        path
        for path in incoming_dir.iterdir()
        if path.is_file() and path.suffix.lower() in MANUAL_FILE_SUFFIXES
    ]
    return tuple(sorted(candidates))


def _warnings_for_files(
    *,
    incoming_dir: Path,
    incoming_files: tuple[Path, ...],
) -> list[FundamentalDataContractWarningRecord]:
    warnings: list[FundamentalDataContractWarningRecord] = []
    if not incoming_files:
        warnings.append(
            FundamentalDataContractWarningRecord(
                severity="WARN",
                warning_code="MISSING_FUNDAMENTAL_INPUT",
                message=(
                    "未发现 CF 基本面手工输入文件；R51 只建立接口契约，"
                    f"请将人工复核后的仓单、基差、库存、进口或纺织链条文件放入 {incoming_dir}。"
                ),
                human_review_required=("official_fundamental_field_interpretation",),
            )
        )
    else:
        warnings.append(
            FundamentalDataContractWarningRecord(
                severity="INFO",
                warning_code="FUNDAMENTAL_INPUT_PRESENT_NOT_PARSED",
                message=(
                    "已发现基本面手工输入文件，但 R51 不解析、不入库、不生成信号；"
                    "需要后续任务建立字段校验和人工确认后才能使用。"
                ),
                human_review_required=("official_fundamental_field_interpretation",),
            )
        )
    warnings.extend(
        [
            FundamentalDataContractWarningRecord(
                severity="WARN",
                warning_code="MANUAL_REVIEW_REQUIRED",
                message="所有 R51 基本面字段在接入研究结论前均需要人工复核。",
                human_review_required=HUMAN_REVIEW_REQUIRED,
            ),
            FundamentalDataContractWarningRecord(
                severity="INFO",
                warning_code="FUNDAMENTAL_SIGNAL_NOT_CONNECTED",
                message="基本面数据当前不进入 signal matrix、latest brief 自动方向或交易结论。",
                human_review_required=("fundamental_signal_rule_before_use",),
            ),
            FundamentalDataContractWarningRecord(
                severity="INFO",
                warning_code="NO_AUTO_SOURCE_CONNECTED",
                message="R51 不连接外部自动数据源，不进行网络抓取或官方文件解析。",
                human_review_required=("official_fundamental_field_interpretation",),
            ),
        ]
    )
    return warnings


def _status(incoming_files: tuple[Path, ...]) -> str:
    if not incoming_files:
        return "MISSING_FUNDAMENTAL_INPUT"
    return "FUNDAMENTAL_INPUT_PRESENT_CONTRACT_ONLY"


def _write_outputs(
    *,
    result: ResearchFundamentalDataContractResult,
    incoming_files: tuple[Path, ...],
) -> None:
    result.schema_json_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    _write_schema_json(result)
    _write_template_csv(result)
    _write_summary_json(result)
    _write_warning_csv(result)
    _write_manifest(result=result, incoming_files=incoming_files)
    result.markdown_path.write_text(
        _render_markdown(result=result, incoming_files=incoming_files),
        encoding="utf-8",
    )


def _write_schema_json(result: ResearchFundamentalDataContractResult) -> None:
    payload = {
        "report_type": "fundamental_data_contract_schema",
        "rule_version": FUNDAMENTAL_CONTRACT_VERSION,
        "product_code": PRODUCT_CODE,
        "exchange": EXCHANGE,
        "datasets": [contract.to_summary() for contract in result.dataset_contracts],
        "fundamental_signal_status": "not_connected",
        "human_review_required": list(result.human_review_required),
    }
    result.schema_json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_template_csv(result: ResearchFundamentalDataContractResult) -> None:
    with result.template_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "dataset_type",
                "display_name",
                "frequency",
                "required_columns",
                "optional_columns",
                "sample_file_name",
                "source_status",
                "signal_status",
                "data_boundary",
            ],
        )
        writer.writeheader()
        for contract in result.dataset_contracts:
            writer.writerow(
                {
                    "dataset_type": contract.dataset_type,
                    "display_name": contract.display_name,
                    "frequency": contract.frequency,
                    "required_columns": ";".join(contract.required_columns),
                    "optional_columns": ";".join(contract.optional_columns),
                    "sample_file_name": contract.sample_file_name,
                    "source_status": contract.source_status,
                    "signal_status": contract.signal_status,
                    "data_boundary": contract.data_boundary,
                }
            )


def _write_summary_json(result: ResearchFundamentalDataContractResult) -> None:
    result.json_path.write_text(
        json.dumps(result.to_summary(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_warning_csv(result: ResearchFundamentalDataContractResult) -> None:
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
    result: ResearchFundamentalDataContractResult,
    incoming_files: tuple[Path, ...],
) -> None:
    payload = {
        "report_type": "fundamental_data_contract",
        "rule_version": FUNDAMENTAL_CONTRACT_VERSION,
        "generated_at": utc_now().isoformat(),
        "run_id": result.run_id,
        "product_code": PRODUCT_CODE,
        "exchange": EXCHANGE,
        "status": result.status,
        "incoming_dir": str(result.incoming_dir),
        "incoming_files": [str(path) for path in incoming_files],
        "schema_json_path": str(result.schema_json_path),
        "template_csv_path": str(result.template_csv_path),
        "fundamental_signal_status": "not_connected",
        "human_review_required": list(result.human_review_required),
    }
    result.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _render_markdown(
    *,
    result: ResearchFundamentalDataContractResult,
    incoming_files: tuple[Path, ...],
) -> str:
    lines = [
        "# CF 基本面数据接口占位 R51",
        "",
        "## 数据状态",
        "",
        "- 报告类型：`fundamental_data_contract`",
        f"- 状态：`{result.status}`",
        f"- 手工输入路径：`{result.incoming_dir}`",
        f"- 已发现手工输入文件数：`{result.incoming_file_count}`",
        "- 基本面信号状态：`not_connected`",
        "- 当前不接入 signal matrix、latest brief 自动方向或交易结论。",
        "",
        "## 手工输入契约",
        "",
        "| 数据集 | 中文名 | 频率 | 必填字段 | 状态 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for contract in result.dataset_contracts:
        lines.append(
            "| "
            f"`{contract.dataset_type}` | {contract.display_name} | "
            f"{contract.frequency} | `{'; '.join(contract.required_columns)}` | "
            f"`{contract.signal_status}` |"
        )

    lines.extend(["", "## 已发现文件", ""])
    if incoming_files:
        lines.extend(f"- `{path}`" for path in incoming_files)
    else:
        lines.append("- 未发现基本面手工输入文件，已输出 `MISSING_FUNDAMENTAL_INPUT`。")

    lines.extend(
        [
            "",
            "## 输出文件",
            "",
            f"- schema：`{result.schema_json_path}`",
            f"- 模板：`{result.template_csv_path}`",
            f"- warning：`{result.warning_csv_path}`",
            f"- manifest：`{result.manifest_path}`",
            "",
            "## 研究边界",
            "",
            "- forward return 仍只作为历史后验验证标签，R51 不新增收益标签。",
            "- R51 不连接自动数据源，不解析交易所或第三方原始文件。",
            "- 仓单、基差、库存、进口、纺织链条字段全部标记为人工复核项。",
            "- 基本面当前不生成 `fundamental_signal`，也不影响期货或期权信号方向。",
            "- 本报告不构成交易指令。",
            "",
            "## Human Review Required",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    return "\n".join(lines) + "\n"


def _schema_json_path(output_dir: Path | None) -> Path:
    return _output_root(output_dir) / f"{PRODUCT_CODE}_fundamental_data_contract_schema.json"


def _template_csv_path(output_dir: Path | None) -> Path:
    return _output_root(output_dir) / f"{PRODUCT_CODE}_fundamental_manual_input_template.csv"


def _json_path(output_dir: Path | None) -> Path:
    return _output_root(output_dir) / f"{PRODUCT_CODE}_fundamental_data_contract.json"


def _markdown_path(report_output_dir: Path | None) -> Path:
    return _report_root(report_output_dir) / f"{PRODUCT_CODE}_fundamental_data_contract.md"


def _warning_csv_path(report_output_dir: Path | None) -> Path:
    return (
        _report_root(report_output_dir)
        / f"{PRODUCT_CODE}_fundamental_data_contract_warnings.csv"
    )


def _manifest_path(output_dir: Path | None) -> Path:
    return _output_root(output_dir) / f"{PRODUCT_CODE}_fundamental_data_contract_manifest.json"


def _output_root(output_dir: Path | None) -> Path:
    return output_dir or data_dir() / "research" / PRODUCT_CODE / OUTPUT_DIR


def _report_root(report_output_dir: Path | None) -> Path:
    return report_output_dir or reports_dir() / "research" / REPORT_DIR


def _default_run_id() -> str:
    return f"r51_fundamental_contract_{PRODUCT_CODE}_{uuid.uuid4().hex[:8]}"
