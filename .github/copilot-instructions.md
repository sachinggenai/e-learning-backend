# Backend AI Coding Agent Instructions

## Project Overview
FastAPI-based backend for an eLearning authoring platform that validates course data and exports SCORM 1.2 packages. The system uses async SQLAlchemy with SQLite (dev) for persistence and follows a repository pattern for data access.

## Architecture & Key Patterns

### Three-Layer Pydantic Model Strategy
1. **Pydantic Models** (`app/models/course.py`): In-memory validation for import/export
   - `Course`, `Template`, `TemplateData` with Pydantic v1/v2 compatibility shims
   - Template types: `welcome`, `content-video`, `content-text`, `mcq`, `summary`
   - Includes validators for template ordering (sequential 0-indexed), MCQ structure
   
2. **SQLAlchemy ORM Models** (`app/models/persisted_course.py`): Persistence layer
   - `CourseRecord`: Stores JSON blob + metadata (course_id unique index)
   - `TemplateRecord`: Normalized template entities with foreign key cascade
   - Use `Base = declarative_base()` from SQLAlchemy, NOT app.database.Base
   
3. **DTOs** (in routers): Request/response shapes (e.g., `CourseCreate`, `CourseOut`)

**Critical**: When handling course data, use `_ensure_dict()` helper from `scorm_export.py` to safely convert Pydantic models to dicts. Check for both `model_dump()` (v2) and `dict()` (v1) methods.

### Repository Pattern
All database operations go through repositories (`app/repositories/`):
- `CourseRepository`: CRUD for courses, raises `CourseNotFoundError`/`CourseConflictError`
- `TemplateRepository`: Scoped to course_id, maintains order_index
- Repositories accept `AsyncSession`, expose async methods, commit internally
- **Never** call `session.commit()` in routers—let repos handle it

### Validation Flow (Two-Stage)
Export validation happens in `app/utils/validation.py` via `validate_course_json` dependency:

1. **Stage 1**: Pydantic structural validation
   - Parse JSON string → `Course(**course_data)`
   - Includes MCQ pre-normalization for legacy formats (flat `question`/`options` → canonical `questions[]`)
   
2. **Stage 2**: Business rules via `CourseValidator`
   - Template count limits (max 100), title length checks
   - MCQ validation accepts both canonical (`data.questions[]`) AND legacy flat shape
   - Returns 422 with structured detail array on failure

**On validation errors**: Raise HTTPException(422) with `detail=[{type, loc, msg, input}]` format matching FastAPI standards.

## SCORM Export Critical Knowledge

### Export Pipeline (`app/services/scorm_export.py`)
1. Pre-flight: `validate_for_export()` + `estimate_package_size()` (max 50MB)
2. Template validation: `_validate_templates_for_scorm()` checks structure
3. Generate files: `imsmanifest.xml`, `course_data.js`, `index.html`, `scorm_wrapper.js`, `styles.css`
4. Production limits: max 100 templates, max 200 assets

### JavaScript Player Architecture
- **Load order matters**: `scorm_wrapper.js` → `course_data.js` → inline player script (all with `defer`)
- `courseData` MUST be `{courseId, title, templates: [...]}` object, NOT raw array
- Player uses `Player.waitForCourseData(5000)` promise with 100ms polling
- SCORM objectives: Use `obj_0`, `obj_1` format; mark slides complete via `cmi.objectives.N.status = 'completed'`
- MCQ answers: `cmi.interactions.N.id/type/student_response/result/correct_responses.0.pattern`

### Common SCORM Gotchas
- **SCORM 1.2 does NOT support**: `cmi.objectives.N.score.scaled`, `cmi.interactions.N.latency`
- Always preserve `isCorrect` as boolean in MCQ options during JSON serialization
- Use `_sanitize_mcq_questions()` to prevent XSS while keeping booleans intact
- HTML content: Use BeautifulSoup sanitization if available, fallback to `_sanitize_text()`

## Database & Migrations

### Alembic Setup
- Runs from workspace root: `alembic upgrade head`
- Config in `alembic.ini` (placeholder URL overridden by `DATABASE_URL` env var)
- Auto-migrate on startup: Set `AUTO_MIGRATE=true` (disabled by default)
- Migrations in `alembic/versions/` follow naming: `YYYYMMDD_NNNN_description.py`

### Session Management
```python
from app.db.config import get_session  # NOT app.database
async with get_session() as session:
    repo = CourseRepository(session)
    # repos commit internally
```

**Database location**: `data/elearning.db` (auto-created on first run)

## Testing

### Running Tests
```bash
# All tests
pytest

# Specific test file
pytest tests/test_courses_api.py

# With coverage
pytest --cov=app tests/

# Markers
pytest -m unit          # Unit tests only
pytest -m integration   # Integration tests only
```

### Test Patterns
- Use `test_client` fixture (FastAPI TestClient with app instance)
- Fixtures in `conftest.py`: `sample_course_data`, `mock_scorm_service`
- Async tests require `@pytest.mark.asyncio`
- Test naming: `test_<feature>_<scenario>` (e.g., `test_export_validates_template_ordering`)

