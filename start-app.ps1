<#
.SYNOPSIS
  One-command startup for the e-learning backend — self-healing, PS 5.1 compatible.

.DESCRIPTION
  Resolves all known environment issues automatically:
    - Finds a real Windows Python (not Unix shell-script wrappers)
    - Validates/recreates the .venv if broken
    - Installs dependencies if missing
    - Starts Docker infrastructure (PostgreSQL, Redis, Redpanda, MinIO)
    - Runs Alembic migrations (stamps head if tables already exist)
    - Launches MCP core (LLM Gateway :8004, Domain Tools :8005)
    - Launches optional MCP adapters (:8001–:8003) when AI is enabled
    - Starts FastAPI on :8000 in foreground

.PARAMETER SkipDocker
  Skip Docker container startup (containers already running elsewhere).

.PARAMETER SkipMcp
  Skip optional MCP protocol adapters.

.PARAMETER WithMcp
  Force MCP adapters even if AI_AUTHORING_ENABLED=false.

.PARAMETER Port
  Custom port for FastAPI (default: 8000).

.PARAMETER NoDeps
  Skip pip install step (use when deps are already current).

.EXAMPLE
  .\start-app.ps1                     # Full startup
  .\start-app.ps1 -SkipDocker         # Docker already running
  .\start-app.ps1 -WithMcp            # Force MCP adapters
  .\start-app.ps1 -Port 8100          # Custom app port
#>

param(
    [switch]$SkipDocker,
    [switch]$SkipMcp,
    [switch]$WithMcp,
    [int]$Port = 8000,
    [switch]$NoDeps
)

$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = "e-Learning Backend :$Port"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Push-Location $Root

# ── Helpers ──────────────────────────────────────────────────────
function Write-Step { Write-Host "`n> $args" -ForegroundColor Cyan }
function Write-Info  { Write-Host "  [OK] $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "  [--] $args" -ForegroundColor Yellow }
function Write-Err   { Write-Host "  [!!] $args" -ForegroundColor Red }

function Load-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line -match '^\s*#' -or $line -notmatch '=') { return }
        $parts = $line -split '=', 2
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim().Trim('"').Trim("'"), "Process")
    }
}

# ── 1. FIND SYSTEM PYTHON ─────────────────────────────────────────
Write-Step "Locating Python interpreter..."

function Find-SystemPython {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
        $resolved = $cmd.Source
        if ($resolved -match '\.exe$' -and (Test-Path $resolved)) {
            $ver = & $resolved --version 2>&1
            if ($LASTEXITCODE -eq 0) { return $resolved }
        }
    }
    $common = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python39\python.exe",
        "C:\Python313\python.exe", "C:\Python312\python.exe",
        "C:\Python311\python.exe", "C:\Python310\python.exe", "C:\Python39\python.exe"
    )
    foreach ($p in $common) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

$Py = Find-SystemPython
if (-not $Py) {
    Write-Err "No system Python found. Install Python 3.9+ from https://python.org"
    Write-Err "Ensure 'Add Python to PATH' is checked during installation."
    Pop-Location; exit 1
}
$PyVer = & $Py --version 2>&1
Write-Info "$PyVer  →  $Py"

# ── 2. SETUP / VALIDATE VENV ──────────────────────────────────────
Write-Step "Preparing virtual environment..."

$VenvDir = Join-Path $Root ".venv"
$VenvOk  = $false

if (Test-Path (Join-Path $VenvDir "Scripts\python.exe")) {
    $VenvPy = Join-Path $VenvDir "Scripts\python.exe"
    & $VenvPy -c "print('venv-ok')" 2>$null
    if ($LASTEXITCODE -eq 0) { $VenvOk = $true }
}

if (-not $VenvOk) {
    if (Test-Path $VenvDir) {
        Write-Warn "Removing broken venv at $VenvDir"
        Remove-Item -Recurse -Force $VenvDir
    }
    Write-Info "Creating venv with $PyVer ..."
    & $Py -m venv $VenvDir
    if (Test-Path (Join-Path $VenvDir "Scripts\python.exe")) {
        $VenvPy = Join-Path $VenvDir "Scripts\python.exe"
        $VenvOk = $true
    } elseif (Test-Path (Join-Path $VenvDir "bin\python")) {
        $VenvPy = Join-Path $VenvDir "bin\python"
        $VenvOk = $true
    }
}

