"""Minimal weekly-output guardrails; this file does not publish or overwrite data."""

import argparse
from pathlib import Path


FORBIDDEN_VAGUE_PHRASES = ("市场情绪有所修复", "资金面整体平稳")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("weekly_markdown", type=Path)
    args = parser.parse_args()
    text = args.weekly_markdown.read_text(encoding="utf-8")
    hits = [phrase for phrase in FORBIDDEN_VAGUE_PHRASES if phrase in text]
    if hits:
        raise SystemExit(f"发现需补充具体指标和比较基准的空泛表达: {hits}")
    required = ("适用期限", "传导机制", "触发条件", "证伪条件", "跟踪指标")
    missing = [field for field in required if field not in text]
    if missing:
        raise SystemExit(f"市场判断五要素不完整: {missing}")
    print("weekly validation: PASS")


if __name__ == "__main__":
    main()
