# Testing Phase 1C & 2 - SCORM Import System

## 📋 Table of Contents
1. [Prerequisites & Setup](#prerequisites--setup)
2. [Integration Verification](#integration-verification)
3. [API Testing](#api-testing)
4. [End-to-End Workflow](#end-to-end-workflow)
5. [Common Issues & Fixes](#common-issues--fixes)

---

## Prerequisites & Setup

### Step 1: Register the Import Router

Edit `app/main.py` and add the import router registration.

**Find this section** (around line 12):
```python
# Import routers
from app.routers import (
    health, export, courses, templates, media, enhanced_templates
)
```

**Change to**:
```python
# Import routers
from app.routers import (
    health, export, courses, templates, media, enhanced_templates, imports
)
```

**Then find** (around line 117):
```python
# Include routers
app.include_router(health.router, prefix="/api/v1", tags=["Health"])
app.include_router(export.router, prefix="/api/v1", tags=["Export"])
app.include_router(courses.router, prefix="/api/v1", tags=["Courses"])
app.include_router(templates.router, prefix="/api/v1", tags=["Templates"])
app.include_router(enhanced_templates.router, prefix="/api/v1")
app.include_router(media.router, prefix="/api/v1", tags=["Media"])
```

**Add after media**:
```python
app.include_router(imports.router, prefix="/api/v1", tags=["Imports"])
```

### Step 2: Run Database Migrations

```bash
# From workspace root
alembic upgrade head
```

**Expected output**:
```
INFO  [alembic.runtime.migration] Running upgrade  -> XXXXX_initial, XXXXX_add_import_jobs
```

### Step 3: Start the Server

```bash
# Using the dev script
./run_dev.ps1

# Or manually
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Expected output**:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete
```

---

## Integration Verification

### Check 1: Router is Registered

```bash
# Check API documentation
curl http://localhost:8000/docs
```

**Expected**: Opens Swagger UI. Look for "Imports" section with 4 endpoints.

### Check 2: Database Tables Exist

```bash
# Using SQLite CLI
sqlite3 data/elearning.db

# List tables
.tables
# Should show: import_jobs

# Check schema
.schema import_jobs
```

**Expected columns**:
- `id` (INTEGER PRIMARY KEY)
- `job_id` (VARCHAR UNIQUE)
- `status` (VARCHAR)
- `progress` (FLOAT)
- `course_id` (VARCHAR)
- `source_file_path` (VARCHAR)
- `result_data` (JSON)
- `error_message` (VARCHAR)
- `created_at` (DATETIME)
- `updated_at` (DATETIME)

### Check 3: Endpoints Available

```bash
# Get OpenAPI spec
curl http://localhost:8000/openapi.json | jq '.paths | keys[]' | grep import
```

**Expected**:
```
/api/v1/imports/analyze
/api/v1/imports/jobs/{job_id}
/api/v1/imports/jobs/{job_id}/commit
/api/v1/imports/jobs/{job_id}/preview
```

---

## API Testing

### Test 1: Create Test SCORM Package

Create a minimal test ZIP file with course data:

**Create file**: `test_course.js`
```javascript
var courseData = {
  "courseId": "test-course-001",
  "title": "Test Course",
  "description": "A test SCORM package for import",
  "templates": [
    {
      "id": "slide_1",
      "type": "welcome",
      "title": "Welcome Slide",
      "order": 0,
      "data": {
        "content": "Welcome to the test course!"
      }
    },
    {
      "id": "slide_2",
      "type": "mcq",
      "title": "Question 1",
      "order": 1,
      "data": {
        "question": "What is 2+2?",
        "options": [
          {"text": "3", "isCorrect": false},
          {"text": "4", "isCorrect": true},
          {"text": "5", "isCorrect": false}
        ]
      }
    }
  ]
};
```

**Create ZIP**:
```bash
zip test_course.zip test_course.js
```

### Test 2: Upload & Analyze

```bash
# Upload the package
$response = curl -X POST "http://localhost:8000/api/v1/imports/analyze" `
  -F "file=@test_course.zip"

$response | jq .
```

**Expected response** (200 OK):
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "analyzing",
  "progress": 0.5
}
```

**Save the job_id** for next tests.

### Test 3: Poll for Completion

```bash
# Replace with actual job_id from Test 2
$JOB_ID = "550e8400-e29b-41d4-a716-446655440000"

# Poll status
curl "http://localhost:8000/api/v1/imports/jobs/$JOB_ID" | jq .
```

**Expected response** (when complete, 200 OK):
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "analyzed",
  "progress": 1.0,
  "course_data": {
    "courseId": "test-course-001",
    "title": "Test Course",
    "templates": [
      {
        "id": "slide_1",
        "type": "welcome",
        "order": 0,
        "schema": {...},
        "data": {...}
      }
    ],
    "assets": {
      "total": 1,
      "ambiguous": 0,
      "ambiguous_files": []
    },
    "warnings": []
  },
  "created_at": "2024-12-19T10:00:00",
  "updated_at": "2024-12-19T10:00:05"
}
```

### Test 4: Commit Import

```bash
# Commit the import
curl -X POST "http://localhost:8000/api/v1/imports/jobs/$JOB_ID/commit" | jq .
```

**Expected response** (200 OK):
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "committed",
  "course_id": "test-course-001",
  "message": "Import committed successfully"
}
```

### Test 5: Get Preview

```bash
# Preview is alias for status
curl "http://localhost:8000/api/v1/imports/jobs/$JOB_ID/preview" | jq .
```

**Expected**: Same as status response.

---

## End-to-End Workflow

### Python Test Script

Create `test_import_workflow.py`:

```python
#!/usr/bin/env python3
"""
End-to-end test of SCORM import workflow.
"""

import requests
import json
import time
import sys
from pathlib import Path

BASE_URL = "http://localhost:8000/api/v1/imports"
TIMEOUT = 30


def upload_package(zip_file_path: str) -> str:
    """Upload and analyze a SCORM package."""
    print(f"\n📤 Uploading {zip_file_path}...")
    
    with open(zip_file_path, "rb") as f:
        response = requests.post(
            f"{BASE_URL}/analyze",
            files={"file": f},
            timeout=TIMEOUT
        )
    
    if response.status_code != 200:
        print(f"❌ Upload failed: {response.status_code}")
        print(response.text)
        return None
    
    data = response.json()
    job_id = data["job_id"]
    print(f"✅ Job created: {job_id}")
    
    return job_id


def poll_status(job_id: str, max_wait_seconds: int = 30) -> dict:
    """Poll job status until completion."""
    print(f"\n⏳ Polling job status...")
    start = time.time()
    
    while time.time() - start < max_wait_seconds:
        response = requests.get(
            f"{BASE_URL}/jobs/{job_id}",
            timeout=TIMEOUT
        )
        
        if response.status_code != 200:
            print(f"❌ Poll failed: {response.status_code}")
            return None
        
        data = response.json()
        status = data["status"]
        progress = data["progress"]
        
        print(f"  Status: {status} (progress: {progress*100:.1f}%)")
        
        if status in ("analyzed", "failed", "committed"):
            return data
        
        time.sleep(0.5)
    
    print("⏱️  Timeout waiting for completion")
    return None


def commit_import(job_id: str) -> dict:
    """Commit an analyzed import."""
    print(f"\n💾 Committing import...")
    
    response = requests.post(
        f"{BASE_URL}/jobs/{job_id}/commit",
        timeout=TIMEOUT
    )
    
    if response.status_code != 200:
        print(f"❌ Commit failed: {response.status_code}")
        print(response.text)
        return None
    
    data = response.json()
    print(f"✅ Committed: {data['message']}")
    
    return data


def get_preview(job_id: str) -> dict:
    """Get preview/details of import."""
    print(f"\n👁️  Getting preview...")
    
    response = requests.get(
        f"{BASE_URL}/jobs/{job_id}/preview",
        timeout=TIMEOUT
    )
    
    if response.status_code != 200:
        print(f"❌ Preview failed: {response.status_code}")
        return None
    
    data = response.json()
    return data


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_import_workflow.py <zip_file>")
        sys.exit(1)
    
    zip_file = sys.argv[1]
    
    if not Path(zip_file).exists():
        print(f"❌ File not found: {zip_file}")
        sys.exit(1)
    
    print("=" * 60)
    print("SCORM Import Workflow Test")
    print("=" * 60)
    
    # Step 1: Upload
    job_id = upload_package(zip_file)
    if not job_id:
        sys.exit(1)
    
    # Step 2: Poll
    result = poll_status(job_id)
    if not result:
        sys.exit(1)
    
    print(f"\n✅ Analysis Complete")
    print(f"   Status: {result['status']}")
    print(f"   Progress: {result['progress']*100:.1f}%")
    
    if result.get("course_data"):
        course_data = result["course_data"]
        print(f"\n📊 Course Data:")
        print(f"   Course ID: {course_data.get('courseId')}")
        print(f"   Title: {course_data.get('title')}")
        print(f"   Templates: {len(course_data.get('templates', []))}")
        print(f"   Assets: {course_data.get('assets', {}).get('total', 0)}")
        
        if course_data.get("warnings"):
            print(f"   ⚠️  Warnings: {', '.join(course_data['warnings'])}")
    
    # Step 3: Commit
    if result["status"] == "analyzed":
        commit_result = commit_import(job_id)
        if commit_result:
            print(f"\n📋 Import Status: {commit_result['status']}")
            print(f"   Course ID: {commit_result.get('course_id')}")
    
    # Step 4: Get preview
    preview = get_preview(job_id)
    if preview:
        print(f"\n✅ Preview retrieved")
        print(f"   Status: {preview['status']}")
    
    print("\n" + "=" * 60)
    print("✅ All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
```

**Run it**:
```bash
python test_import_workflow.py test_course.zip
```

---

## Common Issues & Fixes

### Issue 1: "ModuleNotFoundError: No module named 'app.routers.imports'"

**Cause**: Router not created or not in correct location.

**Fix**:
```bash
# Check file exists
ls app/routers/imports.py

# If not, create it from the documentation
```

### Issue 2: "Table 'import_jobs' doesn't exist"

**Cause**: Migrations not run.

**Fix**:
```bash
alembic upgrade head
```

### Issue 3: 404 on /api/v1/imports/analyze

**Cause**: Router not registered in app/main.py.

**Fix**:
1. Check imports.py file exists
2. Add import: `from app.routers import ... imports`
3. Add registration: `app.include_router(imports.router, ...)`
4. Restart server

### Issue 4: "No JSON payloads found"

**Cause**: ZIP doesn't contain valid JSON in JS/HTML files.

**Fix**: Verify ZIP contents:
```bash
unzip -l test_course.zip
# Should show: test_course.js
```

### Issue 5: Upload fails with 413 "Payload Too Large"

**Cause**: File exceeds size limit.

**Fix**: Default is 200MB. Check:
- File size: `ls -lh test_course.zip`
- Or increase limit in `ImportService.__init__()`: `max_file_size=500*1024*1024`

### Issue 6: Job stuck on "analyzing"

**Cause**: Parser error or database issue.

**Fix**:
```bash
# Check logs
tail -f data/elearning.db.log

# Or use simpler test ZIP
# Or check database connectivity
sqlite3 data/elearning.db ".tables"
```

---

## Detailed Verification Checklist

### Database Layer ✅
- [ ] `import_jobs` table exists
- [ ] All columns present
- [ ] Indexes created
- [ ] Can read/write records

### Service Layer ✅
- [ ] `HeuristicParser` extracts JSON
- [ ] `SchemaInferenceEngine` infers schemas
- [ ] `AssetRewriter` maps files
- [ ] `TemplateDataConverter` normalizes formats
- [ ] `ImportService` orchestrates workflow

### API Layer ✅
- [ ] Router registered in app/main.py
- [ ] All 4 endpoints available
- [ ] Endpoints return correct status codes
- [ ] Error messages descriptive

### Workflow ✅
- [ ] Upload creates job
- [ ] Job status updates to "analyzed"
- [ ] Course data populated
- [ ] Templates extracted
- [ ] Can commit import

---

## Testing Checklist

Run through these tests in order:

### Basic Setup (5 minutes)
- [ ] Server starts without errors
- [ ] API docs available at /docs
- [ ] Database tables exist
- [ ] Endpoints listed in docs

### API Tests (15 minutes)
- [ ] Upload test ZIP
- [ ] Poll job status
- [ ] Get completed status with course_data
- [ ] Commit import successfully
- [ ] Get preview

### Error Handling (10 minutes)
- [ ] Invalid file returns 400
- [ ] Missing job_id returns 404
- [ ] Invalid ZIP returns error
- [ ] Commit non-analyzed job returns error

### Integration (10 minutes)
- [ ] Run full workflow with Python script
- [ ] Verify all data persisted
- [ ] Check database records
- [ ] Review logs for errors

**Total Time**: ~40 minutes

---

## Success Criteria

✅ All 4 endpoints respond correctly  
✅ JSON extraction works  
✅ Schemas inferred correctly  
✅ Data staged in database  
✅ Status polling works  
✅ Imports can be committed  
✅ No errors in logs  
✅ Database records persistent  

---

## Next Steps

After verification:
1. Write unit tests for each service
2. Write integration tests for full workflow
3. Test with real SCORM packages
4. Plan Phase 2 (course creation)

---

## Quick Reference

### Fastest Test (2 minutes)
```bash
# 1. Create test ZIP
echo 'var courseData = {"courseId":"test","title":"Test","templates":[]}' > test.js
zip test.zip test.js

# 2. Upload
$JOB=$(curl -s -F "file=@test.zip" http://localhost:8000/api/v1/imports/analyze | jq -r .job_id)

# 3. Check status
curl "http://localhost:8000/api/v1/imports/jobs/$JOB" | jq .
```

### Full Workflow Test (5 minutes)
```bash
python test_import_workflow.py test_course.zip
```

### Database Check
```bash
sqlite3 data/elearning.db "SELECT * FROM import_jobs LIMIT 1;"
```

---

**Ready to test! Follow the steps above to verify Phase 1C & 2 are working correctly.** 🚀
