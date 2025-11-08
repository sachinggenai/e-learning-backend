"""
Template Seeding Script

Creates initial template data in the database for testing and development.
Provides welcome, content, video, and quiz templates.
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.models.persisted_course import Base, CourseRecord, TemplateRecord


# Template definitions
SEED_TEMPLATES = [
    {
        "template_uid": "welcome_basic",
        "template_type": "welcome",
        "title": "Welcome Page",
        "order_index": 0,
        "json_data": {
            "type": "welcome",
            "title": "Welcome to the Course",
            "subtitle": "Get started with your learning journey",
            "objectives": [
                "Understand the course structure",
                "Learn key concepts",
                "Apply knowledge through exercises"
            ],
            "estimatedDuration": "2 hours",
            "prerequisites": [],
            "content": {
                "welcomeMessage": "Welcome! This course will guide you through...",
                "showObjectives": True,
                "showDuration": True,
                "showPrerequisites": False
            }
        }
    },
    {
        "template_uid": "content_text",
        "template_type": "content-text",
        "title": "Text Content Page",
        "order_index": 1,
        "json_data": {
            "type": "content-text",
            "title": "Content Title",
            "content": {
                "text": "Enter your content here...",
                "formatting": "html",
                "showNavigation": True,
                "allowNotes": True
            },
            "navigation": {
                "showPrevious": True,
                "showNext": True,
                "showProgress": True
            }
        }
    },
    {
        "template_uid": "video_basic",
        "template_type": "video",
        "title": "Video Page",
        "order_index": 2,
        "json_data": {
            "type": "video",
            "title": "Video Lesson",
            "content": {
                "videoUrl": "",
                "videoType": "youtube",
                "description": "Watch this video to learn about...",
                "transcript": "",
                "showControls": True,
                "autoplay": False,
                "showTranscript": True
            },
            "interactions": {
                "allowPause": True,
                "showProgress": True,
                "enableNotes": True
            }
        }
    },
    {
        "template_uid": "quiz_multiple_choice",
        "template_type": "quiz",
        "title": "Multiple Choice Quiz",
        "order_index": 3,
        "json_data": {
            "type": "quiz",
            "title": "Knowledge Check",
            "content": {
                "questions": [
                    {
                        "id": "q1",
                        "type": "multiple-choice",
                        "question": "Enter your question here",
                        "options": [
                            {"id": "a", "text": "Option A", "correct": False},
                            {"id": "b", "text": "Option B", "correct": True},
                            {"id": "c", "text": "Option C", "correct": False},
                            {"id": "d", "text": "Option D", "correct": False}
                        ],
                        "explanation": "Explanation for the correct answer"
                    }
                ],
                "showFeedback": True,
                "allowRetries": True,
                "passingScore": 70
            },
            "scoring": {
                "pointsPerQuestion": 10,
                "showScore": True,
                "trackProgress": True
            }
        }
    },
    {
        "template_uid": "image_content",
        "template_type": "content-image",
        "title": "Image with Text",
        "order_index": 4,
        "json_data": {
            "type": "content-image",
            "title": "Image Content",
            "content": {
                "imageUrl": "",
                "imageAlt": "Descriptive text for the image",
                "imagePosition": "left",
                "text": "Content text that accompanies the image...",
                "caption": "",
                "showCaption": False
            },
            "layout": {
                "imageSize": "medium",
                "textWrap": True,
                "responsive": True
            }
        }
    },
    {
        "template_uid": "interactive_hotspot",
        "template_type": "interactive",
        "title": "Interactive Hotspots",
        "order_index": 5,
        "json_data": {
            "type": "interactive",
            "title": "Explore the Image",
            "content": {
                "baseImageUrl": "",
                "baseImageAlt": "Interactive image with hotspots",
                "hotspots": [
                    {
                        "id": "hotspot1",
                        "x": 100,
                        "y": 100,
                        "title": "Hotspot 1",
                        "description": "Click to learn more about this area",
                        "content": "Detailed information about this hotspot..."
                    }
                ],
                "instructions": "Click on the hotspots to learn more"
            },
            "behavior": {
                "autoReveal": False,
                "allowMultipleOpen": False,
                "showProgress": True
            }
        }
    }
]


async def seed_templates():
    """Seed the database with initial template data."""
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

    # Create a demo course to attach templates to
    async with async_session() as session:
        # Check if demo course exists
        from sqlalchemy import select
        result = await session.execute(
            select(CourseRecord).where(CourseRecord.course_id == "demo_course")
        )
        demo_course = result.scalar_one_or_none()
        
        if not demo_course:
            demo_course = CourseRecord(
                course_id="demo_course",
                title="Demo Course for Templates",
                description="A course to hold template examples",
                json_data={"pages": [], "templates": []},
                status="draft"
            )
            session.add(demo_course)
            await session.flush()  # Get the ID
        
        # Check if templates already exist
        result = await session.execute(
            select(TemplateRecord).where(TemplateRecord.course_id == demo_course.id)
        )
        existing_templates = result.scalars().all()
        
        if existing_templates:
            print(f"Templates already exist for demo course (found {len(existing_templates)})")
            return
        
        # Create template records
        template_records = []
        for template_data in SEED_TEMPLATES:
            template_record = TemplateRecord(
                course_id=demo_course.id,
                template_uid=template_data["template_uid"],
                template_type=template_data["template_type"],
                title=template_data["title"],
                order_index=template_data["order_index"],
                json_data=template_data["json_data"]
            )
            template_records.append(template_record)
            session.add(template_record)
        
        await session.commit()
        print(f"Successfully seeded {len(template_records)} templates for demo course")


if __name__ == "__main__":
    asyncio.run(seed_templates())