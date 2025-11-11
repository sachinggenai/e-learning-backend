<#
.SYNOPSIS
  Create a user-owned virtual environment and install backend dependencies.

.DESCRIPTION
  This script creates a virtual environment under $env:USERPROFILE\venvs\arora-backend,
  installs the project's requirements file, and can optionally start the FastAPI server.

.PARAMETER InstallOnly
  Only create venv and install dependencies; do not start the server.

.PARAMETER StartServer
  After installing dependencies, start uvicorn on the given Port.

.PARAMETER Port
  Port to run the server on (default 8000).

.PARAMETER RequirementsFile
  Path to the requirements file (default: requirements.txt).

.PARAMETER AppPath
  Python import path for the FastAPI app (default: app.main:app).

.PARAMETER LogFile
  Optional path to store setup logs.

.EXAMPLE
  .\setup_user_venv.ps1 -InstallOnly
  .\setup_user_venv.ps1 -StartServer -Port 9000 -AppPath 'src.api:app'
#>

[CmdletBinding()]
param(
    [switch]$InstallOnly,
    [switch]$StartServer,
    [int]$Port = 8000,
    [string]$RequirementsFile = 'requirements.txt',
    [string]$AppPath = 'app.main:app',
    [string]$LogFile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --------------------------
# Detect Environment
# --------------------------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectDir = Resolve-Path $ScriptDir
Write-Host "[setup] Project dir: $ProjectDir"

# Verify python is available
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python not found. Please install Python 3.9+ and ensure it's in your PATH."
    exit 1
}

# --------------------------
# Prepare Virtual Environment
# --------------------------
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

# Determine python executable inside the venv (cross-platform)
if ($IsWindows) {
    $PythonExe = Join-Path $VenvPath 'Scripts\python.exe'
    $ActivateCmd = "& '$VenvPath\Scripts\Activate.ps1'"
} else {
    $PythonExe = Join-Path $VenvPath 'bin/python'
    $ActivateCmd = "source '$VenvPath/bin/activate'"
}

if (-not (Test-Path $PythonExe)) {
    Write-Error "[setup] Python executable not found in venv: $PythonExe"
    exit 1
}

Write-Host "[setup] Using python: $PythonExe"

# --------------------------
# Optional Logging
# --------------------------
if ($LogFile) {
    Write-Host "[setup] Logging output to $LogFile"
    Start-Transcript -Path $LogFile -Append
}

try {
    # --------------------------
    # Install Dependencies
    # --------------------------
    Write-Host '[setup] Upgrading pip...'
    & $PythonExe -m pip install --upgrade pip

    $ReqFile = Join-Path $ProjectDir $RequirementsFile
    if (-not (Test-Path $ReqFile)) {
        Write-Error "[setup] Requirements file not found: $ReqFile"
        exit 1
    }

    Write-Host "[setup] Installing requirements from $ReqFile"
    & $PythonExe -m pip install --upgrade --no-cache-dir -r $ReqFile

    # Check for uvicorn
    Write-Host '[setup] Checking uvicorn installation...'
    & $PythonExe -c "import importlib,sys; sys.exit(0 if importlib.util.find_spec('uvicorn') else 2)"
    if ($LASTEXITCODE -eq 2) {
        Write-Host "[setup] Installing uvicorn[standard]"
        & $PythonExe -m pip install --no-cache-dir 'uvicorn[standard]'
    } else {
        Write-Host "[setup] uvicorn appears installed"
    }

    Write-Host '[setup] Installation complete.'
    Write-Host "[setup] To activate venv: $ActivateCmd"
    Write-Host "[setup] To run manually: python -m uvicorn $AppPath --host 0.0.0.0 --port $Port --reload"

    # --------------------------
    # Optionally Start Server
    # --------------------------
    if ($StartServer -and -not $InstallOnly) {
        Write-Host "[setup] Starting uvicorn on port $Port using app '$AppPath'"
        Push-Location $ProjectDir
        $env:PYTHONPATH = $ProjectDir
        & $PythonExe -m uvicorn $AppPath --host 0.0.0.0 --port $Port --reload
        Pop-Location
    }

} finally {
    if ($LogFile) { Stop-Transcript | Out-Null }
}

Write-Host '[setup] Done.'
