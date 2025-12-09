"""Seed builtin template types into the database.

Run this after migrations to populate the template_types table with
the standard templates that can be used across all courses.
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.template_type import Base
from app.repositories.template_type_repo import TemplateTypeRepository


# Builtin template definitions
BUILTIN_TEMPLATES = [
    {
        "template_id": "template_intro_001",
        "name": "Course Introduction",
        "description": (
            "Welcome page with course overview and objectives"
        ),
        "category": "introduction",
        "thumbnail": "/thumbnails/intro.png",
        "estimated_duration": 5,
        "rating": 4.7,
        "usage_count": 156,
        "can_be_page": True,
        "fields": [
            {
                "id": "course_title",
                "name": "courseTitle",
                "type": "text",
                "label": "Course Title",
                "required": True,
                "placeholder": "Enter course title",
            }
        ],
    },
    {
        "template_id": "template_lab_001",
        "name": "Virtual Lab Setup",
        "description": "Interactive lab setup with equipment selection",
        "category": "lab",
        "thumbnail": "/thumbnails/lab_setup.png",
        "estimated_duration": 15,
        "rating": 4.5,
        "usage_count": 89,
        "can_be_page": True,
        "fields": [
            {
                "id": "lab_name",
                "name": "labName",
                "type": "text",
                "label": "Lab Name",
                "required": True,
            }
        ],
    },
    {
        "template_id": "template_assessment_001",
        "name": "Quiz Assessment",
        "description": "Multiple choice quiz with automatic grading",
        "category": "assessment",
        "thumbnail": "/thumbnails/quiz.png",
        "estimated_duration": 20,
        "rating": 4.3,
        "usage_count": 234,
        "can_be_page": True,
        "fields": [
            {
                "id": "quiz_title",
                "name": "quizTitle",
                "type": "text",
                "label": "Quiz Title",
                "required": True,
            }
        ],
    },
]


async def seed_templates():
    """Seed the database with builtin template types."""
    # Import database configuration from app
    from app.db.config import DATABASE_URL

    engine = create_async_engine(DATABASE_URL, future=True)
    async_session = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Create tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed templates
    async with async_session() as session:
        repo = TemplateTypeRepository(session)

        for template_data in BUILTIN_TEMPLATES:
            try:
                # Check if template already exists
                await repo.get_by_template_id(
                    template_data["template_id"]
                )
                print(
                    f"Template '{template_data['name']}' already exists"
                )
            except Exception:
                # Template doesn't exist, create it
                tmpl = await repo.create(
                    template_id=template_data["template_id"],
                    name=template_data["name"],
                    description=template_data["description"],
                    category=template_data["category"],
                    thumbnail=template_data.get("thumbnail"),
                    estimated_duration=template_data.get(
                        "estimated_duration"
                    ),
                    rating=template_data.get("rating", 0.0),
                    usage_count=template_data.get("usage_count", 0),
                    can_be_page=template_data.get("can_be_page", True),
                    fields=template_data.get("fields", {}),
                    is_active=True,
                )
                print(
                    f"Created template: '{tmpl.name}' "
                    f"(ID: {tmpl.template_id})"
                )

        print(f"✅ Successfully seeded {len(BUILTIN_TEMPLATES)} templates")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_templates())
