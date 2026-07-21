from __future__ import annotations

import pandas as pd

from cotton_factor.research_workbench import (
    build_research_framework_context,
    display_threshold_status,
    research_framework_markdown_lines,
    validated_stance_label,
)


def test_research_framework_separates_signal_strength_from_reliability() -> None:
    latest = {
        "signal_matrix_context": {
            "primary_horizon": 20,
            "primary_direction": "long",
            "primary_confidence": "high",
            "rows": [
                {
                    "horizon": 10,
                    "direction": "long",
                    "confidence": "high",
                    "option_signal": "confirm_long",
                    "option_signal_direction": "long",
                    "option_factor_status": "READY",
                    "option_atm_iv_rank": 0.035,
                    "option_skew_proxy": -0.001,
                },
                {
                    "horizon": 20,
                    "direction": "long",
                    "confidence": "high",
                    "option_signal": "confirm_long",
                    "option_signal_direction": "long",
                    "option_factor_status": "READY",
                    "option_atm_iv_rank": 0.035,
                    "option_skew_proxy": -0.001,
                },
            ],
        },
        "signal_threshold_context": {
            "horizon_alignment_status": "ALTERNATE_ONLY",
            "alternate_candidates": [
                {
                    "horizon": 10,
                    "candidate_status": "READY_CANDIDATE",
                    "directional_hit_rate": 0.61,
                }
            ],
        },
    }
    decay = pd.DataFrame(
        [
            {
                "horizon": 10,
                "directional_hit_rate": 0.4716,
                "mean_net_return_normal_cost": 0.0039,
                "stability_status": "WATCH",
            },
            {
                "horizon": 20,
                "directional_hit_rate": 0.4394,
                "mean_net_return_normal_cost": 0.0033,
                "stability_status": "WEAK_OR_UNSTABLE",
            },
        ]
    )
    stability = pd.DataFrame(
        [
            {
                "horizon": 10,
                "candidate_status": "READY_CANDIDATE",
                "stability_status": "READY",
            }
        ]
    )

    context = build_research_framework_context(
        latest=latest,
        decay=decay,
        stability=stability,
    )

    assert context["historical_reliability"]["reliability_level"] == "WEAK_OR_CONFLICTED"
    assert context["threshold_interpretation"]["publish_status"] == "WATCH_ONLY_OOS_REQUIRED"
    assert validated_stance_label(context) == "EVIDENCE_CONFLICT_BLOCKED"
    assert context["validated_stance"]["auto_reverse_allowed"] is False
    assert context["option_framework_context"]["volatility_state"] == "low_iv_breakout_not_priced"
    assert context["event_labeling_gap"]["missing_event_lifecycle_labels"] is True
    assert context["evidence_conflicts"]

    markdown = "\n".join(research_framework_markdown_lines(context))
    assert "R67" in markdown
    assert "signal_strength" in markdown
    assert "historical_reliability" in markdown
    assert "high confidence" in markdown
    assert "Triple Barrier" in markdown
    assert "WATCH_ONLY_OOS_REQUIRED" in markdown


def test_display_threshold_status_requires_oos_for_ready_candidates() -> None:
    assert display_threshold_status("READY_CANDIDATE") == "WATCH_ONLY_OOS_REQUIRED"
    assert display_threshold_status("WATCH_CANDIDATE") == "WATCH_ONLY_OOS_REQUIRED"
    assert display_threshold_status("WEAK_OR_UNSTABLE") == "WEAK_OR_UNSTABLE"
