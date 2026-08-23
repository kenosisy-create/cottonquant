from __future__ import annotations

import subprocess
from pathlib import Path


def test_update_cf_latest_research_is_valid_windows_powershell() -> None:
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "$errors=$null; "
                "[System.Management.Automation.Language.Parser]::ParseFile("
                "'scripts\\update_cf_latest_research.ps1', [ref]$null, [ref]$errors) "
                "| Out-Null; if ($errors.Count -gt 0) { "
                "$errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
            ),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_update_cf_latest_research_has_weekly_pack_contract() -> None:
    script = Path("scripts/update_cf_latest_research.ps1").read_text(encoding="utf-8")

    assert "[switch]$RunWeeklyResearchPack" in script
    assert "$runHistoricalEvidenceEffective" in script
    assert "$runEventExplanationEffective" in script
    assert "$runEventThresholdSensitivityEffective" in script
    assert "$runFuturesOptionDivergenceEffective" in script
    assert "$runFuturesOptionPlaybookEffective" in script
    assert "$runMemberPositionResearchEffective" in script
    assert "$runOptionStrikePositionResearchEffective" in script
    assert "$runValidatedBriefEffective" in script
    assert "$runPublishPackEffective" in script
    assert "[switch]$RunDailyOperationAudit" in script
    assert "$runDailyOperationAuditEffective" in script
    assert "$runPublishPackEffective = $RunPublishPack.IsPresent" in script
    assert "$runWeeklyManifestEffective = $RunWeeklyResearchPack.IsPresent" in script
    assert "$RunPublishPack.IsPresent -or $RunWeeklyResearchPack.IsPresent" not in script
    assert "[switch]$SkipStateUpgradePack" in script
    assert "build-cf-dual-price-state" in script
    assert "build-cf-chain-oi-structure" in script
    assert "build-cf-option-structure-research" in script
    assert "build-cf-trend-phase-v2" in script
    assert "build-cf-current-watch-window" in script
    assert "[switch]$RunTrendForwardLedger" in script
    assert "[switch]$RunForwardEvidenceWeekly" in script
    assert "$runTrendForwardLedgerEffective" in script
    assert "$runForwardEvidenceWeeklyEffective" in script
    assert "[switch]$RunFundamentalTrendIncremental" in script
    assert "$runFundamentalTrendIncrementalEffective" in script
    assert "[switch]$RunTrendConfirmationTiming" in script
    assert "$runTrendConfirmationTimingEffective" in script
    assert "[switch]$RunOptionMaturityConfirmation" in script
    assert "$runOptionMaturityConfirmationEffective" in script
    assert "build-cf-symmetric-trend-research" in script
    assert "build-cf-fundamental-trend-incremental-research" in script
    assert "build-cf-trend-confirmation-timing-research" in script
    assert "build-cf-option-maturity-confirmation-research" in script
    assert "build-cf-trend-candidate-forward-ledger" in script
    assert "build-cf-forward-evidence-weekly" in script
    assert '--continuous-price-path "$($strategyInput.continuous_price_path)"' in script
    assert script.index("strategy prepare-inputs") < script.index(
        "build-cf-symmetric-trend-research"
    )
    assert "--current-watch-window-json-path" in script
    assert "--state-transition-json-path" in script
    assert "--option-volatility-json-path" in script
    assert "state_transition_competing_risk.json" in script
    assert "option_volatility.json" in script
    option_fallback = (
        '$effectiveOptionFactorPath = Get-LatestResearchPath -Directory '
        '"data\\research\\CF\\option_factors"'
    )
    assert script.index(option_fallback) < script.index("$signalMatrixArgs = @(")

    assert "--fundamental-context-path" in script
    assert "--event-detail-path" in script
    assert "build-cf-event-threshold-sensitivity" in script
    assert "--event-threshold-summary-path" in script
    assert "[switch]$RunFuturesOptionDivergence" in script
    assert "build-cf-futures-option-divergence-research" in script
    assert "[switch]$RunFuturesOptionPlaybook" in script
    assert "build-cf-futures-option-divergence-playbook" in script
    assert "--futures-option-divergence-json-path" in script
    assert "--futures-option-playbook-json-path" in script
    assert "[switch]$RunMemberPositionResearch" in script
    assert "fetch-cf-official-member-position" in script
    assert "connect-cf-member-position-history" in script
    assert "build-cf-member-position-research" in script
    assert "member_position_research" in script
    assert "member_position_is_member_level_not_customer_identity" in script
    assert "[switch]$RunOptionStrikePositionResearch" in script
    assert "[switch]$RunDynamicOptionWallResearch" in script
    assert "$runDynamicOptionWallResearchEffective" in script
    assert "[switch]$RunOptionWallFactorV2" in script
    assert "$runOptionWallFactorV2Effective" in script
    assert "[switch]$RunFuturesOptionEventPath" in script
    assert "$runFuturesOptionEventPathEffective" in script
    assert "[switch]$RunFuturesOptionRegimeInteraction" in script
    assert "$runFuturesOptionRegimeInteractionEffective" in script
    assert "build-cf-option-strike-position-research" in script
    assert "build-cf-futures-option-dynamic-wall-research" in script
    assert "build-cf-futures-option-wall-factor-v2" in script
    assert "build-cf-futures-option-event-path-research" in script
    assert "build-cf-futures-option-regime-interaction-research" in script
    assert "futures_option_dynamic_wall" in script
    assert "futures_option_wall_factor_v2" in script
    assert "futures_option_event_path" in script
    assert "futures_option_regime_interaction" in script
    assert "option_strike_position_research" in script
    assert "option_open_interest_long_short_ownership_unknown" in script
    assert "--fundamental-observation-json-path" in script
    assert script.count('Test-Path "reports\\research\\futures_option_divergence"') >= 2
    assert script.count('Pattern "CF_*_futures_option_divergence.json"') >= 2

    assert "cf_weekly_research_run_manifest" in script
    assert "R58_cf_weekly_research_run_v2" in script
    assert "build-cf-weekly-research-audit" in script
    assert "reports\\research\\weekly_audit" in script
    assert "runs\\weekly\\CF" in script
    assert "latest_signal_only_contains_forward_return_validation" in script
    assert "historical_forward_returns_are_validation_labels" in script
    assert "fundamental_signal_status" in script
    assert "trend_confirmation_timing" in script
    assert "option_maturity_confirmation" in script
    assert "futures_option_divergence_interpretation" in script
    assert "futures_option_playbook_interpretation" in script
    assert "event_path_fixed_checkpoint_interpretation" in script
    assert "event_path_purged_loo_interpretation" in script
    assert "historical_release_date_backfill" in script
    assert "fundamental_incremental_sample_size" in script


