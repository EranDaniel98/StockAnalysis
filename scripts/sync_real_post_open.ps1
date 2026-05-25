# One-shot wrapper: sync Alpaca paper to user's real holdings after
# market open + after the queued flatten orders have filled.
#
# Registered with Windows Task Scheduler as a one-time trigger at
# 2026-05-19 16:45 IL (= 09:45 ET, ~15 min after the open). 15-min
# offset gives the 52 close orders from scripts/flatten_paper.py time
# to fill before this submits BUYs.
#
# Logs output to data/daily_picks/execution_log/2026-05-19_sync_real.log

$ErrorActionPreference = 'Stop'
$projectDir = 'C:\Users\Eran Daniel\Desktop\Personal\StockNew'
$logPath = Join-Path $projectDir 'data\daily_picks\execution_log\2026-05-19_sync_real.log'

Set-Location $projectDir

$logDir = Split-Path $logPath -Parent
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Force $logDir | Out-Null
}

"=== sync_real_post_open started $(Get-Date -Format o) ===" | Out-File -FilePath $logPath -Encoding utf8

$uv = 'C:\Users\Eran Daniel\.local\bin\uv.exe'

& $uv run python -m scripts.sync_real_holdings --execute 2>&1 | Tee-Object -FilePath $logPath -Append

"=== exited $(Get-Date -Format o) with code $LASTEXITCODE ===" | Out-File -FilePath $logPath -Append -Encoding utf8
