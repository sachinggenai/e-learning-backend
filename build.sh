#!/usr/bin/env bash
# Render build script for FastAPI backend

set -o errexit  # Exit on error
set -o nounset  # Exit on undefined variable
set -o pipefail # Exit on pipe failure

echo "========================================="
echo "Building eLearning Backend for Production"
echo "========================================="

echo "Python version:"
python --version

echo ""
echo "Installing Python dependencies..."
pip install --upgrade pip wheel setuptools

# Install from requirements.txt
if [ -f requirements.txt ]; then
    echo "Installing from requirements.txt..."
    pip install --no-cache-dir -r requirements.txt
else
    echo "ERROR: requirements.txt not found!"
    exit 1
fi

# Install production web server (gunicorn)
echo ""
echo "Installing production server (gunicorn)..."
pip install --no-cache-dir gunicorn

# Install PostgreSQL adapter if needed
if [[ "$DATABASE_URL" =~ ^postgres ]]; then
    echo ""
    echo "PostgreSQL detected, installing psycopg2-binary..."
    pip install --no-cache-dir psycopg2-binary
fi

# Create necessary directories
echo ""
echo "Creating data directory..."
mkdir -p data
mkdir -p media/global/audio
mkdir -p media/global/image

# Run database migrations
echo ""
echo "Running database migrations..."
if [ "${AUTO_MIGRATE:-false}" = "true" ]; then
    echo "AUTO_MIGRATE is enabled, running alembic upgrade head..."
    alembic upgrade head || {
        echo "WARNING: Migration failed, but continuing build..."
        echo "You may need to run migrations manually after deployment."
    }
else
    echo "AUTO_MIGRATE is disabled, skipping migrations"
    echo "Run 'alembic upgrade head' manually after deployment if needed"
fi

# Verify installation
echo ""
echo "Verifying installation..."
python -c "import app.main; print('✓ App imports successfully')" || {
    echo "ERROR: Failed to import app.main"
    exit 1
}

echo ""
echo "========================================="
echo "Build completed successfully!"
echo "========================================="
echo "Installed packages:"
pip list | grep -E "(fastapi|uvicorn|gunicorn|sqlalchemy|alembic|pydantic)" || true