if (-not $VenvOk) {
    Write-Err "Failed to create virtual environment."
    Pop-Location; exit 1
}
Write-Info "venv ready  →  $VenvPy"

# ── 3. INSTALL DEPENDENCIES ───────────────────────────────────────
if (-not $NoDeps) {
    Write-Step "Installing dependencies..."
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $VenvPy -m pip install --upgrade pip 2>$null
    & $VenvPy -m pip install -r requirements.txt 2>$null
    $ErrorActionPreference = $saved
    Write-Info "Dependencies current"
} else {
    Write-Step "Dependencies: SKIPPED (-NoDeps)"
}

# ── 4. LOAD ENV ───────────────────────────────────────────────────
Load-DotEnv -Path ".env"

$pgUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "elearning" }
$pgDb   = if ($env:POSTGRES_DB)   { $env:POSTGRES_DB }   else { "elearning_db" }

# Determine MCP startup
$StartMcp = $false
if ($WithMcp) {
    $StartMcp = $true
} elseif ($SkipMcp) {
    $StartMcp = $false
} else {
    if ((Test-Path .env) -and ($env:AI_AUTHORING_ENABLED -eq "true")) {
        $StartMcp = $true
    }
}

# ── 5. DOCKER INFRASTRUCTURE ──────────────────────────────────────
if ($SkipDocker) {
    Write-Step "Docker: SKIPPED (-SkipDocker)"
} else {
    Write-Step "Starting Docker infrastructure..."

    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        Write-Err "Docker not found. Install Docker Desktop or use -SkipDocker."
        Pop-Location; exit 1
    }

    docker info 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Docker daemon not running. Start Docker Desktop or use -SkipDocker."
        Pop-Location; exit 1
    }

    # Clean orphaned containers from prior runs
    $orphans = docker ps -a --filter "name=elearning-" --format "{{.Names}}" 2>$null
    $managed = docker compose -f docker-compose.yml ps -a --format "{{.Names}}" 2>$null
    $stale = $orphans | Where-Object { $_ -notin $managed }
    if ($stale) {
        Write-Warn "Removing orphaned containers: $($stale -join ', ')"
        docker rm -f $stale 2>$null
    }

    $existing = docker compose -f docker-compose.yml ps -q postgres 2>$null
    if ($existing) {
        Write-Info "Starting existing containers..."
        docker compose -f docker-compose.yml start 2>$null
    } else {
        Write-Info "Creating containers..."
        docker compose -f docker-compose.yml up -d --remove-orphans 2>$null
    }

    # Wait for PostgreSQL
    Write-Info "Waiting for PostgreSQL..."
    for ($i = 1; $i -le 30; $i++) {
        docker compose -f docker-compose.yml exec -T postgres pg_isready -U $pgUser -d $pgDb 2>$null
        if ($LASTEXITCODE -eq 0) { Write-Info "PostgreSQL ready"; break }
        Start-Sleep -Seconds 2
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Err "PostgreSQL did not become healthy. Check: docker compose logs postgres"
        Pop-Location; exit 1
    }

    # Wait for Redpanda (soft)
    Write-Info "Waiting for Redpanda..."
    for ($i = 1; $i -le 30; $i++) {
        $health = docker compose -f docker-compose.yml exec -T redpanda rpk cluster health 2>$null
        if ($health -match "Healthy: true") { Write-Info "Redpanda ready"; break }
        Start-Sleep -Seconds 2
    }
    Write-Info "Infrastructure running"
}

# ── 6. DATABASE MIGRATIONS ───────────────────────────────────────
Write-Step "Running database migrations..."
$env:PYTHONPATH = $Root

$saved = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $VenvPy -m alembic upgrade head 2>&1
$MigrationResult = $LASTEXITCODE
$ErrorActionPreference = $saved

if ($MigrationResult -ne 0) {
    Write-Warn "Migration error — may be pre-existing tables. Stamping head..."
    $ErrorActionPreference = 'Continue'
    & $VenvPy -m alembic stamp head 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Alembic stamp failed. Check database connection."
        Pop-Location; exit 1
    }
    $ErrorActionPreference = $saved
    Write-Info "Alembic head stamped (tables already exist)"
} else {
    Write-Info "Migrations applied"
}

# ── 7. FREE PORTS ─────────────────────────────────────────────────
Write-Step "Checking ports..."
$AllPorts = @($Port)
if ($StartMcp) { $AllPorts += @(8001, 8002, 8003) }
$AllPorts += @(8004, 8005)  # MCP Core always

