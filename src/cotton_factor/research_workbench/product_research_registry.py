"""R50 CF product config and research factor registry snapshot."""

from __future__ import annotations

import csv
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.common.time import utc_now
from cotton_factor.core.contract_master import ProductConfig, load_product_config
from cotton_factor.research import FactorDefinition, load_factor_registry

PRODUCT_CODE = "CF"
PRODUCT_REGISTRY_VERSION = "R50_cf_product_research_registry_v1"
OUTPUT_DIR = "product_registry"
FUTURES_SIGNAL_OBJECT_ID = "CF.C1"
FUTURES_UNIVERSE = "CF_MAIN"
EXPECTED_FUTURES_FACTOR_IDS = (
    "mom_20_v1",
    "carry_nf_v1",
    "curve_slope_v1",
    "oi_pressure_v1",
)
OPTION_PROXY_FACTORS = (
    {
        "factor_id": "option_atm_iv_proxy_v1",
        "family": "option_volatility",
        "source_task": "R48",
        "source_artifact": "option_factor_proxy_daily.atm_iv_proxy",
        "required_inputs": ("core_option_quote_daily", "core_quote_daily"),
        "status": "research_proxy",
        "human_review_required": ("american_option_iv_proxy_model_boundary",),
    },
    {
        "factor_id": "option_iv_rank_proxy_v1",
        "family": "option_volatility",
        "source_task": "R48",
        "source_artifact": "option_factor_proxy_daily.atm_iv_rank",
        "required_inputs": ("core_option_quote_daily", "core_quote_daily"),
        "status": "research_proxy",
        "human_review_required": ("american_option_iv_proxy_model_boundary",),
    },
    {
        "factor_id": "option_pcr_volume_v1",
        "family": "option_positioning",
        "source_task": "R48",
        "source_artifact": "option_factor_proxy_daily.pcr_volume",
        "required_inputs": ("core_option_quote_daily",),
        "status": "research_proxy",
        "human_review_required": ("option_liquidity_thresholds",),
    },
    {
        "factor_id": "option_pcr_oi_v1",
        "family": "option_positioning",
        "source_task": "R48",
        "source_artifact": "option_factor_proxy_daily.pcr_oi",
        "required_inputs": ("core_option_quote_daily",),
        "status": "research_proxy",
        "human_review_required": ("option_liquidity_thresholds",),
    },
    {
        "factor_id": "option_skew_proxy_v1",
        "family": "option_skew",
        "source_task": "R48",
        "source_artifact": "option_factor_proxy_daily.skew_proxy",
        "required_inputs": ("core_option_quote_daily", "core_quote_daily"),
        "status": "research_proxy",
        "human_review_required": ("moneyness_and_skew_proxy_definition",),
    },
    {
        "factor_id": "option_liquidity_score_v1",
        "family": "option_liquidity",
        "source_task": "R48",
        "source_artifact": "option_factor_proxy_daily.option_liquidity_score",
        "required_inputs": ("core_option_quote_daily",),
        "status": "research_proxy",
        "human_review_required": ("option_liquidity_thresholds",),
    },
)
R50_HUMAN_REVIEW_REQUIRED = (
    "contract_rule_and_last_trading_day_review_before_trading_use",
    "factor_thresholds",
    "option_signal_filter_rules_before_trading_use",
    "american_option_iv_proxy_model_boundary",
    "moneyness_and_skew_proxy_definition",
    "official_option_field_interpretation",
    "option_liquidity_thresholds",
)


@dataclass(frozen=True)
class ResearchProductRegistryResult:
    """Result of building the R50 CF product/factor registry snapshot."""

    product_code: str
    run_id: str
    status: str
    product_config_path: Path
    factor_registry_path: Path
    json_path: Path
    markdown_path: Path
    manifest_path: Path
    factor_csv_path: Path
    futures_factor_count: int
    option_proxy_factor_count: int
    human_review_required: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """Return whether R50 completed with a valid CF registry snapshot."""
        return self.status == "COMPLETED"

    def to_summary(self) -> dict[str, object]:
        """Return a compact CLI summary."""
        return {
            "product_code": self.product_code,
            "run_id": self.run_id,
            "status": self.status,
            "passed": self.passed,
            "product_config_path": str(self.product_config_path),
            "factor_registry_path": str(self.factor_registry_path),
            "json_path": str(self.json_path),
            "markdown_path": str(self.markdown_path),
            "manifest_path": str(self.manifest_path),
            "factor_csv_path": str(self.factor_csv_path),
            "futures_factor_count": self.futures_factor_count,
            "option_proxy_factor_count": self.option_proxy_factor_count,
            "human_review_required": list(self.human_review_required),
        }


