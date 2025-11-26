import asyncio
from sqlalchemy import select
from app.db.config import get_session, SessionLocal
from app.models.persisted_course import CourseRecord

async def list_courses():
    async with SessionLocal() as session:
        result = await session.execute(select(CourseRecord))
        courses = result.scalars().all()
        print(f"Found {len(courses)} courses:")
        for c in courses:
            print(f"ID: {c.id}, CourseID: {c.course_id}, Title: {c.title}")

if __name__ == "__main__":
    asyncio.run(list_courses())
