# Phase 1C & 2 - Command Reference Card

## 🚀 QUICK START (Copy & Paste)

### Terminal 1 - Start Server
```powershell
cd d:\projects\elearning_project\e-learning-backend
./run_dev.ps1
```
Wait for: `Application startup complete`

### Terminal 2 - Run Tests  
```powershell
cd d:\projects\elearning_project\e-learning-backend
python test_import_quick.py
```
Expect: `✅ ALL TESTS PASSED!`

---

## 🔍 VERIFICATION COMMANDS

### Verify Setup
```powershell
python verify_setup.py
```

### Check Database
```powershell
sqlite3 data/elearning.db
SELECT job_id, status FROM import_jobs ORDER BY created_at DESC LIMIT 5;
.quit
```

### Kill Port 8000 (if in use)
```powershell
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

---

## 🧪 MANUAL API TESTING (Using curl)

### 1. Upload & Analyze (Create import job)
```powershell
# Create test ZIP first
python -c "
import zipfile
import json
from io import BytesIO

# Create minimal SCORM package
with zipfile.ZipFile('test.zip', 'w') as z:
    manifest = '''<?xml version=\"1.0\"?>
    <manifest>
        <organizations>
            <organization>
                <title>Test Course</title>
                <item identifier=\"item1\"><title>Slide 1</title></item>
            </organization>
        </organizations>
    </manifest>'''
    z.writestr('imsmanifest.xml', manifest)
    z.writestr('content.html', '<h1>Test</h1>')
"

# Upload
curl -X POST http://localhost:8000/api/v1/imports/analyze `
  -F 'file=@test.zip' `
  -H 'Content-Type: multipart/form-data'

# Output: {"job_id": "uuid-here", "status": "analyzing", ...}
```

### 2. Check Status (Poll for results)
```powershell
# Replace JOB_ID with actual UUID from step 1
$JOB_ID = "your-job-id-here"

curl -X GET "http://localhost:8000/api/v1/imports/jobs/$JOB_ID"

# Response: {"job_id": "...", "status": "analyzed", "result_data": {...}}
```

### 3. Get Preview (Same as check status)
```powershell
$JOB_ID = "your-job-id-here"

curl -X GET "http://localhost:8000/api/v1/imports/jobs/$JOB_ID/preview"
```

### 4. Commit Import (Finalize)
```powershell
$JOB_ID = "your-job-id-here"

curl -X POST "http://localhost:8000/api/v1/imports/jobs/$JOB_ID/commit"

# Response: {"status": "committed", "job_id": "..."}
```

---

## 📊 SWAGGER UI TESTING

Open in browser: http://localhost:8000/docs

Then:
1. Click "POST /api/v1/imports/analyze"
2. Click "Try it out"
3. Click "Choose File" and select a test SCORM ZIP
4. Click "Execute"
5. Copy the returned `job_id`
6. Use same endpoint to poll until status is "analyzed"
7. Use other endpoints with the job_id

---

## 📋 DOCUMENTATION REFERENCES

| Document | Command | Purpose |
|----------|---------|---------|
| Setup checklist | `cat PHASE_1C_2_READY_CHECKLIST.md` | Quick status |
| Quick start | `cat TESTING_QUICK_START.md` | 5-min guide |
| Full guide | `cat HOW_TO_TEST_PHASE_1C_AND_2.md` | 40-min guide |
| Reference | `cat TESTING_QUICK_REFERENCE.md` | Commands |
| Technical | `cat TESTING_PHASE_1C_AND_2.md` | Deep dive |
| This file | `cat COMMAND_REFERENCE.md` | Commands |

---

## 🐛 DEBUGGING

### View Server Logs (Terminal 1)
Look for:
- `POST /api/v1/imports/analyze` - Upload endpoint
- `GET /api/v1/imports/jobs/` - Status check
- `ERROR` or `ERROR` - Any errors

### Check Job in Database
```powershell
sqlite3 data/elearning.db
SELECT json_extract(result_data, '$.course_id') as course_id,
       json_extract(result_data, '$.templates') as templates,
       status,
       progress
FROM import_jobs 
WHERE status = 'committed' 
ORDER BY created_at DESC LIMIT 1;
```

