# Windows Setup - Visual Guide & Decision Tree

Quick visual guide to help you choose the right path for setting up the backend on Windows 11.

## 🎯 Start Here

```
┌─────────────────────────────────────────────┐
│  Do you have Python 3.10+ installed?       │
└─────────────────────────────────────────────┘
           │                    │
         YES                   NO
           │                    │
           ↓                    ↓
    ┌──────────┐      ┌─────────────────────┐
    │ Continue │      │ Install Python from │
    │          │      │ python.org          │
    │          │      │ ✓ Add to PATH!      │
    └──────────┘      └─────────────────────┘
           │                    │
           │                    ↓
           │           ┌─────────────────┐
           │           │ Restart         │
           │           │ PowerShell      │
           │           └─────────────────┘
           │                    │
           └────────────────────┘
                      │
                      ↓
        ┌─────────────────────────────┐
        │  What's your experience?    │
        └─────────────────────────────┘
           │          │          │
      Beginner   Intermediate  Expert
           │          │          │
           ↓          ↓          ↓
```

## 🎓 Path 1: Beginner (First Time)

```
START
  │
  ↓
┌────────────────────────────┐
│ Read WINDOWS_README.md     │
│ (10 minutes)               │
└────────────────────────────┘
  │
  ↓
┌────────────────────────────┐
│ Open PowerShell in backend │
│ directory                  │
└────────────────────────────┘
  │
  ↓
┌────────────────────────────┐
│ Run:                       │
│ .\setup_windows.ps1        │
└────────────────────────────┘
  │
  ↓
┌────────────────────────────┐
│ Wait 2-5 minutes           │
│ (installing dependencies)  │
└────────────────────────────┘
  │
  ↓
┌────────────────────────────┐
│ Server starts automatically│
│ http://localhost:8000      │
└────────────────────────────┘
  │
  ↓
┌────────────────────────────┐
│ Open browser to:           │
│ http://localhost:8000/docs │
└────────────────────────────┘
  │
  ↓
┌────────────────────────────┐
│ Test health endpoint       │
│ See green "200 OK"         │
└────────────────────────────┘
  │
  ↓
SUCCESS! ✓
  │
  ↓
┌────────────────────────────┐
│ Bookmark these:            │
│ • WINDOWS_QUICKSTART.md    │
│ • http://localhost:8000/docs│
└────────────────────────────┘
```

## 💼 Path 2: Intermediate (Know Python)

```
START
  │
  ↓
┌────────────────────────────┐
│ Quick scan:                │
│ WINDOWS_QUICKSTART.md      │
│ (2 minutes)                │
└────────────────────────────┘
  │
  ↓
┌────────────────────────────┐
│ Open PowerShell            │
│ in backend directory       │
└────────────────────────────┘
  │
  ↓
┌────────────────────────────┐
│ Run: .\run_dev.ps1         │
└────────────────────────────┘
  │
  ↓
┌────────────────────────────┐
│ Script handles:            │
│ • Venv creation            │
│ • Dependency check         │
│ • Port selection           │
│ • Server start             │
└────────────────────────────┘
  │
  ↓
SUCCESS! ✓
```

## 🚀 Path 3: Expert (Just Give Me the Command)

```
START → cd backend → .\run_dev.ps1 → DONE ✓
```

## 🔧 Troubleshooting Decision Tree

```
┌─────────────────────────────┐
│  Something not working?     │
└─────────────────────────────┘
              │
              ↓
┌─────────────────────────────┐
│ Do you know what's wrong?   │
└─────────────────────────────┘
        │              │
       YES            NO
        │              │
        │              ↓
        │    ┌──────────────────────┐
        │    │ Run diagnostic:      │
        │    │ .\troubleshoot_      │
        │    │   windows.ps1 -Fix   │
        │    └──────────────────────┘
        │              │
        │              ↓
        │    ┌──────────────────────┐
        │    │ Issues found?        │
        │    └──────────────────────┘
        │         │          │
        │        YES        NO
        │         │          │
        │         │          ↓
        │         │     ┌─────────┐
        │         │     │ Success │
        │         │     └─────────┘
        │         │
        ↓         ↓
┌─────────────────────────────┐
│ Check specific issue below  │
└─────────────────────────────┘
```

## 🎯 Specific Issue Resolution

### Issue: "Python not found"

```
┌────────────────────┐
│ Python not found   │
└────────────────────┘
         │
         ↓
┌────────────────────┐
│ Is Python          │
│ installed?         │
└────────────────────┘
    │            │
   NO           YES
    │            │
    ↓            ↓
┌─────────┐  ┌───────────────┐
│ Install │  │ Is it in      │
│ Python  │  │ PATH?         │
└─────────┘  └───────────────┘
    │            │          │
    │           NO         YES
    │            │          │
    ↓            ↓          ↓
┌─────────────────────────────┐
│ Reinstall Python            │
│ ✓ CHECK "Add to PATH"       │
│ ✓ Restart PowerShell        │
└─────────────────────────────┘
```

