"""CF 日常运行编排入口。"""

from typing import Any

__all__ = [
    "CfDailyUpdateConfig",
    "CfDailyUpdateResult",
    "default_run_id",
    "run_cf_daily_update",
]


def __getattr__(name: str) -> Any:
    """按需加载编排器，避免 `python -m` 重复导入模块。"""
    if name in __all__:
        from cotton_factor.operations import daily_update

        return getattr(daily_update, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
