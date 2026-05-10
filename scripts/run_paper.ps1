<#
.SYNOPSIS
    Wrapper invoked by Windows Task Scheduler to run a `paper` subcommand.

.DESCRIPTION
    Executes `uv run python -m src.main paper <subcmd> [args]` from the project
    root, with stdout and stderr captured to logs/paper_<subcmd>_<stamp>.log.

.EXAMPLE
    .\scripts\run_paper.ps1 status
    .\scripts\run_paper.ps1 trade --strategy long_term_growth --top 10
#>

param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$SubCommand,

    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Continue"

$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $ProjectRoot
$env:PYTHONIOENCODING = "utf-8"

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logsDir = Join-Path $ProjectRoot "logs"
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}
$logFile = Join-Path $logsDir "paper_${SubCommand}_${stamp}.log"

$restJoined = if ($Rest) { ($Rest -join " ") } else { "" }

$allArgs = @("run", "python", "-m", "src.main", "paper", $SubCommand)
if ($Rest) { $allArgs += $Rest }

# Buffer output so all writes use consistent UTF-8 encoding (no UTF-16 surprises
# from PowerShell 5.1's `*>>` operator).
$captured = & uv @allArgs 2>&1 | Out-String
$rc = $LASTEXITCODE

$body = @(
    "[START $stamp] paper $SubCommand $restJoined",
    $captured.TrimEnd(),
    "[END exit=$rc]"
) -join "`r`n"

[System.IO.File]::WriteAllText($logFile, $body, [System.Text.UTF8Encoding]::new($false))
exit $rc
