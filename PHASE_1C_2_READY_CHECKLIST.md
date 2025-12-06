# Phase 1C & 2 - READY TO TEST CHECKLIST

## ✅ Pre-Flight Check (PASSED)

All setup items verified and ready:

### Code Components
- ✅ HeuristicParser service (extraction engine)
- ✅ SchemaInferenceEngine service (template detection)
- ✅ AssetRewriter service (file path fixing)
- ✅ TemplateDataConverter service (data normalization)
- ✅ ImportService (orchestrator)
- ✅ ImportJobRepository (persistence layer)
- ✅ ImportRouter (REST API with 4 endpoints)

### Infrastructure
- ✅ FastAPI installed and configured
- ✅ SQLAlchemy async ORM ready
- ✅ Pydantic validation library
- ✅ Database file created (`data/elearning.db`)
- ✅ Router registered in `app/main.py`
- ✅ Alembic migrations prepared

### Documentation
- ✅ `HOW_TO_TEST_PHASE_1C_AND_2.md` - Master testing guide
- ✅ `TESTING_QUICK_START.md` - 5-minute quick start
- ✅ `TESTING_QUICK_REFERENCE.md` - Copy-paste commands
- ✅ `test_import_quick.py` - Automated test script
- ✅ `verify_setup.py` - Setup verification script

---

## 🚀 Testing Start (Next Steps)

### Step 1: Start the Server

**Terminal 1:**
```powershell
cd d:\projects\elearning_project\e-learning-backend
./run_dev.ps1
```

**Expected output:**
```
Uvicorn running on http://127.0.0.1:8000
Application startup complete
```

**Wait for "Application startup complete" before proceeding.**

### Step 2: Run the Test Suite

**Terminal 2 (while server is running):**
```powershell
cd d:\projects\elearning_project\e-learning-backend
python test_import_quick.py
```

**Expected output:**
```
Testing Phase 1C & 2 - Import System
=====================================

✅ Step 1/5: Created test SCORM package
✅ Step 2/5: Uploaded and analyzed package
✅ Step 3/5: Polled job status
✅ Step 4/5: Committed import
✅ Step 5/5: Verified final result

✅ ALL TESTS PASSED!
```

---

## 📋 What Gets Tested

The `test_import_quick.py` script verifies:

| Component | Test | Expected |
|-----------|------|----------|
| **Phase 1C Analysis** | Upload SCORM ZIP | Returns `job_id` and status `analyzing` |
| **JSON Extraction** | Service parses imsmanifest.xml | Identifies course structure |
| **Schema Inference** | Engine detects template types | Classifies templates correctly |
| **Asset Analysis** | Rewriter maps media files | Finds course assets |
| **Phase 2 Persistence** | Job saved to database | Returns status `analyzed` |
| **Data Staging** | Course data staged in DB | Query returns `result_data` JSON |
| **Commit API** | Finalization endpoint | Status changes to `committed` |

---

## 🔍 Verification Checkpoints

After tests pass, verify each component:

### 1. API Endpoints (via Swagger UI)
Open http://localhost:8000/docs and test:
- `POST /api/v1/imports/analyze` - Create import job
- `GET /api/v1/imports/jobs/{job_id}` - Poll status
- `GET /api/v1/imports/jobs/{job_id}/preview` - Get preview
- `POST /api/v1/imports/jobs/{job_id}/commit` - Finalize

### 2. Database Records
In Terminal 3 (SQLite query):
```powershell
# Connect to database
sqlite3 data/elearning.db

# Check import_jobs table
.schema import_jobs

# View last test job
SELECT job_id, status, progress FROM import_jobs ORDER BY created_at DESC LIMIT 1;

# View staged data
SELECT result_data FROM import_jobs WHERE status='committed' LIMIT 1;
```

### 3. Server Logs (in Terminal 1)
Look for:
- `POST /api/v1/imports/analyze` - 200 response
- `GET /api/v1/imports/jobs/{job_id}` - 200 response
- `POST /api/v1/imports/jobs/{job_id}/commit` - 200 response

