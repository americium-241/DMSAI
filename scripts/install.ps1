# DMSAI native installer - Windows / PowerShell
# Usage: .\scripts\install.ps1
#
# Installs Python deps, frontend deps, and PostgreSQL natively (winget),
# then provisions the dmsai role/database.

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root      = Split-Path -Parent $ScriptDir

Set-Location $Root

$PythonExe = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }

# All install logic lives in the canonical Python script.
& $PythonExe (Join-Path $ScriptDir "install.py") $args
exit $LASTEXITCODE
