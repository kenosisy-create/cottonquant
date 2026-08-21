"""Report extraction preflight only.

Initialization deliberately stops before report-card generation. This entry point
refuses batch extraction until the Gate A approval marker exists.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPROVAL = ROOT / "09_audit" / "gate_a_user_approval.json"


def main() -> None:
    if not APPROVAL.exists():
        raise SystemExit(
            "Gate A 尚未获得用户书面批准：只允许注册与质量审计，不生成报告卡片。"
        )
    raise SystemExit("抽取流水线尚未实现；不得绕过3份Gate A试处理。")


if __name__ == "__main__":
    main()
