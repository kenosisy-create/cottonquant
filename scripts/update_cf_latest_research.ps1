param(
    [int]$Year = (Get-Date).Year,
    [string]$SourceDir = "data\incoming\CF\history",
    [string]$OptionSourceDir = "data\incoming\CF\options\history",
    [string]$MemberPositionSourceDir = "data\incoming\CF\member_positions\history",
    [string]$DownloadDate = (Get-Date -Format yyyy-MM-dd),
    [string]$RunId = "cf_daily_update_$(Get-Date -Format yyyyMMdd_HHmmss)",
    [switch]$DownloadOfficialDaily,
    [switch]$SkipOptionDailyDownload,
    [switch]$OverwriteOfficialDaily,
    [switch]$SkipDataContinuityAudit,
    [switch]$RunDailyOperationAudit,
    [switch]$RemoveDownloadedDailyAfterIngest,
    [switch]$RunResearchWindow,
    [switch]$RunOptionCoreIngest,
    [switch]$RunOptionFactorProxy,
    [switch]$SkipStateUpgradePack,
    [switch]$RunHistoricalEvidence,
    [switch]$RunEventExplanation,
    [switch]$RunEventThresholdSensitivity,
    [switch]$RunFuturesOptionDivergence,
    [switch]$RunFuturesOptionPlaybook,
    [switch]$RunMemberPositionResearch,
    [switch]$RunOptionStrikePositionResearch,
    [switch]$RunValidatedBrief,
    [switch]$RunPublishPack,
    [switch]$RunWeeklyResearchPack,
    [string]$TrendRuleCandidatePath = "",
    [string]$TrendQualityCalibrationManifestPath = "",
    [string]$SignalThresholdResearchPath = "",
    [string]$OptionFactorPath = "",
    [int]$TrendBoardLookbackDays = 20,
    [int]$LookbackTradingDays = 80
)

$ErrorActionPreference = "Stop"
$dailyRunStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot
$env:PYTHONPATH = "src"
$env:PYTHONIOENCODING = "utf-8"

function Get-LatestResearchPath {
    param(
        [string]$Directory,
        [string]$Pattern
    )
    if (-not (Test-Path $Directory)) {
        return ""
    }
    $candidate = Get-ChildItem -Path $Directory -Filter $Pattern -File |
        Sort-Object LastWriteTime, Name |
        Select-Object -Last 1
    if ($null -eq $candidate) {
        return ""
    }
    return $candidate.FullName
}

$fundamentalObservationJsonPath = "data\research\CF\fundamentals\CF_fundamental_observation.json"
$fundamentalContextPath = "data\research\CF\fundamental_context\CF_fundamental_context_daily.parquet"
$runHistoricalEvidenceEffective = $RunHistoricalEvidence.IsPresent -or $RunWeeklyResearchPack.IsPresent
$runEventExplanationEffective = $RunEventExplanation.IsPresent -or $RunWeeklyResearchPack.IsPresent
$runEventThresholdSensitivityEffective = $RunEventThresholdSensitivity.IsPresent -or $RunWeeklyResearchPack.IsPresent
$runFuturesOptionDivergenceEffective = $RunFuturesOptionDivergence.IsPresent -or $RunWeeklyResearchPack.IsPresent
$runFuturesOptionPlaybookEffective = $RunFuturesOptionPlaybook.IsPresent -or $RunWeeklyResearchPack.IsPresent
$runMemberPositionResearchEffective = $RunMemberPositionResearch.IsPresent -or $RunWeeklyResearchPack.IsPresent
$runOptionStrikePositionResearchEffective = $RunOptionStrikePositionResearch.IsPresent -or $RunWeeklyResearchPack.IsPresent
$runValidatedBriefEffective = $RunValidatedBrief.IsPresent -or $RunWeeklyResearchPack.IsPresent
$runPublishPackEffective = $RunPublishPack.IsPresent
$runDailyOperationAuditEffective = $RunDailyOperationAudit.IsPresent -or $RunWeeklyResearchPack.IsPresent
$runWeeklyManifestEffective = $RunWeeklyResearchPack.IsPresent
$runOptionCoreIngestEffective = (
    $RunOptionCoreIngest.IsPresent -or
    ($DownloadOfficialDaily.IsPresent -and -not $SkipOptionDailyDownload.IsPresent)
)
$runOptionFactorProxyEffective = (
    $RunOptionFactorProxy.IsPresent -or
    ($DownloadOfficialDaily.IsPresent -and -not $SkipOptionDailyDownload.IsPresent)
)
$runStateUpgradeEffective = -not $SkipStateUpgradePack.IsPresent
$effectiveSourceDir = $SourceDir
$effectiveOptionSourceDir = $OptionSourceDir
$effectiveOptionFactorPath = $OptionFactorPath

if ($DownloadOfficialDaily.IsPresent) {
    $dailyFetchArgs = @(
        "-3.12",
        "-m",
        "cotton_factor.cli.main",
        "research",
        "fetch-cf-official-daily-files",
        "--date",
        "$DownloadDate",
        "--futures-source-dir",
        "$SourceDir",
        "--options-source-dir",
        "$OptionSourceDir",
        "--report-output-dir",
        "reports\research\official_daily_files",
        "--run-id",
        "$RunId"
    )
    if ($SkipOptionDailyDownload.IsPresent) {
        $dailyFetchArgs += @("--skip-options")
    }
    if ($OverwriteOfficialDaily.IsPresent) {
        $dailyFetchArgs += @("--overwrite")
    }
    $officialDailyFetchJson = & py @dailyFetchArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CF official daily file download failed."
    }
    $officialDailyFetch = $officialDailyFetchJson | ConvertFrom-Json
    $Year = [int]$officialDailyFetch.trade_date.Substring(0, 4)
    $effectiveSourceDir = "$($officialDailyFetch.futures_connect_source_dir)"
    $effectiveOptionSourceDir = "$($officialDailyFetch.options_connect_source_dir)"
    Write-Host "Official daily date format: $($officialDailyFetch.date_format)"
    Write-Host "Official futures URL: $($officialDailyFetch.futures_url)"
    Write-Host "Official options URL: $($officialDailyFetch.options_url)"
    Write-Host "Official futures file: $($officialDailyFetch.futures_path)"
    if (-not $SkipOptionDailyDownload.IsPresent) {
        Write-Host "Official options file: $($officialDailyFetch.options_path)"
    }
}

$sourceRoot = Resolve-Path $effectiveSourceDir
$candidateNames = @(
    "FutureDataDailyCF.xlsx",
    "FutureDataDailyCF$Year.xlsx",
    "CFFUTURES$Year.xlsx",
    "CFFUTURES$Year.xls",
    "ALLFUTURES$Year.zip"
)
$sourceFiles = @()
foreach ($candidateName in $candidateNames) {
    $candidatePath = Join-Path $sourceRoot $candidateName
    if (Test-Path $candidatePath) {
        $sourceFiles += (Resolve-Path $candidatePath)
    }
}
if ($sourceFiles.Count -eq 0) {
    throw "No CF history file found for $Year under $sourceRoot."
}

Write-Host "Found source files: $($sourceFiles -join ', ')"

$connectArgs = @(
    "-3.12",
    "-m",
    "cotton_factor.cli.main",
    "research",
    "connect-cf-official-history",
    "--years",
    "$Year",
    "--source-dir",
    "$effectiveSourceDir",
    "--report-output-dir",
    "reports\research\official_history_$Year",
    "--run-id",
    "$RunId"
)
& py @connectArgs
if ($LASTEXITCODE -ne 0) {
    throw "CF official history connection failed."
}

$runResearch = if ($RunResearchWindow.IsPresent) { "true" } else { "false" }
$metadataJson = @'
from __future__ import annotations

import csv
import json
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

year = int(sys.argv[1])
run_id = sys.argv[2]
run_research = sys.argv[3].lower() == "true"
lookback_trading_days = int(sys.argv[4])

core_path = Path("data/core/CF/core_quote_daily.parquet")
if not core_path.exists():
    raise SystemExit(f"core quote table not found: {core_path}")

