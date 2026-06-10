from __future__ import annotations

import math

import pytest

from cotton_factor.common.exceptions import FactorError
from cotton_factor.research import rank_series, winsorize_series, zscore_series


def test_winsorize_series_clamps_to_interpolated_bounds() -> None:
    result = winsorize_series([100, 1, 2, 3], lower_quantile=0.25, upper_quantile=0.75)

    assert result == pytest.approx([27.25, 1.75, 2, 3])


def test_zscore_series_handles_empty_and_constant_values_explicitly() -> None:
    assert zscore_series([]) == []
    assert zscore_series([5, 5, 5]) == [0.0, 0.0, 0.0]

    values = zscore_series([1, 2, 3])
    assert values == pytest.approx([-math.sqrt(1.5), 0.0, math.sqrt(1.5)])


def test_rank_series_uses_average_tie_ranks_and_preserves_order() -> None:
    assert rank_series([]) == []
    assert rank_series([2, 1, 2, 4]) == [2.5, 1.0, 2.5, 4.0]


def test_preprocessing_rejects_non_finite_values_and_bad_quantiles() -> None:
    with pytest.raises(FactorError, match="finite"):
        zscore_series([1, float("nan")])

    with pytest.raises(FactorError, match="quantiles"):
        winsorize_series([1, 2, 3], lower_quantile=0.9, upper_quantile=0.1)
