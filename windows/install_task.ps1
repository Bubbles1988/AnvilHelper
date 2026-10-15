# Registers Anvil Helper as a Windows scheduled task that starts with the server
# and keeps running without anyone logged in.
# Run in an *administrator* PowerShell:  powershell -ExecutionPolicy Bypass -File windows\install_task.ps1
#Requires -RunAsAdministrator

$TaskName = "AnvilHelper Discord Bot"
$Root = Split-Path -Parent $PSScriptRoot
$Bat = Join-Path $PSScriptRoot "start_bot.bat"

if (-not (Test-Path (Join-Path $Root ".env"))) {
    Write-Error "No .env file in $Root. Copy .env.example to .env and add your bot token first."
    exit 1
}

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$Bat`"" -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "Installed and started '$TaskName'. Logs: $Root\logs\bot.log"
Write-Host "Stop:      Stop-ScheduledTask -TaskName '$TaskName'"
Write-Host "Remove:    Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
