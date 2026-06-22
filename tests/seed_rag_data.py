"""Seed courses + pages from template types, then populate embeddings via worker.

Run: PYTHONPATH=. python tests/seed_rag_data.py
"""
from __future__ import annotations
import asyncio, os, sys

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://elearning:elearning_secret@localhost:5432/elearning_db")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.config import SessionLocal
from app.models.persisted_course import CourseRecord
from app.models.page_component import PageRecord, ComponentRecord

# Course templates with realistic titles and descriptions
COURSES = [
    {"course_id": "COURSE-INTRO-001", "title": "Introduction to Data Science with Python",
     "description": "A comprehensive beginner course covering Python fundamentals, data analysis with pandas, visualization with matplotlib, and introductory machine learning concepts. Includes hands-on labs and quiz assessments."},
    {"course_id": "COURSE-LAB-001", "title": "Virtual Chemistry Lab: Organic Reactions",
     "description": "Interactive virtual chemistry lab focusing on organic reaction mechanisms, functional group analysis, and synthesis pathways. Features step-by-step lab procedures, safety protocols, and assessment quizzes."},
    {"course_id": "COURSE-QUIZ-001", "title": "Advanced JavaScript Assessment Suite",
     "description": "Comprehensive assessment course covering ES6+ features, async programming, closures, prototypes, and design patterns. Includes multiple-choice quizzes, coding challenges, and performance tracking."},
    {"course_id": "COURSE-VIDEO-001", "title": "Digital Photography Masterclass",
     "description": "Video-based learning course covering camera techniques, composition rules, lighting setups, post-processing workflows, and portfolio building. Includes video tutorials, hands-on assignments, and peer reviews."},
    {"course_id": "COURSE-TABS-001", "title": "Project Management Professional (PMP) Prep",
     "description": "Tabbed content course organizing PMP exam topics: Initiation, Planning, Execution, Monitoring, and Closing. Each tab covers key concepts, formulas, and practice questions for certification preparation."},
    {"course_id": "COURSE-ACCORD-001", "title": "Web Development Bootcamp: Full Stack",
     "description": "Expandable accordion-based course covering HTML, CSS, JavaScript, React, Node.js, and databases. Each section expands into detailed lessons with code examples and interactive exercises."},
    {"course_id": "COURSE-MIXED-001", "title": "Machine Learning Engineering Fundamentals",
     "description": "Mixed-format course with text content, quizzes, video tutorials, and tabbed reference guides. Covers supervised learning, unsupervised learning, neural networks, MLOps, and model deployment strategies."},
]

PAGES = [
    (0, "Welcome to Data Science", "text-content", "Introduction to Python, pandas, numpy, and the data science workflow. Set up your environment and write your first analysis."),
    (0, "Data Analysis with Pandas", "tabs", "Tabbed reference: DataFrames, Series, GroupBy, Merging, Time Series — each tab with practical examples."),
    (0, "Python Quiz: Fundamentals", "quiz", "10-question assessment on Python basics: variables, loops, functions, and data structures."),
    (1, "Lab Safety and Equipment", "text-content", "Essential safety protocols for organic chemistry lab work. Equipment setup and handling procedures."),
    (1, "Organic Reaction Mechanisms", "accordion", "Expandable panels for SN1, SN2, E1, E2, and addition reactions with step-by-step mechanisms."),
    (1, "Chemistry Assessment", "quiz", "Quiz on functional groups, reaction mechanisms, and synthesis pathways."),
    (2, "ES6+ Features Overview", "text-content", "Arrow functions, destructuring, spread/rest, template literals, and modules."),
    (2, "Async JavaScript Deep Dive", "tabs", "Callbacks, Promises, Async/Await, Event Loop — each tab with code examples."),
    (2, "JavaScript Design Patterns", "accordion", "Singleton, Factory, Observer, Module, and Prototype patterns with ES6 implementations."),
    (3, "Camera Fundamentals", "text-content", "Aperture, shutter speed, ISO, exposure triangle, and lens selection."),
    (3, "Lighting Techniques", "video", "Video tutorials on natural light, studio lighting, flash photography, and light modifiers."),
    (3, "Portfolio Review Quiz", "quiz", "Assessment on composition rules, lighting setups, and post-processing workflows."),
    (4, "Project Initiation", "text-content", "Project charter, stakeholder identification, and scope definition for PMP exam prep."),
    (4, "PMP Formula Reference", "tabs", "EVM formulas, critical path, float calculation, and risk analysis organized by knowledge area."),
    (5, "HTML & CSS Foundations", "text-content", "Semantic HTML5 elements, CSS Grid, Flexbox, responsive design, and accessibility best practices."),
    (5, "React Component Architecture", "accordion", "Functional components, hooks, context API, state management, and performance optimization."),
    (5, "Database Design Fundamentals", "text-content", "Relational vs NoSQL, normalization, indexing strategies, and query optimization."),
    (6, "Supervised Learning Algorithms", "text-content", "Linear regression, logistic regression, decision trees, random forests, and SVMs with scikit-learn examples."),
    (6, "Neural Networks and Deep Learning", "tabs", "Feedforward networks, CNNs, RNNs, Transformers — each tab with architecture diagrams and PyTorch code."),
    (6, "MLOps and Deployment", "accordion", "Model versioning, CI/CD pipelines, containerization, monitoring, and A/B testing for ML systems."),
]


async def seed():
    async with SessionLocal() as session:
        # ── Create courses ──────────────────────────────
        created = 0
        for c in COURSES:
            existing = await session.execute(
                __import__("sqlalchemy").select(CourseRecord).where(CourseRecord.course_id == c["course_id"])
            )
            if existing.scalar_one_or_none():
                print(f"  SKIP (exists): {c['course_id']}")
                continue
            record = CourseRecord(
                course_id=c["course_id"],
                title=c["title"],
                description=c["description"],
                json_data={},
            )
            session.add(record)
            created += 1
            print(f"  CREATED course: {c['course_id']} — {c['title'][:60]}")
        await session.commit()
        print(f"\n  Courses: {created} created, {len(COURSES)} total")

        # ── Create pages ────────────────────────────────
        page_count = 0
        for course_idx, title, ptype, excerpt in PAGES:
            c = COURSES[course_idx]
            page = PageRecord(
                page_id=f"PAGE-{c['course_id']}-{ptype}-{page_count+1}",
                course_id=c["course_id"],
                title=title,
                order_index=page_count,
            )
            session.add(page)
            page_count += 1
        await session.commit()
        print(f"  Pages: {page_count} created across {len(COURSES)} courses")

    print("\n═══ SEED COMPLETE ═══")
    print(f"  {created} courses, {page_count} pages")
    print(f"  Run embedding worker: PYTHONPATH=. python -c \"from app.workers.embedding_worker import EmbeddingWorker; import asyncio; asyncio.run(EmbeddingWorker().start())\"")


if __name__ == "__main__":
    asyncio.run(seed())