def build_cf_product_research_registry(
    *,
    product_config_path: Path | None = None,
    factor_registry_path: Path | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchProductRegistryResult:
    """Build R50 CF product config and factor registry snapshot."""
    product_path = product_config_path or _default_product_config_path()
    factor_path = factor_registry_path or _default_factor_registry_path()
    config = load_product_config(PRODUCT_CODE, product_path.parent)
    if config.product_code != PRODUCT_CODE:
        raise ResearchWorkbenchError(f"R50 only supports CF, got {config.product_code}")
    factor_registry = load_factor_registry(factor_path)
    futures_factors = _futures_factor_rows(factor_registry.factors)
    option_proxy_factors = _option_proxy_rows()
    registry_run_id = run_id or _default_run_id()
    human_review_required = _human_review_required(
        config=config,
        futures_factors=futures_factors,
        option_proxy_factors=option_proxy_factors,
    )
    result = ResearchProductRegistryResult(
        product_code=PRODUCT_CODE,
        run_id=registry_run_id,
        status="COMPLETED",
        product_config_path=product_path,
        factor_registry_path=factor_path,
        json_path=_json_path(output_dir),
        markdown_path=_markdown_path(report_output_dir),
        manifest_path=_manifest_path(output_dir),
        factor_csv_path=_factor_csv_path(output_dir),
        futures_factor_count=len(futures_factors),
        option_proxy_factor_count=len(option_proxy_factors),
        human_review_required=human_review_required,
    )
    payload = _payload(
        result=result,
        config=config,
        futures_factors=futures_factors,
        option_proxy_factors=option_proxy_factors,
    )
    _write_json(result.json_path, payload)
    _write_manifest(result.manifest_path, payload)
    _write_factor_csv(
        path=result.factor_csv_path,
        futures_factors=futures_factors,
        option_proxy_factors=option_proxy_factors,
    )
    _write_markdown(
        result=result,
        config=config,
        futures_factors=futures_factors,
        option_proxy_factors=option_proxy_factors,
    )
    return result


def _futures_factor_rows(
    definitions: object,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if not isinstance(definitions, dict):
        raise ResearchWorkbenchError("factor registry definitions must be a mapping")
    missing = [
        factor_id
        for factor_id in EXPECTED_FUTURES_FACTOR_IDS
        if factor_id not in definitions
    ]
    if missing:
        raise ResearchWorkbenchError(f"factor registry missing CF futures factors: {missing}")
    for factor_id in EXPECTED_FUTURES_FACTOR_IDS:
        definition = definitions[factor_id]
        if not isinstance(definition, FactorDefinition):
            raise ResearchWorkbenchError(f"invalid factor definition for {factor_id}")
        raw_like = [
            table_name
            for table_name in definition.required_inputs
            if table_name.startswith("raw_")
        ]
        if raw_like:
            raise ResearchWorkbenchError(f"{factor_id}: raw inputs are not allowed: {raw_like}")
        rows.append(
            {
                "factor_id": definition.factor_id,
                "factor_layer": "futures_factor_registry",
                "family": definition.family,
                "version": definition.version,
                "source_task": "D12_D13_R11_R14",
                "source_artifact": "research_factor_value_daily",
                "required_inputs": definition.required_inputs,
                "status": definition.status,
                "human_review_required": definition.human_review_required,
            }
        )
    return rows


def _option_proxy_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in OPTION_PROXY_FACTORS:
        # 期权 proxy 属于 R48/R49 过滤层，不混入旧的 research_factor_value_daily。
        rows.append(
            {
                "factor_id": item["factor_id"],
                "factor_layer": "option_proxy_registry",
                "family": item["family"],
                "version": "v1",
                "source_task": item["source_task"],
                "source_artifact": item["source_artifact"],
                "required_inputs": item["required_inputs"],
                "status": item["status"],
                "human_review_required": item["human_review_required"],
            }
        )
    return rows


def _human_review_required(
    *,
    config: ProductConfig,
    futures_factors: list[dict[str, object]],
    option_proxy_factors: list[dict[str, object]],
) -> tuple[str, ...]:
    values = set(R50_HUMAN_REVIEW_REQUIRED)
    values.update(config.human_review_required)
    for row in [*futures_factors, *option_proxy_factors]:
        raw = row.get("human_review_required")
        if isinstance(raw, tuple):
            values.update(str(item) for item in raw)
        elif isinstance(raw, list):
            values.update(str(item) for item in raw)
    return tuple(sorted(values))


def _payload(
    *,
    result: ResearchProductRegistryResult,
    config: ProductConfig,
    futures_factors: list[dict[str, object]],
    option_proxy_factors: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "report_type": "cf_product_research_registry",
        "rule_version": PRODUCT_REGISTRY_VERSION,
        "generated_at": utc_now().isoformat(),
        "run_id": result.run_id,
        "product": {
            "product_code": config.product_code,
            "display_name": config.display_name,
            "exchange": config.exchange,
            "instrument_type": config.instrument_type,
            "status": config.status,
            "currency": config.currency,
            "multiplier": config.multiplier,
            "tick_size": config.tick_size,
            "delivery_months": config.delivery_months,
            "last_trade_day_rule": config.last_trade_day_rule,
            "option_style": config.option_style,
            "signal_object_id": FUTURES_SIGNAL_OBJECT_ID,
            "universe": FUTURES_UNIVERSE,
            "source_config_version": config.source_config_version,
            "rule_version_id": config.rule_version_id,
            "human_review_required": config.human_review_required,
        },
        "futures_factor_registry": futures_factors,
        "option_proxy_registry": option_proxy_factors,
        "registry_boundary": {
            "cf_first_only": True,
            "no_multi_product_expansion": True,
            "option_proxy_not_strategy": True,
            "research_functions_must_read_core_not_raw": True,
        },
        "human_review_required": list(result.human_review_required),
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=list) + "\n",
        encoding="utf-8",
    )


def _write_manifest(path: Path, payload: dict[str, object]) -> None:
    manifest = {
        "report_type": payload["report_type"],
        "rule_version": payload["rule_version"],
        "generated_at": payload["generated_at"],
        "run_id": payload["run_id"],
        "product_code": PRODUCT_CODE,
        "futures_factor_count": len(payload["futures_factor_registry"]),  # type: ignore[arg-type]
        "option_proxy_factor_count": len(payload["option_proxy_registry"]),  # type: ignore[arg-type]
        "human_review_required": payload["human_review_required"],
    }
    _write_json(path, manifest)


def _write_factor_csv(
    *,
    path: Path,
    futures_factors: list[dict[str, object]],
    option_proxy_factors: list[dict[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "factor_id",
        "factor_layer",
        "family",
        "version",
        "source_task",
        "source_artifact",
        "required_inputs",
        "status",
        "human_review_required",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in [*futures_factors, *option_proxy_factors]:
            writer.writerow(
                {
                    **row,
                    "required_inputs": ";".join(_string_tuple(row["required_inputs"])),
                    "human_review_required": ";".join(
                        _string_tuple(row["human_review_required"])
                    ),
                }
            )


def _write_markdown(
    *,
    result: ResearchProductRegistryResult,
    config: ProductConfig,
    futures_factors: list[dict[str, object]],
    option_proxy_factors: list[dict[str, object]],
) -> None:
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# CF 产品配置与因子注册快照 R50",
        "",
        "## 一、配置状态",
        "",
        f"- 产品：`{config.product_code}`",
        f"- 交易所：`{config.exchange}`",
        "- 频率：`daily`",
        f"- signal object：`{FUTURES_SIGNAL_OBJECT_ID}`",
        f"- universe：`{FUTURES_UNIVERSE}`",
        f"- 合约乘数：`{config.multiplier}`",
        f"- 最小变动价位：`{config.tick_size}`",
        f"- 交割月份：`{','.join(str(item) for item in config.delivery_months)}`",
        f"- 最后交易日规则：`{config.last_trade_day_rule}`",
        "",
        "## 二、期货因子注册",
        "",
        "| Factor ID | Family | Inputs | Status | Review |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in futures_factors:
        lines.append(_factor_markdown_row(row))
    lines.extend(
        [
            "",
            "## 三、期权 proxy 注册",
            "",
            "| Factor ID | Family | Inputs | Status | Review |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in option_proxy_factors:
        lines.append(_factor_markdown_row(row))
    lines.extend(
        [
            "",
            "## 四、边界",
            "",
            "- R50 只固化 CF，不启动多品种扩展。",
            "- 研究函数仍只能读取 core/research 标准化表，不读取交易所 raw 文件。",
            "- 期权 proxy 是 R48/R49 过滤层，不是期权策略，也不进入旧因子回测表。",
            "- 本快照不构成交易指令。",
            "",
            "## 五、人工复核项",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in result.human_review_required)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _factor_markdown_row(row: dict[str, object]) -> str:
    return (
        "| "
        + " | ".join(
            [
                str(row["factor_id"]),
                str(row["family"]),
                ";".join(_string_tuple(row["required_inputs"])),
                str(row["status"]),
                ";".join(_string_tuple(row["human_review_required"])) or "-",
            ]
        )
        + " |"
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, (tuple, list)):
        return tuple(str(item) for item in value)
    if value is None:
        return ()
    return (str(value),)


def _json_path(output_dir: Path | None) -> Path:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / OUTPUT_DIR
    return root / f"{PRODUCT_CODE}_product_research_registry.json"


def _manifest_path(output_dir: Path | None) -> Path:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / OUTPUT_DIR
    return root / f"{PRODUCT_CODE}_product_research_registry_manifest.json"


def _factor_csv_path(output_dir: Path | None) -> Path:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / OUTPUT_DIR
    return root / f"{PRODUCT_CODE}_factor_registry_snapshot.csv"


def _markdown_path(report_output_dir: Path | None) -> Path:
    root = report_output_dir or reports_dir() / "research" / OUTPUT_DIR
    return root / f"{PRODUCT_CODE}_product_research_registry.md"


def _default_product_config_path() -> Path:
    return data_dir().parent / "configs" / "products" / f"{PRODUCT_CODE}.yaml"


def _default_factor_registry_path() -> Path:
    return data_dir().parent / "configs" / "factor_registry.yaml"


def _default_run_id() -> str:
    return f"r50_cf_product_registry_{uuid.uuid4().hex[:8]}"
