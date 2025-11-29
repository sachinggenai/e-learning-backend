<#
.SYNOPSIS
  First-time setup script for Windows 11 - FastAPI Backend

.DESCRIPTION
  Automated setup script that:
  - Checks Python installation
  - Creates virtual environment
  - Installs dependencies
  - Creates .env file
  - Runs database migrations
  - Starts the development server

.PARAMETER SkipServerStart
  Complete setup but don't start the server automatically

.PARAMETER Port
  Port to run the server on (default: 8000)

.EXAMPLE
  .\setup_windows.ps1
  .\setup_windows.ps1 -SkipServerStart
  .\setup_windows.ps1 -Port 8080
#>

[CmdletBinding()]
param(
    [switch]$SkipServerStart,
    [int]$Port = 8000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Colors for output
function Write-Success { Write-Host "✓ $args" -ForegroundColor Green }
function Write-Info { Write-Host "ℹ $args" -ForegroundColor Cyan }
function Write-Warn { Write-Host "⚠ $args" -ForegroundColor Yellow }
function Write-Fail { Write-Host "✗ $args" -ForegroundColor Red }
function Write-Step { Write-Host "`n▶ $args" -ForegroundColor Magenta }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Push-Location $ScriptDir

try {
    Write-Host "`n╔════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║   FastAPI Backend - Windows 11 Setup     ║" -ForegroundColor Cyan
    Write-Host "╚════════════════════════════════════════════╝`n" -ForegroundColor Cyan

    # Step 1: Check Python Installation
    Write-Step "Checking Python installation..."
    
    $pythonCmd = $null
    try {
        $pythonVersion = & python --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $pythonCmd = "python"
            Write-Success "Found: $pythonVersion"
        }
    } catch {}

    if (-not $pythonCmd) {
        try {
            $pythonVersion = & python3 --version 2>&1
            if ($LASTEXITCODE -eq 0) {
                $pythonCmd = "python3"
                Write-Success "Found: $pythonVersion"
            }
        } catch {}
    }

    if (-not $pythonCmd) {
        Write-Fail "Python is not installed or not in PATH"
        Write-Info "Please install Python 3.10+ from https://www.python.org/downloads/"
        Write-Info "Make sure to check 'Add Python to PATH' during installation"
        exit 1
    }

    # Check Python version
    $versionOutput = & $pythonCmd --version 2>&1
    if ($versionOutput -match "Python (\d+)\.(\d+)") {
        $major = [int]$matches[1]
        $minor = [int]$matches[2]
        if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
            Write-Warn "Python $major.$minor found. Python 3.10+ recommended"
        } else {
            Write-Success "Python version is compatible ($major.$minor)"
        }
    }

    # Step 2: Check PowerShell Execution Policy
    Write-Step "Checking PowerShell execution policy..."
    $policy = Get-ExecutionPolicy -Scope CurrentUser
    if ($policy -eq "Restricted" -or $policy -eq "AllSigned") {
        Write-Warn "Current execution policy: $policy"
        Write-Info "Attempting to set execution policy to RemoteSigned..."
        try {
            Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
            Write-Success "Execution policy updated"
        } catch {
            Write-Warn "Could not update execution policy automatically"
            Write-Info "Please run PowerShell as Administrator and execute:"
            Write-Info "  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser"
        }
    } else {
        Write-Success "Execution policy is compatible: $policy"
    }

    # Step 3: Create Virtual Environment
    Write-Step "Setting up virtual environment..."
    $venvDir = Join-Path $ScriptDir ".venv"
    
    if (Test-Path $venvDir) {
        Write-Info "Virtual environment already exists"
    } else {
        Write-Info "Creating virtual environment..."
        & $pythonCmd -m venv $venvDir
        if ($LASTEXITCODE -ne 0) {
            Write-Fail "Failed to create virtual environment"
            exit 1
        }
        Write-Success "Virtual environment created at .venv"
    }

    # Determine Python executable in venv
    $venvPython = Join-Path $venvDir "Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Fail "Virtual environment Python not found at $venvPython"
        exit 1
    }

    # Step 4: Upgrade pip
    Write-Step "Upgrading pip..."
    & $venvPython -m pip install --upgrade pip --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Success "pip upgraded successfully"
    } else {
        Write-Warn "pip upgrade had issues (continuing anyway)"
    }

    # Step 5: Install Dependencies
    Write-Step "Installing dependencies (this may take a few minutes)..."
    $reqFile = Join-Path $ScriptDir "requirements.txt"
    if (-not (Test-Path $reqFile)) {
        Write-Fail "requirements.txt not found"
        exit 1
    }

    & $venvPython -m pip install -r $reqFile --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Success "All dependencies installed"
    } else {
        Write-Warn "Some dependencies may have installation issues"
    }

    # Step 6: Create .env file if it doesn't exist
    Write-Step "Configuring environment variables..."
    $envFile = Join-Path $ScriptDir ".env"
    $envExample = Join-Path $ScriptDir ".env.example"

    if (Test-Path $envFile) {
        Write-Info ".env file already exists"
    } elseif (Test-Path $envExample) {
        Copy-Item $envExample $envFile
        Write-Success "Created .env file from .env.example"
        Write-Info "You can edit .env to customize configuration"
    } else {
        # Create minimal .env
        $minimalEnv = @"
# FastAPI Backend Configuration
ENVIRONMENT=development
HOST=0.0.0.0
PORT=$Port
CORS_ORIGINS=http://localhost:3000,http://localhost:3001,http://localhost:5173
AUTO_MIGRATE=true
DATABASE_URL=sqlite+aiosqlite:///./data/elearning.db
"@
        Set-Content -Path $envFile -Value $minimalEnv
        Write-Success "Created minimal .env file"
    }

    # Step 7: Create data directory
    Write-Step "Creating data directory..."
    $dataDir = Join-Path $ScriptDir "data"
    if (-not (Test-Path $dataDir)) {
        New-Item -ItemType Directory -Path $dataDir | Out-Null
        Write-Success "Created data directory"
    } else {
        Write-Info "Data directory already exists"
    }

    # Step 8: Run Database Migrations
    Write-Step "Running database migrations..."
    $env:PYTHONPATH = $ScriptDir
    
    # Check if alembic is available
    $alembicCheck = & $venvPython -m alembic --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        try {
            & $venvPython -m alembic upgrade head
            if ($LASTEXITCODE -eq 0) {
                Write-Success "Database migrations completed"
            } else {
                Write-Warn "Database migrations had warnings (may be okay for fresh install)"
            }
        } catch {
            Write-Warn "Could not run migrations: $_"
        }
    } else {
        Write-Info "Alembic not available, skipping migrations"
    }

    # Step 9: Verify Installation
    Write-Step "Verifying installation..."
    
    $checkScript = @"
