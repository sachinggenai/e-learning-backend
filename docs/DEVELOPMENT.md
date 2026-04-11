# Development

## Local Run

1. Create virtual environment.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Run API:
   - `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`

## Database

- Alembic config is in `alembic.ini` and `alembic/`.
- Typical migration flow:
  - `alembic revision --autogenerate -m "message"`
  - `alembic upgrade head`

## Environment Variables

- `DATABASE_URL`
- `CORS_ORIGINS`
- `AUTO_MIGRATE`
