# Testing Quick Reference Card

Print this for quick reference while testing!

---

## 🚀 Start Here (Copy & Paste)

```bash
# Terminal 1: Start server
cd d:\projects\elearning_project\e-learning-backend
& ".\.venv\Scripts\Activate.ps1"
./run_dev.ps1

# Wait for "Application startup complete"

# Terminal 2: Run test
cd d:\projects\elearning_project\e-learning-backend
& ".\.venv\Scripts\Activate.ps1"
python test_import_quick.py
```

**Expected**: ✅ All tests passed!

---

## 🔗 API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/v1/imports/analyze` | Upload & analyze SCORM package |
| GET | `/api/v1/imports/jobs/{id}` | Get job status & results |
| GET | `/api/v1/imports/jobs/{id}/preview` | Get preview (alias for status) |
| POST | `/api/v1/imports/jobs/{id}/commit` | Commit the import |

---

## 🧪 One-Liner Tests

```bash
# 1. Create test ZIP
echo 'var courseData = {"courseId":"test","title":"Test","templates":[]}' > test.js
zip test.zip test.js

# 2. Upload
$RESPONSE = curl -s -F "file=@test.zip" http://localhost:8000/api/v1/imports/analyze
$JOB_ID = ($RESPONSE | ConvertFrom-Json).job_id
Write-Host "Job: $JOB_ID"

# 3. Poll status
curl "http://localhost:8000/api/v1/imports/jobs/$JOB_ID"

# 4. Commit
curl -X POST "http://localhost:8000/api/v1/imports/jobs/$JOB_ID/commit"

# 5. Check database
sqlite3 data/elearning.db "SELECT job_id, status FROM import_jobs LIMIT 1;"
```

---

## ✅ Verification Checklist

- [ ] Server starts on port 8000
- [ ] http://localhost:8000/docs loads
- [ ] "Imports" section visible in Swagger
- [ ] 4 import endpoints listed
- [ ] Test script runs without errors
- [ ] Job created in database
- [ ] Status updates to "analyzed"
- [ ] Course data populated
- [ ] Templates extracted
- [ ] Can commit import

---

## 🐛 Quick Fixes

| Issue | Solution |
|-------|----------|
| ModuleNotFoundError | Check venv activated: `& ".\.venv\Scripts\Activate.ps1"` |
| Connection refused | Start server: `./run_dev.ps1` |
| 404 on /imports | Restart server after code changes |
| Table not found | Run: `python -m alembic upgrade head` |
| No payloads found | ZIP must contain JS file with JSON |
| Timeout | Increase timeout: `timeout=60` in script |

---

## 📊 Database Queries

```bash
# Connect to database
sqlite3 data/elearning.db

# Show all jobs
SELECT job_id, status, progress FROM import_jobs ORDER BY created_at DESC;

# Show latest job details
SELECT * FROM import_jobs ORDER BY created_at DESC LIMIT 1;

# Count jobs by status
SELECT status, COUNT(*) FROM import_jobs GROUP BY status;

# View course data
SELECT job_id, result_data FROM import_jobs WHERE status = 'analyzed' LIMIT 1;
```

---

## 🎯 Testing Sequence

1. ✅ **API Available** - Swagger UI loads
2. ✅ **Upload Works** - Can upload ZIP
3. ✅ **Processing** - Job moves to "analyzed"
4. ✅ **Data Extraction** - Templates extracted
5. ✅ **Persistence** - Data in database
6. ✅ **Polling** - Status updates correctly
7. ✅ **Commitment** - Can commit job
8. ✅ **Error Handling** - Errors returned properly

---

## 📁 Important Files

| File | Purpose |
|------|---------|
| `app/main.py` | Router registration ✅ |
| `app/routers/imports.py` | API endpoints |
| `app/services/import_service.py` | Core logic |
| `app/repositories/import_job_repository.py` | Database layer |
| `test_import_quick.py` | Quick test script |
| `TESTING_QUICK_START.md` | This guide |

---

## 🔍 Response Examples

### Upload Response (200 OK)
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "analyzing",
  "progress": 0.5
}
```

### Status Response (200 OK)
```json
{
  "job_id": "550e8400-...",
  "status": "analyzed",
  "progress": 1.0,
  "course_data": {
    "courseId": "test-course-001",
    "title": "Test Course",
    "templates": [...],
    "assets": {...}
  }
}
```

### Commit Response (200 OK)
```json
{
  "job_id": "550e8400-...",
  "status": "committed",
  "course_id": "test-course-001",
  "message": "Import committed successfully"
}
```

---

## 🚨 Error Examples

### Invalid File (400)
```json
{
  "detail": "File must be a ZIP archive (.zip)"
}
```

### Job Not Found (404)
```json
{
  "detail": "Job not found"
}
```

### No Payloads (400)
```json
{
  "detail": "No JSON payloads found in package"
}
```

---

## 🎓 What Each Service Does

| Service | Does |
|---------|------|
| HeuristicParser | Extracts JSON from JS/HTML |
| SchemaInferenceEngine | Infers data types & schemas |
| AssetRewriter | Maps files & finds duplicates |
| TemplateDataConverter | Normalizes template formats |
| ImportService | Orchestrates workflow |
| ImportJobRepository | Persists jobs to DB |

---

## ⏱️ Timing Reference

| Operation | Time |
|-----------|------|
| Upload | <100ms |
| Analysis | 100-500ms |
| Poll (first) | <50ms |
| Full workflow | 1-2s |
| Database write | ~30ms |

---

## 🔑 Key Concepts

- **Job ID**: UUID for tracking import
- **Status**: analyzing → analyzed → committed
- **Progress**: 0.0 - 1.0 (0% - 100%)
- **Course Data**: Staged import ready for review
- **Templates**: Extracted and analyzed
- **Assets**: Files detected and mapped
- **Schemas**: Inferred from template data

---

**Ready to test!**

Run: `python test_import_quick.py`

Expected: ✅ All tests passed!
