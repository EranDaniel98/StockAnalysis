param(
    [Parameter(Mandatory=$true)][int]$WaitPid,
    [string]$LogFile = "data\sweep_insider_flow_russell1000.log"
)

$ErrorActionPreference = "Continue"
Set-Location "C:\Users\Eran Daniel\Desktop\Personal\StockNew"

$ts = { Get-Date -Format "yyyy-MM-dd HH:mm:ss" }
function Log($msg) { "$(& $ts) $msg" | Tee-Object -FilePath $LogFile -Append }

Log "launcher: waiting for backfill PID $WaitPid to exit"
try {
    Wait-Process -Id $WaitPid -ErrorAction Stop
    Log "launcher: PID $WaitPid exited"
} catch {
    Log "launcher: PID $WaitPid was not running (already done?) — continuing"
}

Log "launcher: starting insider-flow A/B sweep (swing_trading on russell_1000, 2y)"
$cmd = @(
    "run", "python", "-m", "scripts.sweep_insider_flow",
    "--strategy", "swing_trading",
    "--universe", "russell_1000",
    "--years", "2",
    "--save", "data\sweep_insider_flow_russell1000.json"
)
& uv @cmd 2>&1 | Tee-Object -FilePath $LogFile -Append
$rc = $LASTEXITCODE
Log "launcher: sweep finished with exit code $rc"
exit $rc
