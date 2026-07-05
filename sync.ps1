# Sync the most recent days (default 2). Usage: .\sync.ps1
param([int]$Days = 2)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot\backend
& "..\.venv\Scripts\python.exe" -m app.cli sync --days $Days
