"""Research workbench helpers."""

from cotton_factor.research_workbench.carry import (
    ResearchCarryBuildResult,
    build_cf_carry_factor,
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
from cotton_factor.research_workbench.data_quality import (
    CfDataQualityResult,
    DataQualityIssue,
    check_cf_data_quality,
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
from cotton_factor.research_workbench.momentum import (
    ResearchMomentumBuildResult,
    build_cf_momentum_factor,
)
from cotton_factor.research_workbench.multifactor_diagnostics import (
    MultifactorDiagnosticWarningRecord,
    ResearchMultifactorDiagnosticsResult,
    build_cf_multifactor_diagnostics,
)
from cotton_factor.research_workbench.official_history import (
    OfficialHistoryConnectResult,
    OfficialHistoryYearRecord,
    connect_cf_official_history,
    default_recent_history_years,
    official_history_url,
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
    "ResearchRawFileRecord",
    "ResearchRawIngestResult",
    "ResearchStructureFactorsBuildResult",
    "ResearchModeConfig",
    "ResearchSingleFactorBacktestResult",
    "ResearchSignalMatrixResult",
    "ResearchSignalMatrixValidationResult",
    "ResearchSignalThresholdResult",
    "CfDataQualityResult",
    "ContractRuleReviewResult",
    "ContractRuleReviewRow",
    "CostSensitivitySummaryRow",
    "CostSensitivityWarningRecord",
    "DailyBriefWarningRecord",
    "DailyOperationAuditWarningRecord",
    "DataQualityIssue",
    "EventThresholdSensitivityWarningRecord",
    "ResearchMappingBuildResult",
    "ResearchContinuousBuildResult",
    "ResearchCostSensitivityResult",
    "ResearchDailyBriefResult",
    "ResearchDailyOperationAuditResult",
    "FactorOutputArtifactContract",
    "FactorOutputContractResult",
    "FactorWarningRecord",
    "ForwardReturnWarningRecord",
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
    "ResearchFundamentalDataContractResult",
    "ResearchFundamentalContextResult",
    "ResearchFundamentalObservationResult",
    "ResearchHistoricalEventExplanationResult",
    "ResearchHistoricalEvidenceResult",
    "ResearchEventThresholdSensitivityResult",
    "ResearchMultifactorDiagnosticsResult",
    "ResearchMomentumBuildResult",
    "ResearchOptionDataContractResult",
    "ResearchOptionCoreIngestResult",
    "ResearchOptionFactorProxyResult",
    "ResearchDailyPipelineResult",
    "ResearchProductRegistryResult",
    "ResearchTrendTurningPointResult",
    "ResearchTrendContinuityBoardResult",
    "ResearchTrendPhaseEventResult",
    "ResearchTrendPhaseValidationResult",
    "ResearchTrendQualityCalibrationResult",
    "ResearchTrendRuleCandidateResult",
    "ResearchValidatedBriefResult",
    "OfficialHistoryConnectResult",
    "OfficialHistoryYearRecord",
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
    "ResearchReplayArtifact",
    "ResearchReplayCheck",
    "ExpansionGateRequirement",
    "SingleFactorBacktestWarningRecord",
    "SignalMatrixWarningRecord",
    "SignalMatrixValidationWarningRecord",
    "SignalThresholdResearchWarningRecord",
    "PostR22ValidationPackResult",
    "TrendPhaseResult",
    "build_cf_contract_rule_review",
    "build_cf_carry_factor",
    "build_cf_cost_sensitivity",
    "build_cf_daily_brief",
    "build_cf_daily_operation_audit",
    "build_cf_factor_diagnostics",
    "build_cf_factor_output_contract",
    "build_cf_forward_returns",
    "build_cf_fundamental_data_contract",
    "build_cf_fundamental_context",
    "build_cf_fundamental_observation",
    "build_cf_historical_event_explanation",
    "build_cf_historical_evidence_pack",
    "build_cf_latest_signal_brief",
    "build_cf_option_data_contract",
    "build_cf_option_factor_proxy",
    "build_cf_post_r22_validation_pack",
    "build_cf_product_research_registry",
    "build_cf_publish_pack",
    "connect_cf_official_history",
    "connect_cf_option_history",
    "build_cf_daily_research_pipeline",
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
    "build_cf_structure_factors",
    "build_cf_trend_turning_point_analysis",
    "build_cf_trend_continuity_board",
    "build_cf_trend_phase_events",
    "build_cf_trend_phase_validation",
    "build_cf_trend_quality_calibration",
    "build_cf_trend_rule_candidates",
    "build_cf_validated_research_brief",
    "build_cf_weekly_research_audit",
    "check_cf_data_quality",
    "classify_cf_trend_phase",
    "default_recent_history_years",
    "factor_output_artifact_contracts",
    "ingest_cf_raw",
    "list_cf_raw_manifest",
    "load_research_mode_config",
    "normalize_cf_core_quotes",
    "official_history_url",
    "replay_cf_research_pipeline_outputs",
]
