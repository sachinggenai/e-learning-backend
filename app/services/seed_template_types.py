"""Seed data for builtin template types.

Called on startup to populate the template_types table.
Uses upsert to avoid duplicates on repeated restarts.
"""
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.template_type_repo import TemplateTypeRepository


# ── Builtin Template Type Definitions ────────
BUILTIN_TEMPLATES: list[dict] = [
    {
        "template_id": "template_intro_001",
        "name": "Course Introduction",
        "description": "Welcome page with course overview and objectives",
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
    {
        "template_id": "template_content_001",
        "name": "Text Content",
        "description": "Simple text content page",
        "category": "content",
        "thumbnail": "/thumbnails/text.png",
        "estimated_duration": 5,
        "rating": 4.2,
        "usage_count": 120,
        "can_be_page": True,
        "fields": [
            {
                "id": "content",
                "name": "content",
                "type": "richtext",
                "label": "Content",
                "required": True,
            }
        ],
    },
    {
        "template_id": "template_video_001",
        "name": "Video Content",
        "description": "Video-based learning content",
        "category": "media",
        "thumbnail": "/thumbnails/video.png",
        "estimated_duration": 10,
        "rating": 4.5,
        "usage_count": 145,
        "can_be_page": True,
        "fields": [
            {
                "id": "video_url",
                "name": "videoUrl",
                "type": "text",
                "label": "Video URL",
                "required": True,
            }
        ],
    },
    {
        "template_id": "template_tabs_001",
        "name": "Tabbed Content",
        "description": "Content organized in tabs",
        "category": "content",
        "thumbnail": "/thumbnails/tabs.png",
        "estimated_duration": 10,
        "rating": 4.1,
        "usage_count": 98,
        "can_be_page": True,
        "fields": [
            {
                "id": "tabs",
                "name": "tabs",
                "type": "array",
                "label": "Tabs",
                "required": True,
            }
        ],
    },
    {
        "template_id": "template_accordion_001",
        "name": "Accordion",
        "description": "Expandable accordion content",
        "category": "content",
        "thumbnail": "/thumbnails/accordion.png",
        "estimated_duration": 8,
        "rating": 4.0,
        "usage_count": 76,
        "can_be_page": True,
        "fields": [
            {
                "id": "panels",
                "name": "panels",
                "type": "array",
                "label": "Panels",
                "required": True,
            }
        ],
    },
]


async def seed_template_types(session: AsyncSession) -> int:
    """Seed or update all builtin template types. Returns count of created/updated items."""
    repo = TemplateTypeRepository(session)
    count = 0
    for item in BUILTIN_TEMPLATES:
        template_id = item.pop("template_id")
        try:
            # Try to get existing template type by template_id
            existing = None
            try:
                existing = await repo.get_by_template_id(template_id)
            except Exception:
                pass
            
            if not existing:
                await repo.create(template_id=template_id, **item)
                count += 1
        except Exception:
            # Already exists or other error - skip
            pass
        
        item["template_id"] = template_id  # Put it back for idempotency
    
    return count
