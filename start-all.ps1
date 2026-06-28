<#
.SYNOPSIS
  Start all e-learning-backend services for local development.

.DESCRIPTION
  Starts services in chronological order with health checks and port conflict
  resolution. Ctrl+C stops Python services (Docker stays running).

  Service startup order:
    Step 0: Port conflict resolution
    Step 1: Docker infrastructure (PostgreSQL, Redis, Redpanda, MinIO)
    Step 2: Database migrations (Alembic)
    Step 3: Optional MCP servers (content_writer, safety_scan, template_registry)
    Step 3a: MCP Core Infrastructure (LLM Gateway :8004, Domain Tools :8005)
    Step 4: FastAPI backend (:8000)

  MCP Architecture requires Ollama running locally (:11434) with models:
    - qwen2.5:7b (GENERATOR)
    - phi3:mini (PLANNER)
    - nomic-embed-text (EMBEDDINGS)

.PARAMETER SkipDocker
  Skip Docker container startup (containers already running elsewhere).

.PARAMETER SkipMcp
  Skip optional MCP protocol adapters (content_writer, safety_scan, template_registry).

.PARAMETER WithMcp
  Force optional MCP adapters even if AI_AUTHORING_ENABLED=false.

.PARAMETER AppPort
  Custom port for FastAPI (default: 8000).

.EXAMPLE
  .\start-all.ps1                          Start everything
  .\start-all.ps1 -SkipDocker              Skip Docker
  .\start-all.ps1 -WithMcp                 Force optional MCP servers
  .\start-all.ps1 -AppPort 8100            Custom app port
#>
param(
    [switch]$SkipDocker,
    [switch]$SkipMcp,
    [switch]$WithMcp,
    [int]$AppPort = 8000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$global:LASTEXITCODE = 0

$AppHost = if ($env:HOST) { $env:HOST } else { "0.0.0.0" }
$McpPorts = @(8001, 8002, 8003)
$McpModules = @(
    "app.mcp.content_writer.server:app",
    "app.mcp.safety_scan.server:app",
    "app.mcp.template_registry.server:app"
)
$McpNames = @("content-writer-mcp", "safety-scan-mcp", "template-registry-mcp")

# MCP Core Infrastructure (LLM Gateway + Domain Tools) — Phase 1-4
$GatewayPort = 8004
$GatewayModule = "app.mcp.llm_gateway.server:app"
$GatewayName = "llm-gateway-mcp"
$DomainPort = 8005
$DomainModule = "app.mcp.domain_tools.server:app"
$DomainName = "domain-tools-mcp"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Push-Location $Root

# --- Helpers -----------------------------------------------------
function Write-Step { Write-Host "`n> $args" -ForegroundColor Cyan }
function Write-Info  { Write-Host "[start-all] $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "[start-all] $args" -ForegroundColor Yellow }
function Write-Err   { Write-Host "[start-all] $args" -ForegroundColor Red }

function Clear-Port {
    param([int]$Port)
    $conns = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
        Where-Object { $_.State -eq 'Listen' }
    if (-not $conns) { return $true }

    foreach ($conn in $conns) {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Warn "Port $Port in use by $($proc.ProcessName) (PID: $($proc.Id)) -- killing stale process"
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            $proc.WaitForExit(5000)
        }
    }
    Start-Sleep -Seconds 1

    # Verify port is free
    $retry = 0
    while ($retry -lt 5) {
        $still = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
            Where-Object { $_.State -eq 'Listen' }
        if (-not $still) {
            Write-Info "Port $Port freed"
            return $true
        }
        Start-Sleep -Seconds 1
        $retry++
    }
    Write-Err "Port $Port could not be freed after 5s"
    return $false
}

function Load-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line -match '^\s*#') { return }
        if ($line -notmatch '=') { return }
        $parts = $line -split '=', 2
        $key = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        [Environment]::SetEnvironmentVariable($key, $value, "Process")
    }
}

# --- Cleanup handler (Ctrl+C) ------------------------------------
$McpJobs = @()
$script:IsCleaningUp = $false