## Development Workflow

### Starting the Server
```bash
./run_dev.sh  # Auto-creates venv, installs deps, runs on :8000 with reload
# Or: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Environment Variables
- `DATABASE_URL`: Override SQLite path (default: `sqlite+aiosqlite:///./data/elearning.db`)
- `CORS_ORIGINS`: Comma-separated (default: `http://localhost:3000,http://localhost:3001`)
- `AUTO_MIGRATE`: Enable Alembic auto-upgrade on startup (default: `false`)
- `EXPORT_HEADERS`: Add `X-Course-Hash`/`X-Export-Warnings` to exports (default: off)

### API Documentation
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Code Style Conventions

### Imports
```python
from __future__ import annotations  # Enable forward refs in type hints
from typing import List, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
```

### Error Handling
- Use `HTTPException(status_code=400/404/422/500, detail=...)`
- Custom exceptions: `CourseNotFoundError`, `CourseConflictError`
- Always log errors: `logger.error("msg", exc_info=True)` for unexpected failures

### Async Patterns
- All DB operations are async: `await repo.create(...)`, `await session.execute(...)`
- Router endpoints: `async def endpoint(...):`
- Service methods: `async def generate_scorm_package(...):`

## File Organization
```
app/
├── main.py              # FastAPI app, CORS, routers, exception handlers
├── database.py          # DEPRECATED (use app.db.config)
├── db/config.py         # get_session dependency, async engine setup
├── models/
│   ├── course.py        # Pydantic validation models
│   └── persisted_course.py  # SQLAlchemy ORM models
├── repositories/        # Data access layer
├── routers/            # API endpoints
├── services/
│   └── scorm_export.py  # SCORM package generation
└── utils/
    ├── validation.py    # validate_course_json dependency
    └── feature_flags.py # (placeholder)
```

## Common Tasks

### Adding a New Template Type
1. Add literal to `TemplateType` in `course.py`
2. Add validation in `CourseValidator._validate_template()`
3. Add renderer in `scorm_export.py` player's `loadSlide()` switch
4. Update SCORM template validation in `_validate_templates_for_scorm()`

### Adding a New API Endpoint
1. Create/extend router in `app/routers/`
2. Add DTOs (Pydantic models) at top of router file
3. Register in `main.py`: `app.include_router(router, prefix="/api/v1")`
4. Add tests in `tests/test_<router>_api.py`

### Modifying Database Schema
1. Edit SQLAlchemy models in `app/models/persisted_course.py`
2. Generate migration: `alembic revision --autogenerate -m "description"`
3. Review generated migration in `alembic/versions/`
4. Apply: `alembic upgrade head`

## Known Issues & Workarounds

### Pydantic v1 vs v2 Compatibility
The codebase uses try/except imports for validators:
```python
try:
    from pydantic import field_validator, model_validator  # v2
    PYDANTIC_V2 = True
except ImportError:
    from pydantic import validator  # v1
    PYDANTIC_V2 = False
```
When serializing: prefer `model_dump()` with v2 check, fallback to `dict()`.

### MCQ Data Structure Legacy Support
Export validation must handle three MCQ shapes:
1. Canonical: `data.questions[{id, question, options[{id, text, isCorrect}]}]`
2. Flat legacy: `data.question` + `data.options[]`
3. JSON-stuffed: `data.content` contains JSON string of shape #2

Pre-normalization in `validate_course_json` converts #2/#3 → #1 before Pydantic validation.

### SCORM Mock API Testing
Player includes mock SCORM API using localStorage for local testing when no LMS is present. Check `scormReady` flag and `mockMode` state in debug output.

## Deployment (Render)

### Quick Deploy
```bash
# 1. Push code with render.yaml to Git
# 2. Render Dashboard → New → Blueprint → Connect repo
# 3. Set CORS_ORIGINS environment variable
# 4. Deploy automatically starts
```

### Key Files
- `render.yaml`: Blueprint configuration (web service + database)
- `build.sh`: Build script (installs deps, runs migrations)
- `start.sh`: Start script (gunicorn with uvicorn workers)
- `Dockerfile.production`: Production Docker image (alternative method)

### Environment Variables (Production)
```bash
ENVIRONMENT=production
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db  # or sqlite
CORS_ORIGINS=https://yourfrontend.com
AUTO_MIGRATE=true
WORKERS=4
```

### Database Options
- **SQLite**: `sqlite+aiosqlite:///./data/elearning.db` (need Render Disk at `/app/data`)
- **PostgreSQL**: `postgresql+asyncpg://...` (recommended, create via Render Dashboard)

### Deployment Docs
- Quick start: `RENDER_QUICKSTART.md`
- Full guide: `DEPLOYMENT.md`
- Setup summary: `DEPLOY_README.md`

## Critical File References
- SCORM player logic: `scorm_export.py` lines 600-1200 (index.html inline script)
- Validation dependency: `validation.py:validate_course_json()`
- Session management: `db/config.py:get_session()`
- Main app setup: `main.py` (CORS, routers, exception handlers)
- Deployment config: `render.yaml`, `build.sh`, `start.sh`
