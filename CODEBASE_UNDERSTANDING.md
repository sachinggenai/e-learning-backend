# Codebase Understanding: eLearning Backend

## 1. Overall Project Structure

### Main Modules/Packages
- **app/**: Core application with submodules for models, routers, services, repositories, utils, and db.
- **alembic/**: Database migration management.
- **tests/**: Test suites for validation.
- **scripts/**: Utility scripts for seeding and setup.
- Root-level: Deployment scripts, requirements, and configs.

### Component Dependencies
- Routers depend on services and repositories for business logic and data access.
- Services use utils for validation and repositories for persistence.
- Models provide validation (Pydantic) and persistence (SQLAlchemy).
- Alembic manages schema changes for SQLAlchemy models.

### High-Level Architecture
- **Layered Architecture**: API Layer (routers) → Business Logic (services) → Data Access (repositories) → Infrastructure (db).
- **Services**: Handle complex operations like SCORM export.
- **Utilities**: Shared logic like validation.
- **Models**: Domain entities for validation and persistence.

## 2. Execution Flow

### Entry Point
- `app/main.py`: FastAPI app instance started via `uvicorn`.

### Step-by-Step Flow
1. Load environment variables.
2. Initialize FastAPI app with CORS and routers.
3. Run startup event for auto-migrations.
4. Server listens for requests.
5. On API call (e.g., export): Router injects validation, calls service to generate SCORM, returns response.
6. Async DB operations handled via sessions.

### Key Functions/Classes
- `FastAPI()`: App setup.
- `get_session()`: DB session provider.
- `validate_course_json()`: Pre-export validation.
- `generate_scorm_package()`: Core export logic.

### Background/Async Processes
- All DB ops are async.
- No explicit background tasks; SCORM generation is synchronous per request.

## 3. Purpose of Important Files

- **app/main.py**: App entry point, router inclusion, exception handling.
- **app/db/config.py**: DB configuration and session management.
- **app/models/course.py**: Pydantic models for validation.
- **app/models/persisted_course.py**: SQLAlchemy ORM models.
- **app/repositories/**: Data access classes (e.g., CourseRepository).
- **app/routers/**: API endpoints (e.g., courses.py for CRUD).
- **app/services/scorm_export.py**: SCORM package generation.
- **app/utils/validation.py**: Course validation logic.
- **alembic/env.py**: Migration setup.
- **tests/**: Test files for coverage.

Interactions: Routers call services/repos, services use utils/models.

## 4. Important Patterns

### Design Patterns
- Repository Pattern: Abstracts data access.
- Dependency Injection: FastAPI dependencies.
- Layered Architecture: Separation of concerns.

### APIs/Libraries
- FastAPI: Web framework.
- SQLAlchemy: Async ORM.
- Pydantic: Validation.
- Alembic: Migrations.
- BeautifulSoup: Sanitization.

### Configuration
- ENV vars: DATABASE_URL, CORS_ORIGINS, AUTO_MIGRATE.
- Loaded via dotenv.

## 5. Documentation

### README.md
```markdown
# eLearning Backend

FastAPI backend for SCORM export.

## Setup
1. Clone repo.
2. Run `./run_dev.sh`.

## Running
- `uvicorn app.main:app --reload`

## Testing
- `pytest`

## Architecture
Layered: Routers → Services → Repositories → DB.

## Extending
Add templates in models, update services.
```

### Architecture Diagram (Text-Based)
```
[User] → [Routers] → [Services] → [Repositories] → [DB]
           ↓
      [Utils/Validation]
```

### Setup Instructions
- Install Python, clone repo, run `./run_dev.sh` (sets up venv, installs deps).

### How to Run/Test/Extend
- Run: `uvicorn app.main:app`
- Test: `pytest`
- Extend: Modify models for new templates, update services.

## 6. Suggestions for Improvements

### Code Quality
- Add docstrings to all functions/classes.
- Use type hints consistently.

### Missing Documentation
- Inline comments for complex logic.
- API docs via FastAPI's /docs.

### Refactoring Areas
- Centralize validation logic.
- Reduce hardcoded limits.
- Improve error handling for async ops.
