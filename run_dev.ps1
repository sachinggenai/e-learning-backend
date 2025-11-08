<#
.SYNOPSIS
  Windows dev launcher for the FastAPI backend.

.DESCRIPTION
  Creates a virtual environment (if missing), installs dependencies (optionally),
  probes the requested port, sets PYTHONPATH and launches uvicorn using the venv's
  python interpreter. Includes a DryRun mode for safe validation.

.PARAMETER Port
  Port to bind uvicorn to. Defaults to 8000.

.PARAMETER Host
  Host to bind to. Defaults to 0.0.0.0.

.PARAMETER Reinstall
  Force reinstall of requirements.

.PARAMETER ForcePort
  If set, ignore port-in-use checks and attempt to start anyway.

.PARAMETER DryRun
  Print the actions that would be taken without performing them.

#>
param(
    [int]$Port = 8000,
    [string]$Host = '0.0.0.0',
    [switch]$Reinstall,
    [switch]$ForcePort,
    [switch]$DryRun
)

Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Push-Location $Root
try {
    Write-Host "[dev] Root: $Root"

    $VenvDir = Join-Path $Root '.venv'

    if (-not (Test-Path $VenvDir)) {
        Write-Host '[dev] Creating virtual environment (.venv)...'
        if ($DryRun) { Write-Host "[DryRun] python -m venv $VenvDir" } else { python -m venv $VenvDir }
    }

    # Prefer Windows Scripts layout, then POSIX bin
    if (Test-Path (Join-Path $VenvDir 'Scripts\python.exe')) {
        $PythonExe = Join-Path $VenvDir 'Scripts\python.exe'
    } elseif (Test-Path (Join-Path $VenvDir 'bin/python')) {
        $PythonExe = Join-Path $VenvDir 'bin/python'
    } else {
        $PythonExe = 'python'
    }

    Write-Host "[dev] Using python: $PythonExe"

    function Run-Command($cmd) {
        if ($DryRun) { Write-Host "[DryRun] $cmd"; return 0 }
        Write-Host "[dev] Executing: $cmd"
        iex $cmd
        return $LASTEXITCODE
    }

    # Install dependencies if needed
    if ($Reinstall) {
        Write-Host '[dev] Reinstall requested: upgrading pip and reinstalling requirements...'
        if (-not $DryRun) { & $PythonExe -m pip install --upgrade pip }
        Run-Command "& '$PythonExe' -m pip install -r requirements.txt"
    } else {
        # Quick check for uvicorn
        $checkCmd = "try: import uvicorn; print('OK')\\nexcept Exception: import sys; sys.exit(2)"
        $tmpFile = [IO.Path]::GetTempFileName()
        Set-Content -Path $tmpFile -Value $checkCmd -NoNewline -Encoding Ascii
        $proc = & $PythonExe - <<<'PY'
import sys
try:
    import uvicorn
    sys.exit(0)
except Exception:
    sys.exit(2)
PY
        if ($LASTEXITCODE -ne 0) {
            Write-Host '[dev] uvicorn not found in venv; installing requirements...' 
            Run-Command "& '$PythonExe' -m pip install -r requirements.txt"
        } else {
            Write-Host '[dev] uvicorn present; skipping dependency install.'
        }
    }

    # Probe port availability
    function Test-PortAvailable([int]$port) {
        try {
            $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, $port)
            $listener.Start()
            $listener.Stop()
            return $true
        } catch {
            return $false
        }
    }

    if (-not $ForcePort) {
        if (-not (Test-PortAvailable -port $Port)) {
            if ($Port -eq 8000) {
                $Alt = 8100
                Write-Host "[dev] Port 8000 appears busy; falling back to $Alt"
                $Port = $Alt
            } else {
                Write-Error "[dev] Port $Port busy. Use -ForcePort to ignore or choose another port."
                exit 2
            }
        }
    } else {
        Write-Host '[dev] ForcePort set: skipping port probe.'
    }

    # Set PYTHONPATH so 'app' package resolves
    $env:PYTHONPATH = $Root
    Write-Host "[dev] PYTHONPATH set to $env:PYTHONPATH"

    $uvicornCmd = "& '$PythonExe' -m uvicorn app.main:app --host $Host --port $Port --reload"

    if ($DryRun) {
        Write-Host "[DryRun] Would run: $uvicornCmd"
    } else {
        Write-Host "[dev] Starting FastAPI on http://$Host:$Port (reload enabled)"
        iex $uvicornCmd
    }

} finally {
    Pop-Location
}