### Issue: "Port already in use"

```
┌────────────────────┐
│ Port 8000 busy     │
└────────────────────┘
         │
         ↓
   ┌─────────┐
   │ Options │
   └─────────┘
    │    │    │
    ↓    ↓    ↓
┌────┐ ┌────┐ ┌────┐
│ A  │ │ B  │ │ C  │
└────┘ └────┘ └────┘
  │      │      │
  ↓      ↓      ↓

A: Use different port
   .\run_dev.ps1 -Port 8080

B: Kill process
   netstat -ano | findstr :8000
   taskkill /PID <PID> /F

C: Let script handle it
   .\run_dev.ps1
   (auto-switches to 8100)
```

### Issue: "Script won't run"

```
┌────────────────────────┐
│ Script execution error │
└────────────────────────┘
         │
         ↓
┌────────────────────────┐
│ Error mentions         │
│ "execution policy"?    │
└────────────────────────┘
    │            │
   YES          NO
    │            │
    ↓            ↓
┌──────────┐  ┌──────────┐
│ Run PS   │  │ Different│
│ as Admin │  │ issue    │
└──────────┘  └──────────┘
    │            │
    ↓            ↓
Set-ExecutionPolicy    Check
-ExecutionPolicy       WINDOWS_SETUP
RemoteSigned          _GUIDE.md
-Scope CurrentUser
```

### Issue: "Module not found"

```
┌────────────────────┐
│ ModuleNotFoundError│
└────────────────────┘
         │
         ↓
┌────────────────────┐
│ Is venv activated? │
└────────────────────┘
    │            │
   NO           YES
    │            │
    ↓            ↓
Activate:    Reinstall:
.\.venv\Scripts\  .\run_dev.ps1
Activate.ps1      -Reinstall
```

## 📊 Feature Comparison Chart

```
Feature              setup_windows  run_dev  troubleshoot
─────────────────────────────────────────────────────────
First-time setup        ⭐⭐⭐       ⭐⭐        ❌
Daily development         ❌         ⭐⭐⭐      ❌
Diagnostics             ⭐          ⭐        ⭐⭐⭐
Auto-fix issues         ⭐          ⭐        ⭐⭐⭐
Install deps           Always     If needed  If needed
Run migrations          ✓           ❌         ❌
Start server            ✓           ✓         ❌
─────────────────────────────────────────────────────────
```

## 🎬 Step-by-Step Visual: First Time Setup

```
┌─────────────────────────────────────────────┐
│ STEP 1: Install Python                      │
│ ✓ Download from python.org                  │
│ ✓ Run installer                              │
│ ✓ CHECK "Add Python to PATH"                │
│ ✓ Click Install                              │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ STEP 2: Open PowerShell                     │
│ • Windows + X                                │
│ • Select "Windows PowerShell"                │
│ • Navigate to backend folder:               │
│   cd C:\path\to\backend                      │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ STEP 3: Run Setup Script                    │
│ Type: .\setup_windows.ps1                   │
│ Press: Enter                                 │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ STEP 4: Wait (2-5 minutes)                  │
│ Script will:                                 │
│ ✓ Check Python                               │
│ ✓ Create virtual environment                │
│ ✓ Install dependencies                       │
│ ✓ Setup database                             │
│ ✓ Start server                               │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ STEP 5: Verify Success                      │
│ You should see:                              │
│ "Uvicorn running on http://0.0.0.0:8000"    │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ STEP 6: Test in Browser                     │
│ Open: http://localhost:8000/docs             │
│ Should see: API documentation page           │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ SUCCESS! ✓ You're ready to develop!         │
└─────────────────────────────────────────────┘
```

## 🎬 Step-by-Step Visual: Daily Development

```
┌─────────────────────────────────────────────┐
│ STEP 1: Open PowerShell                     │
│ Navigate to: cd C:\path\to\backend           │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ STEP 2: Start Server                        │
│ Type: .\run_dev.ps1                         │
│ Press: Enter                                 │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ STEP 3: Wait (10-30 seconds)                │
│ Server starts automatically                  │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ STEP 4: Develop!                            │
│ • Make code changes                          │
│ • Server auto-reloads                        │
│ • Test at http://localhost:8000/docs         │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ STEP 5: Stop Server (when done)             │
│ Press: Ctrl + C                              │
└─────────────────────────────────────────────┘
```

