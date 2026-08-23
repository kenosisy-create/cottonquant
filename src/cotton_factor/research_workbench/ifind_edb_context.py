"""R93H normalized iFinD EDB context inputs for CF research."""

from __future__ import annotations

import csv
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from cotton_factor.common.exceptions import ResearchWorkbenchError
from cotton_factor.common.paths import data_dir, reports_dir
from cotton_factor.common.time import utc_now

PRODUCT_CODE = "CF"
RULE_VERSION = "V5.1_R93H_ifind_edb_context_v1"
COTTON_EDB = {
    "S002885871": ("spot", "现货价:棉花(3128B级)", "CNY_PER_TON_REVIEW_REQUIRED"),
    "S003986676": ("policy", "储备棉抛储:成交比例", "PERCENT_REVIEW_REQUIRED"),
    "S003986671": ("policy", "储备棉抛储:计划投放量:进口棉", "REVIEW_REQUIRED"),
    "S003986670": ("policy", "储备棉抛储:计划投放量:国产棉", "REVIEW_REQUIRED"),
    "S003986669": ("policy", "储备棉抛储:计划投放量", "REVIEW_REQUIRED"),
    "S004363662": ("yarn", "现货价:纯棉纱(C32s)", "CNY_PER_TON_REVIEW_REQUIRED"),
    "S004363663": ("yarn", "现货价:纯棉纱(C40s)", "CNY_PER_TON_REVIEW_REQUIRED"),
    "S005402522": ("yarn", "现货价:人棉纱", "CNY_PER_TON_REVIEW_REQUIRED"),
    "S005402517": ("yarn", "现货价:棉纱21S", "CNY_PER_TON_REVIEW_REQUIRED"),
}
FX_SWAP_TENORS = {
    "L004366599": "ON",
    "L004366600": "TN",
    "L004366601": "SN",
    "L004366602": "1W",
    "L004366603": "2W",
    "L004366604": "3W",
    "L004366605": "1M",
    "L004366606": "2M",
    "L004366607": "3M",
    "L004366608": "4M",
    "L004366609": "5M",
    "L004366610": "6M",
    "L004366611": "9M",
    "L004366612": "1Y",
    "L004366613": "18M",
    "L004366614": "2Y",
    "L004366615": "3Y",
    "L004366616": "4Y",
    "L004366617": "5Y",
}
RESEARCH_BOUNDARY = (
    "iFinD EDB仅作为外部研究观察；USD/CNY掉期曲线不是即期汇率，"
    "储备棉与纱线字段不进入composite_score，不构成交易指令。"
)


@dataclass(frozen=True)
class IFindEdbWarningRecord:
    """One R93H warning or explicit boundary."""

    severity: str
    warning_code: str
    message: str
    human_review_required: tuple[str, ...] = ()

    def to_summary(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "warning_code": self.warning_code,
            "message": self.message,
            "human_review_required": list(self.human_review_required),
        }


@dataclass(frozen=True)
class ResearchIFindEdbContextResult:
    """R93H normalized artifacts and data coverage."""

    run_id: str
    status: str
    data_start: date
    data_end: date
    source_dir: Path
    cotton_source_path: Path
    fx_swap_source_path: Path
    cotton_context_path: Path
    spot_extension_path: Path
    policy_event_path: Path
    yarn_price_path: Path
    fx_swap_curve_path: Path
    quality_csv_path: Path
    warning_csv_path: Path
    json_path: Path
    manifest_path: Path
    markdown_path: Path
    latest_spot_date: date
    latest_spot_price: float
    cotton_row_count: int
    fx_swap_row_count: int
    warning_records: tuple[IFindEdbWarningRecord, ...]

    @property
    def warning_count(self) -> int:
        return sum(row.severity in {"WARN", "ERROR"} for row in self.warning_records)

    def to_summary(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "product_code": PRODUCT_CODE,
            "data_start": self.data_start.isoformat(),
            "data_end": self.data_end.isoformat(),
            "source_dir": str(self.source_dir),
            "cotton_source_path": str(self.cotton_source_path),
            "fx_swap_source_path": str(self.fx_swap_source_path),
            "cotton_context_path": str(self.cotton_context_path),
            "spot_extension_path": str(self.spot_extension_path),
            "policy_event_path": str(self.policy_event_path),
            "yarn_price_path": str(self.yarn_price_path),
            "fx_swap_curve_path": str(self.fx_swap_curve_path),
            "quality_csv_path": str(self.quality_csv_path),
            "warning_csv_path": str(self.warning_csv_path),
            "json_path": str(self.json_path),
            "manifest_path": str(self.manifest_path),
            "markdown_path": str(self.markdown_path),
            "latest_spot_date": self.latest_spot_date.isoformat(),
            "latest_spot_price": self.latest_spot_price,
            "cotton_row_count": self.cotton_row_count,
            "fx_swap_row_count": self.fx_swap_row_count,
            "warning_count": self.warning_count,
            "warnings": [row.to_summary() for row in self.warning_records],
            "signal_status": "not_connected",
        }