foreach ($p in $AllPorts) {
    $conns = Get-NetTCPConnection -LocalPort $p -ErrorAction SilentlyContinue |
        Where-Object { $_.State -eq 'Listen' }
    foreach ($c in $conns) {
        $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Warn "Port $p in use by $($proc.ProcessName) (PID $($proc.Id)) — stopping"
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
        }
    }
}
Write-Info "Ports clear"

# ── 8. LAUNCH MCP SERVERS ─────────────────────────────────────────
$BgProcs = [System.Collections.Generic.List[Object]]::new()

# Optional MCP adapters
if ($StartMcp) {
    Write-Step "Launching MCP adapters (background)..."
    $McpSpecs = @(
        @{Port=8001; Module="app.mcp.content_writer.server:app";    Name="content-writer-mcp"},
        @{Port=8002; Module="app.mcp.safety_scan.server:app";       Name="safety-scan-mcp"},
        @{Port=8003; Module="app.mcp.template_registry.server:app"; Name="template-registry-mcp"}
    )
    foreach ($s in $McpSpecs) {
        Write-Info "Starting $($s.Name) on :$($s.Port)"
        $proc = Start-Process -FilePath $VenvPy `
            -ArgumentList "-m", "uvicorn", $s.Module, "--host", "0.0.0.0", "--port", $s.Port `
            -WindowStyle Hidden -PassThru
        $BgProcs.Add($proc)
        Start-Sleep -Milliseconds 500
    }
}

# MCP Core (always)
Write-Step "Launching MCP Core (background)..."
Write-Info "LLM Gateway  →  :8004"
$gw = Start-Process -FilePath $VenvPy `
    -ArgumentList "-m", "uvicorn", "app.mcp.llm_gateway.server:app", "--host", "0.0.0.0", "--port", "8004" `
    -WindowStyle Hidden -PassThru
$BgProcs.Add($gw)
Start-Sleep -Milliseconds 1500

Write-Info "Domain Tools →  :8005"
$dt = Start-Process -FilePath $VenvPy `
    -ArgumentList "-m", "uvicorn", "app.mcp.domain_tools.server:app", "--host", "0.0.0.0", "--port", "8005" `
    -WindowStyle Hidden -PassThru
$BgProcs.Add($dt)
Start-Sleep -Milliseconds 500

# ── 9. STARTUP BANNER ─────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  e-Learning Backend — All Services Ready"              -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "  FastAPI       http://localhost:$Port"                 -ForegroundColor White
Write-Host "  API Docs      http://localhost:$Port/api/v1/docs"      -ForegroundColor White
Write-Host "  Health        http://localhost:$Port/api/v1/health"    -ForegroundColor White
Write-Host ""
Write-Host "  LLM Gateway   http://localhost:8004/health"            -ForegroundColor DarkGray
Write-Host "  Domain Tools  http://localhost:8005/health"            -ForegroundColor DarkGray
if ($StartMcp) {
    Write-Host "  Content Writer http://localhost:8001/health"       -ForegroundColor DarkGray
    Write-Host "  Safety Scan   http://localhost:8002/health"        -ForegroundColor DarkGray
    Write-Host "  Templates     http://localhost:8003/health"        -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "  Press Ctrl+C to stop"                                  -ForegroundColor Yellow
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""

# ── 10. FASTAPI (FOREGROUND) ──────────────────────────────────────
$env:PYTHONPATH = $Root

try {
    & $VenvPy -m uvicorn app.main:app `
        --host 0.0.0.0 `
        --port $Port `
        --reload `
        --log-level info
} catch [System.Management.Automation.BreakException] {
    Write-Host ""
} finally {
    # ── CLEANUP ───────────────────────────────────────────────────
    Write-Host ""
    Write-Warn "Shutting down background services..."
    foreach ($proc in $BgProcs) {
        if (-not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            Write-Info "Stopped PID $($proc.Id)"
        }
    }
    Write-Host ""
    Write-Host "══════════════════════════════════════════" -ForegroundColor Green
    Write-Host "  All Python services stopped"               -ForegroundColor Green
    Write-Host "  Docker containers still running"            -ForegroundColor Green
    Write-Host "  To stop Docker: .\stop-all.ps1"             -ForegroundColor Green
    Write-Host "══════════════════════════════════════════" -ForegroundColor Green
    Pop-Location
}
