"""Research workbench helpers."""

from cotton_factor.research_workbench.carry import (
    ResearchCarryBuildResult,
    build_cf_carry_factor,
)
from cotton_factor.research_workbench.chain_oi_structure import (
    ResearchChainOiStructureResult,
    build_cf_chain_oi_structure,
)
from cotton_factor.research_workbench.config import (
    ResearchModeConfig,
    load_research_mode_config,
)
from cotton_factor.research_workbench.continuous import (
    ResearchContinuousBuildResult,
    build_cf_research_continuous,
)
from cotton_factor.research_workbench.contract_review import (
    ContractRuleReviewResult,
    ContractRuleReviewRow,
    build_cf_contract_rule_review,
)
from cotton_factor.research_workbench.core_quotes import (
    ResearchCoreQuoteBuildResult,
    normalize_cf_core_quotes,
)
from cotton_factor.research_workbench.cost_sensitivity import (
    CostSensitivitySummaryRow,
    CostSensitivityWarningRecord,
    ResearchCostSensitivityResult,
    build_cf_cost_sensitivity,
)
from cotton_factor.research_workbench.current_watch_window import (
    ResearchCurrentWatchWindowResult,
    build_cf_current_watch_window,
)
from cotton_factor.research_workbench.daily_brief import (
    DailyBriefWarningRecord,
    ResearchDailyBriefResult,
    build_cf_daily_brief,
)
from cotton_factor.research_workbench.daily_operation_audit import (
    DailyOperationAuditWarningRecord,
    ResearchDailyOperationAuditResult,
    build_cf_daily_operation_audit,
)
from cotton_factor.research_workbench.data_continuity_audit import (
    DataContinuityDatasetAudit,
    DataContinuityWarningRecord,
    ResearchDataContinuityAuditResult,
    build_cf_data_continuity_audit,
)
from cotton_factor.research_workbench.data_quality import (
    CfDataQualityResult,
    DataQualityIssue,
    check_cf_data_quality,
)
from cotton_factor.research_workbench.dual_price_state import (
    ResearchDualPriceStateResult,
    build_cf_dual_price_state,
)
from cotton_factor.research_workbench.event_lifecycle import (
    ResearchEventLifecycleResult,
    build_cf_event_lifecycle_research,
)
from cotton_factor.research_workbench.event_threshold_review_ledger import (
    EventThresholdReviewWarningRecord,
    ResearchEventThresholdReviewResult,
    build_cf_event_threshold_review_ledger,
)
from cotton_factor.research_workbench.event_threshold_sensitivity import (
    EventThresholdSensitivityWarningRecord,
    ResearchEventThresholdSensitivityResult,
    build_cf_event_threshold_sensitivity,
)
from cotton_factor.research_workbench.expansion_gate import (
    ExpansionGateRequirement,
    ResearchExpansionGateResult,
    build_cf_expansion_gate,
)
from cotton_factor.research_workbench.factor_artifacts import FactorWarningRecord
from cotton_factor.research_workbench.factor_diagnostics import (
    ResearchFactorDiagnosticsBuildResult,
    build_cf_factor_diagnostics,
)
from cotton_factor.research_workbench.forward_returns import (
    ForwardReturnWarningRecord,
    ResearchForwardReturnsBuildResult,
    build_cf_forward_returns,
)
from cotton_factor.research_workbench.fundamental_context import (
    FundamentalContextWarningRecord,
    ResearchFundamentalContextResult,
    build_cf_fundamental_context,
)
from cotton_factor.research_workbench.fundamental_data_contract import (
    FundamentalDataContractWarningRecord,
    FundamentalDatasetContract,
    ResearchFundamentalDataContractResult,
    build_cf_fundamental_data_contract,
)
from cotton_factor.research_workbench.fundamental_observation import (
    FundamentalObservationDatasetSummary,
    FundamentalObservationWarningRecord,
    ResearchFundamentalObservationResult,
    build_cf_fundamental_observation,
)
from cotton_factor.research_workbench.futures_option_divergence import (
    FuturesOptionDivergenceWarningRecord,
    ResearchFuturesOptionDivergenceResult,
    build_cf_futures_option_divergence_research,
)
from cotton_factor.research_workbench.futures_option_divergence_playbook import (
    FuturesOptionDivergencePlaybookWarningRecord,
    ResearchFuturesOptionDivergencePlaybookResult,
    build_cf_futures_option_divergence_playbook,
)
from cotton_factor.research_workbench.historical_event_explanation import (
    HistoricalEventExplanationWarningRecord,
    ResearchHistoricalEventExplanationResult,
    build_cf_historical_event_explanation,
)
from cotton_factor.research_workbench.historical_evidence import (
    HistoricalEvidenceWarningRecord,
    ResearchHistoricalEvidenceResult,
    build_cf_historical_evidence_pack,
)
from cotton_factor.research_workbench.latest_signal_brief import (
    LatestSignalBriefResult,
    LatestSignalWarningRecord,
    build_cf_latest_signal_brief,
)
from cotton_factor.research_workbench.mapping import (
    ResearchMappingBuildResult,
    build_cf_research_mapping,
)
from cotton_factor.research_workbench.member_position_ingest import (
    MemberPositionSourceRecord,
    OfficialMemberPositionFetchResult,
    OfficialMemberPositionHistoryFetchResult,
    ResearchMemberPositionIngestResult,
    connect_cf_member_position_history,
    fetch_cf_official_member_position,
    fetch_cf_official_member_position_history,
    official_member_position_url,
    official_member_position_urls,
)
from cotton_factor.research_workbench.member_position_research import (
    ResearchMemberPositionResult,
    build_cf_member_position_research,
)
from cotton_factor.research_workbench.momentum import (
    ResearchMomentumBuildResult,
    build_cf_momentum_factor,
)
from cotton_factor.research_workbench.multifactor_diagnostics import (
    MultifactorDiagnosticWarningRecord,
    ResearchMultifactorDiagnosticsResult,
    build_cf_multifactor_diagnostics,
)
from cotton_factor.research_workbench.official_daily_files import (
    OfficialDailyFileRecord,
    OfficialDailyFilesFetchResult,
    fetch_cf_official_daily_files,
    official_daily_date_key,
    official_daily_file_url,
    official_daily_file_urls,
)
from cotton_factor.research_workbench.official_history import (
    OfficialHistoryConnectResult,
    OfficialHistoryYearRecord,
    connect_cf_official_history,
    default_recent_history_years,
    official_history_url,
)
from cotton_factor.research_workbench.oi_roll_window_research import (
    ResearchOiRollWindowResult,
    build_cf_oi_roll_window_research,
)
from cotton_factor.research_workbench.option_core_ingest import (
    OptionQualityRow,
    OptionSourceRecord,
    ResearchOptionCoreIngestResult,
    connect_cf_option_history,
)
from cotton_factor.research_workbench.option_data_contract import (
    OptionDataContractWarningRecord,
    ResearchOptionDataContractResult,
    build_cf_option_data_contract,
)
from cotton_factor.research_workbench.option_factor_proxy import (
    OptionFactorProxyWarningRecord,
    ResearchOptionFactorProxyResult,
    build_cf_option_factor_proxy,
)
from cotton_factor.research_workbench.option_strike_position_research import (
    ResearchOptionStrikePositionResult,
    build_cf_option_strike_position_research,
)
from cotton_factor.research_workbench.option_structure_research import (
    ResearchOptionStructureResult,
    build_cf_option_structure_research,
)
from cotton_factor.research_workbench.option_volatility_term_structure import (
    ResearchOptionVolatilityTermStructureResult,
    build_cf_option_volatility_term_structure_research,
)
from cotton_factor.research_workbench.output_contracts import (
    FactorOutputArtifactContract,
    FactorOutputContractResult,
    build_cf_factor_output_contract,
    factor_output_artifact_contracts,
)
from cotton_factor.research_workbench.pipeline import (
    ResearchDailyPipelineResult,
    ResearchPipelineStep,
    build_cf_daily_research_pipeline,
)
from cotton_factor.research_workbench.product_research_registry import (
    ResearchProductRegistryResult,
    build_cf_product_research_registry,
)
from cotton_factor.research_workbench.publish_pack import (
    ResearchPublishPackResult,
    build_cf_publish_pack,
)
from cotton_factor.research_workbench.raw_ingest import (
    ResearchRawFileRecord,
    ResearchRawIngestResult,
    ingest_cf_raw,
    list_cf_raw_manifest,
)
from cotton_factor.research_workbench.replay import (
    ResearchPipelineReplayResult,
    ResearchReplayArtifact,
    ResearchReplayCheck,
    replay_cf_research_pipeline_outputs,
)
from cotton_factor.research_workbench.research_framework import (
    RESEARCH_FRAMEWORK_VERSION,
    build_research_framework_context,
    display_threshold_status,
    research_framework_markdown_lines,
    validated_stance_label,
    validated_stance_title_text,
)
from cotton_factor.research_workbench.signal_matrix import (
    ResearchSignalMatrixResult,
    SignalMatrixWarningRecord,
    build_cf_signal_matrix,
)
from cotton_factor.research_workbench.signal_matrix_validation import (
    ResearchSignalMatrixValidationResult,
    SignalMatrixValidationWarningRecord,
    build_cf_signal_matrix_validation,
)
from cotton_factor.research_workbench.signal_threshold_research import (
    ResearchSignalThresholdResult,
    SignalThresholdResearchWarningRecord,
    build_cf_signal_threshold_research,
)
from cotton_factor.research_workbench.single_factor_backtest import (
    ResearchSingleFactorBacktestResult,
    SingleFactorBacktestWarningRecord,
    build_cf_single_factor_backtest,
)
from cotton_factor.research_workbench.stage_decision_pack import (
    ResearchStageDecisionPackResult,
    build_cf_stage_decision_pack,
)
from cotton_factor.research_workbench.state_transition_competing_risk import (
    ResearchStateTransitionCompetingRiskResult,
    build_cf_state_transition_competing_risk_research,
)
from cotton_factor.research_workbench.structure_factors import (
    ResearchStructureFactorsBuildResult,
    build_cf_structure_factors,
)
from cotton_factor.research_workbench.trend_continuity_board import (
    ResearchTrendContinuityBoardResult,
    TrendContinuityWarningRecord,
    build_cf_trend_continuity_board,
)
from cotton_factor.research_workbench.trend_phase import (
    TrendPhaseResult,
    classify_cf_trend_phase,
)
from cotton_factor.research_workbench.trend_phase_events import (
    ResearchTrendPhaseEventResult,
    TrendPhaseEventWarningRecord,
    build_cf_trend_phase_events,
)
from cotton_factor.research_workbench.trend_phase_v2 import (
    ResearchTrendPhaseV2Result,
    build_cf_trend_phase_v2,
)
from cotton_factor.research_workbench.trend_phase_validation import (
    ResearchTrendPhaseValidationResult,
    TrendPhaseValidationWarningRecord,
    build_cf_trend_phase_validation,
)
from cotton_factor.research_workbench.trend_quality_calibration import (
    ResearchTrendQualityCalibrationResult,
    TrendQualityCalibrationWarningRecord,
    build_cf_trend_quality_calibration,
)
from cotton_factor.research_workbench.trend_rule_candidates import (
    ResearchTrendRuleCandidateResult,
    TrendRuleCandidateWarningRecord,
    build_cf_trend_rule_candidates,
)
from cotton_factor.research_workbench.trend_turning_points import (
    ResearchTrendTurningPointResult,
    build_cf_trend_turning_point_analysis,
)
from cotton_factor.research_workbench.validated_research_brief import (
    ResearchValidatedBriefResult,
    build_cf_validated_research_brief,
)
from cotton_factor.research_workbench.validation_pack import (
    PostR22ValidationPackResult,
    build_cf_post_r22_validation_pack,
)
from cotton_factor.research_workbench.weekly_research_audit import (
    ResearchWeeklyAuditResult,
    WeeklyResearchAuditWarningRecord,
    build_cf_weekly_research_audit,
)