frame = pd.read_parquet(core_path)
frame["_trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
year_frame = frame.loc[frame["_trade_date"].map(lambda value: value.year == year)].copy()
if year_frame.empty:
    raise SystemExit(f"no CF core rows found for {year}")

trade_dates = sorted(set(year_frame["_trade_date"]))
max_trade_date = trade_dates[-1]

calendar_path = Path("configs/calendars") / f"CZCE_{year}_OFFICIAL.csv"
calendar_path.parent.mkdir(parents=True, exist_ok=True)
trading_date_set = set(trade_dates)
current = date(year, 1, 1)
last = date(year, 12, 31)
with calendar_path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(
        handle,
        fieldnames=[
            "exchange",
            "trade_date",
            "is_trading_day",
            "calendar_version",
            "source_snapshot_id",
        ],
    )
    writer.writeheader()
    while current <= last:
        writer.writerow(
            {
                "exchange": "CZCE",
                "trade_date": current.isoformat(),
                "is_trading_day": "true" if current in trading_date_set else "false",
                "calendar_version": f"CZCE_OFFICIAL_{year}_CF_HISTORY_TO_DATE",
                "source_snapshot_id": f"czce_{year}_official_cf_history_to_date",
            }
        )
        current += timedelta(days=1)

metadata = {
    "year": year,
    "run_id": run_id,
    "core_path": str(core_path),
    "calendar_path": str(calendar_path),
    "max_trade_date": max_trade_date.isoformat(),
    "row_count": int(len(year_frame)),
    "trading_day_count": len(trade_dates),
}

if run_research:
    # Latest date has no future-return labels, so choose a date at least 5 trading days back.
    if len(trade_dates) < 6:
        raise SystemExit("not enough trading dates to run a 1/3/5 horizon research window")
    analysis_index = len(trade_dates) - 6
    analysis_date = trade_dates[analysis_index]
    start_index = max(0, analysis_index - lookback_trading_days + 1)
    start_date = trade_dates[start_index]
    end_date = trade_dates[-2]
    run_root = Path("runs/codex") / run_id
    input_dir = run_root / "incoming" / "CF" / analysis_date.isoformat()
    input_dir.mkdir(parents=True, exist_ok=True)
    input_path = input_dir / "cf_daily.csv"

    day_frame = year_frame.loc[year_frame["_trade_date"] == analysis_date].copy()
    day_frame = day_frame.rename(columns={"contract_code": "contract_id"})
    export_columns = [
        "trade_date",
        "exchange",
        "product_code",
        "contract_id",
        "open",
        "high",
        "low",
        "close",
        "settle",
        "pre_settle",
        "volume",
        "open_interest",
        "turnover",
        "quote_status",
    ]
    day_frame[export_columns].to_csv(input_path, index=False, encoding="utf-8")

    run_core_path = run_root / "core" / "CF" / "core_quote_daily.parquet"
    run_core_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(core_path, run_core_path)

    metadata.update(
        {
            "analysis_date": analysis_date.isoformat(),
            "window_start": start_date.isoformat(),
            "window_end": end_date.isoformat(),
            "run_root": str(run_root),
            "daily_input_path": str(input_path),
            "run_core_path": str(run_core_path),
        }
    )

print(json.dumps(metadata, ensure_ascii=False, sort_keys=True))
'@ | py -3.12 - "$Year" "$RunId" "$runResearch" "$LookbackTradingDays"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to refresh calendar or prepare research input."
}
$metadata = $metadataJson | ConvertFrom-Json

Write-Host "Core data: $($metadata.core_path)"
Write-Host "Latest trade date: $($metadata.max_trade_date)"
Write-Host "Trading days in year: $($metadata.trading_day_count)"
Write-Host "Calendar refreshed: $($metadata.calendar_path)"

if ($runOptionCoreIngestEffective) {
    $optionCoreArgs = @(
        "-3.12",
        "-m",
        "cotton_factor.cli.main",
        "research",
        "connect-cf-option-history",
        "--source-dir",
        "$effectiveOptionSourceDir",
        "--raw-root",
        "data\raw",
        "--core-output-dir",
        "data\core",
        "--core-quote-path",
        "$($metadata.core_path)",
        "--report-output-dir",
        "reports\research\option_core_ingest",
        "--run-id",
        "$RunId"
    )
    $optionCoreJson = & py @optionCoreArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CF option core ingest failed."
    }
    $optionCore = $optionCoreJson | ConvertFrom-Json
    Write-Host "Option core ingest: $($optionCore.markdown_path)"
    Write-Host "Option core status: $($optionCore.status), rows=$($optionCore.core_row_count)"
}

if (-not $SkipDataContinuityAudit.IsPresent) {
    $dataContinuityArgs = @(
        "-3.12",
        "-m",
        "cotton_factor.cli.main",
        "research",
        "build-cf-data-continuity-audit",
        "--date",
        "$($metadata.max_trade_date)",
        "--core-quote-path",
        "$($metadata.core_path)",
        "--calendar-path",
        "$($metadata.calendar_path)",
        "--raw-root",
        "data\raw",
        "--output-root",
        "runs\daily",
        "--run-id",
        "$RunId"
    )
    if ($runOptionCoreIngestEffective) {
        $dataContinuityArgs += @(
            "--option-core-path",
            "data\core\CF\core_option_quote_daily.parquet"
        )
    }
    else {
        $dataContinuityArgs += @("--no-require-options")
    }
    $officialDailyFetchValue = Get-Variable -Name "officialDailyFetch" -ValueOnly -ErrorAction SilentlyContinue
    if ($null -ne $officialDailyFetchValue -and $officialDailyFetchValue.json_path) {
        $dataContinuityArgs += @(
            "--official-daily-fetch-json-path",
            "$($officialDailyFetchValue.json_path)"
        )
    }
    $dataContinuityJson = & py @dataContinuityArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CF data continuity audit failed."
    }
    $dataContinuity = $dataContinuityJson | ConvertFrom-Json
    Write-Host "Data continuity audit: $($dataContinuity.markdown_path)"
    Write-Host "Data continuity status: $($dataContinuity.continuity_status), errors=$($dataContinuity.error_count), warnings=$($dataContinuity.warning_count)"

    if ($RemoveDownloadedDailyAfterIngest.IsPresent) {
        if (-not $dataContinuity.passed) {
            throw "Refusing to remove official daily files because data continuity audit did not pass."
        }
        $incomingRoot = (Resolve-Path -LiteralPath "data\incoming").Path
        $cleanupRecords = @()
        foreach ($downloadPath in $dataContinuity.downloaded_file_paths) {
            if ([string]::IsNullOrWhiteSpace("$downloadPath")) {
                continue
            }
            if (-not (Test-Path -LiteralPath "$downloadPath")) {
                continue
            }
            $resolvedDownloadPath = (Resolve-Path -LiteralPath "$downloadPath").Path
            if (-not $resolvedDownloadPath.StartsWith($incomingRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Refusing to remove file outside data\incoming: $resolvedDownloadPath"
            }
            Remove-Item -LiteralPath $resolvedDownloadPath -Force
            $cleanupRecords += [ordered]@{
                path = "$resolvedDownloadPath"
                action = "removed_after_successful_core_and_raw_retention_audit"
            }
        }
        $cleanupManifestDir = Join-Path -Path "runs\daily\CF" -ChildPath "$($metadata.max_trade_date)"
        New-Item -ItemType Directory -Force -Path $cleanupManifestDir | Out-Null
        $cleanupManifestPath = Join-Path -Path $cleanupManifestDir -ChildPath "official_daily_cleanup_manifest.json"
        [ordered]@{
            report_type = "official_daily_cleanup_manifest"
            rule_version = "R63_official_daily_cleanup_v1"
            generated_at = (Get-Date).ToUniversalTime().ToString("o")
            run_id = "$RunId"
            data_asof = "$($metadata.max_trade_date)"
            data_continuity_audit_json_path = "$($dataContinuity.json_path)"
            removed_files = $cleanupRecords
            protected_roots = @("data\raw", "data\core", "data\research")
        } |
            ConvertTo-Json -Depth 8 |
            Set-Content -Path $cleanupManifestPath -Encoding UTF8
        Write-Host "Official daily cleanup manifest: $cleanupManifestPath"
    }
}

