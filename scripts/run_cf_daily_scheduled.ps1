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
    $output = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "scripts\update_cf_latest_research.ps1") -DownloadOfficialDaily -RunDailyOperationAudit 2>&1
    $output | Out-String | Out-File -FilePath $log -Append -Encoding utf8
    "[$stamp] finished, exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) { exit 1 }
} catch {
    $_ | Out-String | Out-File -FilePath $log -Append -Encoding utf8
    exit 1
}
