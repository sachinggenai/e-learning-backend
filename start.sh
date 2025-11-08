#!/usr/bin/env bash
# Production start script for Render

set -o errexit

echo "Starting eLearning Backend API..."

# Run migrations if AUTO_MIGRATE is enabled
if [ "$AUTO_MIGRATE" = "true" ]; then
    echo "Running database migrations..."
    alembic upgrade head
fi

# Start the application with gunicorn
exec gunicorn app.main:app \
    --workers ${WORKERS:-4} \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:${PORT:-8000} \
    --timeout ${TIMEOUT:-120} \
    --access-logfile - \
    --error-logfile - \
    --log-level ${LOG_LEVEL:-info}
