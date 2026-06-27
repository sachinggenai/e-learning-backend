"""Seed courses + pages from template types, then populate embeddings.

Creates 10 diverse courses with realistic titles, descriptions, and pages,
then generates embeddings for each course using the configured provider.

Supports both mock (deterministic) and OpenAI embeddings.
Idempotent — safe to run multiple times.

Run: PYTHONPATH=. python tests/seed_rag_data.py

Phase 0.9: Enhanced from 7 to 10 courses with embedding generation.
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
    # ── New courses (Phase 0.9) ──────────────────────────────
    {"course_id": "COURSE-SEC-001", "title": "Cybersecurity Awareness Training",
     "description": "Enterprise security awareness course covering phishing detection, password hygiene, social engineering defense, data protection regulations, and incident response procedures. Includes scenario-based assessments and compliance tracking."},
    {"course_id": "COURSE-LEAD-001", "title": "Leadership and Management Essentials",
     "description": "Professional development course on leadership styles, team motivation, conflict resolution, strategic planning, and performance management. Features case studies, self-assessments, and interactive scenario exercises."},
    {"course_id": "COURSE-DESIGN-001", "title": "UI/UX Design Principles and Practices",
     "description": "Comprehensive design course covering user research methods, wireframing, prototyping, visual design principles, accessibility standards, and usability testing. Includes Figma tutorials and portfolio project assessments."},
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
    # ── New pages for courses 7-9 (Phase 0.9) ──────────────
    (7, "Phishing Awareness", "text-content", "Identify phishing emails, malicious links, social engineering techniques, and reporting procedures."),
    (7, "Password Security Best Practices", "accordion", "Password managers, 2FA setup, passphrase creation, and credential management policies."),
    (7, "Security Compliance Quiz", "quiz", "Assessment on data protection regulations, security policies, and incident response procedures."),
    (8, "Leadership Styles and Approaches", "tabs", "Autocratic, democratic, transformational, servant, and situational leadership — each tab with case studies."),
    (8, "Conflict Resolution Workshop", "click-reveal", "Interactive scenarios for mediating team conflicts, negotiation techniques, and win-win outcomes."),
    (8, "Strategic Planning Assessment", "quiz", "Quiz on SWOT analysis, OKR setting, stakeholder management, and performance metrics."),
    (9, "User Research Fundamentals", "text-content", "Interview techniques, survey design, persona creation, journey mapping, and usability heuristics."),
    (9, "Wireframing and Prototyping", "tabs", "Low-fidelity sketches, interactive prototypes, Figma workflows, and design system components."),
    (9, "Accessibility Standards", "accordion", "WCAG 2.1 guidelines, screen reader testing, color contrast requirements, and inclusive design patterns."),
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

    # ── Generate embeddings (Phase 0.9) ──────────────────
    print("\n── Generating embeddings for all courses ──")
    from app.repositories.similar_course_repo import SimilarCourseRepository
    from app.services.ai.embedding_provider import get_embedding_provider
    import hashlib

    provider = get_embedding_provider()
    provider_type = type(provider).__name__
    print(f"  Embedding provider: {provider_type}")

    async with SessionLocal() as session:
        repo = SimilarCourseRepository(session)
        embedded = 0

        for c in COURSES:
            # Get the course record PK
            from sqlalchemy import select as sa_select
            result = await session.execute(
                sa_select(CourseRecord).where(CourseRecord.course_id == c["course_id"])
            )
            record = result.scalar_one_or_none()
            if record is None:
                print(f"  SKIP (no record): {c['course_id']}")
                continue

            # Build text for embedding
            course_text = f"{c['title']}. {c['description']}"
            # Append page titles for richer embedding
            course_pages = [p for p in PAGES if p[0] == COURSES.index(c)]
            for _, ptitle, ptype, pexcerpt in course_pages[:5]:  # Max 5 pages
                course_text += f" {ptitle}: {pexcerpt}"

            content_hash = hashlib.sha256(course_text.encode()).hexdigest()

            try:
                vector = await provider.embed(course_text)
                await repo.upsert_embedding(
                    course_record_id=record.id,  # Integer PK
                    organization_id="default",
                    embedding=vector,
                    content_hash=content_hash,
                    embedding_model=(
                        provider._model
                        if hasattr(provider, '_model')
                        else os.getenv("EMBEDDING_MODEL", "text-embedding-ada-002")
                    ),
                )
                embedded += 1
                dim_info = f"{len(vector)}d" if hasattr(vector, '__len__') else "?"
                print(f"  EMBEDDED: {c['course_id']} ({dim_info}) — {c['title'][:50]}")
            except Exception as exc:
                print(f"  FAILED: {c['course_id']} — {exc}")

        await session.commit()
        print(f"  Embeddings: {embedded}/{len(COURSES)} courses embedded")

    print("\n═══ SEED COMPLETE ═══")
    print(f"  {created} courses, {page_count} pages, {embedded} embeddings")
    print(f"  Total RAG dataset: {len(COURSES)} courses ready for similarity search")


if __name__ == "__main__":
    asyncio.run(seed())