def connect_cf_ifind_edb_context(
    *,
    source_dir: Path | None = None,
    as_of_date: date | None = None,
    output_dir: Path | None = None,
    report_output_dir: Path | None = None,
    run_id: str | None = None,
) -> ResearchIFindEdbContextResult:
    """Validate preserved iFinD EDB files and write normalized research tables."""
    selected_source_dir = source_dir or _latest_source_dir()
    cotton_source = selected_source_dir / "cotton_policy_spot_yarn_edb.parquet"
    fx_source = selected_source_dir / "usdcny_swap_curve_edb.parquet"
    cotton_raw = _read_source(cotton_source, "cotton/policy/yarn EDB")
    fx_raw = _read_source(fx_source, "USD/CNY swap EDB")
    selected_as_of = as_of_date or date.today()

    cotton, cotton_quality = _normalize_cotton_edb(cotton_raw, selected_as_of)
    fx_swap, fx_quality = _normalize_fx_swap_edb(fx_raw, selected_as_of)
    quality = pd.concat([cotton_quality, fx_quality], ignore_index=True)
    spot_extension = _spot_extension(cotton, cotton_source)
    policy = cotton.loc[cotton["dataset_type"].eq("policy")].reset_index(drop=True)
    yarn = cotton.loc[cotton["dataset_type"].eq("yarn")].reset_index(drop=True)
    warnings = _warning_records(cotton=cotton, fx_swap=fx_swap)
    paths = _output_paths(
        start=min(cotton["trade_date"].min(), fx_swap["trade_date"].min()).date(),
        end=max(cotton["trade_date"].max(), fx_swap["trade_date"].max()).date(),
        output_dir=output_dir,
        report_output_dir=report_output_dir,
    )
    _write_parquet(paths["cotton"], cotton)
    _write_parquet(paths["spot"], spot_extension)
    _write_parquet(paths["policy"], policy)
    _write_parquet(paths["yarn"], yarn)
    _write_parquet(paths["fx_swap"], fx_swap)
    _write_quality(paths["quality"], quality)

    latest_spot = spot_extension.sort_values("trade_date").iloc[-1]
    result = ResearchIFindEdbContextResult(
        run_id=run_id or _default_run_id(),
        status="IFIND_EDB_CONTEXT_READY_WITH_WARNINGS",
        data_start=min(cotton["trade_date"].min(), fx_swap["trade_date"].min()).date(),
        data_end=max(cotton["trade_date"].max(), fx_swap["trade_date"].max()).date(),
        source_dir=selected_source_dir,
        cotton_source_path=cotton_source,
        fx_swap_source_path=fx_source,
        cotton_context_path=paths["cotton"],
        spot_extension_path=paths["spot"],
        policy_event_path=paths["policy"],
        yarn_price_path=paths["yarn"],
        fx_swap_curve_path=paths["fx_swap"],
        quality_csv_path=paths["quality"],
        warning_csv_path=paths["warnings"],
        json_path=paths["json"],
        manifest_path=paths["manifest"],
        markdown_path=paths["markdown"],
        latest_spot_date=pd.Timestamp(latest_spot["trade_date"]).date(),
        latest_spot_price=float(latest_spot["indicator_value"]),
        cotton_row_count=len(cotton),
        fx_swap_row_count=len(fx_swap),
        warning_records=tuple(warnings),
    )
    _write_warnings(result)
    _write_json(result)
    _write_markdown(result=result, cotton=cotton, policy=policy, yarn=yarn, fx_swap=fx_swap)
    _write_manifest(result=result)
    return result


