#!/usr/bin/env bash
# rollback.sh — Rollback the last Alembic migration
# Usage: bash docker/rollback.sh [revision]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TARGET="${1:--1}"

cd "$PROJECT_DIR"

echo "⚠️  WARNING: This will rollback the most recent migration."
echo "   Current state:"
PYTHONPATH=. alembic current
echo ""
echo "   Target: $TARGET"
echo ""

read -rp "Continue? [y/N]: " CONFIRM
if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "📦 Creating database backup..."
BACKUP_FILE="backup_$(date +%Y%m%d_%H%M%S).sql"
PGPASSWORD=elearning_secret pg_dump -h localhost -U elearning -d elearning_db > "$BACKUP_FILE"
echo "✅ Backup created: $BACKUP_FILE"

echo ""
echo "⬇️  Rolling back..."
PYTHONPATH=. alembic downgrade "$TARGET"

echo ""
echo "✅ Rollback complete. New state:"
PYTHONPATH=. alembic current
echo ""
echo "   Restore backup with: psql -h localhost -U elearning -d elearning_db < $BACKUP_FILE"
