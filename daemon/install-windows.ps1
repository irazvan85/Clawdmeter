<#
.SYNOPSIS
  Install the Clawdmeter usage daemon as a per-user Scheduled Task on Windows.

.DESCRIPTION
  Creates daemon\.venv (httpx + psutil) if missing, then registers a
  Scheduled Task that starts the daemon at logon, runs it hidden in your user
  session (so `gh` and ~/.claude credentials all work), restarts it on
  failure, and never times out.

  A true session-0 Windows service isn't used here for now -- historically
  that was because bleak's WinRT Bluetooth backend couldn't enumerate
  devices outside an interactive session, which no longer applies now that
  the daemon talks to the device over HTTP instead of BLE (see CLAUDE.md
  gotcha #14). Switching to a real Service (so the daemon survives
  logoff/lock-screen) is a reasonable follow-up, just not done here.

.PARAMETER Uninstall
  Remove the Scheduled Task (leaves the venv and logs in place).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File daemon\install-windows.ps1
  powershell -ExecutionPolicy Bypass -File daemon\install-windows.ps1 -Uninstall
#>
param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'
$TaskName   = 'ClawdmeterDaemon'
$daemonDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$script     = Join-Path $daemonDir 'claude_usage_daemon.py'
$venvDir    = Join-Path $daemonDir '.venv'
$pythonw    = Join-Path $venvDir 'Scripts\pythonw.exe'
$pip        = Join-Path $venvDir 'Scripts\python.exe'
$logDir     = Join-Path $env:LOCALAPPDATA 'claude-usage-monitor'
$logFile    = Join-Path $logDir 'daemon.log'

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed scheduled task '$TaskName'."
    } else {
        Write-Host "Task '$TaskName' is not registered."
    }
    return
}

if (-not (Test-Path $script)) { throw "Not found: $script" }

# --- venv ---
if (-not (Test-Path $pythonw)) {
    $basePy = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $basePy) { throw "Python 3.10+ not found on PATH. Install it, then re-run." }
    Write-Host "Creating venv in $venvDir ..."
    & $basePy -m venv $venvDir
    & $pip -m pip install --quiet --upgrade pip
    & $pip -m pip install --quiet httpx psutil
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# --- scheduled task ---
$action = New-ScheduledTaskAction -Execute $pythonw `
    -Argument "`"$script`" --log `"$logFile`"" -WorkingDirectory $daemonDir

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 5 `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force `
    -Description 'Clawdmeter: push Claude / Copilot / host usage to the ESP32 over WiFi' | Out-Null

Start-ScheduledTask -TaskName $TaskName

Write-Host ""
Write-Host "Registered '$TaskName' - starts at logon, running now."
Write-Host "  Logs:   $logFile"
Write-Host "  Status: Get-ScheduledTask $TaskName | Get-ScheduledTaskInfo"
Write-Host "  Stop:   Stop-ScheduledTask $TaskName"
Write-Host "  Remove: .\install-windows.ps1 -Uninstall"
Write-Host ""
Write-Host "For the 'Claude needs you' signal, also install the Claude Code hooks:"
Write-Host "  $pip $(Join-Path $daemonDir 'install_hooks.py')"