---

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| **Port 8000 already in use** | `netstat -ano \| findstr :8000` then kill process |
| **Module not found errors** | Run `pip install -r requirements.txt` |
| **Database locked** | Close any SQLite connections, restart server |
| **Test script fails to connect** | Ensure server shows "Application startup complete" |
| **Job status stuck on "analyzing"** | Check server logs for import service errors |

**Full troubleshooting**: See `HOW_TO_TEST_PHASE_1C_AND_2.md` section "Common Issues"

---

## 📊 Success Criteria

- ✅ `test_import_quick.py` completes without errors
- ✅ Database contains `import_jobs` with committed jobs
- ✅ API endpoints respond correctly in Swagger UI
- ✅ Server logs show no import service errors
- ✅ Result data contains valid course structure JSON

---

## 📚 Documentation Map

| Document | Purpose | Read Time |
|----------|---------|-----------|
| **This file** | Quick checklist & start guide | 5 min |
| `TESTING_QUICK_START.md` | 5-minute end-to-end walkthrough | 5 min |
| `HOW_TO_TEST_PHASE_1C_AND_2.md` | Comprehensive testing manual | 40 min |
| `TESTING_QUICK_REFERENCE.md` | Copy-paste commands & examples | 10 min |
| `TESTING_PHASE_1C_AND_2.md` | Deep technical reference | 60 min |

**Recommended order for first-time testers:**
1. This checklist (verify setup) ← **Start here**
2. Run `./run_dev.ps1` (Terminal 1)
3. Run `python test_import_quick.py` (Terminal 2)
4. Review `TESTING_QUICK_START.md` for next steps

---

## 🎯 What's Being Tested

### Phase 1C - Analysis Components

**HeuristicParser** (heuristic_parser.py)
- Extracts SCORM 1.2 package contents
- Identifies manifest, content, assets
- Handles multiple content structures

**SchemaInferenceEngine** (schema_inference.py)
- Auto-detects template types from HTML/content
- Classifies as: welcome, content-video, content-text, mcq, summary
- Maintains backward compatibility with legacy SCORM

**AssetRewriter** (asset_rewriter.py)
- Maps media file paths
- Fixes broken references
- Tracks assets for inclusion

**TemplateDataConverter** (template_data_converter.py)
- Normalizes template data structures
- Handles legacy MCQ formats
- Prepares for storage

### Phase 2 - Persistence Layer

**ImportJobRepository** (import_job_repository.py)
- Stores jobs in `import_jobs` table
- Tracks status: analyzing → analyzed → committed
- Manages progress tracking (0.0-1.0)

**ImportService** (import_service.py)
- Orchestrates entire workflow
- Coordinates all Phase 1C components
- Interfaces with repository

---

## 🔄 Test Workflow Timeline

```
Start Test (test_import_quick.py)
    ↓
1. Create test SCORM ZIP (5-10 MB sample)
    ↓
2. Upload via POST /api/v1/imports/analyze
    ↓ (Phase 1C Analysis)
3. HeuristicParser extracts package
    ↓
4. SchemaInferenceEngine classifies templates
    ↓
5. AssetRewriter maps media
    ↓
6. TemplateDataConverter normalizes data
    ↓ (Phase 2 Persistence)
7. ImportService saves job to database
    ↓
8. Poll GET /api/v1/imports/jobs/{job_id}
    ↓
9. Status transitions: analyzing → analyzed
    ↓
10. POST /api/v1/imports/jobs/{job_id}/commit
    ↓
11. Status becomes: committed
    ↓
12. Result verified in database
    ↓
End Test (✅ All tests passed!)
```

**Expected duration:** 5-15 seconds per test job

---

## 📝 Notes

- **Database**: SQLite (`data/elearning.db`) - created automatically
- **Alembic**: Migrations auto-applied on server startup
- **Async/Await**: All I/O is non-blocking
- **Error Handling**: All errors logged; 400/404 responses documented
- **Test Data**: Script generates its own ZIP; no external files needed

---

## ✨ Ready?

**Go ahead and run the test!**

```powershell
# Terminal 1
./run_dev.ps1

# Terminal 2 (after seeing "Application startup complete")
python test_import_quick.py
```

Good luck! 🚀
