"""Safe weekly snapshot entry point (disabled during initialization)."""

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def within_project(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
        return True
    except ValueError:
        return False


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-manifest", type=Path, required=True)
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--no-promote", action="store_true")
    parser.add_argument("--no-publish", action="store_true")
    args = parser.parse_args()
    if not (args.no_fetch and args.no_promote and args.no_publish):
        raise SystemExit("初始化阶段只允许 --no-fetch --no-promote --no-publish 演练。")
    manifest = json.loads(args.run_manifest.read_text(encoding="utf-8"))
    output_root = Path(manifest.get("output_root", ""))
    if not output_root or not within_project(output_root):
        raise SystemExit("run manifest 的 output_root 必须位于 CGB_Research 内。")
    required = {
        "frozen_inputs",
        "writer_id",
        "active_contracts",
        "cffex_snapshot_sha256",
        "cffex_snapshot_complete",
        "dynamic_conversion_factor_validated",
        "single_writer_lock_validated",
        "atomic_current_update_validated",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        raise SystemExit(f"run manifest 缺少字段: {missing}")
    frozen_inputs = manifest["frozen_inputs"]
    if len(frozen_inputs) != 12 or len({item["dataset_id"] for item in frozen_inputs}) != 12:
        raise SystemExit("冻结输入必须恰好包含12个唯一生产数据集。")
    for item in frozen_inputs:
        input_path = ROOT / item["relative_path"]
        if not input_path.is_file() or not within_project(input_path):
            raise SystemExit(f"冻结输入不存在或越界: {item['relative_path']}")
        if sha256(input_path) != item["sha256"]:
            raise SystemExit(f"冻结输入SHA不一致: {item['dataset_id']}")
    expected_products = {"TS", "TF", "T", "TL"}
    if set(manifest["active_contracts"]) != expected_products:
        raise SystemExit("active_contracts必须分别记录TS/TF/T/TL。")
    blockers = [
        name for name in (
            "cffex_snapshot_complete",
            "dynamic_conversion_factor_validated",
            "single_writer_lock_validated",
            "atomic_current_update_validated",
        ) if not manifest[name]
    ]
    print(json.dumps({
        "dry_run_guardrails": "PASS",
        "frozen_input_count": len(frozen_inputs),
        "fetch": False,
        "promote": False,
        "publish": False,
        "production_enablement": "BLOCKED" if blockers else "ELIGIBLE_FOR_SEPARATE_APPROVAL",
        "blockers": blockers,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
