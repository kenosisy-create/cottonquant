# Cottonquant CF daily research update - scheduled task launcher
# 判断今天是否交易日(读官方日历), 是则调用日更链; 日志滚动保留最近30份
$ErrorActionPreference = "Stop"
$repo = "D:\Cottonquant"
$logDir = Join-Path $repo "logs\daily_update"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$log = Join-Path $logDir "cf_daily_$stamp.log"

# 清理30天前的旧日志
Get-ChildItem $logDir -Filter "cf_daily_*.log" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

try {
    $today = Get-Date -Format "yyyy-MM-dd"
    $cal = Import-Csv (Join-Path $repo "configs\calendars\CZCE_2026_OFFICIAL.csv") |
        Where-Object { $_.trade_date -eq $today }
    if ($null -eq $cal -or $cal.is_trading_day -ne "true") {
        "[$stamp] $today not a trading day (or calendar not covered), skip." | Out-File -FilePath $log -Encoding utf8
        exit 0
    }
    "[$stamp] start daily update for $today" | Out-File -FilePath $log -Encoding utf8
    $attempt = 0
    $maxAttempts = 3
    $coreFresh = $false
    while (-not $coreFresh -and $attempt -lt $maxAttempts) {
        if ($attempt -gt 0) {
            "[$stamp] CZCE data not fresh yet, retry $($attempt+1)/$maxAttempts in 40 minutes" | Out-File -FilePath $log -Append -Encoding utf8
            Start-Sleep -Seconds (40 * 60)
        }
        $attempt++
        $output = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "scripts\update_cf_latest_research.ps1") -DownloadOfficialDaily -RunDailyOperationAudit 2>&1
        $output | Out-String | Out-File -FilePath $log -Append -Encoding utf8
        if ($LASTEXITCODE -ne 0) {
            "[$stamp] update attempt $attempt failed with exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
            continue
        }
        # 完整性检查: core 最新交易日必须等于今天(官方下载模式)
        $pyCheck = & py -3.12 -c "import pandas as pd; print(pd.read_parquet(r'D:\Cottonquant\data\core\CF\core_quote_daily.parquet', columns=['trade_date']).trade_date.max())"
        if ("$pyCheck".Trim() -eq $today) {
            $coreFresh = $true
        } else {
            "[$stamp] core latest=$pyCheck expected=$today" | Out-File -FilePath $log -Append -Encoding utf8
        }
    }
    "[$stamp] finished, coreFresh=$coreFresh, exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
    # 状态快照供外部监控(Hermes cron)读取
    $statusPath = Join-Path $logDir "last_run_status.json"
    $status = [ordered]@{
        run_at = (Get-Date).ToString("o")
        trade_date = $today
        core_fresh = $coreFresh
        attempts = $attempt
        exit_code = $LASTEXITCODE
        log_path = $log
    }
    $status | ConvertTo-Json | Set-Content -Path $statusPath -Encoding UTF8
    if (-not $coreFresh) { exit 1 }
} catch {
    $_ | Out-String | Out-File -FilePath $log -Append -Encoding utf8
    $statusPath = Join-Path $logDir "last_run_status.json"
    @{ run_at = (Get-Date).ToString("o"); trade_date = $today; core_fresh = $false; error = ($_ | Out-String); log_path = $log } |
        ConvertTo-Json | Set-Content -Path $statusPath -Encoding UTF8
    exit 1
}
