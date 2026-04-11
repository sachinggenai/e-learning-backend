#!/bin/bash
# Implementation script for Template Database migration
# Automatically runs migrations and seeds templates

set -e

echo "════════════════════════════════════════════════════════════════"
echo "   TEMPLATE DATABASE IMPLEMENTATION SCRIPT"
echo "════════════════════════════════════════════════════════════════"
echo ""

# Check if venv is activated
if [[ -z "$VIRTUAL_ENV" ]]; then
    echo "❌ Virtual environment not activated!"
    echo "Please run: source .venv/bin/activate"
    exit 1
fi

echo "✅ Virtual environment activated"
echo ""

# Step 1: Run migrations
echo "Step 1: Running Alembic migrations..."
echo "─────────────────────────────────────────────────────────────────"
alembic upgrade head
echo ""

# Step 2: Seed templates
echo "Step 2: Seeding builtin templates..."
echo "─────────────────────────────────────────────────────────────────"
python scripts/seed_builtin_templates.py
echo ""

# Step 3: Verify
echo "Step 3: Verifying database..."
echo "─────────────────────────────────────────────────────────────────"
python << 'EOF'
import asyncio
import sys
from app.db.config import DATABASE_URL
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from app.models.template_type import TemplateType

async def verify():
    engine = create_async_engine(DATABASE_URL, future=True)
    async_session = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    try:
        async with async_session() as session:
            result = await session.execute(
                select(TemplateType).order_by(TemplateType.rating.desc())
            )
            templates = result.scalars().all()
            
            if not templates:
                print("❌ No templates found in database!")
                await engine.dispose()
                return False
            
            print(f"✅ Found {len(templates)} templates in database:\n")
            for tmpl in templates:
                print(f"   • {tmpl.name} ({tmpl.template_id})")
                print(f"     Category: {tmpl.category}")
                print(f"     Rating: {tmpl.rating} | Usage: {tmpl.usage_count}")
                print(f"     Active: {tmpl.is_active}\n")
            
            await engine.dispose()
            return True
    except Exception as e:
        print(f"❌ Verification failed: {e}")
        await engine.dispose()
        return False

if asyncio.run(verify()):
    sys.exit(0)
else:
    sys.exit(1)
EOF

if [ $? -eq 0 ]; then
    echo ""
    echo "════════════════════════════════════════════════════════════════"
    echo "✅ IMPLEMENTATION COMPLETE!"
    echo "════════════════════════════════════════════════════════════════"
    echo ""
    echo "Next steps:"
    echo "1. Start the server: uvicorn app.main:app --reload"
    echo "2. Test the endpoint: curl http://localhost:8000/api/v1/courses/templates/available"
    echo "3. Review: docs/SCORM.md"
    echo ""
else
    echo ""
    echo "════════════════════════════════════════════════════════════════"
    echo "❌ VERIFICATION FAILED"
    echo "════════════════════════════════════════════════════════════════"
    echo ""
    echo "Please check:"
    echo "1. Database connection is working"
    echo "2. Migrations completed successfully"
    echo "3. Seeding script ran without errors"
    echo ""
    exit 1
fi
