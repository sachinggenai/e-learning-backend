# US-PEND-012: Fix SCORM Export Tempfile Leak + Non-Functional Download URL — FULLY ENRICHED

| Field | Value |
|-------|-------|
| **Type** | 🐛 Bug |
| **Priority** | 🟡 HIGH |
| **Batch** | 3 — Reliability Fixes |
| **Depends On** | US-PEND-005 (CourseRepository fix) |
| **Estimated Effort** | 1.5 hours |
| **Target File** | `app/services/workflow/steps/scorm_export.py` lines 115-131 |

---

## User Story

**As a** course author exporting a SCORM package,
**I want** the exported ZIP file to be stored persistently and accessible via a real download URL,
**So that** I can download the SCORM package after the export job completes instead of getting a broken `file://` link.

---

## Intent of Work

Two bugs in one function (`create_zip_step`):

1. **Tempfile leak:** `tempfile.mkdtemp()` creates a permanent temp directory with NO cleanup. On every export, a new directory leaks. On a system with 100 exports/day, this adds up fast.

2. **Dead `file://` URL:** The result stores `"download_url": "file://{zip_path}"` which is a server-local path inaccessible to the client. After the orchestrator restarts or container recycles, the file is gone.

**The fix uses the EXISTING `StorageService`** at `app/services/storage.py` which already has `save_scorm_package()`, `get_scorm_package()`, and `cleanup_scorm_package()` methods backed by `LocalFileSystemStorage`. No new libraries or infrastructure needed.

---

## Current State (Code Verified 2026-06-21)

```python
# scorm_export.py:115-131 — ACTUAL CODE ON DISK
tmp_dir = tempfile.mkdtemp(
    prefix=f"scorm-{course.get('course_id', 'unknown')}-"
)

try:
    zip_path = os.path.join(tmp_dir, "package.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "imsmanifest.xml",
            _json.dumps(checkpoint.get("manifest", {})),
        )

    checkpoint["result"] = {
        "download_url": f"file://{zip_path}",  # ← BROKEN: server-local path
        "file_size_bytes": os.path.getsize(zip_path),
        "generated_at": datetime.utcnow().isoformat(),
    }
except Exception as exc:
    return StepResult(
        success=False,
        error={"code": "ZIP_CREATION_FAILED", "message": str(exc)},
        checkpoint_data=checkpoint,
    )
# ← BUG: No finally block — tmp_dir never cleaned up
```

**Verified Facts:**
- `tempfile.mkdtemp` creates PERMANENT directories (unlike `mkstemp` for files)
- Line 119-131: `try:` block exists but NO `finally:` for cleanup
- Line 128: `file://` URL is dead-on-arrival for any client
- **`app/services/storage.py` EXISTS** with `StorageService.save_scorm_package()` (line 270), `LocalFileSystemStorage` (line 110), and `StorageResult` dataclass (line 18)
- Storage uses `aiofiles` (already in `requirements.txt`) for async I/O
- `StorageService` generates proper file paths under `uploads/` directory

---

## Expected State (Using Existing StorageService)

```python
# scorm_export.py:create_zip_step — FIXED VERSION
import shutil  # ADD to imports at top of file
from app.services.storage import StorageService  # ADD to imports

@registry.register("scorm_export", "create_zip")
async def create_zip_step(
    job_id: uuid.UUID,
    input_data: Dict[str, Any],
    checkpoint: Dict[str, Any],
    logger: logging.Logger,
    step_config: Dict[str, Any],
) -> StepResult:
    """Build the SCORM ZIP package and store it persistently."""
    import json as _json
    import io

    course = checkpoint.get("course", {})
    course_id = course.get("course_id", "unknown")
    tmp_dir = tempfile.mkdtemp(prefix=f"scorm-{course_id}-")

    try:
        # ── Build ZIP in temp directory ─────────────────
        zip_path = os.path.join(tmp_dir, "package.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Write manifest
            zf.writestr(
                "imsmanifest.xml",
                _json.dumps(checkpoint.get("manifest", {})),
            )
            # Write course content files
            # TODO: Add actual course pages from checkpoint when available
            zf.writestr(
                "course_structure.json",
                _json.dumps(checkpoint.get("course", {})),
            )

        # ── Store persistently via StorageService ────────
        storage = StorageService()
        file_size = os.path.getsize(zip_path)

        with open(zip_path, "rb") as f:
            result = await storage.save_scorm_package(
                file_data=f,
                filename=f"{course_id}_scorm.zip",
                job_id=str(job_id),
            )

        if not result.success:
            return StepResult(
                success=False,
                error={
                    "code": "STORAGE_WRITE_FAILED",
                    "message": result.error_message or "Failed to store SCORM package",
                },
                checkpoint_data=checkpoint,
            )

        checkpoint["result"] = {
            "download_url": f"/api/v1/files/{result.file_path}",
            "file_path": result.file_path,
            "file_size_bytes": file_size,
            "generated_at": datetime.utcnow().isoformat(),
            "storage_backend": "local",
        }

    except Exception as exc:
        return StepResult(
            success=False,
            error={"code": "ZIP_CREATION_FAILED", "message": str(exc)},
            checkpoint_data=checkpoint,
        )
    finally:
        # ── ALWAYS clean up temp directory ──────────────
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return StepResult(success=True, checkpoint_data=checkpoint, progress=1.0)
```

