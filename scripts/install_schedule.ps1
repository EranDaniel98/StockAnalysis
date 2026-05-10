<#
.SYNOPSIS
    Registers Windows Scheduled Tasks for the paper-trading validation loop.

.DESCRIPTION
    Creates three tasks under \StockScanner\:
      - StockScanner-Trade     weekly Sunday 18:00 — runs `paper trade`
      - StockScanner-Sync      weekdays 23:30      — runs `paper sync`
      - StockScanner-Evaluate  weekly Monday 09:00 — runs `paper evaluate`

    All times are in your machine's local timezone (Israel for this user, so
    23:30 local = ~30 min after US market close in summer).

    Runs as the current user — no admin / elevated permissions required.

.PARAMETER Strategy
    Which strategy to pass to `paper trade`. Default: long_term_growth.

.PARAMETER Top
    --top value for paper trade. Default: 10.

.PARAMETER MinScore
    --min-score value for paper trade. Default: 55.

.PARAMETER Force
    Replace existing tasks if they already exist.

.EXAMPLE
    .\scripts\install_schedule.ps1
    .\scripts\install_schedule.ps1 -Strategy short_term_momentum -Top 5 -Force
#>

param(
    [string]$Strategy = "long_term_growth",
    [int]$Top = 10,
    [int]$MinScore = 55,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$Wrapper = Join-Path $ProjectRoot "scripts\run_paper.ps1"
$TaskFolder = "\StockScanner\"

if (-not (Test-Path $Wrapper)) {
    Write-Error "Wrapper script not found: $Wrapper"
    exit 1
}

function Register-PaperTask {
    param(
        [string]$Name,
        [string]$Description,
        [string]$WrapperArgs,
        [Microsoft.Management.Infrastructure.CimInstance]$Trigger
    )

    $fullName = "$TaskFolder$Name"

    $existing = Get-ScheduledTask -TaskPath $TaskFolder -TaskName $Name -ErrorAction SilentlyContinue
    if ($existing) {
        if (-not $Force) {
            Write-Warning "Task '$fullName' already exists. Use -Force to replace."
            return
        }
        Unregister-ScheduledTask -TaskPath $TaskFolder -TaskName $Name -Confirm:$false
        Write-Host "Removed existing task: $fullName"
    }

    # Invoke PowerShell with the wrapper script and forwarded args.
    $psArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$Wrapper`" $WrapperArgs"

    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument $psArgs `
        -WorkingDirectory $ProjectRoot

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1)

    Register-ScheduledTask `
        -TaskPath $TaskFolder `
        -TaskName $Name `
        -Description $Description `
        -Action $action `
        -Trigger $Trigger `
        -Settings $settings `
        -User $env:USERNAME | Out-Null

    Write-Host "Registered: $fullName"
}

# --- Trade: every Sunday at 18:00 ---
$tradeArgs = "trade --strategy $Strategy --top $Top --min-score $MinScore"
$tradeTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 18:00
Register-PaperTask `
    -Name "StockScanner-Trade" `
    -Description "Weekly: scan + submit paper bracket orders for top picks." `
    -WrapperArgs $tradeArgs `
    -Trigger $tradeTrigger

# --- Sync: weekdays at 23:30 (~30 min after US market close, Israel time) ---
$syncTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 23:30
Register-PaperTask `
    -Name "StockScanner-Sync" `
    -Description "Daily after-close: pull Alpaca positions into portfolio.yaml." `
    -WrapperArgs "sync" `
    -Trigger $syncTrigger

# --- Evaluate: every weekday at 09:00 ---
$evalTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 09:00
Register-PaperTask `
    -Name "StockScanner-Evaluate" `
    -Description "Weekdays: reconcile closed paper trades and emit calibration report." `
    -WrapperArgs "evaluate" `
    -Trigger $evalTrigger

Write-Host ""
Write-Host "Done. View tasks: Get-ScheduledTask -TaskPath '$TaskFolder'"
Write-Host "Run a task on demand: Start-ScheduledTask -TaskPath '$TaskFolder' -TaskName 'StockScanner-Trade'"
Write-Host "Logs land in: $ProjectRoot\logs\"
