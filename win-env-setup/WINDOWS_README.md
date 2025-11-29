# 🪟 Windows 11 Setup - README

Complete guide to running the FastAPI eLearning backend on Windows 11.

## 🚀 Super Quick Start (2 minutes)

### Prerequisites
- ✅ Windows 11 (or Windows 10)
- ✅ Python 3.10+ ([Download here](https://www.python.org/downloads/))
- ✅ PowerShell (included with Windows)

### One-Command Setup

```powershell
# Open PowerShell in the backend directory, then run:
.\setup_windows.ps1
```

**That's it!** The script will:
- ✓ Check Python installation
- ✓ Create virtual environment
- ✓ Install all dependencies
- ✓ Configure environment variables
- ✓ Run database migrations
- ✓ Start the development server

**Server runs at:** http://localhost:8000  
**API Docs:** http://localhost:8000/docs

---

## 📚 Documentation Files

We've created multiple guides for different needs:

| File | Purpose | Best For |
|------|---------|----------|
| **WINDOWS_QUICKSTART.md** | Ultra-quick reference | Experienced developers |
| **WINDOWS_SETUP_GUIDE.md** | Comprehensive guide | First-time setup, troubleshooting |
| **setup_windows.ps1** | Automated setup script | Easiest installation |
| **run_dev.ps1** | Daily development script | Running the server |
| **This file** | Overview & navigation | Understanding what's available |

---

## 🎯 Choose Your Setup Method

### Method 1: Automated Script (Recommended)
**Best for:** Everyone, especially beginners

```powershell
.\setup_windows.ps1
```

Handles everything automatically. Just run and go!

---

### Method 2: Daily Development Script
**Best for:** After initial setup

```powershell
.\run_dev.ps1
```

Use this for daily work. Automatically handles:
- Virtual environment
- Port availability
- Dependency checks

---

### Method 3: Manual Setup
**Best for:** Full control, learning, troubleshooting

See **WINDOWS_SETUP_GUIDE.md** for step-by-step manual instructions.

---

## 📖 Quick Reference

### Common Commands

```powershell
# First time setup
.\setup_windows.ps1

# Daily development
.\run_dev.ps1

# Different port
.\run_dev.ps1 -Port 8080

# Reinstall dependencies
.\run_dev.ps1 -Reinstall

# Activate virtual environment manually
.\.venv\Scripts\Activate.ps1

# Run tests
pytest

# Check API health
Invoke-RestMethod http://localhost:8000/api/v1/health
```

### Project Structure

```
backend/
├── app/                    # Application code
│   ├── main.py            # FastAPI app entry point
│   ├── routers/           # API endpoints
│   ├── models/            # Data models
│   ├── services/          # Business logic
│   └── db/                # Database configuration
├── tests/                 # Test suite
├── data/                  # SQLite database (auto-created)
├── .venv/                 # Virtual environment (auto-created)
├── .env                   # Environment config (auto-created)
├── requirements.txt       # Python dependencies
│
├── setup_windows.ps1      # ⭐ Automated setup
├── run_dev.ps1           # ⭐ Daily dev script
├── WINDOWS_QUICKSTART.md # ⭐ Quick reference
└── WINDOWS_SETUP_GUIDE.md # ⭐ Full guide
```

---

## 🔧 Configuration

### Environment Variables (.env)

The setup script creates a `.env` file automatically. You can edit it:

```bash
# Basic Settings
ENVIRONMENT=development
HOST=0.0.0.0
PORT=8000

# Database (SQLite - easiest)
DATABASE_URL=sqlite+aiosqlite:///./data/elearning.db

# Frontend URLs (adjust as needed)
CORS_ORIGINS=http://localhost:3000,http://localhost:5173

# Auto-run migrations on startup
AUTO_MIGRATE=true
```

### PostgreSQL (Optional)

If you prefer PostgreSQL over SQLite:

1. Install PostgreSQL for Windows
2. Create database: `CREATE DATABASE elearning;`
3. Update `.env`:
   ```bash
   DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/elearning
   ```

---

## 🧪 Testing

```powershell
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Run all tests
pytest

# Run specific test file
pytest tests\test_courses_api.py

# Run with coverage
pytest --cov=app tests\

# Run specific test
pytest tests\test_courses_api.py::test_create_course
```

---

## 🌐 API Endpoints

Once running, explore the API:

### Interactive Documentation
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Key Endpoints
- `GET /api/v1/health` - Health check
- `GET /api/v1/courses` - List all courses
- `POST /api/v1/courses` - Create course
- `GET /api/v1/courses/{course_id}` - Get course details
- `PUT /api/v1/courses/{course_id}` - Update course
- `DELETE /api/v1/courses/{course_id}` - Delete course
- `POST /api/v1/export/{course_id}` - Export SCORM package

### Testing with PowerShell

```powershell
# Health check
Invoke-RestMethod http://localhost:8000/api/v1/health

# List courses
Invoke-RestMethod http://localhost:8000/api/v1/courses

# Create a course
$body = @{
    courseId = "test-001"
    title = "My Test Course"
    templates = @()
} | ConvertTo-Json

Invoke-RestMethod -Uri http://localhost:8000/api/v1/courses `
    -Method Post `
    -Body $body `
    -ContentType "application/json"
```

---

## 🐛 Troubleshooting

### "Cannot run script - execution policy"

```powershell
# Run PowerShell as Administrator
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Port 8000 already in use

```powershell
# Option 1: Use different port
.\run_dev.ps1 -Port 8080

# Option 2: Kill process using port 8000
netstat -ano | findstr :8000
taskkill /PID <ProcessID> /F
```

### Python not found

1. Install Python from [python.org](https://www.python.org/downloads/)
2. **Important:** Check "Add Python to PATH" during installation
3. Restart PowerShell after installation

### Module not found errors

```powershell
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Reinstall dependencies
pip install -r requirements.txt

# Or use the run script with reinstall flag
.\run_dev.ps1 -Reinstall
```

### Database errors

```powershell
# Delete and recreate database (SQLite only - CAUTION: deletes data)
Remove-Item .\data\elearning.db

# Recreate with migrations
.\.venv\Scripts\Activate.ps1
alembic upgrade head
```

### More Help

See **WINDOWS_SETUP_GUIDE.md** for detailed troubleshooting section.

---

## 💻 VS Code Setup (Recommended)

### 1. Install Extensions
- Python (by Microsoft)
- Pylance (usually comes with Python extension)

### 2. Select Interpreter
- Press `Ctrl+Shift+P`
- Type: "Python: Select Interpreter"
- Choose: `.venv\Scripts\python.exe`

### 3. Integrated Terminal
The terminal will automatically activate the virtual environment.

### 4. Run/Debug
Press `F5` to start debugging with breakpoints!

---

## 📦 Production Deployment

### Windows Server

For production on Windows Server:

1. **Use Waitress** (more Windows-friendly than Uvicorn):
   ```powershell
   pip install waitress
   waitress-serve --host=0.0.0.0 --port=8000 app.main:app
   ```

2. **Run as Windows Service**:
   - Use NSSM (Non-Sucking Service Manager)
   - Or Windows Task Scheduler

3. **Behind IIS**:
   - Install IIS
   - Use `wfastcgi` module
   - Configure web.config

### Cloud Deployment (Render, Heroku, etc.)

See **DEPLOYMENT.md** for cloud deployment instructions.

---

## 🔗 Related Documentation

- **QUICKSTART.md** - General quickstart (Mac/Linux focus)
- **DEPLOYMENT.md** - Production deployment guide
- **README.md** - Main project documentation
- **API_CURL_COMMANDS.md** - API examples

---

## 🆘 Getting Help

1. **Check Documentation**
   - Read WINDOWS_SETUP_GUIDE.md for detailed instructions
   - Check WINDOWS_QUICKSTART.md for quick commands

2. **API Documentation**
   - Visit http://localhost:8000/docs while server is running

3. **Common Issues**
   - See Troubleshooting section above
   - Check .env file configuration

4. **Error Messages**
   - Server logs appear in terminal
   - Check error details at http://localhost:8000/docs

---

## ✅ Setup Checklist

Before you start:

- [ ] Python 3.10+ installed
- [ ] "Add Python to PATH" was checked during installation
- [ ] PowerShell execution policy configured
- [ ] Downloaded/cloned project to your computer
- [ ] Opened PowerShell in the backend directory

Then run:

- [ ] `.\setup_windows.ps1` (first time)
- [ ] Open http://localhost:8000/docs
- [ ] Test API with sample request

---

## 📞 Support

For issues specific to Windows setup:
1. Check **WINDOWS_SETUP_GUIDE.md** troubleshooting section
2. Verify Python installation: `python --version`
3. Check virtual environment exists: `Test-Path .\.venv`
4. Review server logs in terminal

---

## 🎉 You're Ready!

Once setup is complete:

1. **Server runs at**: http://localhost:8000
2. **API docs at**: http://localhost:8000/docs
3. **Test health**: http://localhost:8000/api/v1/health

### Next Steps:
- Explore the API documentation
- Create your first course
- Export a SCORM package
- Connect your frontend application

**Happy coding!** 🚀
