# Wipe local data for a clean start. Usage: .\reset.ps1
# Deletes data\ (synced history + Garmin login tokens). Keeps .env and the app.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

if (-not (Test-Path "data")) {
    Write-Host "Nothing to reset - no data folder found."
    exit 0
}

Write-Host ""
Write-Host "This deletes ALL synced Garmin history and login tokens in 'data\'." -ForegroundColor Yellow
Write-Host "Your credentials (.env) and the app itself are kept."
Write-Host "The next login will ask for a Garmin MFA code again."
Write-Host "Stop the app first (Ctrl+C in its window) if it is running."
Write-Host ""
$answer = Read-Host "Type RESET to confirm"
if ($answer -cne "RESET") {
    Write-Host "Cancelled - nothing was deleted."
    exit 0
}

try {
    Remove-Item -Recurse -Force "data" -ErrorAction Stop
} catch {
    Write-Host "Could not delete data\ - is the app still running? Stop it and re-run." -ForegroundColor Red
    exit 1
}
Write-Host "Done. data\ deleted. Run .\backfill.ps1 to start fresh." -ForegroundColor Green
