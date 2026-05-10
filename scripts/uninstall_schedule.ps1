<#
.SYNOPSIS
    Removes the StockScanner Windows Scheduled Tasks.
#>

$ErrorActionPreference = "Stop"
$TaskFolder = "\StockScanner\"

$tasks = Get-ScheduledTask -TaskPath $TaskFolder -ErrorAction SilentlyContinue

if (-not $tasks) {
    Write-Host "No tasks found under $TaskFolder."
    exit 0
}

foreach ($t in $tasks) {
    Unregister-ScheduledTask -TaskPath $TaskFolder -TaskName $t.TaskName -Confirm:$false
    Write-Host "Removed: $TaskFolder$($t.TaskName)"
}

# Try to remove the now-empty folder (best effort — Get-ScheduledTask has no delete-folder cmdlet)
try {
    $svc = New-Object -ComObject "Schedule.Service"
    $svc.Connect()
    $root = $svc.GetFolder("\")
    $root.DeleteFolder("StockScanner", 0)
    Write-Host "Removed empty folder: $TaskFolder"
} catch {
    Write-Host "(Folder $TaskFolder may still exist; safe to ignore.)"
}
