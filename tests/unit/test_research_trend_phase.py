from __future__ import annotations

from cotton_factor.research_workbench import classify_cf_trend_phase


def test_classify_cf_trend_phase_s0_when_signal_context_is_incomplete() -> None:
    result = classify_cf_trend_phase(
        signal_states={"momentum": "long", "carry": "unknown", "curve": "neutral"},
        latest_settle=100,
        ma20=None,
        momentum_20=0.02,
        latest_return=0.01,
        oi_pressure=0.01,
    )

    assert result.phase_code == "S0"
    assert result.direction == "unknown"


def test_classify_cf_trend_phase_s1_start_observation() -> None:
    result = classify_cf_trend_phase(
        signal_states={
            "momentum": "long",
            "carry": "long",
            "curve": "long",
            "oi_pressure": "neutral",
        },
        latest_settle=100,
        ma20=101,
        momentum_20=0.02,
        latest_return=0.01,
        oi_pressure=None,
    )

    assert result.phase_code == "S1"
    assert result.direction == "long"


def test_classify_cf_trend_phase_s2_trend_in_progress() -> None:
    result = classify_cf_trend_phase(
        signal_states={
            "momentum": "long",
            "carry": "long",
            "curve": "long",
            "oi_pressure": "long",
        },
        latest_settle=110,
        ma20=100,
        momentum_20=0.08,
        latest_return=0.01,
        oi_pressure=0.02,
    )

    assert result.phase_code == "S2"
    assert result.direction == "long"
    assert result.confidence == "high"


def test_classify_cf_trend_phase_s3_exhaustion_observation() -> None:
    result = classify_cf_trend_phase(
        signal_states={
            "momentum": "long",
            "carry": "long",
            "curve": "long",
            "oi_pressure": "neutral",
        },
        latest_settle=110,
        ma20=100,
        momentum_20=-0.01,
        latest_return=-0.005,
        oi_pressure=0.01,
    )

    assert result.phase_code == "S3"
    assert result.direction == "long"


def test_classify_cf_trend_phase_s4_end_confirmation() -> None:
    result = classify_cf_trend_phase(
        signal_states={
            "momentum": "short",
            "carry": "short",
            "curve": "short",
            "oi_pressure": "short",
        },
        latest_settle=95,
        ma20=100,
        momentum_20=-0.06,
        latest_return=-0.02,
        oi_pressure=0.03,
    )

    assert result.phase_code == "S4"
    assert result.direction == "short"
