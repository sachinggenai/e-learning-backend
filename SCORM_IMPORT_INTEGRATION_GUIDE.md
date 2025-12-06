# SCORM Import Phase 1 - Integration Guide

## Quick Start

### 1. Register the Import Router

Edit `app/main.py` and add the import router registration:

```python
# Near the top with other router imports
from app.routers.imports import router as import_router

# Later, after app creation and other routers:
app.include_router(import_router)  # /api/v1/imports/...
```

**Location**: Add after other `app.include_router()` calls around line 80-100.

### 2. Run Database Migrations

Execute migrations to create the `import_jobs` table:

```bash
# From workspace root
alembic upgrade head
```

This creates:
- `import_jobs` table: Stores job state and data
- `import_job_templates` table: Stores analyzed templates (indexed for queries)

### 3. Test the API

```bash
# Start the server
./run_dev.ps1  # Windows
# or
./run_dev.sh   # Linux/Mac

# In another terminal, test upload
curl -X POST "http://localhost:8000/api/v1/imports/analyze" \
  -F "file=@test_package.zip" \
  -H "Content-Type: multipart/form-data"

# You should get a response like:
# {"job_id": "550e8400-...", "status": "analyzing", "progress": 0.5}
```

---

## API Usage

### Upload & Analyze

```bash
# Upload a SCORM ZIP package
curl -X POST "http://localhost:8000/api/v1/imports/analyze" \
  -F "file=@course.zip"

# Response
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "analyzing",
  "progress": 0.5
}
```

### Poll Status

```bash
# Poll for completion
curl -X GET "http://localhost:8000/api/v1/imports/jobs/550e8400-e29b-41d4-a716-446655440000"

# Response (when complete)
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "analyzed",
  "progress": 1.0,
  "course_data": {
    "courseId": "course-123",
    "title": "Imported Course",
    "templates": [...],
    "assets": {...},
    "warnings": [...]
  },
  "created_at": "2024-12-19T10:00:00",
  "updated_at": "2024-12-19T10:00:05"
}
```

### Commit Import

```bash
# Commit the analyzed import
curl -X POST "http://localhost:8000/api/v1/imports/jobs/550e8400-e29b-41d4-a716-446655440000/commit"

# Response
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "committed",
  "course_id": "course-123",
  "message": "Import committed successfully"
}
```

---

## Testing

### Minimal Test ZIP

Create a test ZIP with this JavaScript file:

**course_data.js**:
```javascript
var courseData = {
  "courseId": "test-course-001",
  "title": "Test Course",
  "description": "A test course for import",
  "templates": [
    {
      "id": "slide_1",
      "type": "welcome",
      "title": "Welcome",
      "order": 0,
      "data": {
        "content": "Welcome to the course"
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

Zip it:
```bash
zip test_course.zip course_data.js
```

### Python Test Script

Create `test_import_upload.py`:

```python
import requests
import json
import time
import sys

BASE_URL = "http://localhost:8000/api/v1/imports"

def upload_and_analyze(zip_file_path):
    """Upload and analyze a SCORM package."""
    print(f"Uploading {zip_file_path}...")
    
    with open(zip_file_path, "rb") as f:
        response = requests.post(
            f"{BASE_URL}/analyze",
            files={"file": f}
        )
    
    if response.status_code != 200:
        print(f"Upload failed: {response.status_code}")
        print(response.text)
        return None
    
    data = response.json()
    job_id = data["job_id"]
    print(f"Job created: {job_id}")
    
    return job_id

def poll_status(job_id, max_wait_seconds=30):
    """Poll job status until completion."""
    start = time.time()
    
    while time.time() - start < max_wait_seconds:
        response = requests.get(f"{BASE_URL}/jobs/{job_id}")
        
        if response.status_code != 200:
            print(f"Poll failed: {response.status_code}")
            return None
        
        data = response.json()
        status = data["status"]
        progress = data["progress"]
        
        print(f"Status: {status} (progress: {progress*100:.1f}%)")
        
        if status in ("analyzed", "failed", "committed"):
            return data
        
        time.sleep(0.5)
    
    print("Timeout waiting for job completion")
    return None

def commit_import(job_id):
    """Commit an analyzed import."""
    print(f"Committing import {job_id}...")
    
    response = requests.post(f"{BASE_URL}/jobs/{job_id}/commit")
    
    if response.status_code != 200:
        print(f"Commit failed: {response.status_code}")
        print(response.text)
        return None
    
    return response.json()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_import_upload.py <zip_file>")
        sys.exit(1)
    
    zip_file = sys.argv[1]
    
    # Step 1: Upload
    job_id = upload_and_analyze(zip_file)
    if not job_id:
        sys.exit(1)
    
    # Step 2: Poll
    result = poll_status(job_id)
    if not result:
        sys.exit(1)
    
    print(f"\nAnalysis Result:")
    print(json.dumps(result, indent=2))
    
    if result["status"] == "analyzed":
        # Step 3: Commit
        commit_result = commit_import(job_id)
        if commit_result:
            print(f"\nCommit Result:")
            print(json.dumps(commit_result, indent=2))