__all__ = [
    "ResearchCoreQuoteBuildResult",
    "ResearchCarryBuildResult",
    "ResearchChainOiStructureResult",
    "ResearchOiRollWindowResult",
    "ResearchCurrentWatchWindowResult",
    "ResearchRawFileRecord",
    "ResearchRawIngestResult",
    "ResearchStructureFactorsBuildResult",
    "ResearchModeConfig",
    "ResearchSingleFactorBacktestResult",
    "ResearchSignalMatrixResult",
    "ResearchSignalMatrixValidationResult",
    "ResearchSignalThresholdResult",
    "ResearchStageDecisionPackResult",
    "CfDataQualityResult",
    "ContractRuleReviewResult",
    "ContractRuleReviewRow",
    "CostSensitivitySummaryRow",
    "CostSensitivityWarningRecord",
    "DailyBriefWarningRecord",
    "DailyOperationAuditWarningRecord",
    "DataQualityIssue",
    "DataContinuityDatasetAudit",
    "DataContinuityWarningRecord",
    "EventThresholdReviewWarningRecord",
    "EventThresholdSensitivityWarningRecord",
    "ResearchMappingBuildResult",
    "ResearchMemberPositionIngestResult",
    "ResearchMemberPositionResult",
    "ResearchContinuousBuildResult",
    "ResearchCostSensitivityResult",
    "ResearchDailyBriefResult",
    "ResearchDailyOperationAuditResult",
    "ResearchDataContinuityAuditResult",
    "ResearchDualPriceStateResult",
    "FactorOutputArtifactContract",
    "FactorOutputContractResult",
    "FactorWarningRecord",
    "ForwardReturnWarningRecord",
    "FuturesOptionDivergenceWarningRecord",
    "FundamentalDataContractWarningRecord",
    "FundamentalDatasetContract",
    "FundamentalContextWarningRecord",
    "FundamentalObservationDatasetSummary",
    "FundamentalObservationWarningRecord",
    "HistoricalEventExplanationWarningRecord",
    "HistoricalEvidenceWarningRecord",
    "MultifactorDiagnosticWarningRecord",
    "ResearchFactorDiagnosticsBuildResult",
    "ResearchForwardReturnsBuildResult",
    "ResearchFuturesOptionDivergenceResult",
    "ResearchFundamentalDataContractResult",
    "ResearchFundamentalContextResult",
    "ResearchFundamentalObservationResult",
    "ResearchHistoricalEventExplanationResult",
    "ResearchHistoricalEvidenceResult",
    "ResearchEventLifecycleResult",
    "ResearchStateTransitionCompetingRiskResult",
    "ResearchEventThresholdReviewResult",
    "ResearchEventThresholdSensitivityResult",
    "ResearchMultifactorDiagnosticsResult",
    "ResearchMomentumBuildResult",
    "ResearchOptionDataContractResult",
    "ResearchOptionCoreIngestResult",
    "ResearchOptionFactorProxyResult",
    "ResearchOptionStructureResult",
    "ResearchOptionStrikePositionResult",
    "ResearchOptionVolatilityTermStructureResult",
    "ResearchDailyPipelineResult",
    "ResearchProductRegistryResult",
    "ResearchTrendTurningPointResult",
    "ResearchTrendContinuityBoardResult",
    "ResearchTrendPhaseEventResult",
    "ResearchTrendPhaseValidationResult",
    "ResearchTrendPhaseV2Result",
    "ResearchTrendQualityCalibrationResult",
    "ResearchTrendRuleCandidateResult",
    "ResearchValidatedBriefResult",
    "OfficialHistoryConnectResult",
    "OfficialHistoryYearRecord",
    "OfficialDailyFileRecord",
    "OfficialDailyFilesFetchResult",
    "OfficialMemberPositionFetchResult",
    "OfficialMemberPositionHistoryFetchResult",
    "MemberPositionSourceRecord",
    "OptionDataContractWarningRecord",
    "OptionFactorProxyWarningRecord",
    "OptionQualityRow",
    "OptionSourceRecord",
    "LatestSignalBriefResult",
    "LatestSignalWarningRecord",
    "TrendPhaseValidationWarningRecord",
    "TrendContinuityWarningRecord",
    "TrendPhaseEventWarningRecord",
    "TrendRuleCandidateWarningRecord",
    "TrendQualityCalibrationWarningRecord",
    "WeeklyResearchAuditWarningRecord",
    "ResearchExpansionGateResult",
    "ResearchWeeklyAuditResult",
    "ResearchPipelineStep",
    "ResearchPublishPackResult",
    "ResearchPipelineReplayResult",
    "RESEARCH_FRAMEWORK_VERSION",
    "ResearchReplayArtifact",
    "ResearchReplayCheck",
    "ExpansionGateRequirement",
    "SingleFactorBacktestWarningRecord",
    "SignalMatrixWarningRecord",
    "SignalMatrixValidationWarningRecord",
    "SignalThresholdResearchWarningRecord",
    "FuturesOptionDivergencePlaybookWarningRecord",
    "ResearchFuturesOptionDivergencePlaybookResult",
    "PostR22ValidationPackResult",
    "TrendPhaseResult",
    "build_cf_chain_oi_structure",
    "build_cf_oi_roll_window_research",
    "build_cf_contract_rule_review",
    "build_cf_carry_factor",
    "build_cf_cost_sensitivity",
    "build_cf_daily_brief",
    "build_cf_daily_operation_audit",
    "build_cf_current_watch_window",
    "build_cf_data_continuity_audit",
    "build_cf_dual_price_state",
    "build_cf_factor_diagnostics",
    "build_cf_factor_output_contract",
    "build_cf_forward_returns",
    "build_cf_futures_option_divergence_research",
    "build_cf_futures_option_divergence_playbook",
    "build_cf_fundamental_data_contract",
    "build_cf_fundamental_context",
    "build_cf_fundamental_observation",
    "build_cf_historical_event_explanation",
    "build_cf_historical_evidence_pack",
    "build_cf_event_lifecycle_research",
    "build_cf_state_transition_competing_risk_research",
    "build_cf_latest_signal_brief",
    "build_cf_member_position_research",
    "build_research_framework_context",
    "build_cf_option_data_contract",
    "build_cf_option_factor_proxy",
    "build_cf_option_structure_research",
    "build_cf_option_strike_position_research",
    "build_cf_option_volatility_term_structure_research",
    "build_cf_post_r22_validation_pack",
    "build_cf_product_research_registry",
    "build_cf_publish_pack",
    "connect_cf_official_history",
    "connect_cf_option_history",
    "connect_cf_member_position_history",
    "fetch_cf_official_daily_files",
    "fetch_cf_official_member_position",
    "fetch_cf_official_member_position_history",
    "build_cf_daily_research_pipeline",
    "build_cf_event_threshold_review_ledger",
    "build_cf_event_threshold_sensitivity",
    "build_cf_expansion_gate",
    "build_cf_momentum_factor",
    "build_cf_multifactor_diagnostics",
    "build_cf_research_continuous",
    "build_cf_research_mapping",
    "build_cf_single_factor_backtest",
    "build_cf_signal_matrix",
    "build_cf_signal_matrix_validation",
    "build_cf_signal_threshold_research",
    "build_cf_stage_decision_pack",
    "build_cf_structure_factors",
    "build_cf_trend_turning_point_analysis",
    "build_cf_trend_continuity_board",
    "build_cf_trend_phase_events",
    "build_cf_trend_phase_validation",
    "build_cf_trend_phase_v2",
    "build_cf_trend_quality_calibration",
    "build_cf_trend_rule_candidates",
    "build_cf_validated_research_brief",
    "build_cf_weekly_research_audit",
    "check_cf_data_quality",
    "classify_cf_trend_phase",
    "default_recent_history_years",
    "display_threshold_status",
    "factor_output_artifact_contracts",
    "ingest_cf_raw",
    "list_cf_raw_manifest",
    "load_research_mode_config",
    "normalize_cf_core_quotes",
    "official_history_url",
    "official_daily_date_key",
    "official_daily_file_url",
    "official_daily_file_urls",
    "official_member_position_url",
    "official_member_position_urls",
    "research_framework_markdown_lines",
    "replay_cf_research_pipeline_outputs",
    "validated_stance_label",
    "validated_stance_title_text",
]