if ($runOptionFactorProxyEffective) {
    $optionFactorStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $optionCoreValue = Get-Variable -Name "optionCore" -ValueOnly -ErrorAction SilentlyContinue
    if ($null -eq $optionCoreValue -or [string]::IsNullOrWhiteSpace("$($optionCoreValue.core_option_quote_path)")) {
        throw "RunOptionFactorProxy requires option core ingest output."
    }
    $optionFactorArgs = @(
        "-3.12",
        "-m",
        "cotton_factor.cli.main",
        "research",
        "build-cf-option-factor-proxy",
        "--option-core-path",
        "$($optionCoreValue.core_option_quote_path)",
        "--core-quote-path",
        "$($metadata.core_path)",
        "--output-dir",
        "data\research\CF\option_factors",
        "--report-output-dir",
        "reports\research\option_factors",
        "--run-id",
        "$RunId"
    )
    if (-not $RunWeeklyResearchPack.IsPresent) {
        $optionFactorArgs += @("--incremental")
    }
    $optionFactorJson = & py @optionFactorArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CF option factor proxy failed."
    }
    $optionFactor = $optionFactorJson | ConvertFrom-Json
    $effectiveOptionFactorPath = "$($optionFactor.factor_parquet_path)"
    Write-Host "Option factor proxy: $($optionFactor.markdown_path)"
    Write-Host "Option factor build mode: $($optionFactor.build_mode), elapsed seconds: $([math]::Round($optionFactorStopwatch.Elapsed.TotalSeconds, 2))"
}

# Reuse the latest option-factor artifact when the daily run does not rebuild it.
if ([string]::IsNullOrWhiteSpace($effectiveOptionFactorPath)) {
    if (Test-Path "data\research\CF\option_factors") {
        $effectiveOptionFactorPath = Get-LatestResearchPath -Directory "data\research\CF\option_factors" -Pattern "CF_*_option_factor_proxy_daily.parquet"
    }
}

$signalMatrixArgs = @(
    "-3.12",
    "-m",
    "cotton_factor.cli.main",
    "research",
    "build-cf-signal-matrix",
    "--end",
    "$($metadata.max_trade_date)",
    "--horizons",
    "1,3,5,10,20,40",
    "--core-quote-path",
    "$($metadata.core_path)",
    "--output-dir",
    "data\research\CF\signal_matrix",
    "--report-output-dir",
    "reports\research\signal_matrix",
    "--run-id",
    "$RunId"
)
if (-not [string]::IsNullOrWhiteSpace($TrendRuleCandidatePath)) {
    $signalMatrixArgs += @(
        "--trend-rule-candidate-path",
        "$TrendRuleCandidatePath"
    )
}
if (-not [string]::IsNullOrWhiteSpace($effectiveOptionFactorPath)) {
    $signalMatrixArgs += @(
        "--option-factor-path",
        "$effectiveOptionFactorPath"
    )
}
$signalMatrixJson = & py @signalMatrixArgs
if ($LASTEXITCODE -ne 0) {
    throw "CF signal matrix failed."
}
$signalMatrix = $signalMatrixJson | ConvertFrom-Json
Write-Host "Signal matrix: $($signalMatrix.markdown_path)"
Write-Host "Signal matrix latest snapshot: $($signalMatrix.latest_snapshot_json_path)"

if ($runStateUpgradeEffective) {
    $dualPriceJson = & py -3.12 -m cotton_factor.cli.main research build-cf-dual-price-state `
        --core-quote-path "$($metadata.core_path)" `
        --output-dir "data\research\CF\dual_price_state" `
        --report-output-dir "reports\research\dual_price_state" `
        --run-id "$RunId"
    if ($LASTEXITCODE -ne 0) {
        throw "CF dual-price state failed."
    }
    $dualPriceState = $dualPriceJson | ConvertFrom-Json
    Write-Host "Dual-price state: $($dualPriceState.markdown_path)"

    $chainOiJson = & py -3.12 -m cotton_factor.cli.main research build-cf-chain-oi-structure `
        --core-quote-path "$($metadata.core_path)" `
        --output-dir "data\research\CF\chain_oi_structure" `
        --report-output-dir "reports\research\chain_oi_structure" `
        --run-id "$RunId"
    if ($LASTEXITCODE -ne 0) {
        throw "CF chain OI structure failed."
    }
    $chainOiStructure = $chainOiJson | ConvertFrom-Json
    Write-Host "Chain OI structure: $($chainOiStructure.markdown_path)"

    if (-not [string]::IsNullOrWhiteSpace($effectiveOptionFactorPath)) {
        $optionStructureJson = & py -3.12 -m cotton_factor.cli.main research build-cf-option-structure-research `
            --option-factor-path "$effectiveOptionFactorPath" `
            --signal-matrix-path "$($signalMatrix.matrix_parquet_path)" `
            --output-dir "data\research\CF\option_structure" `
            --report-output-dir "reports\research\option_structure" `
            --run-id "$RunId"
        if ($LASTEXITCODE -ne 0) {
            throw "CF option structure research failed."
        }
        $optionStructure = $optionStructureJson | ConvertFrom-Json
        Write-Host "Option structure: $($optionStructure.markdown_path)"

        $trendPhaseV2Json = & py -3.12 -m cotton_factor.cli.main research build-cf-trend-phase-v2 `
            --dual-price-path "$($dualPriceState.daily_parquet_path)" `
            --chain-oi-path "$($chainOiStructure.daily_parquet_path)" `
            --option-structure-path "$($optionStructure.daily_parquet_path)" `
            --signal-matrix-path "$($signalMatrix.matrix_parquet_path)" `
            --output-dir "data\research\CF\trend_phase_v2" `
            --report-output-dir "reports\research\trend_phase_v2" `
            --run-id "$RunId"
        if ($LASTEXITCODE -ne 0) {
            throw "CF trend phase v2 failed."
        }
        $trendPhaseV2 = $trendPhaseV2Json | ConvertFrom-Json
        Write-Host "Trend phase v2: $($trendPhaseV2.markdown_path)"
    }
    else {
        Write-Warning "R75-R77 skipped because no option factor proxy path is available."
    }
}

$latestSignalArgs = @(
    "-3.12",
    "-m",
    "cotton_factor.cli.main",
    "research",
    "build-cf-latest-signal-brief",
    "--date",
    "$($metadata.max_trade_date)",
    "--core-quote-path",
    "$($metadata.core_path)",
    "--output-root",
    "runs\daily",
    "--run-id",
    "$RunId",
    "--signal-matrix-path",
    "$($signalMatrix.latest_snapshot_json_path)"
)
if (-not [string]::IsNullOrWhiteSpace($TrendRuleCandidatePath)) {
    $latestSignalArgs += @(
        "--trend-rule-candidate-path",
        "$TrendRuleCandidatePath"
    )
}
if (-not [string]::IsNullOrWhiteSpace($SignalThresholdResearchPath)) {
    $latestSignalArgs += @(
        "--signal-threshold-research-path",
        "$SignalThresholdResearchPath"
    )
}
$latestSignalJson = & py @latestSignalArgs
if ($LASTEXITCODE -ne 0) {
    throw "CF latest signal-only brief failed."
}
$latestSignal = $latestSignalJson | ConvertFrom-Json
Write-Host "Latest signal brief: $($latestSignal.markdown_path)"
if ($latestSignal.trend_rule_context) {
    Write-Host "Trend rule context: $($latestSignal.trend_rule_context.transition_code) $($latestSignal.trend_rule_context.candidate_status)"
}

$trendBoardArgs = @(
    "-3.12",
    "-m",
    "cotton_factor.cli.main",
    "research",
    "build-cf-trend-continuity-board",
    "--date",
    "$($metadata.max_trade_date)",
    "--core-quote-path",
    "$($metadata.core_path)",
    "--output-root",
    "runs\daily",
    "--run-id",
    "$RunId",
    "--lookback-trading-days",
    "$TrendBoardLookbackDays"
)
if (-not [string]::IsNullOrWhiteSpace($TrendRuleCandidatePath)) {
    $trendBoardArgs += @(
        "--trend-rule-candidate-path",
        "$TrendRuleCandidatePath"
    )
}
if (-not [string]::IsNullOrWhiteSpace($TrendQualityCalibrationManifestPath)) {
    $trendBoardArgs += @(
        "--trend-quality-calibration-manifest-path",
        "$TrendQualityCalibrationManifestPath"
    )
}
$trendBoardJson = & py @trendBoardArgs
if ($LASTEXITCODE -ne 0) {
    throw "CF trend continuity board failed."
}
$trendBoard = $trendBoardJson | ConvertFrom-Json
Write-Host "Trend continuity board: $($trendBoard.markdown_path)"
if ($trendBoard.trend_quality_calibration_context -and $trendBoard.trend_quality_calibration_context.context_status -eq "PROVIDED") {
    Write-Host "Trend quality calibration: $($trendBoard.trend_quality_calibration_context.latest_score_context_label) $($trendBoard.trend_quality_calibration_context.alignment_status)"
}

