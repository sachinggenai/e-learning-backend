# Windows 11 Setup - Complete Resource Guide

This document provides an overview of all Windows-specific resources created for setting up and running the FastAPI backend on Windows 11.

## 📂 Available Resources

### 📄 Documentation Files

| File | Purpose | When to Use |
|------|---------|-------------|
| **WINDOWS_README.md** | Main Windows guide with navigation | Start here - overview of all resources |
| **WINDOWS_QUICKSTART.md** | Ultra-quick reference card | Quick lookup of commands and troubleshooting |
| **WINDOWS_SETUP_GUIDE.md** | Comprehensive step-by-step guide | First-time setup, detailed instructions, troubleshooting |

### 🔧 PowerShell Scripts

| Script | Purpose | When to Use |
|--------|---------|-------------|
| **setup_windows.ps1** | Automated first-time setup | ⭐ Best for: Initial installation |
| **run_dev.ps1** | Daily development launcher | ⭐ Best for: Daily development work |
| **setup_user_venv.ps1** | User-profile virtual environment | Alternative setup method |
| **troubleshoot_windows.ps1** | Diagnostic and troubleshooting | When something isn't working |
| **setup-env.ps1** | Environment setup utility | Advanced configuration |

## 🚀 Quick Start Paths

Choose the path that fits your situation:

### Path 1: Brand New User (Recommended)
```powershell
# 1. Read the overview
cat .\WINDOWS_README.md

# 2. Run automated setup
.\setup_windows.ps1

# 3. Start coding!
```

### Path 2: Experienced Developer
```powershell
# 1. Quick reference
cat .\WINDOWS_QUICKSTART.md

# 2. Run development server
.\run_dev.ps1
```

### Path 3: Troubleshooting Issues
```powershell
# 1. Run diagnostics
.\troubleshoot_windows.ps1

# 2. Auto-fix issues
.\troubleshoot_windows.ps1 -Fix

# 3. Check detailed guide
cat .\WINDOWS_SETUP_GUIDE.md
```

## 📖 Documentation Deep Dive

### WINDOWS_README.md
- **Size**: Comprehensive overview
- **Covers**: All methods, quick reference, VS Code setup
- **Best for**: Understanding available options
- **Read time**: 10 minutes

### WINDOWS_SETUP_GUIDE.md
- **Size**: Very detailed (longest document)
- **Covers**: Step-by-step instructions, manual setup, troubleshooting, common commands
- **Best for**: First-time Windows users, troubleshooting problems
- **Read time**: 20-30 minutes (or use as reference)

### WINDOWS_QUICKSTART.md
- **Size**: Compact reference card
- **Covers**: Essential commands and quick fixes
- **Best for**: Quick lookups, daily reference
- **Read time**: 2 minutes

## 🛠️ Script Details

### setup_windows.ps1
**Full automated setup script**

Features:
- ✅ Checks Python installation and version
- ✅ Configures PowerShell execution policy
- ✅ Creates virtual environment
- ✅ Installs all dependencies
- ✅ Creates .env configuration file
- ✅ Creates data directory
- ✅ Runs database migrations
- ✅ Verifies installation
- ✅ Starts development server

Usage:
```powershell
# Full setup with auto-start
.\setup_windows.ps1

# Setup only (no server start)
.\setup_windows.ps1 -SkipServerStart

# Custom port
.\setup_windows.ps1 -Port 8080
```

### run_dev.ps1
**Daily development script**

Features:
- ✅ Creates venv if missing
- ✅ Auto-installs dependencies if needed
- ✅ Checks port availability
- ✅ Auto-switches to alternate port if 8000 busy
- ✅ Sets PYTHONPATH correctly
- ✅ Starts server with hot-reload

Usage:
```powershell
# Standard run
.\run_dev.ps1

# Custom port
.\run_dev.ps1 -Port 8080

# Force reinstall dependencies
.\run_dev.ps1 -Reinstall

# Dry run (see what would happen)
.\run_dev.ps1 -DryRun

# Force port even if busy
.\run_dev.ps1 -ForcePort
```

### troubleshoot_windows.ps1
**Diagnostic and auto-fix tool**

Checks:
- ✅ Python installation and version
- ✅ PowerShell execution policy
- ✅ Virtual environment health
- ✅ Required dependencies
- ✅ Port availability
- ✅ Database configuration
- ✅ File permissions
- ✅ Network connectivity

