# PostgreSQL Migration Guide

This guide explains how to migrate from SQLite to PostgreSQL for the eLearning Backend.

## Why PostgreSQL?

- **Production-Ready**: Robust ACID compliance and concurrency support
- **Better Performance**: Optimized for complex queries and concurrent writes
- **Advanced Features**: Full-text search, JSON operations, triggers
- **Scalability**: Handles large datasets and high traffic
- **Open Source**: Free and well-supported

## Prerequisites

### Install PostgreSQL

**macOS (Homebrew)**:
```bash
brew install postgresql@15
brew services start postgresql@15
```

**Ubuntu/Debian**:
```bash
sudo apt-get update
sudo apt-get install postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

**CentOS/RHEL**:
```bash
sudo yum install postgresql-server postgresql-contrib
sudo postgresql-setup initdb
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

**Docker (Quick Start)**:
```bash
docker run --name elearning-postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=elearning \
  -p 5432:5432 \
  -d postgres:15-alpine
```

## Quick Setup

### 1. Run the Setup Script

```bash
cd /Users/aiwork/iOSStudy/backend
./scripts/setup_postgres.sh
```

This script will:
- Check if PostgreSQL is installed and running
- Create the `elearning` database
- Generate a `.env` file with database credentials

### 2. Install Python Dependencies

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Run Migrations

```bash
# Set environment to use PostgreSQL
export POSTGRES_DB=elearning
export POSTGRES_USER=postgres
export POSTGRES_PASSWORD=postgres

# Run migrations
PYTHONPATH=/Users/aiwork/iOSStudy/backend alembic upgrade head
```

### 4. Seed Template Definitions

```bash
PYTHONPATH=/Users/aiwork/iOSStudy/backend python scripts/seed_template_definitions.py
```

### 5. Start the Server

```bash
./run_dev.sh
```

## Manual Configuration

If you prefer manual setup, add these variables to your `.env` file:

```bash
# PostgreSQL Configuration
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=elearning

# Or use full DATABASE_URL
# DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/elearning

# Application Settings
ENVIRONMENT=development
AUTO_MIGRATE=true
SQL_ECHO=false

# Connection Pool Settings (PostgreSQL only)
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
```

## Environment Variables

### Database Connection

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Full database URL (overrides component vars) | - |
| `POSTGRES_USER` | PostgreSQL username | `postgres` |
| `POSTGRES_PASSWORD` | PostgreSQL password | `postgres` |
| `POSTGRES_HOST` | PostgreSQL host | `localhost` |
| `POSTGRES_PORT` | PostgreSQL port | `5432` |
| `POSTGRES_DB` | Database name | `elearning` |

### Connection Pool (PostgreSQL only)

| Variable | Description | Default |
|----------|-------------|---------|
| `DB_POOL_SIZE` | Number of connections to maintain | `10` |
| `DB_MAX_OVERFLOW` | Maximum overflow connections | `20` |

### Application Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `AUTO_MIGRATE` | Run migrations on startup | `false` |
| `SQL_ECHO` | Log all SQL queries | `false` |

## Database Operations

### Create Database

```bash
psql -U postgres -c "CREATE DATABASE elearning;"
```

### Drop Database (CAUTION!)

```bash
psql -U postgres -c "DROP DATABASE elearning;"
```

### Connect to Database

```bash
psql -U postgres -d elearning
```

### Check Connection

```bash
psql -U postgres -d elearning -c "SELECT version();"
```

## Migration from SQLite

If you have existing data in SQLite that needs to be migrated:

### Export from SQLite

```bash
sqlite3 dev.db .dump > sqlite_dump.sql
```

### Convert and Import to PostgreSQL

```bash
# Install pgloader (recommended)
brew install pgloader  # macOS
sudo apt-get install pgloader  # Ubuntu

# Migrate data
pgloader dev.db postgresql://postgres:postgres@localhost/elearning
```

**Or manually**:
```bash
# Clean up SQLite-specific syntax
sed 's/AUTOINCREMENT/SERIAL/g' sqlite_dump.sql > postgres_dump.sql

# Import
psql -U postgres -d elearning -f postgres_dump.sql
```

## Troubleshooting

### Connection Refused

**Problem**: `psql: error: connection to server at "localhost" (::1), port 5432 failed`

**Solution**:
```bash
# Check if PostgreSQL is running
brew services list  # macOS
sudo systemctl status postgresql  # Linux

# Start PostgreSQL
brew services start postgresql@15  # macOS
sudo systemctl start postgresql  # Linux
```

### Authentication Failed

**Problem**: `FATAL: password authentication failed for user "postgres"`

**Solution**:
```bash
# Reset password (if you have access)
psql -U postgres
ALTER USER postgres PASSWORD 'postgres';
\q

# Or edit pg_hba.conf to use 'trust' (development only!)
# Find location: psql -U postgres -c "SHOW hba_file"
```

### Database Already Exists

**Problem**: `ERROR: database "elearning" already exists`

**Solution**: This is fine! The script detected an existing database.

### Port Already in Use

**Problem**: `ERROR: could not bind IPv4 address "127.0.0.1": Address already in use`

**Solution**:
```bash
# Find what's using port 5432
lsof -i :5432

# Stop the conflicting service or use a different port
export POSTGRES_PORT=5433
```

## Performance Tuning

For production, adjust PostgreSQL settings in `postgresql.conf`:

```conf
# Memory
shared_buffers = 256MB
effective_cache_size = 1GB
work_mem = 4MB

# Connections
max_connections = 100

# Logging
log_min_duration_statement = 1000  # Log slow queries (>1s)
```

## Backup and Restore

### Backup

```bash
pg_dump -U postgres elearning > backup_$(date +%Y%m%d).sql
```

### Restore

```bash
psql -U postgres elearning < backup_20251127.sql
```

## Switching Back to SQLite

To switch back to SQLite (not recommended for production):

```bash
# Remove PostgreSQL environment variables from .env
# Or set DATABASE_URL explicitly
DATABASE_URL=sqlite+aiosqlite:///./dev.db

# Restart the server
./run_dev.sh
```

## Production Deployment

For production environments (Render, AWS, etc.):

1. Provision a PostgreSQL instance
2. Set `DATABASE_URL` environment variable
3. Enable `AUTO_MIGRATE=true` for automatic migrations
4. Set appropriate pool sizes based on your instance

Example Render configuration:
```yaml
services:
  - type: web
    name: elearning-backend
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn -k uvicorn.workers.UvicornWorker app.main:app
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: elearning-db
          property: connectionString
      - key: AUTO_MIGRATE
        value: true
```

## Resources

- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [SQLAlchemy Async Documentation](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [asyncpg Documentation](https://magicstack.github.io/asyncpg/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