if ($runDailyOperationAuditEffective) {
    $dailyAuditArgs = @(
        "-3.12",
        "-m",
        "cotton_factor.cli.main",
        "research",
        "build-cf-daily-operation-audit",
        "--latest-signal-json-path",
        "$($latestSignal.json_path)",
        "--trend-board-json-path",
        "$($trendBoard.json_path)",
        "--core-quote-path",
        "$($metadata.core_path)",
        "--output-root",
        "runs\daily",
        "--run-id",
        "$RunId"
    )
    $dailyAuditJson = & py @dailyAuditArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CF daily operation audit failed."
    }
    $dailyAudit = $dailyAuditJson | ConvertFrom-Json
    Write-Host "Daily operation audit: $($dailyAudit.markdown_path)"
    Write-Host "Daily operation status: $($dailyAudit.operation_status), warnings=$($dailyAudit.warning_count)"
}
else {
    Write-Host "Daily operation audit: skipped; run it with -RunDailyOperationAudit or -RunWeeklyResearchPack."
}

if ($runHistoricalEvidenceEffective) {
    $historicalEvidenceArgs = @(
        "-3.12",
        "-m",
        "cotton_factor.cli.main",
        "research",
        "build-cf-historical-evidence-pack",
        "--core-quote-path",
        "$($metadata.core_path)",
        "--signal-matrix-path",
        "$($signalMatrix.matrix_parquet_path)",
        "--output-dir",
        "data\research\CF\historical_evidence",
        "--report-output-dir",
        "reports\research\historical_evidence",
        "--run-id",
        "$RunId"
    )
    if (-not [string]::IsNullOrWhiteSpace($SignalThresholdResearchPath)) {
        $historicalEvidenceArgs += @(
            "--threshold-weighting-path",
            "$SignalThresholdResearchPath"
        )
    }
    $historicalEvidenceJson = & py @historicalEvidenceArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CF historical evidence pack failed."
    }
    $historicalEvidence = $historicalEvidenceJson | ConvertFrom-Json
    Write-Host "Historical evidence pack: $($historicalEvidence.markdown_path)"
}

if ($runMemberPositionResearchEffective) {
    # R83 属于周度重研究；只有显式周更下载时才额外拉取会员持仓文件。
    if ($DownloadOfficialDaily.IsPresent) {
        $memberFetchArgs = @(
            "-3.12",
            "-m",
            "cotton_factor.cli.main",
            "research",
            "fetch-cf-official-member-position",
            "--date",
            "$DownloadDate",
            "--source-dir",
            "$MemberPositionSourceDir",
            "--report-output-dir",
            "reports\research\member_position_ingest"
        )
        if ($OverwriteOfficialDaily.IsPresent) {
            $memberFetchArgs += @("--overwrite")
        }
        $memberPositionFetchJson = & py @memberFetchArgs
        if ($LASTEXITCODE -ne 0) {
            throw "CF official member-position download failed."
        }
        $memberPositionFetch = $memberPositionFetchJson | ConvertFrom-Json
        Write-Host "Member-position file: $($memberPositionFetch.output_path)"
    }

    $memberIngestArgs = @(
        "-3.12",
        "-m",
        "cotton_factor.cli.main",
        "research",
        "connect-cf-member-position-history",
        "--source-dir",
        "$MemberPositionSourceDir",
        "--report-output-dir",
        "reports\research\member_position_ingest",
        "--run-id",
        "$($RunId)_member_ingest"
    )
    $memberPositionIngestJson = & py @memberIngestArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CF member-position core ingest failed."
    }
    $memberPositionIngest = $memberPositionIngestJson | ConvertFrom-Json

    if (-not [string]::IsNullOrWhiteSpace("$($memberPositionIngest.core_member_position_path)")) {
        $memberResearchArgs = @(
            "-3.12",
            "-m",
            "cotton_factor.cli.main",
            "research",
            "build-cf-member-position-research",
            "--member-position-path",
            "$($memberPositionIngest.core_member_position_path)",
            "--core-quote-path",
            "$($metadata.core_path)",
            "--output-dir",
            "data\research\CF\member_position",
            "--report-output-dir",
            "reports\research\member_position",
            "--run-id",
            "$($RunId)_member_research"
        )
        $historicalEvidenceValue = Get-Variable -Name "historicalEvidence" -ValueOnly -ErrorAction SilentlyContinue
        if ($null -ne $historicalEvidenceValue -and -not [string]::IsNullOrWhiteSpace("$($historicalEvidenceValue.validation_daily_path)")) {
            $memberResearchArgs += @(
                "--validation-daily-path",
                "$($historicalEvidenceValue.validation_daily_path)"
            )
        }
        $memberPositionResearchJson = & py @memberResearchArgs
        if ($LASTEXITCODE -ne 0) {
            throw "CF member-position research failed."
        }
        $memberPositionResearch = $memberPositionResearchJson | ConvertFrom-Json
        Write-Host "Member-position research: $($memberPositionResearch.markdown_path)"
    }
    else {
        Write-Host "Member-position research skipped: MISSING_MEMBER_POSITION_HISTORY."
    }
}

if ($runOptionStrikePositionResearchEffective) {
    # R84 使用已有 option core；只在周度/显式研究链运行，避免拖慢日更。
    $optionStrikeArgs = @(
        "-3.12",
        "-m",
        "cotton_factor.cli.main",
        "research",
        "build-cf-option-strike-position-research",
        "--option-core-path",
        "data\core\CF\core_option_quote_daily.parquet",
        "--core-quote-path",
        "$($metadata.core_path)",
        "--option-expiry-path",
        "configs\products\CF_OPTION_EXPIRY_OFFICIAL.csv",
        "--output-dir",
        "data\research\CF\option_strike_position",
        "--report-output-dir",
        "reports\research\option_strike_position",
        "--run-id",
        "$($RunId)_option_strike"
    )
    $optionStrikePositionJson = & py @optionStrikeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CF option strike-position research failed."
    }
    $optionStrikePosition = $optionStrikePositionJson | ConvertFrom-Json
    Write-Host "Option strike-position research: $($optionStrikePosition.markdown_path)"
}

if ($runEventExplanationEffective) {
    $eventExplanationArgs = @(
        "-3.12",
        "-m",
        "cotton_factor.cli.main",
        "research",
        "build-cf-historical-event-explanation",
        "--output-dir",
        "data\research\CF\event_explanation",
        "--report-output-dir",
        "reports\research\event_explanation",
        "--run-id",
        "$RunId"
    )
    if (Test-Path $fundamentalContextPath) {
        $eventExplanationArgs += @(
            "--fundamental-context-path",
            "$fundamentalContextPath"
        )
    }
    $eventExplanationJson = & py @eventExplanationArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CF historical event explanation failed."
    }
    $eventExplanation = $eventExplanationJson | ConvertFrom-Json
    Write-Host "Historical event explanation: $($eventExplanation.markdown_path)"
}

if ($runEventThresholdSensitivityEffective) {
    $eventThresholdArgs = @(
        "-3.12",
        "-m",
        "cotton_factor.cli.main",
        "research",
        "build-cf-event-threshold-sensitivity",
        "--output-dir",
        "data\research\CF\event_threshold_sensitivity",
        "--report-output-dir",
        "reports\research\event_threshold_sensitivity",
        "--run-id",
        "$RunId",
        "--primary-horizon",
        "20",
        "--horizons",
        "1,3,5,10,20",
        "--threshold-quantiles",
        "0.90,0.95,0.975"
    )
    $eventExplanationValue = Get-Variable -Name "eventExplanation" -ValueOnly -ErrorAction SilentlyContinue
    if ($null -ne $eventExplanationValue -and $eventExplanationValue.event_parquet_path) {
        $eventThresholdArgs += @(
            "--event-path",
            "$($eventExplanationValue.event_parquet_path)"
        )
    }
    $eventThresholdSensitivityJson = & py @eventThresholdArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CF event threshold sensitivity failed."
    }
    $eventThresholdSensitivity = $eventThresholdSensitivityJson | ConvertFrom-Json
    Write-Host "Event threshold sensitivity: $($eventThresholdSensitivity.markdown_path)"
}