### Extract Full Result Data
```powershell
sqlite3 data/elearning.db
SELECT json_pretty(result_data) 
FROM import_jobs 
WHERE status = 'committed' 
LIMIT 1;
```

---

## 🔄 RESTART PROCEDURES

### Restart Server (if needed)
```powershell
# Terminal 1: Press Ctrl+C

# Then restart:
./run_dev.ps1
```

### Reset Database (WARNING: Deletes data)
```powershell
# Delete database
rm data/elearning.db

# Server will auto-recreate and migrate on next start
./run_dev.ps1
```

### Reinstall Dependencies
```powershell
pip install -r requirements.txt
```

---

## 📈 MONITORING

### Watch Database Changes
```powershell
# Run this in separate terminal
while ($true) {
    clear
    sqlite3 data/elearning.db "SELECT job_id, status, progress FROM import_jobs ORDER BY created_at DESC LIMIT 1;"
    Start-Sleep -Seconds 2
}
```

### Watch Server Logs (Terminal 1)
Just keep Terminal 1 visible to see all requests/responses in real-time.

---

## ✅ SUCCESS CRITERIA

All of these should be true after running tests:

```powershell
# ✅ Server running
curl -s http://localhost:8000/docs | findstr -q "swagger-ui"

# ✅ Database has jobs
sqlite3 data/elearning.db "SELECT COUNT(*) FROM import_jobs;"

# ✅ At least one committed job
sqlite3 data/elearning.db "SELECT COUNT(*) FROM import_jobs WHERE status='committed';"

# ✅ Test script completed
python test_import_quick.py | findstr "ALL TESTS PASSED"
```

---

## 🚨 COMMON ERRORS

### "Port 8000 already in use"
```powershell
netstat -ano | findstr :8000
taskkill /PID <number> /F
./run_dev.ps1
```

### "ModuleNotFoundError"
```powershell
pip install -r requirements.txt
./run_dev.ps1
```

### "Database is locked"
```powershell
# Close other SQLite connections
# Restart server
Ctrl+C
./run_dev.ps1
```

### "Test fails to connect"
```powershell
# Check server shows this in Terminal 1:
# "Application startup complete"

# If not, wait 5 seconds
# Then try test again
```

### "Job stuck on 'analyzing'"
```powershell
# Check server logs in Terminal 1 for errors
# Common: missing template data, file parsing issue
# Solution: Try with known-good test file
```

---

## 📞 HELP COMMANDS

```powershell
# View all available endpoints
curl -s http://localhost:8000/docs | findstr "paths"

# View full API spec
curl http://localhost:8000/openapi.json | python -m json.tool

# Count total jobs
sqlite3 data/elearning.db "SELECT COUNT(*) as total_jobs FROM import_jobs;"

# Count by status
sqlite3 data/elearning.db "SELECT status, COUNT(*) as count FROM import_jobs GROUP BY status;"

# View latest error
sqlite3 data/elearning.db "SELECT job_id, error_message FROM import_jobs WHERE error_message IS NOT NULL ORDER BY created_at DESC LIMIT 1;"
```

---

## 🎯 TYPICAL TEST SESSION

```powershell
# 1. Start server (Terminal 1)
./run_dev.ps1

# 2. Wait for "Application startup complete"

# 3. Run tests (Terminal 2)
python test_import_quick.py

# 4. Check results (Terminal 2)
# Should see: ✅ ALL TESTS PASSED!

# 5. Verify database (Terminal 3)
sqlite3 data/elearning.db "SELECT * FROM import_jobs LIMIT 1;"

# 6. Check Swagger UI (Browser)
# Open: http://localhost:8000/docs
# Try each endpoint manually

# Done! ✅
```

---

## 📝 NOTES

- All commands assume you're in: `d:\projects\elearning_project\e-learning-backend`
- Server runs on: `http://localhost:8000`
- Database: `data/elearning.db` (SQLite)
- API prefix: `/api/v1`
- Docs available: `http://localhost:8000/docs`

---

**Print this page and keep it by your terminal!** 📋

Use this as quick reference while testing.
For detailed info, see `HOW_TO_TEST_PHASE_1C_AND_2.md`
