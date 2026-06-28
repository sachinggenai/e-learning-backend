<#
.SYNOPSIS
  Gracefully stop all e-learning-backend services (preserves data).

.DESCRIPTION
  Stops MCP protocol adapters, FastAPI backend, and Docker containers.
  All data (database, cache, files, messages) is PRESERVED.
  To also delete data, use reset-all.ps1 instead.

.PARAMETER Status
  Show what's currently running without stopping anything.

.EXAMPLE
  .\stop-all.ps1               Stop everything
  .\stop-all.ps1 -Status        Show running services
#>
param(
    [switch]$Status
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$global:LASTEXITCODE = 0

$AppPort = if ($env:PORT) { [int]$env:PORT } else { 8000 }
$McpPorts = @(8001, 8002, 8003)
$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition

Push-Location $Root
try {
    # --- Helpers -------------------------------------------------
    function Write-Step { Write-Host "[stop-all] $args" -ForegroundColor Green }
    function Write-Warn  { Write-Host "[stop-all] $args" -ForegroundColor Yellow }
    function Write-Err   { Write-Host "[stop-all] $args" -ForegroundColor Red }

    function Stop-ProcessOnPort {
        param([int]$Port, [string]$Label)

        $conns = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
            Where-Object { $_.State -eq 'Listen' }

        if (-not $conns) {
            return $false
        }

        foreach ($conn in $conns) {
            $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Step "Port $Port occupied by $($proc.ProcessName) (PID: $($proc.Id)) -- stopping $Label"
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                $proc.WaitForExit(5000)
                Write-Step "$Label stopped (was PID $($proc.Id))"
            }
        }
        Start-Sleep -Seconds 1
        return $true
    }

    # --- Status-only mode -----------------------------------------
    if ($Status) {
        Write-Host ""
        Write-Host "=============================================="
        Write-Host "  e-Learning Backend - Running Services"
        Write-Host "=============================================="
        Write-Host ""
        Write-Host "  Python processes:"

        $allPorts = @($AppPort) + $McpPorts
        foreach ($port in $allPorts) {
            $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
                Where-Object { $_.State -eq 'Listen' } | Select-Object -First 1
            if ($conn) {
                $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
                $name = if ($proc) { $proc.ProcessName } else { "unknown" }
                Write-Host "    [UP] Port $port - PID $($conn.OwningProcess) ($name)" -ForegroundColor Green
            } else {
                Write-Host "    [--] Port $port - nothing" -ForegroundColor Red
            }
        }

        Write-Host ""
        Write-Host "  Docker containers:"
        $docker = Get-Command docker -ErrorAction SilentlyContinue
        if ($docker) {
            docker compose -f docker-compose.yml ps 2>$null
        } else {
            Write-Host "    Docker not available"
        }
        Write-Host ""
        exit 0
    }

    # ============================================================
    # STOP PHASE 1 - MCP protocol adapters
    # ============================================================
    Write-Host ""
    Write-Host "=============================================="
    Write-Host "  e-Learning Backend - Graceful Stop"
    Write-Host "=============================================="
    Write-Host ""

    Write-Step "Phase 1/3: Stopping MCP protocol adapters..."
    $stoppedMcp = 0
    foreach ($port in $McpPorts) {
        if (Stop-ProcessOnPort -Port $port -Label "MCP server :$port") {
            $stoppedMcp++
        }
    }
    if ($stoppedMcp -eq 0) {
        Write-Step "No MCP servers were running"
    } else {
        Write-Step "Stopped $stoppedMcp MCP server(s)"
    }

    # ============================================================
    # STOP PHASE 2 - FastAPI backend
    # ============================================================
    Write-Host ""
    Write-Step "Phase 2/3: Stopping FastAPI backend..."
    if (Stop-ProcessOnPort -Port $AppPort -Label "FastAPI backend :$AppPort") {
        Write-Step "FastAPI backend stopped"
    } else {
        Write-Step "FastAPI backend was not running on port $AppPort"
    }

    # ============================================================
    # STOP PHASE 3 - Docker infrastructure
    # ============================================================
    Write-Host ""
    Write-Step "Phase 3/3: Stopping Docker infrastructure..."

    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        Write-Warn "Docker not found - skipping container stop"
    } else {
        $null = docker info 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "Docker daemon not running - skipping container stop"
        } elseif (Test-Path docker-compose.yml) {
            docker compose -f docker-compose.yml stop
            Write-Step "Docker containers stopped (data preserved)"
        } else {
            Write-Warn "docker-compose.yml not found - skipping container stop"
        }
    }

    # ============================================================
    # VERIFY - All ports free
    # ============================================================
    Write-Host ""
    Write-Step "Verifying all ports are free..."
    $allClean = $true
    $allPorts = @($AppPort) + $McpPorts
    foreach ($port in $allPorts) {
        $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
            Where-Object { $_.State -eq 'Listen' } | Select-Object -First 1
        if ($conn) {
            Write-Err "Port $port STILL occupied by PID $($conn.OwningProcess)"
            $allClean = $false
        }
    }

    if ($allClean) {
        Write-Host ""
        Write-Host "=============================================="
        Write-Host "  [OK] All services stopped" -ForegroundColor Green
        Write-Host ""
        Write-Host "  App ports 8000-8003: FREE"
        Write-Host "  Docker containers:   STOPPED (data preserved)"
        Write-Host "  Database, cache, files: SAFE"
        Write-Host ""
        Write-Host "  Restart:  .\start-all.ps1"
        Write-Host "  Wipe all: .\reset-all.ps1"
        Write-Host "=============================================="
    } else {
        Write-Host ""
        Write-Err "Some ports could not be freed. You may need to:"
        Write-Err "  1. Manually kill the PIDs listed above"
        Write-Err "  2. Or run: .\reset-all.ps1 (destructive)"
        exit 1
    }

} finally {
    Pop-Location
}
