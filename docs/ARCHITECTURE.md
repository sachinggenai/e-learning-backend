# Architecture

## Request Flow

1. Incoming course payload reaches router.
2. Validation pipeline normalizes and validates payload.
3. Repositories persist entities via SQLAlchemy async session.
4. SCORM export service generates package artifacts.

## Layers

- Pydantic models: input/output validation and compatibility handling
- SQLAlchemy ORM models: persisted database schema
- Repositories: data access abstraction
- Routers/services: orchestration and business flow

## Key Areas

- App entrypoint: `app/main.py`
- Validation logic: `app/utils/validation.py`
- Course models: `app/models/course.py`
- Persistence models: `app/models/persisted_course.py`
- Repositories: `app/repositories/`
- SCORM export: `app/services/scorm_export.py`
