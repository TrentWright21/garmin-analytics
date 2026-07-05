# Sync the most recent days (default 2). Usage: .\sync.ps1
param([int]$Days = 2)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot\backend
if (-not (Test-Path "..\.venv\Scripts\python.exe")) {
    Write-Host "No virtual environment yet - run .\setup.ps1 first." -ForegroundColor Red
    exit 1
}
& "..\.venv\Scripts\python.exe" -m app.cli sync --days $Days