Usage:
```powershell
# Check for issues
.\troubleshoot_windows.ps1

# Check and auto-fix
.\troubleshoot_windows.ps1 -Fix
```

### setup_user_venv.ps1
**Alternative setup method (user profile venv)**

Creates virtual environment in `C:\Users\YourName\venvs\arora-backend`

Usage:
```powershell
# Install only
.\setup_user_venv.ps1 -InstallOnly

# Install and start
.\setup_user_venv.ps1 -StartServer
```

## 🎯 Common Scenarios

### Scenario 1: First Time Setup
```powershell
# Step 1: Read overview
Start .\WINDOWS_README.md

# Step 2: Run automated setup
.\setup_windows.ps1

# Step 3: Verify
Invoke-RestMethod http://localhost:8000/api/v1/health
```

### Scenario 2: Daily Development
```powershell
# Start server
.\run_dev.ps1

# Make changes (auto-reload works)

# Stop server (Ctrl+C)
```

### Scenario 3: Something Broke
```powershell
# Step 1: Run diagnostics
.\troubleshoot_windows.ps1 -Fix

# Step 2: If still broken, check detailed guide
Start .\WINDOWS_SETUP_GUIDE.md

# Step 3: Nuclear option - fresh install
Remove-Item -Recurse .venv
.\setup_windows.ps1
```

### Scenario 4: Port Already in Use
```powershell
# Option 1: Use different port
.\run_dev.ps1 -Port 8080

# Option 2: Kill process and try again
netstat -ano | findstr :8000
taskkill /PID <ProcessID> /F
.\run_dev.ps1
```

### Scenario 5: Fresh Clone/Pull
```powershell
# After git pull with new dependencies
.\run_dev.ps1 -Reinstall
```

## 📊 Feature Comparison

| Feature | setup_windows.ps1 | run_dev.ps1 | troubleshoot_windows.ps1 |
|---------|-------------------|-------------|--------------------------|
| First-time setup | ✅ Best | ⚠️ Can work | ❌ No |
| Daily use | ❌ Overkill | ✅ Best | ❌ No |
| Diagnostics | ⚠️ Some checks | ⚠️ Basic checks | ✅ Comprehensive |
| Auto-fix issues | ⚠️ Setup only | ⚠️ Limited | ✅ Yes |
| Install dependencies | ✅ Always | ⚠️ If needed | ✅ If needed |
| Run migrations | ✅ Yes | ❌ No | ❌ No |
| Start server | ✅ Default | ✅ Always | ❌ No |

## 🎓 Learning Path

### Beginner (Never used FastAPI/Python on Windows)
1. Read **WINDOWS_README.md** (10 min)
2. Read **WINDOWS_SETUP_GUIDE.md** - Introduction section (5 min)
3. Run `.\setup_windows.ps1`
4. Read **WINDOWS_QUICKSTART.md** for reference
5. Explore API at http://localhost:8000/docs

### Intermediate (Know Python, new to this project)
1. Skim **WINDOWS_QUICKSTART.md** (2 min)
2. Run `.\run_dev.ps1`
3. Keep **WINDOWS_QUICKSTART.md** open for reference

### Advanced (Just need the commands)
```powershell
.\run_dev.ps1
```

## 🔍 Troubleshooting Decision Tree

```
Problem?
│
├─ Don't know what's wrong
│  └─ Run: .\troubleshoot_windows.ps1 -Fix
│
├─ Python not found
│  └─ Check: WINDOWS_SETUP_GUIDE.md → Issue 3
│
├─ Port already in use
│  └─ Check: WINDOWS_QUICKSTART.md → Troubleshooting
│
├─ Module not found
│  └─ Run: .\run_dev.ps1 -Reinstall
│
├─ Script won't run
│  └─ Check: WINDOWS_SETUP_GUIDE.md → Issue 2 (Execution Policy)
│
├─ Database error
│  └─ Check: WINDOWS_SETUP_GUIDE.md → Issue 5
│
└─ Something else
   └─ Read: WINDOWS_SETUP_GUIDE.md → Full Troubleshooting Section
```

## 📞 Support Resources

### Internal Documentation
- **Project README**: `README.md` (general project info)
- **General Quickstart**: `QUICKSTART.md` (Mac/Linux focused)
- **API Commands**: `API_CURL_COMMANDS.md` (API examples)
- **Deployment**: `DEPLOYMENT.md` (production deployment)

