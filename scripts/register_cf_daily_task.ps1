# Register the Cottonquant CF daily research scheduled task
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument '-NoProfile -ExecutionPolicy Bypass -File D:\Cottonquant\scripts\run_cf_daily_scheduled.ps1'
$trigger = New-ScheduledTaskTrigger -Daily -At 18:30
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName 'Cottonquant CF Daily Research Update' `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description 'CF daily research update + studio dashboard rebuild (trading days only)' -Force | Out-Null
$task = Get-ScheduledTask -TaskName 'Cottonquant CF Daily Research Update'
Write-Host "REGISTERED: $($task.TaskName) state=$($task.State)"
Start-ScheduledTask -TaskName 'Cottonquant CF Daily Research Update'
Start-Sleep -Seconds 10
$info = Get-ScheduledTaskInfo -TaskName 'Cottonquant CF Daily Research Update'
Write-Host "TEST RUN: LastRunTime=$($info.LastRunTime) LastTaskResult=$($info.LastTaskResult)"