## 📱 Quick Command Reference Card

```
╔══════════════════════════════════════════════╗
║           ESSENTIAL COMMANDS                 ║
╠══════════════════════════════════════════════╣
║ First time setup:                            ║
║   .\setup_windows.ps1                        ║
║                                              ║
║ Daily development:                           ║
║   .\run_dev.ps1                              ║
║                                              ║
║ Troubleshooting:                             ║
║   .\troubleshoot_windows.ps1 -Fix            ║
║                                              ║
║ Different port:                              ║
║   .\run_dev.ps1 -Port 8080                   ║
║                                              ║
║ Reinstall dependencies:                      ║
║   .\run_dev.ps1 -Reinstall                   ║
║                                              ║
║ Check API:                                   ║
║   http://localhost:8000/docs                 ║
║                                              ║
║ Stop server:                                 ║
║   Ctrl + C                                   ║
╚══════════════════════════════════════════════╝
```

## 🎯 When to Use Which Document

```
┌──────────────────────────┐
│ What do you need?        │
└──────────────────────────┘
            │
    ┌───────┼───────┬──────────┐
    ↓       ↓       ↓          ↓
┌────────┐ ┌────┐ ┌──────┐ ┌──────┐
│Overview│ │Help│ │Quick │ │Setup │
│        │ │    │ │Ref   │ │Guide │
└────────┘ └────┘ └──────┘ └──────┘
    │       │       │          │
    ↓       ↓       ↓          ↓
WINDOWS  WINDOWS  WINDOWS  WINDOWS_
_README  _RESOURCES _QUICK  SETUP_
  .md      .md     START.md GUIDE.md

Start     File     Command  Detailed
here      index    lookup   steps
```

## 🏁 Success Checklist

```
Setup Complete When:

□ Python installed and in PATH
  Test: python --version

□ PowerShell can run scripts
  Test: Get-ExecutionPolicy (should not be "Restricted")

□ Virtual environment created
  Test: Test-Path .\.venv

□ Dependencies installed
  Test: .\.venv\Scripts\python.exe -c "import fastapi"

□ Server can start
  Test: .\run_dev.ps1

□ API responds
  Test: Invoke-RestMethod http://localhost:8000/api/v1/health

□ Documentation loads
  Test: Open http://localhost:8000/docs in browser

All checked? ✓ YOU'RE READY! 🎉
```

## 🎓 Learning Path Timeline

```
Day 1 (30 mins)
├─ Install Python (5 mins)
├─ Run setup_windows.ps1 (5 mins)
├─ Read WINDOWS_QUICKSTART.md (5 mins)
├─ Explore API docs (10 mins)
└─ Test sample requests (5 mins)

Day 2-7 (Daily)
├─ Run: .\run_dev.ps1 (30 secs)
├─ Develop features (your time)
└─ Stop: Ctrl+C (instant)

Week 2+
└─ Smooth sailing! 🚢
```

## 💡 Pro Tips Visual

```
🔖 BOOKMARK THESE:
   ├─ http://localhost:8000/docs
   └─ WINDOWS_QUICKSTART.md

⚡ KEYBOARD SHORTCUTS:
   ├─ Ctrl+C → Stop server
   ├─ ↑ (Up Arrow) → Previous command
   └─ Tab → Auto-complete paths

📁 ORGANIZE:
   └─ Keep PowerShell open in backend directory

🔄 UPDATE WORKFLOW:
   git pull → .\run_dev.ps1 -Reinstall

🎯 QUICK ACCESS:
   Create desktop shortcut to run_dev.ps1
```

## 📚 Documentation Navigator

```
                    WINDOWS_README.md
                          │
            ┌─────────────┼─────────────┐
            ↓             ↓             ↓
    WINDOWS_SETUP    WINDOWS_QUICK   WINDOWS_
    _GUIDE.md        START.md        RESOURCES.md
         │               │                │
    Detailed        Quick Ref        You are here
    Instructions    Commands         (Overview)
         │               │                │
         └───────────────┴────────────────┘
                         │
                    ┌────┴────┐
                    ↓         ↓
                Scripts    Examples
                   │         │
         ┌─────────┼─────────┼─────────┐
         ↓         ↓         ↓         ↓
    setup_    run_dev   troubleshoot  setup_user
    windows   .ps1      _windows      _venv
    .ps1                .ps1          .ps1
```

---

## 🎯 Final Decision: Which Path for You?

```
Never used FastAPI?          → Path 1 (Beginner)
Know Python, new to project? → Path 2 (Intermediate)
Just need it running fast?   → Path 3 (Expert)
Something not working?       → Troubleshooting Tree
```

**Happy coding on Windows!** 🚀🪟
