<#
.SYNOPSIS
  DESTRUCTIVE reset of all e-learning-backend services & data.

.DESCRIPTION
  ⚠️  WARNING: This DELETES ALL DATA — database, cache, files, messages.
  Cannot be undone. For a non-destructive stop, use stop-all.ps1.

.PARAMETER Force
  Skip confirmation prompt (for CI/CD usage).

.EXAMPLE
  .\reset-all.ps1              Interactive — prompts for confirmation
  .\reset-all.ps1 -Force       Non-interactive (CI/CD)
#>
param(
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$AppPort = if ($env:PORT) { [int]$env:PORT } else { 8000 }
$McpPorts = @(8001, 8002, 8003)
$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition

Push-Location $Root
try {
    # ── Helpers ────────────────────────────────────────────────
    function Write-Info { Write-Host "[reset-all] $args" -ForegroundColor Green }
    function Write-Warn { Write-Host "[reset-all] $args" -ForegroundColor Yellow }
    function Write-Err  { Write-Host "[reset-all] $args" -ForegroundColor Red }

    # ═══════════════════════════════════════════════════════════
    # CONFIRMATION GATE
    # ═══════════════════════════════════════════════════════════
    Write-Host ""
    Write-Host "╔══════════════════════════════════════════════════════╗" -ForegroundColor Red
    Write-Host "║  ⚠️  DESTRUCTIVE RESET — ALL DATA WILL BE DELETED  ⚠️  ║" -ForegroundColor Red
    Write-Host "╚══════════════════════════════════════════════════════╝" -ForegroundColor Red
    Write-Host ""
    Write-Host "  This will PERMANENTLY DELETE:"
    Write-Host "    • All database tables and rows (PostgreSQL)"
    Write-Host "    • All cached data (Redis)"
    Write-Host "    • All uploaded files and exports (MinIO)"
    Write-Host "    • All message queue topics and messages (Redpanda)"
    Write-Host "    • All Docker volumes (pgdata, redisdata, rpdata, miniodata)"
    Write-Host ""
    Write-Host "  This CANNOT be undone."
    Write-Host ""

    if ($Force) {
        Write-Warn "-Force flag set — skipping confirmation prompt"
    } else {
        $confirm = Read-Host "  Type 'delete everything' to confirm"
        if ($confirm -ne "delete everything") {
            Write-Host ""
            Write-Info "Cancelled — nothing was deleted."
            Write-Host "  For a non-destructive stop, use: .\stop-all.ps1"
            exit 0
        }
        Write-Host ""
    }

    # ═══════════════════════════════════════════════════════════
    # PHASE 1 — Kill all Python processes
    # ═══════════════════════════════════════════════════════════
    Write-Info "Phase 1/3: Killing Python services..."
    $stopped = 0
    $allPorts = @($AppPort) + $McpPorts

    foreach ($port in $allPorts) {
        $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
            Where-Object { $_.State -eq 'Listen' }
        foreach ($conn in $conns) {
            $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Info "Killing process on port $port — $($proc.ProcessName) (PID: $($proc.Id))"
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                $stopped++
            }
        }
    }

    if ($stopped -eq 0) {
        Write-Info "No Python services were running"
    } else {
        Write-Info "Killed $stopped Python process(es)"
    }
    Start-Sleep -Seconds 1

    # ═══════════════════════════════════════════════════════════
    # PHASE 2 — Destroy Docker containers + volumes
    # ═══════════════════════════════════════════════════════════
    Write-Info "Phase 2/3: Destroying Docker containers and volumes..."

    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        Write-Warn "Docker not found — skipping container teardown"
    } else {
        docker info 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "Docker daemon not running — skipping container teardown"
        } elseif (Test-Path docker-compose.yml) {
            docker compose -f docker-compose.yml down -v
            Write-Info "Containers stopped and volumes DELETED"
        } else {
            Write-Warn "docker-compose.yml not found — skipping"
        }
    }

    # ═══════════════════════════════════════════════════════════
    # PHASE 3 — Verify clean state
    # ═══════════════════════════════════════════════════════════
    Write-Info "Phase 3/3: Verifying clean state..."
    $allClean = $true

    foreach ($port in $allPorts) {
        $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
            Where-Object { $_.State -eq 'Listen' } | Select-Object -First 1
        if ($conn) {
            Write-Err "Port $port still occupied by PID $($conn.OwningProcess)"
            $allClean = $false
        }
    }

    if ($allClean) {
        Write-Host ""
        Write-Host "══════════════════════════════════════════════"
        Write-Host "  ✅ Reset complete" -ForegroundColor Green
        Write-Host ""
        Write-Host "  All services:       STOPPED"
        Write-Host "  All data:           DELETED"
        Write-Host "  Docker volumes:     REMOVED"
        Write-Host "  Python processes:   KILLED"
        Write-Host ""
        Write-Host "  Fresh start:  .\start-all.ps1"
        Write-Host "══════════════════════════════════════════════"
    } else {
        Write-Host ""
        Write-Err "Some resources could not be cleaned. Check the errors above."
        exit 1
    }

} finally {
    Pop-Location
}
