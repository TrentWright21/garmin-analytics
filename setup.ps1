# Waypoint - one-time setup for Windows.
# Right-click this file -> Run with PowerShell, or run .\setup.ps1 in a terminal.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "=== Waypoint setup ===" -ForegroundColor Cyan

# 0. Sanity: are we in the right folder?
if (-not (Test-Path "backend\app\cli.py")) {
    Write-Host "ERROR: Can't find backend\app\cli.py next to this script." -ForegroundColor Red
    Write-Host "Make sure you extracted the whole zip and are running setup.ps1 from inside the project folder."
    exit 1
}

# 1. Find Python 3.12+
$py = $null
foreach ($candidate in @("py -3.13", "py -3.12", "python")) {
    try {
        $v = Invoke-Expression "$candidate --version" 2>$null
        if ($v -match "3\.1[2-9]") { $py = $candidate; break }
    } catch {}
}
if (-not $py) {
    Write-Host "ERROR: Python 3.12+ not found. Install it from python.org, then re-run this." -ForegroundColor Red
    exit 1
}
Write-Host "Using $py ($v)"

# 2. Garmin credentials in .env — created interactively, or repaired if .env
#    exists but the login is missing or still the .env.example placeholders.
$envPath = Join-Path $PSScriptRoot ".env"

function Get-DotEnvValue([string]$Key) {
    if (-not (Test-Path $envPath)) { return $null }
    # ReadAllLines auto-detects and strips a UTF-8 BOM if an editor added one.
    foreach ($line in [System.IO.File]::ReadAllLines($envPath)) {
        if ($line -match "^\s*$Key\s*=\s*(.*)$") { return $Matches[1].Trim() }
    }
    return $null
}

$curEmail     = Get-DotEnvValue "GA_GARMIN_EMAIL"
$curPass      = Get-DotEnvValue "GA_GARMIN_PASSWORD"
$placeholders = @($null, "", "you@example.com", "changeme")
$needCreds    = ($placeholders -contains $curEmail) -or ($placeholders -contains $curPass)

if ($needCreds) {
    Write-Host ""
    Write-Host "Enter your Garmin Connect login. It is stored only in .env on this PC"
    Write-Host "and is only ever sent to Garmin itself."
    $email = Read-Host "  Garmin email"
    # -AsSecureString keeps the password off the screen; it is never echoed.
    $secure = Read-Host "  Garmin password (typing is hidden)" -AsSecureString
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $pass = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }

    # Keep any other lines the user added; replace only the two GA_GARMIN_* keys.
    $other = @()
    if (Test-Path $envPath) {
        foreach ($line in [System.IO.File]::ReadAllLines($envPath)) {
            if ($line -notmatch "^\s*GA_GARMIN_(EMAIL|PASSWORD)\s*=") { $other += $line }
        }
    }
    # Write BOM-less UTF-8: File.WriteAllLines uses UTF8 without a byte-order
    # mark, so pydantic-settings can read GA_GARMIN_EMAIL. (Windows PowerShell
    # 5.1's `Set-Content -Encoding utf8` prepends a BOM and breaks env parsing.)
    [System.IO.File]::WriteAllLines(
        $envPath,
        [string[]](@("GA_GARMIN_EMAIL=$email", "GA_GARMIN_PASSWORD=$pass") + $other)
    )
    Write-Host ".env saved with your Garmin login." -ForegroundColor Green
} else {
    Write-Host ".env already has a Garmin login - keeping it."
}

# 3. Virtual environment + dependencies
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    Invoke-Expression "$py -m venv .venv"
}
Write-Host "Installing dependencies (1-2 minutes)..."
& ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& ".venv\Scripts\python.exe" -m pip install --quiet -e "backend[dev]"

# 4. Verify install by running the test suite
Write-Host "Running self-check..."
Push-Location backend
& "..\\.venv\Scripts\python.exe" -m pytest -q
$tests = $LASTEXITCODE
Pop-Location
if ($tests -ne 0) {
    Write-Host "Self-check FAILED - paste the output above to Claude." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps (run these here):" -ForegroundColor Cyan
Write-Host "  1.  .\backfill.ps1        (first pull: your last 30 days from Garmin;"
Write-Host "                             Garmin may ask once for an MFA code)"
Write-Host "  2.  .\start.ps1           (starts the app at http://localhost:3000)"
Write-Host ""