```

Run it:
```bash
python test_import_upload.py test_course.zip
```

---

## Troubleshooting

### Issue: "ImportError: cannot import name 'ImportJobRecord'"

**Cause**: Table not created yet.

**Solution**:
```bash
alembic upgrade head
```

### Issue: Router not found (404 on /api/v1/imports)

**Cause**: Router not registered in `app/main.py`.

**Solution**: Add to `app/main.py`:
```python
from app.routers.imports import router as import_router
app.include_router(import_router)
```

### Issue: "No JSON payloads found in package"

**Cause**: ZIP doesn't contain valid JSON in JavaScript/HTML files.

**Solution**: Verify the ZIP structure:
```bash
unzip -l your_package.zip
# Should show files like course_data.js, index.html, etc.
```

### Issue: Job stuck on "analyzing"

**Cause**: Parsing error or database issue.

**Solution**:
1. Check logs: `tail -f data/elearning.db.log`
2. Verify database is working
3. Try with simpler test ZIP
4. Check for malformed JSON in files

---

## Database Verification

### Check Import Jobs Table

```sql
-- Using SQLite CLI
sqlite3 data/elearning.db

-- List all import jobs
SELECT job_id, status, progress, created_at FROM import_jobs;

-- View job details
SELECT * FROM import_jobs WHERE job_id = '550e8400-...';

-- View staged data for a job
SELECT job_id, result_data FROM import_jobs 
WHERE status = 'analyzed' 
LIMIT 1;
```

### Check Table Schema

```sql
-- Show table structure
.schema import_jobs
.schema import_job_templates
```

---

## Performance Tuning

### For Large Packages (50MB+)

1. **Increase timeout** in polling client:
   ```python
   response = requests.post(..., timeout=300)  # 5 minutes
   ```

2. **Monitor memory**: Watch database memory usage during large imports
   ```bash
   # Linux/Mac
   watch -n 1 'ps aux | grep python'
   ```

3. **Adjust import service timeout** (optional):
   ```python
   service = ImportService(session, max_file_size=500*1024*1024)  # 500MB
   ```

### For Many Templates (100+)

1. **Schema inference can be slow**: Consider adding caching
2. **Database writes can be slow**: Consider batch inserts in Phase 2
3. **Monitor disk I/O**: Ensure database has SSD storage

---

## Development Workflow

### Adding New Features to Import

1. **Add service logic** in `app/services/import_service.py`
2. **Update repository** if needed in `app/repositories/import_job_repository.py`
3. **Add API endpoint** in `app/routers/imports.py`
4. **Add unit tests** in `tests/test_import_*.py`
5. **Test manually** with sample ZIPs

### Example: Adding Template Validation

```python
# In app/services/import_service.py

async def _validate_templates(self, templates: List[Dict]) -> List[str]:
    """Validate templates for common issues."""
    warnings = []
    
    for idx, template in enumerate(templates):
        # Add validation logic here
        if "type" not in template:
            warnings.append(f"Template {idx} missing 'type'")
        
        if template.get("type") == "mcq":
            # MCQ-specific validation
            if "data" not in template:
                warnings.append(f"MCQ template {idx} missing 'data'")
    
    return warnings
```

---

## Next Phase Preview (Phase 2)

Phase 2 will implement actual course creation from staged data:

### New Endpoints

```bash
# Create course from import
POST /api/v1/courses/from-import/{job_id}

# Get import history for course
GET /api/v1/courses/{course_id}/imports

# Merge import with existing course
POST /api/v1/courses/{course_id}/merge-import/{job_id}
```

### New Service Methods

```python
class ImportService:
    async def create_course_from_import(self, job_id: str) -> str:
        """Create CourseRecord from staged import data."""
        
    async def copy_assets_for_import(self, job_id: str, course_id: str) -> int:
        """Copy/rewrite assets to course directory."""
        
    async def merge_import_with_course(
        self, 
        job_id: str, 
        course_id: str,
        merge_strategy: str = "append"
    ) -> Dict[str, Any]:
        """Merge import with existing course."""
```

---

## Deployment Considerations

### Production Checklist

- [ ] Database backups configured
- [ ] Import logs rotated daily
- [ ] Max file size enforced (200MB default)
- [ ] Temporary files cleaned up regularly
- [ ] Job retention policy (keep for 30 days?)
- [ ] Rate limiting on import endpoint
- [ ] CORS origins configured for frontend

### Environment Variables

```bash
# Optional: Customize import behavior
IMPORT_MAX_FILE_SIZE=209715200          # 200MB
IMPORT_JOB_RETENTION_DAYS=30             # Keep jobs for 30 days
IMPORT_TEMP_DIR=/tmp/elearning-imports   # Temp file location
IMPORT_PARALLEL_WORKERS=4                # For Phase 2 batch imports
```

---

## Support & Documentation

### API Documentation
- Auto-generated: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Code Documentation
- Inline docstrings in each module
- Type hints for IDE autocomplete
- Examples in docstrings

### Testing Documentation
- Unit test examples: `tests/test_import_*.py`
- Integration examples: See test scripts below

---

## Common Questions

### Q: Can I import the same package twice?
**A**: Yes, each upload creates a new import job. Phase 2 will support merging strategies.

### Q: What if analysis fails halfway through?
**A**: The job is marked as "failed" with error details. No partial data persists.

### Q: How long do imports stay in the database?
**A**: Currently indefinite. Phase 2 will add a retention policy (suggested: 30 days).

### Q: Can I cancel an in-progress import?
**A**: Not in Phase 1. Phase 2 will add cancellation support.

### Q: What file formats are supported?
**A**: ZIP archives containing JavaScript/HTML with embedded JSON payloads.

---

## Ready to Integrate!

The Phase 1 implementation is complete and ready for integration. Follow the "Quick Start" steps above to get the import API running.

After integration:
1. Test with sample ZIPs
2. Verify API endpoints work
3. Check database for job records
4. Review logs for any issues
5. Plan Phase 2 implementation

**Next**: Phase 2 will implement actual course creation from staged imports.