function Invoke-Cleanup {
    if ($script:IsCleaningUp) { return }
    $script:IsCleaningUp = $true
    Write-Host ""
    Write-Host ""
    Write-Warn "Shutting down..."

    foreach ($job in $McpJobs) {
        if ($job.HasExited -eq $false) {
            Stop-Process -Id $job.Id -Force -ErrorAction SilentlyContinue
            Write-Info "Stopped MCP server (PID $($job.Id))"
        }
    }
    Write-Info "FastAPI stopped (foreground process)"
    Write-Host ""
    Write-Host "=============================================="
    Write-Host "  [OK] All Python services stopped" -ForegroundColor Green
    Write-Host "  Docker containers are still running (data preserved)"
    Write-Host "  To stop Docker:  .\stop-all.ps1"
    Write-Host "=============================================="
}

# ================================================================
# MAIN — wrapped so finally always executes on any exit path
# ================================================================
function Main {
    # ============================================================
    # PRE-FLIGHT CHECKS
    # ============================================================
    Write-Host ""
    Write-Host "=============================================="
    Write-Host "  e-Learning Backend - Startup"
    Write-Host "=============================================="
    Write-Host ""

    # Verify we're in the right directory
    if (-not (Test-Path docker-compose.yml) -or -not (Test-Path app/main.py)) {
        Write-Err "This script must be run from the project root directory"
        Write-Err "Expected: docker-compose.yml and app/main.py"
        return 1
    }

    # Determine MCP startup
    $StartMcp = $false
    if ($WithMcp) {
        $StartMcp = $true
    } elseif ($SkipMcp) {
        $StartMcp = $false
    } else {
        if (Test-Path .env) {
            $aiLine = Select-String -Path .env -Pattern '^AI_AUTHORING_ENABLED\s*='
            if ($aiLine) {
                $aiVal = ($aiLine.Line -split '=', 2)[1].Trim().Trim('"').Trim("'")
                if ($aiVal -eq "true") { $StartMcp = $true }
            }
        }
    }

    # Load .env early so health checks use correct credentials
    Load-DotEnv -Path ".env"

    # Read PG credentials from env (with defaults for docker-compose)
    $pgUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "elearning" }
    $pgDb   = if ($env:POSTGRES_DB)   { $env:POSTGRES_DB }   else { "elearning_db" }

    # ============================================================
    # STEP 0 - Port conflict resolution
    # ============================================================
    Write-Step "Step 0: Resolving port conflicts..."

    if (-not $SkipDocker) {
        Write-Info "Docker will manage ports 5432, 6379, 19092, 9000, 9001"
    }

    if (-not (Clear-Port -Port $AppPort)) { return 1 }
    # Clear MCP core ports (always when AI enabled)
    if ($StartMcp) {
        foreach ($port in $McpPorts) {
            Clear-Port -Port $port | Out-Null
        }
    }
    # Gateway + Domain Tools are core MCP infrastructure
    Clear-Port -Port $GatewayPort | Out-Null
    Clear-Port -Port $DomainPort | Out-Null
    Write-Info "Port check complete"

    # ============================================================
    # STEP 1 - Docker infrastructure
    # ============================================================
    if ($SkipDocker) {
        Write-Step "Step 1: SKIPPED (-SkipDocker)"
    } else {
        Write-Step "Step 1: Starting Docker infrastructure..."

        $docker = Get-Command docker -ErrorAction SilentlyContinue
        if (-not $docker) {
            Write-Err "Docker is not installed. Install Docker Desktop from: https://docker.com"
            Write-Err "Or use -SkipDocker if your infrastructure is running elsewhere."
            return 1
        }

        $null = docker info 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Err "Docker daemon is not running. Start Docker Desktop first."
            Write-Err "Or use -SkipDocker if your infrastructure is running elsewhere."
            return 1
        }

        # Check for orphaned containers from prior runs
        $orphans = docker ps -a --filter "name=elearning-" --format "{{.Names}}" 2>$null
        $managed = docker compose -f docker-compose.yml ps -a --format "{{.Names}}" 2>$null
        $stale = $orphans | Where-Object { $_ -notin $managed }
        if ($stale) {
            Write-Warn "Removing orphaned containers: $($stale -join ', ')"
            docker rm -f $stale 2>$null
        }

        # Check if containers exist
        $existing = docker compose -f docker-compose.yml ps -q postgres 2>$null
        if ($existing) {
            Write-Info "Containers exist - starting stopped containers..."
            docker compose -f docker-compose.yml start
        } else {
            Write-Info "Creating and starting containers..."
            docker compose -f docker-compose.yml up -d --remove-orphans
        }

        # Wait for PostgreSQL (hard dependency)
        Write-Info "Waiting for PostgreSQL (timeout: 60s)..."
        $pgReady = $false
        for ($i = 1; $i -le 30; $i++) {
            $null = docker compose -f docker-compose.yml exec -T postgres `
                pg_isready -U $pgUser -d $pgDb 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Info "PostgreSQL is ready"
                $pgReady = $true
                break
            }
            Write-Host "   waiting... ($i/30)" -NoNewline; Write-Host "`r" -NoNewline
            Start-Sleep -Seconds 2
        }
        Write-Host ""
        if (-not $pgReady) {
            Write-Err "PostgreSQL did not become healthy within 60 seconds"
            Write-Err "Check: docker compose -f docker-compose.yml logs postgres"
            return 1
        }

        # Wait for Redpanda (soft dependency)
        Write-Info "Waiting for Redpanda (timeout: 60s)..."
        $rpReady = $false
        for ($i = 1; $i -le 30; $i++) {
            $health = docker compose -f docker-compose.yml exec -T redpanda `
                rpk cluster health 2>$null
            if ($health -match "Healthy: true") {
                Write-Info "Redpanda is ready"
                $rpReady = $true
                break
            }
            Write-Host "   waiting... ($i/30)" -NoNewline; Write-Host "`r" -NoNewline
            Start-Sleep -Seconds 2
        }
        Write-Host ""
        if (-not $rpReady) {
            Write-Warn "Redpanda still starting - Kafka features may be unavailable"
            Write-Warn "Check: docker compose -f docker-compose.yml logs redpanda"
        }

        Write-Info "All infrastructure containers running"
    }

    # ============================================================
    # STEP 2 - Database migrations
    # ============================================================
    Write-Step "Step 2: Running database migrations..."

    $VenvDir = Join-Path $Root ".venv"
    if (-not (Test-Path $VenvDir)) {
        Write-Info "Creating virtual environment (.venv)..."
        python -m venv $VenvDir
    }

    if (Test-Path (Join-Path $VenvDir "Scripts\python.exe")) {
        $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
    } elseif (Test-Path (Join-Path $VenvDir "bin\python")) {
        $VenvPython = Join-Path $VenvDir "bin\python"
    } else {
        Write-Err "Could not find Python in virtual environment at $VenvDir"
        return 1
    }
    Write-Info "Using Python: $VenvPython"

    # Verify Python version (requires 3.12+)
    $pyVer = & $VenvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
    if ($LASTEXITCODE -ne 0 -or [version]$pyVer -lt [version]"3.11") {
        Write-Err "Python 3.11+ required, found: $pyVer"
        & $VenvPython --version
        return 1
    }
    Write-Info "Python version: $pyVer"

    # Install dependencies if uvicorn is missing
    $null = & $VenvPython -c "import uvicorn" 2>&1
    if (-not $?) {
        Write-Info "Installing dependencies (this may take a minute)..."
        $null = & $VenvPython -m pip install --upgrade pip 2>&1
        $null = & $VenvPython -m pip install -r requirements.txt 2>&1
    }

    $null = & $VenvPython -c "import alembic" 2>&1
    if (-not $?) {
        Write-Info "Installing alembic..."
        $null = & $VenvPython -m pip install alembic 2>&1
    }

    $env:PYTHONPATH = $Root
    & $VenvPython -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Alembic migration failed - check your database connection"
        return 1
    }
    Write-Info "Migrations applied"

    # ============================================================
    # STEP 3 - MCP protocol adapters (background)
    # ============================================================
    if ($StartMcp) {
        Write-Step "Step 3: Starting optional MCP servers (background)..."
        for ($i = 0; $i -lt $McpPorts.Count; $i++) {
            $port = $McpPorts[$i]
            $module = $McpModules[$i]
            $name = $McpNames[$i]

            Write-Info "Starting $name on port $port..."
            $proc = Start-Process -FilePath $VenvPython `
                -ArgumentList "-m", "uvicorn", $module, "--host", "0.0.0.0", "--port", $port `
                -WindowStyle Hidden -PassThru
            $McpJobs += $proc
            Start-Sleep -Milliseconds 500
        }
        Write-Info "Optional MCP servers started (PIDs: $($McpJobs.Id -join ', '))"
    } else {
        Write-Step "Step 3: Optional MCP servers SKIPPED (use -WithMcp to force)"
    }

    # ============================================================
    # STEP 3a - MCP Core: LLM Gateway + Domain Tools (always)
    # ============================================================
    Write-Step "Step 3a: Starting MCP Core Infrastructure..."
    Write-Info "  LLM Gateway   (port $GatewayPort) — provider-agnostic LLM access"
    Write-Info "  Domain Tools  (port $DomainPort) — 7 AI tools (list_pages, proposals, validate...)"

    $gw = Start-Process -FilePath $VenvPython `
        -ArgumentList "-m", "uvicorn", $GatewayModule, "--host", "0.0.0.0", "--port", $GatewayPort `
        -WindowStyle Hidden -PassThru
    $McpJobs += $gw
    Start-Sleep -Milliseconds 1500

    $dt = Start-Process -FilePath $VenvPython `
        -ArgumentList "-m", "uvicorn", $DomainModule, "--host", "0.0.0.0", "--port", $DomainPort `
        -WindowStyle Hidden -PassThru
    $McpJobs += $dt
    Start-Sleep -Milliseconds 500

    Write-Info "MCP Core started (Gateway PID: $($gw.Id), Domain Tools PID: $($dt.Id))"

    # ============================================================
    # STEP 4 - FastAPI backend (foreground)
    # ============================================================
    Write-Step "Step 4: Starting FastAPI backend..."

    $pgPort = if ($env:POSTGRES_PORT) { $env:POSTGRES_PORT } else { "5432" }
    $s3Port = if ($env:S3_PORT) { $env:S3_PORT } else { "9000" }
    $s3ConsolePort = if ($env:S3_CONSOLE_PORT) { $env:S3_CONSOLE_PORT } else { "9001" }

    Write-Host ""
    Write-Host "=============================================="
    Write-Host "  [OK] All services starting" -ForegroundColor Green
    Write-Host ""
    Write-Host "  PostgreSQL:  localhost:$pgPort"
    Write-Host "  Redis:       localhost:6379"
    Write-Host "  Redpanda:    localhost:19092 (Kafka) | localhost:19644 (Admin)"
    Write-Host "  MinIO:       localhost:$s3Port (API) | localhost:$s3ConsolePort (Console)"
    Write-Host "  Ollama:      localhost:11434 (qwen2.5:7b, phi3:mini, nomic-embed-text)"
    Write-Host ""
    Write-Host "  --- MCP Architecture ---"
    Write-Host "  LLM Gateway:  http://localhost:$GatewayPort/health"
    Write-Host "  Domain Tools: http://localhost:$DomainPort/health"
    if ($StartMcp) {
        for ($i = 0; $i -lt $McpPorts.Count; $i++) {
            Write-Host "  $($McpNames[$i]): http://localhost:$($McpPorts[$i])/health"
        }
    }
    Write-Host ""
    Write-Host "  FastAPI:     http://$($AppHost):$AppPort"
    Write-Host "  API Docs:    http://$($AppHost):$AppPort/api/v1/docs"
    Write-Host "  Health:      http://$($AppHost):$AppPort/api/v1/health"
    Write-Host ""
    Write-Host "  Press Ctrl+C to stop all Python services"
    Write-Host "  (Docker containers keep running - use stop-all.ps1)"
    Write-Host "=============================================="
    Write-Host ""

    # Start FastAPI in FOREGROUND
    # Ctrl+C is caught so the finally block always executes for cleanup
    try {
        & $VenvPython -m uvicorn app.main:app `
            --host $AppHost `
            --port $AppPort `
            --reload `
            --log-level info
    } catch [System.Management.Automation.BreakException] {
        # User pressed Ctrl+C — uvicorn was interrupted
        Write-Host ""
    }

    return 0
}

# ── Execute Main with guaranteed cleanup ─────────────────────
$exitCode = 0
try {
    $exitCode = Main
} finally {
    Invoke-Cleanup
    Pop-Location
}
exit $exitCode
