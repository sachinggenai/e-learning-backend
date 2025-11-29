# Windows Quick Start Guide

Ultra-quick reference for running the FastAPI backend on Windows 11.

## Prerequisites (5 minutes)

1. **Python 3.10+** - [Download](https://www.python.org/downloads/)
   - ✅ Check "Add Python to PATH" during installation
   
2. **PowerShell Execution Policy** (Run PowerShell as Admin):
   ```powershell
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   ```

## Instant Start (30 seconds)

```powershell
# Navigate to backend folder
cd path\to\backend

# Run the automated script
.\run_dev.ps1
```

**Done!** Server runs at: http://localhost:8000

**API Docs**: http://localhost:8000/docs

## Alternative: Manual Setup

### First Time Setup

```powershell
# 1. Create virtual environment
python -m venv .venv

# 2. Activate it
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy environment file
copy .env.example .env

# 5. Run migrations (optional for SQLite)
alembic upgrade head
```

### Daily Use

```powershell
# Activate environment
.\.venv\Scripts\Activate.ps1

# Start server
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Common Commands

| Task | Command |
|------|---------|
| **Start Server** | `.\run_dev.ps1` |
| **Different Port** | `.\run_dev.ps1 -Port 8080` |
| **Reinstall Deps** | `.\run_dev.ps1 -Reinstall` |
| **Activate venv** | `.\.venv\Scripts\Activate.ps1` |
| **Deactivate venv** | `deactivate` |
| **Run Tests** | `pytest` |
| **Check Health** | `Invoke-RestMethod http://localhost:8000/api/v1/health` |
| **Kill Port 8000** | `netstat -ano \| findstr :8000` then `taskkill /PID <PID> /F` |

## Troubleshooting

### Script Won't Run
```powershell
# Fix execution policy
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Port Already in Use
```powershell
# Use different port
.\run_dev.ps1 -Port 8080

# OR kill process
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

### Module Not Found
```powershell
# Reinstall dependencies
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Python Command Not Found
- Reinstall Python
- Check "Add Python to PATH" during installation
- Restart PowerShell/Terminal

## Environment Variables (.env)

Minimal configuration for local development:

```bash
ENVIRONMENT=development
HOST=0.0.0.0
PORT=8000
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
AUTO_MIGRATE=true
```

## Database Options

### SQLite (Default - No Setup Required)
```bash
# In .env file (or leave blank for default)
DATABASE_URL=sqlite+aiosqlite:///./data/elearning.db
```

### PostgreSQL (Optional)
```bash
# Install PostgreSQL, then:
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/elearning
```

## Quick Health Check

```powershell
# PowerShell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/health"

# Browser
http://localhost:8000/api/v1/health
```

Expected Response:
```json
{
  "status": "healthy",
  "timestamp": "2025-11-27T12:34:56.789Z"
}
```

## VS Code Integration

1. Install Python extension
2. Press `Ctrl+Shift+P` → "Python: Select Interpreter"
3. Choose `.venv\Scripts\python.exe`
4. Terminal will auto-activate venv

## Production Mode (Windows Server)

Use Waitress instead of Uvicorn:

```powershell
pip install waitress
waitress-serve --host=0.0.0.0 --port=8000 app.main:app
```

## Need More Help?

📚 **Full Guide**: Read `WINDOWS_SETUP_GUIDE.md` for detailed instructions

🌐 **API Docs**: http://localhost:8000/docs

📖 **Project Docs**: `README.md`, `QUICKSTART.md`

---

**That's it!** You should be up and running in under 2 minutes. 🚀