### Online Resources
- **FastAPI Docs**: https://fastapi.tiangolo.com/
- **Python Windows**: https://docs.python.org/3/using/windows.html
- **PowerShell Docs**: https://docs.microsoft.com/powershell/

### Getting Help
1. Check **WINDOWS_QUICKSTART.md** for quick fixes
2. Run `.\troubleshoot_windows.ps1 -Fix`
3. Read **WINDOWS_SETUP_GUIDE.md** troubleshooting section
4. Check API docs at http://localhost:8000/docs
5. Review error messages in terminal

## ✅ Pre-flight Checklist

Before running any script:

- [ ] Python 3.10+ installed
- [ ] "Add Python to PATH" was checked during Python installation
- [ ] PowerShell execution policy configured (scripts will try to fix this)
- [ ] Opened PowerShell in the backend directory
- [ ] Have administrator rights (for execution policy if needed)

## 🎉 Success Indicators

You'll know setup worked when:

1. ✅ Script completes without errors
2. ✅ Server starts and shows:
   ```
   INFO:     Uvicorn running on http://0.0.0.0:8000
   INFO:     Application startup complete.
   ```
3. ✅ Can access http://localhost:8000/docs
4. ✅ Health check returns success:
   ```json
   {"status": "healthy", "timestamp": "..."}
   ```

## 🚦 What to Run When

| Situation | Command |
|-----------|---------|
| **First time ever** | `.\setup_windows.ps1` |
| **Daily development** | `.\run_dev.ps1` |
| **After git pull with new deps** | `.\run_dev.ps1 -Reinstall` |
| **Something not working** | `.\troubleshoot_windows.ps1 -Fix` |
| **Need different port** | `.\run_dev.ps1 -Port 8080` |
| **Check if ready** | `.\troubleshoot_windows.ps1` |
| **Fresh start** | Delete `.venv`, run `.\setup_windows.ps1` |

## 📝 File Summary

### Created for Windows Support
```
backend/
├── WINDOWS_README.md              # Main Windows guide
├── WINDOWS_SETUP_GUIDE.md         # Detailed setup instructions
├── WINDOWS_QUICKSTART.md          # Quick reference card
├── WINDOWS_RESOURCES.md           # This file
├── setup_windows.ps1              # Automated setup script
├── run_dev.ps1                    # Daily dev launcher (already existed)
├── setup_user_venv.ps1            # User profile venv (already existed)
├── setup-env.ps1                  # Environment setup (already existed)
└── troubleshoot_windows.ps1       # Diagnostic tool
```

### Existing Files (Enhanced)
- `run_dev.ps1` - Already existed, works great
- `setup_user_venv.ps1` - Already existed, documented
- `setup-env.ps1` - Already existed, included in guide

## 🎯 Recommended Workflow

### For New Users
```powershell
# Day 1: Initial Setup
.\setup_windows.ps1
# → Read WINDOWS_SETUP_GUIDE.md while waiting

# Day 2-∞: Daily Development
.\run_dev.ps1
# → Keep WINDOWS_QUICKSTART.md handy
```

### For Experienced Users
```powershell
# Every day:
.\run_dev.ps1

# When issues arise:
.\troubleshoot_windows.ps1 -Fix
```

## 🔄 Update & Maintenance

If you pull new changes:

```powershell
# 1. Pull from git
git pull

# 2. Check for new dependencies
.\run_dev.ps1 -Reinstall

# 3. Check for new migrations
.\.venv\Scripts\Activate.ps1
alembic upgrade head
```

## 💡 Pro Tips

1. **Bookmark** http://localhost:8000/docs for quick API reference
2. **Keep** WINDOWS_QUICKSTART.md open in a browser tab
3. **Use** VS Code with Python extension for best experience
4. **Run** troubleshoot script weekly to catch issues early
5. **Create** a desktop shortcut to run_dev.ps1 for quick access

## 🎓 Next Steps After Setup

1. ✅ Verify setup works: http://localhost:8000/docs
2. ✅ Test API with health check
3. ✅ Create your first course via API
4. ✅ Export a SCORM package
5. ✅ Connect your frontend application
6. ✅ Read the main project documentation

---

**You now have everything you need to run the FastAPI backend on Windows 11!** 🎉

For any specific task, refer to the appropriate document above or run the relevant script.

**Happy coding!** 🚀
