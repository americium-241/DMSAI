# DMSAI native installer - Windows / PowerShell
# Usage: .\scripts\install.ps1

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir

Set-Location $Root

Write-Host ""
Write-Host "=== DMSAI Native Installer ===" -ForegroundColor Cyan
Write-Host ""

# 1 - Environment file
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[1/5] Created .env from .env.example - fill in your secrets before starting." -ForegroundColor Yellow
} else {
    Write-Host "[1/5] .env already exists, skipping."
}

# 2 - Shared Python packages
Write-Host "[2/5] Installing shared Python packages..."
pip install -e core_framework -e shared
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# 3 - API Gateway dependencies
Write-Host "[3/5] Installing api_gateway dependencies..."
pip install -r api_gateway\requirements.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# 4 - Node dependencies
Write-Host "[4/5] Installing pipeline node dependencies..."
Get-ChildItem "nodes" -Directory | ForEach-Object {
    $req = Join-Path $_.FullName "requirements.txt"
    if (Test-Path $req) {
        Write-Host "      $($_.Name)"
        pip install -r $req
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
}

# 5 - Frontend
Write-Host "[5/5] Installing frontend dependencies (npm install)..."
Set-Location frontend
npm install
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Set-Location ..

Write-Host ""
Write-Host "=== Installation complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Edit .env          - set DMSAI_JWT_SECRET, DMSAI_INTERNAL_API_KEY, and your LLM keys."
Write-Host "  2. Start the stack:   python .\dmsai.py start"
Write-Host "  3. Open the app:      http://localhost:5173"
Write-Host "  4. Default admin:     admin@dmsai.com / admin123"
Write-Host ""
