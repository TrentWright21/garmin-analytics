# Pull Garmin history. Usage: .\backfill.ps1        (30 days)
#                             .\backfill.ps1 365    (a full year)
param([int]$Days = 30)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot\backend
& "..\.venv\Scripts\python.exe" -m app.cli backfill --days $Days