$trendPhaseV2Value = Get-Variable -Name "trendPhaseV2" -ValueOnly -ErrorAction SilentlyContinue
if ($runStateUpgradeEffective -and $null -ne $trendPhaseV2Value) {
    $watchWindowArgs = @(
        "-3.12",
        "-m",
        "cotton_factor.cli.main",
        "research",
        "build-cf-current-watch-window",
        "--latest-signal-json-path",
        "$($latestSignal.json_path)",
        "--dual-price-path",
        "$($dualPriceState.daily_parquet_path)",
        "--chain-oi-path",
        "$($chainOiStructure.daily_parquet_path)",
        "--option-structure-path",
        "$($optionStructure.daily_parquet_path)",
        "--trend-phase-v2-path",
        "$($trendPhaseV2.daily_parquet_path)",
        "--core-quote-path",
        "$($metadata.core_path)",
        "--output-dir",
        "data\research\CF\current_watch_window",
        "--report-output-dir",
        "reports\research\current_watch_window",
        "--daily-output-root",
        "runs\daily",
        "--run-id",
        "$RunId"
    )
    $latestPlaybookJsonPath = Get-LatestResearchPath `
        -Directory "reports\research\futures_option_divergence_playbook" `
        -Pattern "CF_*_futures_option_playbook.json"
    if (-not [string]::IsNullOrWhiteSpace($latestPlaybookJsonPath)) {
        $watchWindowArgs += @("--playbook-json-path", "$latestPlaybookJsonPath")
    }
    $watchWindowJson = & py @watchWindowArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CF current watch window failed."
    }
    $currentWatchWindow = $watchWindowJson | ConvertFrom-Json
    Write-Host "Current watch window: $($currentWatchWindow.markdown_path)"
}

if ($runFuturesOptionDivergenceEffective) {
    $signalMatrixValidationPath = ""
    $historicalEvidenceValue = Get-Variable -Name "historicalEvidence" -ValueOnly -ErrorAction SilentlyContinue
    if ($null -ne $historicalEvidenceValue -and $historicalEvidenceValue.validation_daily_path) {
        $signalMatrixValidationPath = "$($historicalEvidenceValue.validation_daily_path)"
    }
    if ([string]::IsNullOrWhiteSpace($signalMatrixValidationPath)) {
        $signalMatrixValidationPath = Get-LatestResearchPath `
            -Directory "data\research\CF\signal_matrix_validation" `
            -Pattern "CF_*_signal_matrix_validation_daily.parquet"
    }
    if ([string]::IsNullOrWhiteSpace($signalMatrixValidationPath)) {
        $signalValidationArgs = @(
            "-3.12",
            "-m",
            "cotton_factor.cli.main",
            "research",
            "build-cf-signal-matrix-validation",
            "--signal-matrix-path",
            "$($signalMatrix.matrix_parquet_path)",
            "--core-quote-path",
            "$($metadata.core_path)",
            "--output-dir",
            "data\research\CF\signal_matrix_validation",
            "--report-output-dir",
            "reports\research\signal_matrix_validation",
            "--run-id",
            "$RunId"
        )
        $signalMatrixValidationJson = & py @signalValidationArgs
        if ($LASTEXITCODE -ne 0) {
            throw "CF signal matrix validation failed for futures-option divergence."
        }
        $signalMatrixValidation = $signalMatrixValidationJson | ConvertFrom-Json
        $signalMatrixValidationPath = "$($signalMatrixValidation.daily_parquet_path)"
        Write-Host "Signal matrix validation: $($signalMatrixValidation.markdown_path)"
    }

    $eventLifecycleTbmPath = Get-LatestResearchPath `
        -Directory "data\research\CF\event_lifecycle" `
        -Pattern "CF_*_event_lifecycle_tbm_labels.parquet"

    $futuresOptionDivergenceArgs = @(
        "-3.12",
        "-m",
        "cotton_factor.cli.main",
        "research",
        "build-cf-futures-option-divergence-research",
        "--signal-matrix-validation-path",
        "$signalMatrixValidationPath",
        "--output-dir",
        "data\research\CF\futures_option_divergence",
        "--report-output-dir",
        "reports\research\futures_option_divergence",
        "--run-id",
        "$RunId",
        "--horizons",
        "1,3,5,10,20,40"
    )
    if (-not [string]::IsNullOrWhiteSpace($effectiveOptionFactorPath)) {
        $futuresOptionDivergenceArgs += @(
            "--option-factor-path",
            "$effectiveOptionFactorPath"
        )
    }
    if (-not [string]::IsNullOrWhiteSpace($eventLifecycleTbmPath)) {
        $futuresOptionDivergenceArgs += @(
            "--event-lifecycle-tbm-path",
            "$eventLifecycleTbmPath"
        )
    }
    $futuresOptionDivergenceJson = & py @futuresOptionDivergenceArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CF futures-option divergence research failed."
    }
    $futuresOptionDivergence = $futuresOptionDivergenceJson | ConvertFrom-Json
    Write-Host "Futures-option divergence: $($futuresOptionDivergence.markdown_path)"
}

if ($runFuturesOptionPlaybookEffective) {
    $futuresOptionDivergenceValue = Get-Variable -Name "futuresOptionDivergence" -ValueOnly -ErrorAction SilentlyContinue
    $futuresOptionEventPath = ""
    $futuresOptionNodeSummaryPath = ""
    if ($null -ne $futuresOptionDivergenceValue) {
        if ($futuresOptionDivergenceValue.event_parquet_path) {
            $futuresOptionEventPath = "$($futuresOptionDivergenceValue.event_parquet_path)"
        }
        if ($futuresOptionDivergenceValue.summary_by_node_parquet_path) {
            $futuresOptionNodeSummaryPath = "$($futuresOptionDivergenceValue.summary_by_node_parquet_path)"
        }
    }
    if ([string]::IsNullOrWhiteSpace($futuresOptionEventPath)) {
        $futuresOptionEventPath = Get-LatestResearchPath `
            -Directory "data\research\CF\futures_option_divergence" `
            -Pattern "CF_*_futures_option_divergence_divergence_event_daily.parquet"
    }
    if ([string]::IsNullOrWhiteSpace($futuresOptionNodeSummaryPath)) {
        $futuresOptionNodeSummaryPath = Get-LatestResearchPath `
            -Directory "data\research\CF\futures_option_divergence" `
            -Pattern "CF_*_futures_option_divergence_summary_by_node.parquet"
    }
    if ([string]::IsNullOrWhiteSpace($futuresOptionEventPath) -or [string]::IsNullOrWhiteSpace($futuresOptionNodeSummaryPath)) {
        throw "CF futures-option playbook requires R69 event and node summary outputs."
    }
    $futuresOptionPlaybookArgs = @(
        "-3.12",
        "-m",
        "cotton_factor.cli.main",
        "research",
        "build-cf-futures-option-divergence-playbook",
        "--event-path",
        "$futuresOptionEventPath",
        "--node-summary-path",
        "$futuresOptionNodeSummaryPath",
        "--latest-signal-json-path",
        "$($latestSignal.json_path)",
        "--output-dir",
        "data\research\CF\futures_option_divergence_playbook",
        "--report-output-dir",
        "reports\research\futures_option_divergence_playbook",
        "--run-id",
        "$RunId"
    )
    $futuresOptionPlaybookJson = & py @futuresOptionPlaybookArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CF futures-option divergence playbook failed."
    }
    $futuresOptionPlaybook = $futuresOptionPlaybookJson | ConvertFrom-Json
    Write-Host "Futures-option playbook: $($futuresOptionPlaybook.markdown_path)"
}

