# Pull Garmin history. Usage: .\backfill.ps1        (30 days)
#                             .\backfill.ps1 365    (a full year)
param([int]$Days = 30)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot\backend
if (-not (Test-Path "..\.venv\Scripts\python.exe")) {
    Write-Host "No virtual environment yet - run .\setup.ps1 first." -ForegroundColor Red
    exit 1
}
& "..\.venv\Scripts\python.exe" -m app.cli backfill --days $Days