def test_update_cf_latest_research_has_official_daily_download_contract() -> None:
    script = Path("scripts/update_cf_latest_research.ps1").read_text(encoding="utf-8")

    assert "[switch]$DownloadOfficialDaily" in script
    assert "[string]$DownloadDate" in script
    assert "[string]$OptionSourceDir" in script
    assert "fetch-cf-official-daily-files" in script
    assert "--futures-source-dir" in script
    assert "--options-source-dir" in script
    assert "FutureDataDailyCF.xlsx" in script
    assert "connect-cf-option-history" in script
    assert "$runOptionCoreIngestEffective" in script
    assert "$runOptionFactorProxyEffective" in script
    option_daily_refresh = (
        "($DownloadOfficialDaily.IsPresent -and -not "
        "$SkipOptionDailyDownload.IsPresent)"
    )
    assert option_daily_refresh in script
    assert '$optionFactorArgs += @("--incremental")' in script
    assert "Option factor build mode" in script
    assert "CF daily update elapsed seconds" in script
    assert "build-cf-data-continuity-audit" in script
    assert "[switch]$RemoveDownloadedDailyAfterIngest" in script
    assert "official_daily_cleanup_manifest" in script
    assert "data\\incoming" in script


def test_readme_documents_weekly_pack_command() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "-RunWeeklyResearchPack" in readme
    assert (
        "R41 -> R83 -> R84 -> R55 -> R60 -> R69 -> R71 -> "
        "R93K -> R93L -> R93M -> R93N -> R93O -> R93P -> R56 -> R59"
        in readme
    )
    assert "build-cf-futures-option-wall-factor-v2" in readme
    assert "build-cf-futures-option-event-path-research" in readme
    assert "build-cf-option-maturity-confirmation-research" in readme
    assert "2022-2023 expansion" in readme
    assert "build-cf-option-strike-position-research" in readme
    assert "build-cf-event-threshold-sensitivity" in readme
    assert "build-cf-weekly-research-audit" in readme
    assert "weekly_research_run_manifest.json" in readme
    assert "-RunDailyOperationAudit" in readme
    assert "paused by default" in readme
    assert "final official trading session" in readme


def test_readme_documents_official_daily_download_command() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "fetch-cf-official-daily-files" in readme
    assert "-DownloadOfficialDaily" in readme
    assert "YYYYMMDD" in readme
    assert "FutureDataDailyCF.xlsx" in readme
    assert "OptionDataDaily.xlsx" in readme
    assert "FutureDataHolding.xlsx" in readme
    assert "fetch-cf-official-member-position" in readme
    assert "fetch-cf-official-member-position-history" in readme
    assert "build-cf-data-continuity-audit" in readme
    assert "-RemoveDownloadedDailyAfterIngest" in readme
    assert "-RunTrendForwardLedger" in readme
    assert "build-cf-forward-evidence-weekly" in readme
