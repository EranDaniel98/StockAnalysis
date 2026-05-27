<#
.SYNOPSIS
    Daily forward paper-trading run — invoked by Windows Task Scheduler.

.DESCRIPTION
    Runs the two-step daily flow from the project root, logging to
    logs/paper_daily_<stamp>.log:
      1. scripts.run_daily_pipeline    -> today's picks + analysis + paper-vs-SPY snapshot
      2. scripts.paper_trade_factor_picks --execute  -> rebalance, or flatten to cash
         when the regime gate is off (the daily-regime protection only fires the
         day this runs, so it MUST run daily).

    Replaces the old `src.main paper <subcmd>` CLI, which was removed in the
    5-engine teardown. Pass -DryRun to skip order submission.

.EXAMPLE
    .\scripts\run_paper.ps1            # live: generate picks + rebalance/flatten
    .\scripts\run_paper.ps1 -DryRun    # picks + plan only, no orders
#>

param(
    [switch]$DryRun,
    [int]$TopN = 24
)

$ErrorActionPreference = "Continue"

$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $ProjectRoot
$env:PYTHONIOENCODING = "utf-8"

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$today = Get-Date -Format "yyyy-MM-dd"
$logsDir = Join-Path $ProjectRoot "logs"
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}
$logFile = Join-Path $logsDir "paper_daily_${stamp}.log"

# Step 1: picks + analysis + baseline snapshot.
$pipelineArgs = @("run", "python", "-m", "scripts.run_daily_pipeline", "--top-n", "$TopN")
# Step 2: rebalance / flatten-on-block (the actual trading).
$tradeArgs = @("run", "python", "-m", "scripts.paper_trade_factor_picks",
               "--picks-date", $today)
if (-not $DryRun) { $tradeArgs += "--execute" }

$captured1 = & uv @pipelineArgs 2>&1 | Out-String
$rc1 = $LASTEXITCODE
$captured2 = & uv @tradeArgs 2>&1 | Out-String
$rc2 = $LASTEXITCODE

$body = @(
    "[START $stamp] daily forward paper run (top-n=$TopN, dryrun=$DryRun)",
    "--- STEP 1: run_daily_pipeline (exit=$rc1) ---",
    $captured1.TrimEnd(),
    "--- STEP 2: paper_trade_factor_picks (exit=$rc2) ---",
    $captured2.TrimEnd(),
    "[END pipeline=$rc1 trade=$rc2]"
) -join "`r`n"

[System.IO.File]::WriteAllText($logFile, $body, [System.Text.UTF8Encoding]::new($false))
# Non-zero if either step failed, so Task Scheduler surfaces it.
if ($rc1 -ne 0) { exit $rc1 }
exit $rc2