---

## 🔧 Open-Source Tooling

**No new libraries needed.** The fix uses only:

| Module | Location | Status |
|--------|----------|--------|
| `StorageService` | `app/services/storage.py:259` | ✅ Already exists |
| `LocalFileSystemStorage` | `app/services/storage.py:110` | ✅ Already exists |
| `shutil` | Python stdlib | ✅ Already available |
| `aiofiles` | `requirements.txt` | ✅ Already installed |

The existing `StorageService` stores files under the `uploads/` directory (configurable via `STORAGE_BASE_PATH` env var). The URL pattern `/api/v1/files/{file_path}` works with the existing FastAPI static file mounting or can be served via a dedicated download endpoint.

---

## Implementation Steps

1. Open `app/services/workflow/steps/scorm_export.py`
2. Add imports at top:
   ```python
   import shutil
   from app.services.storage import StorageService
   ```
3. Wrap lines 115-131 in `try:` ... `finally: shutil.rmtree(tmp_dir, ignore_errors=True)`
4. Replace `file://` URL logic with `StorageService.save_scorm_package()` call
5. Read ZIP bytes into `io.BytesIO` or use file handle for `save_scorm_package()`
6. Generate proper download URL from `result.file_path`
7. Verify: `python -c "from app.services.workflow.steps.scorm_export import create_zip_step"` succeeds

---

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | Temp directory deleted after ZIP creation | `ls /tmp/scorm-*` returns nothing after step execution |
| AC-2 | `download_url` is `/api/v1/files/{path}` (HTTP accessible) | Check `checkpoint["result"]["download_url"]` — no `file://` prefix |
| AC-3 | ZIP content exists after orchestrator restart | `ls uploads/scorm/*.zip` shows file |
| AC-4 | Cleanup happens even if ZIP creation fails (`finally` block) | Test: raise exception mid-zip → temp dir still removed |
| AC-5 | `file://` URL pattern is absent from source | `grep -n "file://" app/services/workflow/steps/scorm_export.py` → 0 matches |

---

## Functional Expectations

- User can download SCORM package via HTTP API after export job completes
- SCORM package persists across application restarts (stored in `uploads/` directory)
- Server disk space does not grow unboundedly from leaked temp directories
- Storage backend is swappable (LocalFileSystemStorage → S3/MinIO via config change)

## Non-Functional Expectations

- `shutil.rmtree` handles missing directory gracefully (`ignore_errors=True`)
- Storage directory configurable via `STORAGE_BASE_PATH` env var (default: `uploads/`)
- Zero new Python package dependencies

---

## Validation

```bash
# 1. Check for shutil import
grep -n "import shutil" app/services/workflow/steps/scorm_export.py

# 2. Check for StorageService import
grep -n "from app.services.storage import" app/services/workflow/steps/scorm_export.py

# 3. Verify no file:// URLs remain
grep -n "file://" app/services/workflow/steps/scorm_export.py
# Expected: 0 matches

# 4. Verify finally block exists
python -c "
from app.services.workflow.steps.scorm_export import create_zip_step
import inspect
source = inspect.getsource(create_zip_step)
assert 'finally:' in source, 'Must have finally block'
assert 'rmtree' in source, 'Must call rmtree'
assert 'StorageService' in source, 'Must use StorageService'
assert 'file://' not in source, 'Must not use file:// URLs'
print('OK')
"

# 5. Run tests
python tests/run_workflow_engine_tests.py
```
