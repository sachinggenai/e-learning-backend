#!/usr/bin/env python3
"""
Seed Data Import Script

Imports the comprehensive master/seed data from the frontend team into the database.
Populates: categories, component_types, themes, and sample courses.

Run this after setting up your database and running migrations:
    python scripts/import_seed_data.py
"""
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession
from app.db.config import engine, SessionLocal
from app.models.base import Base
from app.models.template_type import TemplateType
from app.models.persisted_course import CourseRecord, TemplateRecord
from app.models.theme import ThemeRecord


async def create_tables():
    """Create all database tables."""
    print("Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✓ Tables created")


async def load_json_file(filepath: Path) -> Any:
    """Load and parse a JSON file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


async def import_component_types(session: AsyncSession, data_dir: Path):
    """Import component types from 02-component-types.json."""
    print("\nImporting component types...")
    
    # Check if data already exists
    from sqlalchemy import select, func
    result = await session.execute(select(func.count(TemplateType.id)))
    existing_count = result.scalar()
    
    if existing_count > 0:
        print(f"  Found {existing_count} existing template types. Skipping import.")
        print("  (Delete data/elearning.db to re-import)")
        return
    
    component_types = await load_json_file(data_dir / "02-component-types.json")
    
    imported = 0
    for ct in component_types:
        # Map frontend field names to backend model
        template_type = TemplateType(
            template_id=ct["typeId"],
            name=ct["displayName"],
            description=ct["description"],
            category=ct["category"],
            thumbnail=ct.get("thumbnail"),
            estimated_duration=ct.get("estimatedDuration"),
            rating=0.0,  # Start at 0, will be updated based on usage
            usage_count=0,
            can_be_page=True,  # All component types can be pages
            fields=ct.get("defaultData", {}),  # Store defaultData as fields
            is_active=ct.get("isActive", True),
        )
        session.add(template_type)
        imported += 1
    
    await session.commit()
    print(f"✓ Imported {imported} component types")


async def import_themes(session: AsyncSession, data_dir: Path):
    """Import theme presets from 04-theme-presets.json."""
    print("\nImporting theme presets...")

    from sqlalchemy import select, func
    result = await session.execute(select(func.count(ThemeRecord.id)))
    existing_count = result.scalar()

    if existing_count > 0:
        print(f"  Found {existing_count} existing themes. Skipping import.")
        print("  (Delete data/elearning.db to re-import)")
        return

    theme_presets = await load_json_file(data_dir / "04-theme-presets.json")

    imported = 0
    for tp in theme_presets:
        theme = ThemeRecord(
            theme_id=tp["themeId"],
            name=tp["name"],
            is_preset=tp.get("isPreset", True),
            colors=tp["colors"],
            typography=tp["typography"],
            component_styles=tp.get("componentStyles"),
        )
        session.add(theme)
        imported += 1

    await session.commit()
    print(f"✓ Imported {imported} theme presets")


async def import_courses(session: AsyncSession, data_dir: Path):
    """Import sample courses from 05-courses.json."""
    print("\nImporting sample courses...")
    
    # Check if data already exists
    from sqlalchemy import select, func
    result = await session.execute(select(func.count(CourseRecord.id)))
    existing_count = result.scalar()
    
    if existing_count > 0:
        print(f"  Found {existing_count} existing courses. Skipping import.")
        print("  (Delete data/elearning.db to re-import)")
        return
    
    courses = await load_json_file(data_dir / "05-courses.json")
    
    imported = 0
    for course_data in courses:
        # Create course record with json_data containing full course structure
        course = CourseRecord(
            course_id=course_data["courseId"],
            title=course_data["title"],
            status=course_data.get("status", "draft"),
            description=course_data.get("description", ""),
            json_data=course_data,  # Store full course data including pages
        )
        
        session.add(course)
        await session.flush()  # Get course.id
        
        # Add normalized template records for each page
        for page in course_data.get("pages", []):
            template_data = {
                "pageId": page["pageId"],
                "title": page["title"],
                "order": page["order"],
                "components": page.get("components", []),
                "layout": page.get("layout", {}),
                "pageCompletion": page.get("pageCompletion", {}),
                "theme": page.get("theme", {}),
            }
            
            template = TemplateRecord(
                course_id=course.id,
                template_uid=page["pageId"],
                template_type="page",
                title=page["title"],
                order_index=page["order"],
                json_data=template_data,
            )
            session.add(template)
        
        imported += 1
    
    await session.commit()
    print(f"✓ Imported {imported} courses with {sum(len(c.get('pages', [])) for c in courses)} pages")


async def verify_import(session: AsyncSession):
    """Verify the imported data."""
    print("\nVerifying imported data...")
    
    # Count template types
    from sqlalchemy import select, func
    result = await session.execute(select(func.count(TemplateType.id)))
    template_type_count = result.scalar()
    print(f"  - Template types: {template_type_count}")
    
    # Count themes
    result = await session.execute(select(func.count(ThemeRecord.id)))
    theme_count = result.scalar()
    print(f"  - Theme presets: {theme_count}")

    # Count courses
    result = await session.execute(select(func.count(CourseRecord.id)))
    course_count = result.scalar()
    print(f"  - Courses: {course_count}")
    
    # Sample some template types
    result = await session.execute(
        select(TemplateType.template_id, TemplateType.name, TemplateType.category)
        .limit(5)
    )
    print("\n  Sample template types:")
    for row in result:
        print(f"    - {row.template_id}: {row.name} ({row.category})")
    
    print("\n✓ Verification complete")


async def main():
    """Main import process."""
    print("=" * 60)
    print("eLearning Backend — Seed Data Import")
    print("=" * 60)
    
    # Locate seed data directory
    data_dir = Path(__file__).parent.parent / "seed-data"
    if not data_dir.exists():
        print(f"Error: Seed data directory not found: {data_dir}")
        print("Please ensure the seed-data folder is in the project root.")
        sys.exit(1)
    
    print(f"\nData directory: {data_dir}")
    
    # Create tables
    await create_tables()
    
    # Import data
    async with SessionLocal() as session:
        try:
            # Import in dependency order
            await import_component_types(session, data_dir)
            await import_themes(session, data_dir)
            await import_courses(session, data_dir)
            
            # Verify
            await verify_import(session)
            
            print("\n" + "=" * 60)
            print("✓ Seed data import completed successfully!")
            print("=" * 60)
            print("\nYou can now:")
            print("  - Test GET /api/v1/courses/templates/available")
            print("  - Test GET /api/v1/courses")
            print("  - Create new courses using the template types")
            
        except Exception as e:
            print(f"\n✗ Import failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
