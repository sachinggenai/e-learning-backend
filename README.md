# Backend

FastAPI backend for course validation, persistence, and SCORM 1.2 package generation.

## Quick Start

1. Create/activate virtual environment.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Start server:
   - `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`

## Core Capabilities

- Course JSON validation and normalization
- Course and template persistence via repository pattern
- Dynamic template handling and SCORM export
- Import and processing APIs for course content workflows

## Documentation

- `docs/ARCHITECTURE.md`
- `docs/DEVELOPMENT.md`
- `docs/TESTING.md`
- `docs/API.md`
- `docs/SCORM.md`
- `docs/DEPLOYMENT.md`
