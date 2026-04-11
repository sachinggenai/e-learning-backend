# Deployment

## Runtime

- Production server starts via `start.sh`.
- Build process references `build.sh` and deployment config files.

## Required Environment

- `ENVIRONMENT=production`
- `DATABASE_URL` (PostgreSQL in production)
- `CORS_ORIGINS`

## Validation Checklist

- Database migrations applied
- API health endpoint reachable
- Export flow verified with sample payload
