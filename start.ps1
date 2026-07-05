# Start the Garmin Analytics app at http://localhost:3000
# Builds the React dashboard on first run, then serves API + dashboard together.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# 1. Build the dashboard if it hasn't been built yet.
if (Test-Path "frontend\package.json") {
    if (-not (Test-Path "frontend\node_modules")) {
        Write-Host "Installing dashboard dependencies (one-time, 1-2 min)..." -ForegroundColor Cyan
        Push-Location frontend
        npm install --no-fund --no-audit
        Pop-Location
    }
    if (-not (Test-Path "frontend\dist\index.html")) {
        Write-Host "Building dashboard..." -ForegroundColor Cyan
        Push-Location frontend
        npm run build
        Pop-Location
    }
}

# 2. Serve API + built dashboard on port 3000.
Set-Location -Path "$PSScriptRoot\backend"
Write-Host "Starting... open http://localhost:3000 in your browser. Ctrl+C to stop." -ForegroundColor Green
& "..\.venv\Scripts\python.exe" -m uvicorn app.main:app --port 3000