if ($runValidatedBriefEffective) {
    $validatedBriefArgs = @(
        "-3.12",
        "-m",
        "cotton_factor.cli.main",
        "research",
        "build-cf-validated-research-brief",
        "--latest-signal-json-path",
        "$($latestSignal.json_path)",
        "--output-dir",
        "reports\research\validated_brief",
        "--daily-output-root",
        "runs\daily",
        "--run-id",
        "$RunId"
    )
    $historicalEvidenceValue = Get-Variable -Name "historicalEvidence" -ValueOnly -ErrorAction SilentlyContinue
    if ($null -ne $historicalEvidenceValue) {
        if ($historicalEvidenceValue.decay_parquet_path) {
            $validatedBriefArgs += @(
                "--historical-evidence-decay-path",
                "$($historicalEvidenceValue.decay_parquet_path)"
            )
        }
        if ($historicalEvidenceValue.stability_parquet_path) {
            $validatedBriefArgs += @(
                "--historical-evidence-stability-path",
                "$($historicalEvidenceValue.stability_parquet_path)"
            )
        }
    }
    $eventExplanationValue = Get-Variable -Name "eventExplanation" -ValueOnly -ErrorAction SilentlyContinue
    if ($null -ne $eventExplanationValue) {
        if ($eventExplanationValue.summary_parquet_path) {
            $validatedBriefArgs += @(
                "--event-summary-path",
                "$($eventExplanationValue.summary_parquet_path)"
            )
        }
        if ($eventExplanationValue.event_parquet_path) {
            $validatedBriefArgs += @(
                "--event-detail-path",
                "$($eventExplanationValue.event_parquet_path)"
            )
        }
    }
    elseif (Test-Path "data\research\CF\event_explanation") {
        $latestEventDetailPath = Get-LatestResearchPath `
            -Directory "data\research\CF\event_explanation" `
            -Pattern "CF_*_event_explanation_events.parquet"
        if (-not [string]::IsNullOrWhiteSpace($latestEventDetailPath)) {
            $validatedBriefArgs += @(
                "--event-detail-path",
                "$latestEventDetailPath"
            )
        }
    }
    if (Test-Path $fundamentalObservationJsonPath) {
        $validatedBriefArgs += @(
            "--fundamental-observation-json-path",
            "$fundamentalObservationJsonPath"
        )
    }
    $eventThresholdSensitivityValue = Get-Variable -Name "eventThresholdSensitivity" -ValueOnly -ErrorAction SilentlyContinue
    if ($null -ne $eventThresholdSensitivityValue -and $eventThresholdSensitivityValue.summary_parquet_path) {
        $validatedBriefArgs += @(
            "--event-threshold-summary-path",
            "$($eventThresholdSensitivityValue.summary_parquet_path)"
        )
    }
    elseif (Test-Path "data\research\CF\event_threshold_sensitivity") {
        $latestEventThresholdSummaryPath = Get-LatestResearchPath `
            -Directory "data\research\CF\event_threshold_sensitivity" `
            -Pattern "CF_*_event_threshold_sensitivity_summary.parquet"
        if (-not [string]::IsNullOrWhiteSpace($latestEventThresholdSummaryPath)) {
            $validatedBriefArgs += @(
                "--event-threshold-summary-path",
                "$latestEventThresholdSummaryPath"
            )
        }
    }
    $futuresOptionDivergenceValue = Get-Variable -Name "futuresOptionDivergence" -ValueOnly -ErrorAction SilentlyContinue
    if ($null -ne $futuresOptionDivergenceValue -and $futuresOptionDivergenceValue.json_path) {
        $validatedBriefArgs += @(
            "--futures-option-divergence-json-path",
            "$($futuresOptionDivergenceValue.json_path)"
        )
    }
    elseif (Test-Path "reports\research\futures_option_divergence") {
        $latestFuturesOptionDivergenceJsonPath = Get-LatestResearchPath -Directory "reports\research\futures_option_divergence" -Pattern "CF_*_futures_option_divergence.json"
        if (-not [string]::IsNullOrWhiteSpace($latestFuturesOptionDivergenceJsonPath)) {
            $validatedBriefArgs += @(
                "--futures-option-divergence-json-path",
                "$latestFuturesOptionDivergenceJsonPath"
            )
        }
    }
    $futuresOptionPlaybookValue = Get-Variable -Name "futuresOptionPlaybook" -ValueOnly -ErrorAction SilentlyContinue
    if ($null -ne $futuresOptionPlaybookValue -and $futuresOptionPlaybookValue.json_path) {
        $validatedBriefArgs += @(
            "--futures-option-playbook-json-path",
            "$($futuresOptionPlaybookValue.json_path)"
        )
    }
    elseif (Test-Path "reports\research\futures_option_divergence_playbook") {
        $latestFuturesOptionPlaybookJsonPath = Get-LatestResearchPath `
            -Directory "reports\research\futures_option_divergence_playbook" `
            -Pattern "CF_*_futures_option_playbook.json"
        if (-not [string]::IsNullOrWhiteSpace($latestFuturesOptionPlaybookJsonPath)) {
            $validatedBriefArgs += @(
                "--futures-option-playbook-json-path",
                "$latestFuturesOptionPlaybookJsonPath"
            )
        }
    }
    $currentWatchWindowValue = Get-Variable -Name "currentWatchWindow" -ValueOnly -ErrorAction SilentlyContinue
    if ($null -ne $currentWatchWindowValue -and $currentWatchWindowValue.json_path) {
        $validatedBriefArgs += @(
            "--current-watch-window-json-path",
            "$($currentWatchWindowValue.json_path)"
        )
    }
    # R79/R81 只接入与最新交易日完全一致的周度证据，避免旧后验报告污染当前结论。
    if (Test-Path "reports\research\state_transition") {
        $latestStateTransitionJsonPath = Get-LatestResearchPath `
            -Directory "reports\research\state_transition" `
            -Pattern "CF_*_$($metadata.max_trade_date)_state_transition_competing_risk.json"
        if (-not [string]::IsNullOrWhiteSpace($latestStateTransitionJsonPath)) {
            $validatedBriefArgs += @(
                "--state-transition-json-path",
                "$latestStateTransitionJsonPath"
            )
        }
    }
    if (Test-Path "reports\research\option_volatility") {
        $latestOptionVolatilityJsonPath = Get-LatestResearchPath `
            -Directory "reports\research\option_volatility" `
            -Pattern "CF_*_$($metadata.max_trade_date)_option_volatility.json"
        if (-not [string]::IsNullOrWhiteSpace($latestOptionVolatilityJsonPath)) {
            $validatedBriefArgs += @(
                "--option-volatility-json-path",
                "$latestOptionVolatilityJsonPath"
            )
        }
    }
    $validatedBriefJson = & py @validatedBriefArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CF validated research brief failed."
    }
    $validatedBrief = $validatedBriefJson | ConvertFrom-Json
    Write-Host "Validated research brief: $($validatedBrief.markdown_path)"
}

if ($runPublishPackEffective) {
    $publishPackArgs = @(
        "-3.12",
        "-m",
        "cotton_factor.cli.main",
        "research",
        "build-cf-publish-pack",
        "--latest-signal-json-path",
        "$($latestSignal.json_path)",
        "--core-quote-path",
        "$($metadata.core_path)",
        "--signal-matrix-path",
        "$($signalMatrix.matrix_parquet_path)",
        "--output-root",
        "runs\daily",
        "--run-id",
        "$RunId"
    )
    $validatedBriefValue = Get-Variable -Name "validatedBrief" -ValueOnly -ErrorAction SilentlyContinue
    if ($null -ne $validatedBriefValue -and $validatedBriefValue.markdown_path) {
        $publishPackArgs += @(
            "--validated-brief-path",
            "$($validatedBriefValue.markdown_path)"
        )
    }
    $historicalEvidenceValue = Get-Variable -Name "historicalEvidence" -ValueOnly -ErrorAction SilentlyContinue
    if ($null -ne $historicalEvidenceValue -and $historicalEvidenceValue.decay_parquet_path) {
        $publishPackArgs += @(
            "--historical-evidence-decay-path",
            "$($historicalEvidenceValue.decay_parquet_path)"
        )
    }
    $eventExplanationValue = Get-Variable -Name "eventExplanation" -ValueOnly -ErrorAction SilentlyContinue
    if ($null -ne $eventExplanationValue -and $eventExplanationValue.summary_parquet_path) {
        $publishPackArgs += @(
            "--event-summary-path",
            "$($eventExplanationValue.summary_parquet_path)"
        )
    }
    $futuresOptionDivergenceValue = Get-Variable -Name "futuresOptionDivergence" -ValueOnly -ErrorAction SilentlyContinue
    if ($null -ne $futuresOptionDivergenceValue -and $futuresOptionDivergenceValue.json_path) {
        $publishPackArgs += @(
            "--futures-option-divergence-json-path",
            "$($futuresOptionDivergenceValue.json_path)"
        )
    }
    elseif (Test-Path "reports\research\futures_option_divergence") {
        # 日更未重跑 R69 时，发布包必须继续引用最近一次历史后验证据，不能退化为空上下文。
        $latestFuturesOptionDivergenceJsonPath = Get-LatestResearchPath -Directory "reports\research\futures_option_divergence" -Pattern "CF_*_futures_option_divergence.json"
        if (-not [string]::IsNullOrWhiteSpace($latestFuturesOptionDivergenceJsonPath)) {
            $publishPackArgs += @(
                "--futures-option-divergence-json-path",
                "$latestFuturesOptionDivergenceJsonPath"
            )
        }
    }
    $futuresOptionPlaybookValue = Get-Variable -Name "futuresOptionPlaybook" -ValueOnly -ErrorAction SilentlyContinue
    if ($null -ne $futuresOptionPlaybookValue -and $futuresOptionPlaybookValue.json_path) {
        $publishPackArgs += @(
            "--futures-option-playbook-json-path",
            "$($futuresOptionPlaybookValue.json_path)"
        )
    }
    elseif (Test-Path "reports\research\futures_option_divergence_playbook") {
        $latestFuturesOptionPlaybookJsonPath = Get-LatestResearchPath `
            -Directory "reports\research\futures_option_divergence_playbook" `
            -Pattern "CF_*_futures_option_playbook.json"
        if (-not [string]::IsNullOrWhiteSpace($latestFuturesOptionPlaybookJsonPath)) {
            $publishPackArgs += @(
                "--futures-option-playbook-json-path",
                "$latestFuturesOptionPlaybookJsonPath"
            )
        }
    }
    $currentWatchWindowValue = Get-Variable -Name "currentWatchWindow" -ValueOnly -ErrorAction SilentlyContinue
    if ($null -ne $currentWatchWindowValue -and $currentWatchWindowValue.json_path) {
        $publishPackArgs += @(
            "--current-watch-window-json-path",
            "$($currentWatchWindowValue.json_path)"
        )
    }
    $publishPackJson = & py @publishPackArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CF publish pack failed."
    }
    $publishPack = $publishPackJson | ConvertFrom-Json
    Write-Host "Publish pack article: $($publishPack.wechat_article_path)"
    Write-Host "Publish chart pack: $($publishPack.chart_pack_zip_path)"
}

