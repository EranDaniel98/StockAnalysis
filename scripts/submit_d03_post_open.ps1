# One-shot wrapper: submit d03 paper orders after market open.
#
# Registered with Windows Task Scheduler as a one-time trigger at
# 2026-05-19 16:37 IL (= 09:37 ET, ~7 min after the open).
#
# Logs output to data/daily_picks/execution_log/2026-05-19_post_open.log
# so the user can review what happened on next Claude session.

$ErrorActionPreference = 'Stop'
$projectDir = 'C:\Users\Eran Daniel\Desktop\Personal\StockNew'
$logPath = Join-Path $projectDir 'data\daily_picks\execution_log\2026-05-19_post_open.log'

Set-Location $projectDir

# Make sure the log directory exists (it should already).
$logDir = Split-Path $logPath -Parent
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Force $logDir | Out-Null
}

"=== submit_d03_post_open started $(Get-Date -Format o) ===" | Out-File -FilePath $logPath -Encoding utf8

# Use the user's installed uv (full path so the SCHEDULED context can find it).
$uv = 'C:\Users\Eran Daniel\.local\bin\uv.exe'

& $uv run python -m scripts.paper_trade_factor_picks `
    --picks-date 2026-05-19 `
    --execute `
    --override-drift 2>&1 | Tee-Object -FilePath $logPath -Append

"=== exited $(Get-Date -Format o) with code $LASTEXITCODE ===" | Out-File -FilePath $logPath -Append -Encoding utf8