def _normalize_cotton_edb(
    frame: pd.DataFrame,
    as_of_date: date,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    normalized = _validate_base(frame, expected_ids=set(COTTON_EDB), as_of_date=as_of_date)
    expected_names = {indicator_id: values[1] for indicator_id, values in COTTON_EDB.items()}
    for indicator_id, expected_name in expected_names.items():
        observed = set(
            normalized.loc[normalized["indicator"].eq(indicator_id), "index_name"].astype(str)
        )
        if observed != {expected_name}:
            raise ResearchWorkbenchError(
                f"iFinD EDB name mismatch for {indicator_id}: {sorted(observed)}"
            )
    normalized["dataset_type"] = normalized["indicator"].map(
        lambda value: COTTON_EDB[str(value)][0]
    )
    normalized["unit_status"] = normalized["indicator"].map(
        lambda value: COTTON_EDB[str(value)][2]
    )
    normalized["product_code"] = PRODUCT_CODE
    normalized["indicator_id"] = normalized["indicator"]
    normalized["indicator_name"] = normalized["index_name"]
    normalized["indicator_value"] = normalized["value"]
    normalized["source_name"] = "iFinD EDB"
    normalized["data_quality_flag"] = "REVIEW_REQUIRED"
    normalized["human_review_required"] = True
    normalized["signal_status"] = "not_connected"
    normalized["rule_version"] = RULE_VERSION
    columns = [
        "trade_date",
        "product_code",
        "dataset_type",
        "indicator_id",
        "indicator_name",
        "indicator_value",
        "unit_status",
        "source_name",
        "rtime",
        "fetch_time",
        "source_func",
        "data_quality_flag",
        "human_review_required",
        "signal_status",
        "rule_version",
    ]
    output = normalized[columns].sort_values(["trade_date", "indicator_id"])
    return output.reset_index(drop=True), _quality_rows(output)


def _normalize_fx_swap_edb(
    frame: pd.DataFrame,
    as_of_date: date,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    normalized = _validate_base(frame, expected_ids=set(FX_SWAP_TENORS), as_of_date=as_of_date)
    normalized["product_code"] = PRODUCT_CODE
    normalized["indicator_id"] = normalized["indicator"]
    normalized["tenor"] = normalized["indicator"].map(FX_SWAP_TENORS)
    normalized["swap_value"] = normalized["value"]
    normalized["unit_status"] = "SWAP_POINT_UNIT_REVIEW_REQUIRED"
    normalized["source_name"] = "iFinD EDB"
    normalized["data_quality_flag"] = "REVIEW_REQUIRED"
    normalized["human_review_required"] = True
    normalized["signal_status"] = "not_connected"
    normalized["rule_version"] = RULE_VERSION
    columns = [
        "trade_date",
        "product_code",
        "indicator_id",
        "index_name",
        "tenor",
        "swap_value",
        "unit_status",
        "source_name",
        "rtime",
        "fetch_time",
        "source_func",
        "data_quality_flag",
        "human_review_required",
        "signal_status",
        "rule_version",
    ]
    output = normalized[columns].sort_values(["trade_date", "indicator_id"])
    quality_input = output.rename(
        columns={"indicator_id": "indicator_id", "swap_value": "indicator_value"}
    )
    return output.reset_index(drop=True), _quality_rows(quality_input)


def _validate_base(
    frame: pd.DataFrame,
    *,
    expected_ids: set[str],
    as_of_date: date,
) -> pd.DataFrame:
    required = {
        "date",
        "indicator",
        "value",
        "source_func",
        "fetch_time",
        "index_name",
        "rtime",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ResearchWorkbenchError(f"iFinD EDB source missing columns: {sorted(missing)}")
    normalized = frame.copy()
    normalized["trade_date"] = pd.to_datetime(normalized["date"]).astype("datetime64[ns]")
    normalized["value"] = pd.to_numeric(normalized["value"], errors="coerce")
    observed_ids = set(normalized["indicator"].astype(str))
    if observed_ids != expected_ids:
        raise ResearchWorkbenchError(
            f"iFinD EDB indicator set mismatch: missing={sorted(expected_ids - observed_ids)}, "
            f"extra={sorted(observed_ids - expected_ids)}"
        )
    if normalized["source_func"].ne("THS_EDB").any():
        raise ResearchWorkbenchError("iFinD EDB source_func must be THS_EDB")
    if normalized["value"].isna().any():
        raise ResearchWorkbenchError("iFinD EDB accepted source contains null/non-numeric values")
    if normalized.duplicated(["trade_date", "indicator"]).any():
        raise ResearchWorkbenchError("iFinD EDB source contains duplicate indicator-date rows")
    if normalized["trade_date"].dt.date.gt(as_of_date).any():
        raise ResearchWorkbenchError("iFinD EDB source contains future-dated rows")
    return normalized


def _spot_extension(cotton: pd.DataFrame, source_path: Path) -> pd.DataFrame:
    spot = cotton.loc[cotton["indicator_id"].eq("S002885871")].copy()
    return pd.DataFrame(
        {
            "trade_date": spot["trade_date"],
            "product_code": PRODUCT_CODE,
            "indicator_name": spot["indicator_name"],
            "indicator_value": spot["indicator_value"],
            "unit": "元/吨",
            "source_name": "iFinD EDB",
            "indicator_id": spot["indicator_id"],
            "update_time": spot["rtime"],
            "source_file": str(source_path),
            "data_quality_flag": "REVIEW_REQUIRED",
            "human_review_required": True,
            "remark": (
                "iFinD EDB spot extension; unit and bridge to CCIndex 3128B "
                "require human review"
            ),
        }
    ).reset_index(drop=True)


def _quality_rows(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for indicator_id, group in frame.groupby("indicator_id", sort=True):
        rows.append(
            {
                "indicator_id": indicator_id,
                "row_count": len(group),
                "non_null_count": int(group["indicator_value"].notna().sum()),
                "date_start": group["trade_date"].min(),
                "date_end": group["trade_date"].max(),
                "duplicate_count": int(group.duplicated(["trade_date"]).sum()),
                "status": "PASS",
            }
        )
    return pd.DataFrame(rows)


def _warning_records(
    *,
    cotton: pd.DataFrame,
    fx_swap: pd.DataFrame,
) -> list[IFindEdbWarningRecord]:
    return [
        IFindEdbWarningRecord(
            severity="WARN",
            warning_code="IFIND_EDB_UNIT_REVIEW_REQUIRED",
            message="EDB返回值未携带单位元数据；价格、比例、投放量和掉期点单位需函数库复核。",
            human_review_required=("ifind_edb_units",),
        ),
        IFindEdbWarningRecord(
            severity="WARN",
            warning_code="USD_CNY_SPOT_NOT_CONNECTED",
            message="当前只有USD/CNY掉期曲线，不能替代即期汇率，R93H汇率Beta尚不能运行。",
            human_review_required=("usdcny_spot_indicator_id",),
        ),
        IFindEdbWarningRecord(
            severity="WARN",
            warning_code="ICE_COTTON_NOT_CONNECTED",
            message="尚未提供ICE棉花连续价格代码，全球棉价Beta尚不能运行。",
            human_review_required=("ice_cotton_price_code_and_adjustment",),
        ),
        IFindEdbWarningRecord(
            severity="INFO",
            warning_code="POLICY_ZERO_FILL_DISABLED",
            message="储备棉事件序列缺失期不补零，避免把未公布误写为零投放。",
        ),
        IFindEdbWarningRecord(
            severity="INFO",
            warning_code="IFIND_EDB_SIGNAL_NOT_CONNECTED",
            message=(
                f"已规范化棉花EDB {len(cotton)}行、掉期曲线 {len(fx_swap)}行；"
                "当前仅供研究观察。"
            ),
        ),
    ]


def _output_paths(
    *,
    start: date,
    end: date,
    output_dir: Path | None,
    report_output_dir: Path | None,
) -> dict[str, Path]:
    root = output_dir or data_dir() / "research" / PRODUCT_CODE / "ifind_edb"
    report_root = report_output_dir or reports_dir() / "research" / "ifind_edb"
    stem = f"{PRODUCT_CODE}_{start.isoformat()}_{end.isoformat()}"
    return {
        "cotton": root / f"{stem}_ifind_cotton_context_daily.parquet",
        "spot": root / f"{stem}_ifind_spot_extension_daily.parquet",
        "policy": root / f"{stem}_ifind_policy_event_daily.parquet",
        "yarn": root / f"{stem}_ifind_yarn_price_daily.parquet",
        "fx_swap": root / f"{stem}_ifind_usdcny_swap_curve_daily.parquet",
        "quality": root / f"{stem}_ifind_edb_quality.csv",
        "warnings": root / f"{stem}_ifind_edb_warnings.csv",
        "json": report_root / f"{stem}_ifind_edb_context.json",
        "manifest": root / f"{stem}_ifind_edb_manifest.json",
        "markdown": report_root / f"{stem}_ifind_edb_context.md",
    }


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def _write_quality(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8")


def _write_warnings(result: ResearchIFindEdbContextResult) -> None:
    result.warning_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with result.warning_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "run_id",
                "severity",
                "warning_code",
                "message",
                "human_review_required",
            ),
        )
        writer.writeheader()
        for row in result.warning_records:
            writer.writerow(
                {
                    "run_id": result.run_id,
                    "severity": row.severity,
                    "warning_code": row.warning_code,
                    "message": row.message,
                    "human_review_required": ";".join(row.human_review_required),
                }
            )


def _write_json(result: ResearchIFindEdbContextResult) -> None:
    payload = {
        "report_type": "ifind_edb_context",
        "rule_version": RULE_VERSION,
        "summary": result.to_summary(),
        "contains_forward_labels": False,
        "signal_status": "not_connected",
        "research_boundary": RESEARCH_BOUNDARY,
    }
    result.json_path.parent.mkdir(parents=True, exist_ok=True)
    result.json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_markdown(
    *,
    result: ResearchIFindEdbContextResult,
    cotton: pd.DataFrame,
    policy: pd.DataFrame,
    yarn: pd.DataFrame,
    fx_swap: pd.DataFrame,
) -> None:
    latest_policy = policy.groupby("indicator_name")["trade_date"].max()
    latest_yarn = yarn.groupby("indicator_name")["trade_date"].max()
    lines = [
        "# CF R93H iFinD EDB 数据基座",
        "",
        "## 数据状态",
        "",
        f"- 数据区间：`{result.data_start}` 至 `{result.data_end}`",
        f"- 棉花/政策/纱线：`{len(cotton)}`行，9个指标。",
        f"- USD/CNY掉期曲线：`{len(fx_swap)}`行，19个期限。",
        f"- 最新3128B现货：`{result.latest_spot_date}` / "
        f"`{result.latest_spot_price:,.0f}`。",
        "- 所有接受表均为非空、无重复、无未来日期的THS_EDB真实返回。",
        "",
        "## 储备棉事件覆盖",
        "",
    ]
    lines.extend(f"- {name}：截至 `{value.date()}`" for name, value in latest_policy.items())
    lines.extend(["", "## 纱线价格覆盖", ""])
    lines.extend(f"- {name}：截至 `{value.date()}`" for name, value in latest_yarn.items())
    lines.extend(
        [
            "",
            "## 当前缺口",
            "",
            "- USD/CNY掉期曲线不能替代即期汇率，汇率Beta仍缺即期序列。",
            "- 尚无ICE棉花连续价格，全球棉价Beta仍未启动。",
            "- EDB接口未返回单位元数据，所有单位继续人工复核。",
            "- 周末THS_BD合约快照大量为空，未进入Cottonquant incoming。",
            "",
            "## 研究边界",
            "",
            f"> {RESEARCH_BOUNDARY}",
            "",
            "本数据包不含forward return，不进入策略评分或自动交易结论。",
        ]
    )
    result.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    result.markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_manifest(result: ResearchIFindEdbContextResult) -> None:
    artifacts = (
        result.cotton_context_path,
        result.spot_extension_path,
        result.policy_event_path,
        result.yarn_price_path,
        result.fx_swap_curve_path,
        result.quality_csv_path,
        result.warning_csv_path,
        result.json_path,
        result.markdown_path,
    )
    payload = {
        "report_type": "ifind_edb_context",
        "rule_version": RULE_VERSION,
        "generated_at": utc_now().isoformat(),
        "summary": result.to_summary(),
        "input_sha256": {
            str(result.cotton_source_path): _sha256(result.cotton_source_path),
            str(result.fx_swap_source_path): _sha256(result.fx_swap_source_path),
        },
        "artifact_sha256": {str(path): _sha256(path) for path in artifacts},
        "contains_forward_labels": False,
        "signal_status": "not_connected",
        "research_boundary": RESEARCH_BOUNDARY,
    }
    result.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    result.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _latest_source_dir() -> Path:
    root = data_dir() / "incoming" / PRODUCT_CODE / "ifind_edb"
    candidates = sorted(path for path in root.iterdir() if path.is_dir()) if root.exists() else []
    for candidate in reversed(candidates):
        if (candidate / "cotton_policy_spot_yarn_edb.parquet").exists() and (
            candidate / "usdcny_swap_curve_edb.parquet"
        ).exists():
            return candidate
    raise ResearchWorkbenchError(f"no complete CF iFinD EDB source bundle under {root}")


def _read_source(path: Path, label: str) -> pd.DataFrame:
    if not path.exists() or not path.is_file():
        raise ResearchWorkbenchError(f"{label} source not found: {path}")
    frame = pd.read_parquet(path)
    if frame.empty:
        raise ResearchWorkbenchError(f"{label} source contains no rows: {path}")
    return frame


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_run_id() -> str:
    return f"cf_r93h_ifind_edb_{uuid.uuid4().hex[:8]}"