if ($RunResearchWindow.IsPresent) {
    Write-Host "Running research window date $($metadata.analysis_date)"
    Write-Host "Window: $($metadata.window_start) to $($metadata.window_end)"
    $pipelineArgs = @(
        "-3.12",
        "-m",
        "cotton_factor.cli.main",
        "research",
        "run-cf-daily-pipeline",
        "--date",
        "$($metadata.analysis_date)",
        "--start",
        "$($metadata.window_start)",
        "--end",
        "$($metadata.window_end)",
        "--input-path",
        "$($metadata.daily_input_path)",
        "--raw-output-dir",
        "$($metadata.run_root)\raw",
        "--core-output-dir",
        "$($metadata.run_root)\core",
        "--research-output-root",
        "$($metadata.run_root)\research",
        "--report-output-root",
        "$($metadata.run_root)\reports",
        "--run-id",
        "$RunId",
        "--allow-missing-factors"
    )
    $pipelineJson = & py @pipelineArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CF research window failed."
    }
    $pipeline = $pipelineJson | ConvertFrom-Json
    Write-Host "R20 pipeline report: $($pipeline.markdown_path)"
}

if ($runWeeklyManifestEffective) {
    $weeklyManifestDir = Join-Path -Path "runs\weekly\CF" -ChildPath "$($metadata.max_trade_date)"
    New-Item -ItemType Directory -Force -Path $weeklyManifestDir | Out-Null
    $weeklyManifestPath = Join-Path -Path $weeklyManifestDir -ChildPath "weekly_research_run_manifest.json"

    $historicalEvidenceValue = Get-Variable -Name "historicalEvidence" -ValueOnly -ErrorAction SilentlyContinue
    $eventExplanationValue = Get-Variable -Name "eventExplanation" -ValueOnly -ErrorAction SilentlyContinue
    $eventThresholdSensitivityValue = Get-Variable -Name "eventThresholdSensitivity" -ValueOnly -ErrorAction SilentlyContinue
    $futuresOptionDivergenceValue = Get-Variable -Name "futuresOptionDivergence" -ValueOnly -ErrorAction SilentlyContinue
    $futuresOptionPlaybookValue = Get-Variable -Name "futuresOptionPlaybook" -ValueOnly -ErrorAction SilentlyContinue
    $validatedBriefValue = Get-Variable -Name "validatedBrief" -ValueOnly -ErrorAction SilentlyContinue
    $publishPackValue = Get-Variable -Name "publishPack" -ValueOnly -ErrorAction SilentlyContinue
    $pipelineValue = Get-Variable -Name "pipeline" -ValueOnly -ErrorAction SilentlyContinue
    $dailyAuditValue = Get-Variable -Name "dailyAudit" -ValueOnly -ErrorAction SilentlyContinue
    $memberPositionResearchValue = Get-Variable -Name "memberPositionResearch" -ValueOnly -ErrorAction SilentlyContinue
    $optionStrikePositionValue = Get-Variable -Name "optionStrikePosition" -ValueOnly -ErrorAction SilentlyContinue

    $weeklySteps = [ordered]@{
        signal_matrix = [ordered]@{
            status = "completed"
            matrix_parquet_path = "$($signalMatrix.matrix_parquet_path)"
            latest_snapshot_json_path = "$($signalMatrix.latest_snapshot_json_path)"
            markdown_path = "$($signalMatrix.markdown_path)"
        }
        latest_signal_brief = [ordered]@{
            status = "completed"
            json_path = "$($latestSignal.json_path)"
            markdown_path = "$($latestSignal.markdown_path)"
        }
        trend_continuity_board = [ordered]@{
            status = "completed"
            json_path = "$($trendBoard.json_path)"
            markdown_path = "$($trendBoard.markdown_path)"
        }
    }

    if ($null -ne $dailyAuditValue) {
        $weeklySteps["daily_operation_audit"] = [ordered]@{
            status = "completed"
            operation_status = "$($dailyAuditValue.operation_status)"
            warning_count = $dailyAuditValue.warning_count
            markdown_path = "$($dailyAuditValue.markdown_path)"
        }
    }
    else {
        $weeklySteps["daily_operation_audit"] = [ordered]@{ status = "skipped" }
    }

    if ($null -ne $historicalEvidenceValue) {
        $weeklySteps["historical_evidence"] = [ordered]@{
            status = "completed"
            decay_parquet_path = "$($historicalEvidenceValue.decay_parquet_path)"
            stability_parquet_path = "$($historicalEvidenceValue.stability_parquet_path)"
            markdown_path = "$($historicalEvidenceValue.markdown_path)"
        }
    }
    else {
        $weeklySteps["historical_evidence"] = [ordered]@{ status = "skipped" }
    }

    if ($null -ne $memberPositionResearchValue) {
        $weeklySteps["member_position_research"] = [ordered]@{
            status = "completed"
            daily_parquet_path = "$($memberPositionResearchValue.daily_parquet_path)"
            member_detail_parquet_path = "$($memberPositionResearchValue.member_detail_parquet_path)"
            roll_parquet_path = "$($memberPositionResearchValue.roll_parquet_path)"
            validation_parquet_path = "$($memberPositionResearchValue.validation_parquet_path)"
            markdown_path = "$($memberPositionResearchValue.markdown_path)"
            history_date_count = $memberPositionResearchValue.history_date_count
            latest_main_contract = "$($memberPositionResearchValue.latest_main_contract)"
            latest_member_direction = "$($memberPositionResearchValue.latest_member_direction)"
            warning_count = $memberPositionResearchValue.warning_count
        }
    }
    else {
        $weeklySteps["member_position_research"] = [ordered]@{ status = "skipped" }
    }

    if ($null -ne $optionStrikePositionValue) {
        $weeklySteps["option_strike_position_research"] = [ordered]@{
            status = "completed"
            daily_parquet_path = "$($optionStrikePositionValue.daily_parquet_path)"
            strike_parquet_path = "$($optionStrikePositionValue.strike_parquet_path)"
            validation_summary_parquet_path = "$($optionStrikePositionValue.validation_summary_parquet_path)"
            markdown_path = "$($optionStrikePositionValue.markdown_path)"
            latest_main_contract = "$($optionStrikePositionValue.latest_main_contract)"
            latest_call_wall = $optionStrikePositionValue.latest_call_wall
            latest_put_wall = $optionStrikePositionValue.latest_put_wall
            latest_max_pain = $optionStrikePositionValue.latest_max_pain
            latest_key_level_state = "$($optionStrikePositionValue.latest_key_level_state)"
            warning_count = $optionStrikePositionValue.warning_count
        }
    }
    else {
        $weeklySteps["option_strike_position_research"] = [ordered]@{ status = "skipped" }
    }

    if ($null -ne $eventExplanationValue) {
        $weeklySteps["event_explanation"] = [ordered]@{
            status = "completed"
            event_parquet_path = "$($eventExplanationValue.event_parquet_path)"
            summary_parquet_path = "$($eventExplanationValue.summary_parquet_path)"
            markdown_path = "$($eventExplanationValue.markdown_path)"
            fundamental_context_path = "$($eventExplanationValue.fundamental_context_path)"
        }
    }
    else {
        $weeklySteps["event_explanation"] = [ordered]@{ status = "skipped" }
    }

    if ($null -ne $eventThresholdSensitivityValue) {
        $weeklySteps["event_threshold_sensitivity"] = [ordered]@{
            status = "completed"
            detail_parquet_path = "$($eventThresholdSensitivityValue.detail_parquet_path)"
            summary_parquet_path = "$($eventThresholdSensitivityValue.summary_parquet_path)"
            annual_parquet_path = "$($eventThresholdSensitivityValue.annual_parquet_path)"
            markdown_path = "$($eventThresholdSensitivityValue.markdown_path)"
            warning_count = $eventThresholdSensitivityValue.warning_count
            summary_row_count = $eventThresholdSensitivityValue.summary_row_count
            review_decision_counts = $eventThresholdSensitivityValue.review_decision_counts
            forward_returns_are_validation_labels = $eventThresholdSensitivityValue.forward_returns_are_validation_labels
            trading_instruction = "$($eventThresholdSensitivityValue.trading_instruction)"
        }
    }
    else {
        $weeklySteps["event_threshold_sensitivity"] = [ordered]@{ status = "skipped" }
    }

    if ($null -ne $futuresOptionDivergenceValue) {
        $weeklySteps["futures_option_divergence"] = [ordered]@{
            status = "completed"
            event_parquet_path = "$($futuresOptionDivergenceValue.event_parquet_path)"
            summary_by_horizon_parquet_path = "$($futuresOptionDivergenceValue.summary_by_horizon_parquet_path)"
            summary_by_node_parquet_path = "$($futuresOptionDivergenceValue.summary_by_node_parquet_path)"
            resolution_timing_parquet_path = "$($futuresOptionDivergenceValue.resolution_timing_parquet_path)"
            markdown_path = "$($futuresOptionDivergenceValue.markdown_path)"
            json_path = "$($futuresOptionDivergenceValue.json_path)"
            directional_divergence_count = $futuresOptionDivergenceValue.directional_divergence_count
            average_resolution_horizon = $futuresOptionDivergenceValue.average_resolution_horizon
            main_winner_label = "$($futuresOptionDivergenceValue.main_winner_label)"
        }
    }
    else {
        $weeklySteps["futures_option_divergence"] = [ordered]@{ status = "skipped" }
    }

    if ($null -ne $futuresOptionPlaybookValue) {
        $weeklySteps["futures_option_playbook"] = [ordered]@{
            status = "completed"
            node_table_parquet_path = "$($futuresOptionPlaybookValue.node_table_parquet_path)"
            current_mapping_parquet_path = "$($futuresOptionPlaybookValue.current_mapping_parquet_path)"
            markdown_path = "$($futuresOptionPlaybookValue.markdown_path)"
            json_path = "$($futuresOptionPlaybookValue.json_path)"
            manifest_path = "$($futuresOptionPlaybookValue.manifest_path)"
            node_count = $futuresOptionPlaybookValue.node_count
            ready_node_count = $futuresOptionPlaybookValue.ready_node_count
            directional_node_count = $futuresOptionPlaybookValue.directional_node_count
            current_mapping_count = $futuresOptionPlaybookValue.current_mapping_count
            warning_count = $futuresOptionPlaybookValue.warning_count
        }
    }
    else {
        $weeklySteps["futures_option_playbook"] = [ordered]@{ status = "skipped" }
    }

    if ($null -ne $validatedBriefValue) {
        $weeklySteps["validated_brief"] = [ordered]@{
            status = "completed"
            markdown_path = "$($validatedBriefValue.markdown_path)"
            json_path = "$($validatedBriefValue.json_path)"
            manifest_path = "$($validatedBriefValue.manifest_path)"
            event_detail_path = "$($validatedBriefValue.event_detail_path)"
            event_threshold_summary_path = "$($validatedBriefValue.event_threshold_summary_path)"
            futures_option_divergence_json_path = "$($validatedBriefValue.futures_option_divergence_json_path)"
            state_transition_json_path = "$($validatedBriefValue.state_transition_json_path)"
            option_volatility_json_path = "$($validatedBriefValue.option_volatility_json_path)"
        }
    }
    else {
        $weeklySteps["validated_brief"] = [ordered]@{ status = "skipped" }
    }

    if ($null -ne $publishPackValue) {
        $weeklySteps["publish_pack"] = [ordered]@{
            status = "completed"
            wechat_article_path = "$($publishPackValue.wechat_article_path)"
            wechat_summary_path = "$($publishPackValue.wechat_summary_path)"
            chart_pack_zip_path = "$($publishPackValue.chart_pack_zip_path)"
            manifest_path = "$($publishPackValue.manifest_path)"
            validated_event_context = $publishPackValue.validated_event_context
            futures_option_divergence_context = $publishPackValue.futures_option_divergence_context
        }
    }
    else {
        $weeklySteps["publish_pack"] = [ordered]@{ status = "skipped" }
    }

    if ($null -ne $pipelineValue) {
        $weeklySteps["research_window"] = [ordered]@{
            status = "completed"
            markdown_path = "$($pipelineValue.markdown_path)"
        }
    }
    else {
        $weeklySteps["research_window"] = [ordered]@{ status = "skipped" }
    }

    $weeklyManifest = [ordered]@{
        report_type = "cf_weekly_research_run_manifest"
        rule_version = "R58_cf_weekly_research_run_v1"
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        run_id = "$RunId"
        product_code = "CF"
        data_asof = "$($metadata.max_trade_date)"
        core_path = "$($metadata.core_path)"
        weekly_chain_enabled = $RunWeeklyResearchPack.IsPresent
        effective_steps = [ordered]@{
            historical_evidence = $runHistoricalEvidenceEffective
            event_explanation = $runEventExplanationEffective
            event_threshold_sensitivity = $runEventThresholdSensitivityEffective
            futures_option_divergence = $runFuturesOptionDivergenceEffective
            futures_option_playbook = $runFuturesOptionPlaybookEffective
            member_position_research = $runMemberPositionResearchEffective
            option_strike_position_research = $runOptionStrikePositionResearchEffective
            validated_brief = $runValidatedBriefEffective
            publish_pack = $runPublishPackEffective
            daily_operation_audit = $runDailyOperationAuditEffective
        }
        steps = $weeklySteps
        research_boundary = [ordered]@{
            latest_signal_only_contains_forward_return_validation = $false
            historical_forward_returns_are_validation_labels = $true
            fundamental_signal_status = "not_connected"
            trading_instruction = "not_a_trading_instruction"
            human_review_required = @(
                "historical_evidence_interpretation",
                "historical_event_interpretation",
                "event_thresholds",
                "futures_option_divergence_interpretation",
                "futures_option_playbook_interpretation",
                "member_position_is_member_level_not_customer_identity",
                "member_position_roll_migration_interpretation",
                "option_open_interest_long_short_ownership_unknown",
                "call_put_wall_interpretation",
                "fundamental_context_interpretation",
                "publish_wording"
            )
        }
    }
    $weeklyManifest |
        ConvertTo-Json -Depth 12 |
        Set-Content -Path $weeklyManifestPath -Encoding UTF8
    Write-Host "Weekly research manifest: $weeklyManifestPath"

    $weeklyAuditArgs = @(
        "-3.12",
        "-m",
        "cotton_factor.cli.main",
        "research",
        "build-cf-weekly-research-audit",
        "--weekly-manifest-path",
        "$weeklyManifestPath",
        "--output-dir",
        "reports\research\weekly_audit",
        "--run-id",
        "$RunId"
    )
    $weeklyAuditJson = & py @weeklyAuditArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CF weekly research audit failed."
    }
    $weeklyAudit = $weeklyAuditJson | ConvertFrom-Json
    Write-Host "Weekly research audit: $($weeklyAudit.markdown_path)"
}

Write-Host "CF daily update elapsed seconds: $([math]::Round($dailyRunStopwatch.Elapsed.TotalSeconds, 2))"
