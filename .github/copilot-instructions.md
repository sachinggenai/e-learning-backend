# AI Agent Instructions — Backend (Concise)

This FastAPI backend validates course JSON and generates SCORM 1.2 packages. These notes help AI agents be productive immediately by surfacing project-specific patterns, files, and workflows.

## Architecture at a Glance

**Data flow**: Inbound JSON → `validate_course_json()` (Pydantic structural + business rules) → persisted via `CourseRepository` → SCORM package generated in `scorm_export.py`.

**Three-layer model strategy**:
1. **Pydantic models** (`app/models/course.py`): `Course`, `Template`, `TemplateData` with v1/v2 compatibility shims.
2. **SQLAlchemy ORM** (`app/models/persisted_course.py`): `CourseRecord`, `TemplateRecord` for persistence.
3. **DTOs** (in routers): Request/response shapes.

**Repository pattern** (`app/repositories/`): All DB access through `CourseRepository`, `TemplateRepository`. Repos commit internally—**never** call `session.commit()` in routers. Accept `AsyncSession`, expose `async` methods.

**Dynamic templates**: Types stored in DB, loaded via `app/services/scorm/registries/template_registry.py` on startup. No hardcoded template logic.

## Key Files (Read These First)

- `app/main.py` — FastAPI app, CORS, routers, exception handlers.
- `app/utils/validation.py` — `validate_course_json()` dependency (two-stage validation).
- `app/models/course.py` — Pydantic models with validators.
- `app/models/persisted_course.py` — SQLAlchemy ORM models.
- `app/repositories/` — CRUD operations.
- `app/services/scorm_export.py` — SCORM package generation.
- `app/db/config.py` — `get_session()` dependency.
- `tests/conftest.py` — fixtures (`sample_course_data`, `mock_scorm_service`).

## Project-Specific Patterns

### Pydantic v1/v2 Compatibility
Code uses a try/except shim. When serializing models, prefer `model_dump()` if present, else fall back to `dict()`. See usage in `_ensure_dict()` in `scorm_export.py`.

### MCQ Legacy Support
Validation handles three MCQ shapes:
1. **Canonical**: `data.questions[{id, question, options[{id, text, isCorrect}]}]`
2. **Flat legacy**: `data.question` + `data.options[]`
3. **JSON-stuffed**: `data.content` contains JSON string of shape #2

Pre-normalization in `validate_course_json()` converts shapes #2/#3 → #1 before Pydantic validation.

### SCORM Critical Notes
- `courseData` must be an object `{courseId, title, templates: [...]}`, NOT a raw array.
- Player load order: `scorm_wrapper.js` → `course_data.js` → inline script (use `defer`).
- Limits: ~100 templates max, package size ~50MB.
- Use `_sanitize_mcq_questions()` to prevent XSS while preserving `isCorrect` booleans.
- SCORM 1.2 does NOT support `cmi.objectives.N.score.scaled` or `cmi.interactions.N.latency`.

## Common Workflows

### Local Development
```bash
./run_dev.sh          # Creates venv, installs deps, runs on :8000
# Or manually: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
pytest                # Run all tests
pytest tests/test_dynamic_scorm_export.py  # Run specific test file
pytest --cov=app tests/    # With coverage
```

### Database Changes
1. Edit SQLAlchemy models in `app/models/persisted_course.py`.
2. Generate migration: `alembic revision --autogenerate -m "description"`.
3. Review migration in `alembic/versions/`.
4. Apply: `alembic upgrade head`.

### Testing Patterns
- Use `test_client` fixture (FastAPI TestClient).
- Fixtures in `tests/conftest.py`: `sample_course_data`, `mock_scorm_service`.
- Async tests require `@pytest.mark.asyncio`.
- Test naming: `test_<feature>_<scenario>`.

## Code Analysis Discipline

**Treat every claim as untrusted** until verified with tools. Do not rely on memory or external knowledge.

1. **Locate**: confirm file existence with `list_dir` or `file_search`.
2. **Read**: inspect exact lines with `read_file`; prefer larger ranges.
3. **Corroborate**: use `grep_search` or `semantic_search` to find related usages.
4. **Trace dependencies**: check imports and cross-file relationships.
5. **Validate**: run targeted tests or `get_errors` to confirm behavior.
6. **Report**: cite file paths and line ranges; quote key code.

### Common Gotchas to Avoid
- Don't assume Pydantic behavior—inspect shim usage first.
- Don't guess DB schemas—read `persisted_course.py` and migrations.
- Don't assume routes exist—verify in `main.py` and router files.
- Don't guess config defaults—inspect env var handling.
- Don't assume template types are hardcoded—check the registry.

## Quick Lookup Table

| Question | Answer |
|----------|--------|
| Where are template types defined? | `BUILTIN_TEMPLATE_TYPES` in `app/models/course.py` or the registry. |
| Where is `courseData` assembled? | `app/services/scorm_export.py` (search for `courseData`). |
| Where is DB session configured? | `app/db/config.py:get_session()`. |
| Where are API endpoints? | `app/routers/` and registered in `app/main.py`. |
| Where are validation rules? | `app/utils/validation.py` and `CourseValidator` in `app/models/course.py`. |
| How do I run tests? | `pytest` or `pytest tests/<filename>.py`. |

## Environment Variables (Dev)
- `DATABASE_URL`: SQLite path (default: `sqlite+aiosqlite:///./data/elearning.db`).
- `CORS_ORIGINS`: Comma-separated (default: `http://localhost:3000,http://localhost:3001`).
- `AUTO_MIGRATE`: Auto-run Alembic on startup (default: `false`).

## Production Deployment
See `render.yaml`, `build.sh`, `start.sh`, and `RENDER_QUICKSTART.md`. Key env vars: `ENVIRONMENT=production`, `DATABASE_URL=postgresql://...`, `CORS_ORIGINS=https://yourfrontend.com`.

---

**Questions?** Check the full docs in repo (`DEPLOYMENT.md`, `SCORM_IMPORT_README.md`, etc.) or ask for clarification on specific sections above.