import sys
try:
    import fastapi
    import uvicorn
    import sqlalchemy
    print("OK")
    sys.exit(0)
except ImportError as e:
    print(f"MISSING: {e}")
    sys.exit(1)
"@
    
    $tempCheck = [IO.Path]::GetTempFileName()
    Set-Content -Path $tempCheck -Value $checkScript
    
    $checkResult = & $venvPython $tempCheck 2>&1
    Remove-Item $tempCheck -ErrorAction SilentlyContinue
    
    if ($checkResult -match "OK") {
        Write-Success "All core packages verified"
    } else {
        Write-Warn "Some packages may be missing: $checkResult"
    }

    # Setup Complete!
    Write-Host "`n╔════════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "║          Setup Complete! ✓                ║" -ForegroundColor Green
    Write-Host "╚════════════════════════════════════════════╝`n" -ForegroundColor Green

    Write-Info "Installation Summary:"
    Write-Host "  • Python: $pythonCmd" -ForegroundColor White
    Write-Host "  • Virtual Environment: .venv\" -ForegroundColor White
    Write-Host "  • Database: data\elearning.db (SQLite)" -ForegroundColor White
    Write-Host "  • Configuration: .env" -ForegroundColor White

    # Step 10: Start Server (optional)
    if (-not $SkipServerStart) {
        Write-Host "`n" -NoNewline
        Write-Step "Starting development server..."
        Write-Info "Server will start on http://localhost:$Port"
        Write-Info "Press CTRL+C to stop the server"
        Write-Info "API Documentation: http://localhost:$Port/docs`n"
        
        Start-Sleep -Seconds 2
        
        $env:PYTHONPATH = $ScriptDir
        & $venvPython -m uvicorn app.main:app --host 0.0.0.0 --port $Port --reload
    } else {
        Write-Host "`n📝 Next Steps:" -ForegroundColor Yellow
        Write-Host "  1. Review/edit .env file if needed" -ForegroundColor White
        Write-Host "  2. Start the server:" -ForegroundColor White
        Write-Host "     .\run_dev.ps1" -ForegroundColor Cyan
        Write-Host "  3. Open API docs:" -ForegroundColor White
        Write-Host "     http://localhost:$Port/docs`n" -ForegroundColor Cyan
    }

} catch {
    Write-Host "`n" -NoNewline
    Write-Fail "Setup failed: $_"
    Write-Info "Stack trace: $($_.ScriptStackTrace)"
    exit 1
} finally {
    Pop-Location
}
