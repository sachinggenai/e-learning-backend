#!/bin/bash
# PostgreSQL Setup Script for eLearning Backend

set -e

echo "================================================"
echo "PostgreSQL Database Setup"
echo "================================================"

# Default values
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-elearning}"

echo "Database Configuration:"
echo "  Host: $POSTGRES_HOST"
echo "  Port: $POSTGRES_PORT"
echo "  User: $POSTGRES_USER"
echo "  Database: $POSTGRES_DB"
echo ""

# Check if PostgreSQL is installed
if ! command -v psql &> /dev/null; then
    echo "❌ PostgreSQL is not installed!"
    echo ""
    echo "Install PostgreSQL:"
    echo "  macOS:   brew install postgresql@15"
    echo "  Ubuntu:  sudo apt-get install postgresql postgresql-contrib"
    echo "  CentOS:  sudo yum install postgresql-server postgresql-contrib"
    echo ""
    exit 1
fi

echo "✓ PostgreSQL is installed"

# Check if PostgreSQL is running
if ! pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" &> /dev/null; then
    echo "⚠️  PostgreSQL is not running on $POSTGRES_HOST:$POSTGRES_PORT"
    echo ""
    echo "Start PostgreSQL:"
    echo "  macOS:   brew services start postgresql@15"
    echo "  Ubuntu:  sudo systemctl start postgresql"
    echo "  CentOS:  sudo systemctl start postgresql"
    echo ""
    exit 1
fi

echo "✓ PostgreSQL is running"

# Create database if it doesn't exist
echo ""
echo "Creating database '$POSTGRES_DB'..."

PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -tc \
    "SELECT 1 FROM pg_database WHERE datname = '$POSTGRES_DB'" | grep -q 1 || \
PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -c \
    "CREATE DATABASE $POSTGRES_DB"

echo "✓ Database '$POSTGRES_DB' is ready"

# Test connection
echo ""
echo "Testing database connection..."
PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version();" > /dev/null

echo "✓ Connection successful"

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo ""
    echo "Creating .env file with database configuration..."
    cat > .env << EOF
# Database Configuration
POSTGRES_USER=$POSTGRES_USER
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
POSTGRES_HOST=$POSTGRES_HOST
POSTGRES_PORT=$POSTGRES_PORT
POSTGRES_DB=$POSTGRES_DB

# Alternative: Use full DATABASE_URL
# DATABASE_URL=postgresql+asyncpg://$POSTGRES_USER:$POSTGRES_PASSWORD@$POSTGRES_HOST:$POSTGRES_PORT/$POSTGRES_DB

# Application Settings
ENVIRONMENT=development
CORS_ORIGINS=http://localhost:3000,http://localhost:3001
AUTO_MIGRATE=true
SQL_ECHO=false

# Connection Pool Settings
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
EOF
    echo "✓ Created .env file"
else
    echo ""
    echo "⚠️  .env file already exists - not overwriting"
    echo "   Add these variables to your .env file:"
    echo ""
    echo "   POSTGRES_USER=$POSTGRES_USER"
    echo "   POSTGRES_PASSWORD=$POSTGRES_PASSWORD"
    echo "   POSTGRES_HOST=$POSTGRES_HOST"
    echo "   POSTGRES_PORT=$POSTGRES_PORT"
    echo "   POSTGRES_DB=$POSTGRES_DB"
fi

echo ""
echo "================================================"
echo "✅ PostgreSQL setup complete!"
echo "================================================"
echo ""
echo "Next steps:"
echo "  1. Install Python dependencies: pip install -r requirements.txt"
echo "  2. Run migrations: alembic upgrade head"
echo "  3. Seed template definitions: python scripts/seed_template_definitions.py"
echo "  4. Start the server: ./run_dev.sh"
echo ""
