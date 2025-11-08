<#
.SYNOPSIS
  Create a user-owned virtual environment and install backend dependencies.

.DESCRIPTION
  This script creates a virtual environment under $env:USERPROFILE\venvs\arora-backend,
  installs the project's `requirements.txt`, and can optionally start the FastAPI server.

.PARAMETER InstallOnly
  Only create venv and install dependencies; do not start the server.

.PARAMETER StartServer
  After installing dependencies, start uvicorn on the given Port.

.PARAMETER Port
  Port to run the server on (default 8000).

.EXAMPLE
  .\setup_user_venv.ps1 -InstallOnly
  .\setup_user_venv.ps1 -StartServer -Port 8000
#>
[CmdletBinding()]
param(
    [switch]$InstallOnly,
    [switch]$StartServer,
    [int]$Port = 8000
)

Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectDir = Resolve-Path $ScriptDir
Write-Host "[setup] Project dir: $ProjectDir"

$VenvsRoot = Join-Path $env:USERPROFILE 'venvs'
if (-not (Test-Path $VenvsRoot)) {
    New-Item -ItemType Directory -Path $VenvsRoot | Out-Null
}

$VenvPath = Join-Path $VenvsRoot 'arora-backend'
if (-not (Test-Path $VenvPath)) {
    Write-Host "[setup] Creating venv at: $VenvPath"
    python -m venv $VenvPath
} else {
    Write-Host "[setup] Venv already exists at: $VenvPath"
}

# Determine python executable inside the venv
$PythonExe = Join-Path $VenvPath 'Scripts\python.exe'
if (-not (Test-Path $PythonExe)) {
    Write-Error "[setup] Python executable not found in venv: $PythonExe"
    exit 1
}
Write-Host "[setup] Using python: $PythonExe"

# Upgrade pip and install requirements
Write-Host '[setup] Upgrading pip...'
& $PythonExe -m pip install --upgrade pip

$ReqFile = Join-Path $ProjectDir 'requirements.txt'
if (-not (Test-Path $ReqFile)) {
    Write-Error "[setup] requirements.txt not found in project dir: $ReqFile"
    exit 1
}

Write-Host "[setup] Installing requirements from $ReqFile"
& $PythonExe -m pip install --upgrade --no-cache-dir -r $ReqFile

# Quick check for uvicorn
$check = & $PythonExe -c "import importlib,sys
if importlib.util.find_spec('uvicorn') is None: sys.exit(2)
print('uvicorn ok')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[setup] uvicorn missing; installing uvicorn[standard]"
    & $PythonExe -m pip install --no-cache-dir 'uvicorn[standard]'
} else {
    Write-Host "[setup] uvicorn appears installed"
}

Write-Host '[setup] Installation complete.'
Write-Host "[setup] To activate venv: & '$VenvPath\Scripts\Activate.ps1'"
Write-Host "[setup] To run server manually: `python -m uvicorn app.main:app --host 0.0.0.0 --port $Port --reload` (from project backend dir)"

if ($StartServer -and -not $InstallOnly) {
    Write-Host "[setup] Starting uvicorn on port $Port"
    Push-Location $ProjectDir
  $env:PYTHONPATH = $ProjectDir
  & $PythonExe -m uvicorn app.main:app --host 0.0.0.0 --port $Port --reload
  Pop-Location
}

Write-Host '[setup] Done.'
