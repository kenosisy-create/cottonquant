param(
    [int]$Year = (Get-Date).Year,
    [string]$SourceDir = "data\incoming\CF\history",
    [string]$RunId = "cf_daily_update_$(Get-Date -Format yyyyMMdd_HHmmss)",
    [switch]$RunResearchWindow,
    [switch]$RunHistoricalEvidence,
    [switch]$RunEventExplanation,
    [switch]$RunEventThresholdSensitivity,
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
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot
$env:PYTHONPATH = "src"

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
$runValidatedBriefEffective = $RunValidatedBrief.IsPresent -or $RunWeeklyResearchPack.IsPresent
$runPublishPackEffective = $RunPublishPack.IsPresent -or $RunWeeklyResearchPack.IsPresent
$runWeeklyManifestEffective = (
    $runHistoricalEvidenceEffective -or
    $runEventExplanationEffective -or
    $runEventThresholdSensitivityEffective -or
    $runValidatedBriefEffective -or
    $runPublishPackEffective
)

$sourceRoot = Resolve-Path $SourceDir
$candidateNames = @(
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
    "$SourceDir",
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
if (-not [string]::IsNullOrWhiteSpace($OptionFactorPath)) {
    $signalMatrixArgs += @(
        "--option-factor-path",
        "$OptionFactorPath"
    )
}
$signalMatrixJson = & py @signalMatrixArgs
if ($LASTEXITCODE -ne 0) {
    throw "CF signal matrix failed."
}
$signalMatrix = $signalMatrixJson | ConvertFrom-Json
Write-Host "Signal matrix: $($signalMatrix.markdown_path)"
Write-Host "Signal matrix latest snapshot: $($signalMatrix.latest_snapshot_json_path)"

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
    $validatedBriefValue = Get-Variable -Name "validatedBrief" -ValueOnly -ErrorAction SilentlyContinue
    $publishPackValue = Get-Variable -Name "publishPack" -ValueOnly -ErrorAction SilentlyContinue
    $pipelineValue = Get-Variable -Name "pipeline" -ValueOnly -ErrorAction SilentlyContinue

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
        daily_operation_audit = [ordered]@{
            status = "completed"
            operation_status = "$($dailyAudit.operation_status)"
            warning_count = $dailyAudit.warning_count
            markdown_path = "$($dailyAudit.markdown_path)"
        }
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

    if ($null -ne $validatedBriefValue) {
        $weeklySteps["validated_brief"] = [ordered]@{
            status = "completed"
            markdown_path = "$($validatedBriefValue.markdown_path)"
            json_path = "$($validatedBriefValue.json_path)"
            manifest_path = "$($validatedBriefValue.manifest_path)"
            event_detail_path = "$($validatedBriefValue.event_detail_path)"
            event_threshold_summary_path = "$($validatedBriefValue.event_threshold_summary_path)"
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
            validated_brief = $runValidatedBriefEffective
            publish_pack = $runPublishPackEffective
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
                "fundamental_context_interpretation",
                "publish_wording",
                "chart_readability"
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
