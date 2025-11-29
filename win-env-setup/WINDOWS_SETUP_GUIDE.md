# Windows 11 Setup Guide - FastAPI Backend

Complete step-by-step guide to set up and run the eLearning FastAPI backend on Windows 11 using PowerShell.

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Initial Setup](#initial-setup)
3. [Quick Start (Recommended)](#quick-start-recommended)
4. [Manual Setup (Alternative)](#manual-setup-alternative)
5. [Database Setup](#database-setup)
6. [Running the Application](#running-the-application)
7. [Testing the API](#testing-the-api)
8. [Troubleshooting](#troubleshooting)
9. [Common Commands](#common-commands)

---

## Prerequisites

### 1. Install Python 3.10 or Higher

**Check if Python is installed:**
```powershell
python --version
```

**If not installed:**
1. Download Python from [python.org](https://www.python.org/downloads/)
2. During installation, **CHECK** "Add Python to PATH"
3. Verify installation:
   ```powershell
   python --version
   pip --version
   ```

### 2. Install Git (Optional, for cloning repository)

Download from [git-scm.com](https://git-scm.com/download/win)

### 3. Install PostgreSQL (Optional, for production-like setup)

Download from [postgresql.org](https://www.postgresql.org/download/windows/)

**For development, SQLite works fine (no additional installation needed).**

---

## Initial Setup

### Step 1: Clone or Download the Repository

**Option A: Using Git**
```powershell
cd $HOME\Documents
git clone https://github.com/sachinggenai/e-learning-backend.git
cd e-learning-backend
```

**Option B: Download ZIP**
1. Download and extract the project ZIP file
2. Open PowerShell and navigate to the project:
   ```powershell
   cd "C:\path\to\e-learning-backend"
   ```

### Step 2: Set PowerShell Execution Policy (One-time setup)

PowerShell restricts script execution by default. Allow scripts to run:

```powershell
# Run PowerShell as Administrator, then execute:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**Confirm the prompt by typing `Y` and pressing Enter.**

---

## Quick Start (Recommended)

### Method 1: Using the Automated Script

The project includes a PowerShell script that handles everything automatically:

```powershell
# Navigate to the backend directory
cd path\to\backend

# Run the development script
.\run_dev.ps1
```

**What this does:**
- Creates a virtual environment (`.venv`) if it doesn't exist
- Installs all required dependencies
- Checks if port 8000 is available (uses 8100 if busy)
- Starts the FastAPI server with hot-reload enabled

**Additional Options:**
```powershell
# Force reinstall dependencies
.\run_dev.ps1 -Reinstall

# Use a different port
.\run_dev.ps1 -Port 8080

# Dry run (see what would happen without executing)
.\run_dev.ps1 -DryRun

# Force using port even if busy
.\run_dev.ps1 -ForcePort
```

### Method 2: Using User-Profile Virtual Environment

This creates a reusable virtual environment in your user profile:

```powershell
# Install dependencies (one-time setup)
.\setup_user_venv.ps1 -InstallOnly

# Start the server
.\setup_user_venv.ps1 -StartServer -Port 8000
```

The virtual environment will be created at:
```
C:\Users\YourUsername\venvs\arora-backend
```

---

## Manual Setup (Alternative)

If you prefer manual control or the scripts don't work:

### Step 1: Create Virtual Environment

```powershell
# Navigate to project directory
cd path\to\backend

# Create virtual environment
python -m venv .venv
```

### Step 2: Activate Virtual Environment

```powershell
# Activate the virtual environment
.\.venv\Scripts\Activate.ps1
```

**You should see `(.venv)` prefix in your PowerShell prompt.**

**Troubleshooting Activation:**
If you get an error about execution policy:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Step 3: Upgrade pip

```powershell
python -m pip install --upgrade pip
```

### Step 4: Install Dependencies

```powershell
# Install all required packages
pip install -r requirements.txt
```

**This installs:**
- FastAPI (web framework)
- Uvicorn (ASGI server)
- SQLAlchemy (database ORM)
- Alembic (database migrations)
- PostgreSQL drivers (optional)
- And all other dependencies

### Step 5: Create Environment Configuration

```powershell
# Copy the example environment file
copy .env.example .env
```

**Edit `.env` file** (use Notepad or VS Code):
```bash
# Minimal configuration for local development
ENVIRONMENT=development
HOST=0.0.0.0
PORT=8000

# For SQLite (default, easiest):
# DATABASE_URL=sqlite+aiosqlite:///./data/elearning.db

# For PostgreSQL (if installed):
# DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/elearning

CORS_ORIGINS=http://localhost:3000,http://localhost:3001,http://localhost:5173
AUTO_MIGRATE=true
```

---

## Database Setup

### Option 1: SQLite (Recommended for Development)

**No setup required!** The database will be created automatically at:
```
backend\data\elearning.db
```

### Option 2: PostgreSQL (Production-like Setup)

**After installing PostgreSQL:**

1. **Open pgAdmin or psql command line**

2. **Create Database:**
   ```sql
   CREATE DATABASE elearning;
   ```

3. **Update `.env` file:**
   ```bash
   DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@localhost:5432/elearning
   ```

4. **Run Migrations:**
   ```powershell
   # Make sure virtual environment is activated
   .\.venv\Scripts\Activate.ps1
   
   # Run database migrations
   alembic upgrade head
   ```

### Seed Template Definitions (Optional)

```powershell
# Activate venv first
.\.venv\Scripts\Activate.ps1

# Run seed script
python scripts\seed_template_definitions.py
```

---

## Running the Application

### Method 1: Using the Run Script (Easiest)

```powershell
.\run_dev.ps1
```

### Method 2: Direct Uvicorn Command

```powershell
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Set PYTHONPATH
$env:PYTHONPATH = $PWD

# Start server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Method 3: Using Python Module

```powershell
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Run with python
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Success Indicators

You should see output like:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [12345] using WatchFiles
INFO:     Started server process [67890]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

---

## Testing the API

### 1. Open API Documentation

**Swagger UI (Interactive):**
```
http://localhost:8000/docs
```

**ReDoc (Alternative):**
```
http://localhost:8000/redoc
```

### 2. Health Check

**Using PowerShell:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/health" -Method Get
```

**Using Browser:**
Navigate to: `http://localhost:8000/api/v1/health`

**Expected Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-11-27T12:34:56.789Z"
}
```

### 3. Test Course API

**Create a sample course:**
```powershell
$body = @{
    courseId = "test-course-001"
    title = "My First Course"
    templates = @()
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8000/api/v1/courses" `
    -Method Post `
    -Body $body `
    -ContentType "application/json"
```

**List all courses:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/courses" -Method Get
```

---

## Troubleshooting

### Issue 1: Port Already in Use

**Error:** `Address already in use`

**Solution 1: Use different port**
```powershell
.\run_dev.ps1 -Port 8080
```

**Solution 2: Kill process on port 8000**
```powershell
# Find process using port
netstat -ano | findstr :8000

# Kill the process (replace PID with actual process ID)
taskkill /PID <PID> /F
```

### Issue 2: Script Execution Policy Error

**Error:** `cannot be loaded because running scripts is disabled`

**Solution:**
```powershell
# Run as Administrator
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Issue 3: Python Not Found

**Error:** `python: command not found`

**Solution:**
1. Reinstall Python with "Add to PATH" checked
2. Or manually add Python to PATH:
   - Search "Environment Variables" in Windows
   - Edit "Path" variable
   - Add: `C:\Python310` (or your Python installation path)

### Issue 4: Module Import Errors

**Error:** `ModuleNotFoundError: No module named 'fastapi'`

**Solution:**
```powershell
# Ensure virtual environment is activated
.\.venv\Scripts\Activate.ps1

# Reinstall dependencies
pip install -r requirements.txt
```

### Issue 5: Database Connection Errors

**For SQLite:**
- Check that `data` directory exists (it will be created automatically)
- Verify `.env` has correct SQLite path

**For PostgreSQL:**
- Verify PostgreSQL service is running:
  ```powershell
  Get-Service -Name postgresql*
  ```
- Check connection string in `.env`
- Test connection with pgAdmin

### Issue 6: CORS Errors from Frontend

**Solution:** Update `.env` file:
```bash
CORS_ORIGINS=http://localhost:3000,http://localhost:5173,http://localhost:3001
```

Add your frontend URL to the list.

---

## Common Commands

### Virtual Environment

```powershell
# Create virtual environment
python -m venv .venv

# Activate
.\.venv\Scripts\Activate.ps1

# Deactivate
deactivate
```

### Package Management

```powershell
# Install dependencies
pip install -r requirements.txt

# Install single package
pip install package-name

# List installed packages
pip list

# Update package
pip install --upgrade package-name
```

### Database Migrations

```powershell
# Run migrations
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "description"

# Show current version
alembic current

# Rollback one migration
alembic downgrade -1
```

### Running Tests

```powershell
# Install dev dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest

# Run specific test file
pytest tests\test_courses_api.py

# Run with coverage
pytest --cov=app tests\
```

### Server Management

```powershell
# Start server (with reload)
.\run_dev.ps1

# Start server (specific port)
.\run_dev.ps1 -Port 8080

# Stop server
# Press CTRL+C in the terminal

# Check if server is running
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/health"
```

### Debugging

```powershell
# Check Python version
python --version

# Check pip version
pip --version

# Check installed packages
pip list

# Check port usage
netstat -ano | findstr :8000

# View server logs
# Logs appear in the terminal where uvicorn is running
```

---

## Next Steps

1. **Configure your frontend** to connect to `http://localhost:8000`
2. **Explore the API** at `http://localhost:8000/docs`
3. **Create courses** using the POST `/api/v1/courses` endpoint
4. **Export SCORM packages** using POST `/api/v1/export/{course_id}`
5. **Read the documentation** in the project's README and other .md files

---

## Development Workflow

### Daily Workflow

```powershell
# 1. Navigate to project
cd path\to\backend

# 2. Activate virtual environment
.\.venv\Scripts\Activate.ps1

# 3. Pull latest changes (if using Git)
git pull

# 4. Install/update dependencies (if requirements changed)
pip install -r requirements.txt

# 5. Run migrations (if database schema changed)
alembic upgrade head

# 6. Start server
.\run_dev.ps1

# 7. Make changes (server auto-reloads)

# 8. Test your changes
pytest

# 9. Stop server (CTRL+C)
```

### Making Code Changes

The development server runs with `--reload` flag, which means:
- **Automatic restart** when you save Python files
- **No need to manually restart** the server
- Changes are reflected immediately

---

## VS Code Setup (Recommended)

If using Visual Studio Code:

### 1. Install Python Extension
- Open VS Code
- Install "Python" extension by Microsoft

### 2. Select Python Interpreter
- Press `Ctrl+Shift+P`
- Type "Python: Select Interpreter"
- Choose `.venv\Scripts\python.exe`

### 3. Configure Integrated Terminal
Add to `.vscode\settings.json`:
```json
{
  "python.defaultInterpreterPath": ".venv\\Scripts\\python.exe",
  "python.terminal.activateEnvironment": true,
  "terminal.integrated.env.windows": {
    "PYTHONPATH": "${workspaceFolder}"
  }
}
```

### 4. Run/Debug Configuration
Add to `.vscode\launch.json`:
```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: FastAPI",
      "type": "python",
      "request": "launch",
      "module": "uvicorn",
      "args": [
        "app.main:app",
        "--reload",
        "--host",
        "0.0.0.0",
        "--port",
        "8000"
      ],
      "jinja": true,
      "justMyCode": true,
      "env": {
        "PYTHONPATH": "${workspaceFolder}"
      }
    }
  ]
}
```

---

## Production Deployment on Windows Server

For production Windows Server deployment:

### 1. Install Python as a Windows Service

Use tools like:
- **NSSM** (Non-Sucking Service Manager)
- **Windows Task Scheduler**

### 2. Use Waitress (Instead of Uvicorn)

Waitress is more Windows-friendly for production:

```powershell
pip install waitress

# Run with waitress
waitress-serve --host=0.0.0.0 --port=8000 app.main:app
```

### 3. IIS with FastAPI

Use `wfastcgi` to run FastAPI behind IIS:
1. Install IIS
2. Install `wfastcgi`
3. Configure web.config

---

## Additional Resources

- **FastAPI Documentation**: https://fastapi.tiangolo.com/
- **Uvicorn Documentation**: https://www.uvicorn.org/
- **SQLAlchemy Documentation**: https://docs.sqlalchemy.org/
- **Alembic Documentation**: https://alembic.sqlalchemy.org/
- **Python Virtual Environments**: https://docs.python.org/3/library/venv.html

---

## Support

For issues or questions:
1. Check the [Troubleshooting](#troubleshooting) section
2. Review project documentation files (README.md, QUICKSTART.md)
3. Check the API docs at `http://localhost:8000/docs`
4. Open an issue on the project repository

---

## Summary

**Quickest way to get started:**

```powershell
# 1. Ensure Python 3.10+ is installed
python --version

# 2. Navigate to project
cd path\to\backend

# 3. Set execution policy (one-time)
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# 4. Run the automated script
.\run_dev.ps1

# 5. Open browser to http://localhost:8000/docs
```

That's it! You're now running the FastAPI backend on Windows 11! 🎉
