"""Deterministic preprocessing helpers for factor values."""

from __future__ import annotations

import math
from collections.abc import Sequence

from cotton_factor.common.exceptions import FactorError


def winsorize_series(
    values: Sequence[float],
    *,
    lower_quantile: float = 0.05,
    upper_quantile: float = 0.95,
) -> list[float]:
    """Clamp values to deterministic linear-interpolated quantile bounds."""
    clean_values = _finite_values(values)
    if not clean_values:
        return []
    if not 0 <= lower_quantile <= upper_quantile <= 1:
        raise FactorError("winsorize quantiles must satisfy 0 <= lower <= upper <= 1")

    sorted_values = sorted(clean_values)
    lower_bound = _quantile(sorted_values, lower_quantile)
    upper_bound = _quantile(sorted_values, upper_quantile)
    return [min(max(value, lower_bound), upper_bound) for value in clean_values]


def zscore_series(values: Sequence[float]) -> list[float]:
    """Return population z-scores while preserving input order."""
    clean_values = _finite_values(values)
    if not clean_values:
        return []

    mean = sum(clean_values) / len(clean_values)
    variance = sum((value - mean) ** 2 for value in clean_values) / len(clean_values)
    std = math.sqrt(variance)
    if std == 0:
        # 常数序列没有横截面差异，统一返回 0，避免后续因子误读为异常缺失。
        return [0.0 for _ in clean_values]
    return [(value - mean) / std for value in clean_values]


def rank_series(values: Sequence[float]) -> list[float]:
    """Return 1-based average ranks with ties, preserving input order."""
    clean_values = _finite_values(values)
    if not clean_values:
        return []

    indexed = sorted(enumerate(clean_values), key=lambda item: (item[1], item[0]))
    ranks = [0.0 for _ in clean_values]
    start = 0
    while start < len(indexed):
        end = start
        while end + 1 < len(indexed) and indexed[end + 1][1] == indexed[start][1]:
            end += 1
        average_rank = (start + 1 + end + 1) / 2
        for offset in range(start, end + 1):
            original_index = indexed[offset][0]
            ranks[original_index] = float(average_rank)
        start = end + 1
    return ranks


def _finite_values(values: Sequence[float]) -> list[float]:
    clean_values = [float(value) for value in values]
    non_finite = [value for value in clean_values if not math.isfinite(value)]
    if non_finite:
        raise FactorError(f"factor preprocessing values must be finite: {non_finite}")
    return clean_values


def _quantile(sorted_values: Sequence[float], quantile: float) -> float:
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * quantile
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return float(sorted_values[lower_index])
    weight = position - lower_index
    return float(
        sorted_values[lower_index] * (1 - weight)
        + sorted_values[upper_index] * weight
    )
