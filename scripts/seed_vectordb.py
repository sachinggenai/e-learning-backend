#!/usr/bin/env python
"""
Seed Vector Database — populate pgvector with course embeddings.

Usage:
    PYTHONPATH=. python scripts/seed_vectordb.py                    # Seed with defaults
    PYTHONPATH=. python scripts/seed_vectordb.py --backup-only      # Only backup
    PYTHONPATH=. python scripts/seed_vectordb.py --restore FILE     # Restore from backup
    PYTHONPATH=. python scripts/seed_vectordb.py --force            # Skip confirmation prompt

Architecture:
    1. BACKUP: Export course_embeddings → seed_backup_YYYYMMDD_HHMMSS.json
    2. SEED COURSES: Insert sample courses if DB is empty (5 courses, 15 pages)
    3. EMBED: Generate embeddings via nomic-embed-text (768-dim) through Ollama
    4. STORE: Insert into course_embeddings table (vector(768))
    5. VALIDATE: Run test queries to verify RAG returns results

Prerequisites:
    - Ollama running on localhost:11434
    - nomic-embed-text model pulled
    - PostgreSQL with pgvector extension
    - DATABASE_URL env var set
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_vectordb")


# ── Configuration ──────────────────────────────────────────────

DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://elearning:elearning_secret@localhost:5432/elearning_db",
)
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
VECTOR_DIM = int(os.getenv("EMBEDDING_DIMENSION", "768"))
BACKUP_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "vectordb_backups")

# ── Sample Course Data ─────────────────────────────────────────

SAMPLE_COURSES = [
    {
        "course_id": "SEED-COURSE-001",
        "title": "Introduction to Instructional Design",
        "description": (
            "Learn the fundamentals of instructional design including ADDIE model, "
            "learning objectives, assessment strategies, and content sequencing. "
            "This course covers Bloom's taxonomy, Gagne's nine events of instruction, "
            "and backward design principles."
        ),
        "pages": [
            {
                "title": "What is Instructional Design?",
                "content": "Instructional design (ID) is the systematic process of creating "
                "educational experiences that make learning more efficient, effective, and engaging. "
                "It applies learning theory, cognitive science, and best practices to create "
                "instructional materials. Key models include ADDIE (Analysis, Design, Development, "
                "Implementation, Evaluation), SAM (Successive Approximation Model), and Kirkpatrick's "
                "Four Levels of Evaluation.",
                "template_type": "text-content",
            },
            {
                "title": "Learning Objectives and Bloom's Taxonomy",
                "content": "Learning objectives describe what learners should know or be able to do "
                "after completing instruction. Bloom's Taxonomy classifies cognitive skills into six "
                "levels: Remember, Understand, Apply, Analyze, Evaluate, and Create. Well-written "
                "objectives use measurable verbs and specify conditions and criteria for success.",
                "template_type": "text-content",
            },
            {
                "title": "Assessment Design Strategies",
                "content": "Effective assessments measure whether learning objectives have been achieved. "
                "Types include formative (during learning), summative (after learning), diagnostic "
                "(before learning), and authentic (real-world application). Multiple choice, essays, "
                "projects, portfolios, and performance tasks each serve different assessment purposes.",
                "template_type": "tabs",
            },
        ],
    },
    {
        "course_id": "SEED-COURSE-002",
        "title": "E-Learning Development with Articulate Storyline",
        "description": (
            "Master e-learning authoring using Articulate Storyline. Build interactive modules, "
            "quizzes, simulations, and branching scenarios. Covers triggers, variables, states, "
            "layers, and responsive design for mobile learning."
        ),
        "pages": [
            {
                "title": "Getting Started with Storyline",
                "content": "Articulate Storyline is a powerful e-learning authoring tool for creating "
                "interactive courses. The interface includes a slide view, timeline, triggers panel, "
                "and states panel. Storyline supports importing PowerPoint, embedding web content, "
                "and publishing to SCORM, xAPI, and HTML5 formats for LMS delivery.",
                "template_type": "text-content",
            },
            {
                "title": "Interactive Elements and Triggers",
                "content": "Triggers in Storyline create interactivity by responding to user actions. "
                "Common triggers: jump to slide, show/hide layer, change state, adjust variable, "
                "submit quiz. Combine triggers with conditions to create branching scenarios where "
                "learner choices determine the path through the content. Use variables to track "
                "learner progress, scores, and preferences across slides.",
                "template_type": "click-reveal",
            },
            {
                "title": "Building Effective Quizzes",
                "content": "Storyline provides graded questions, survey questions, and freeform "
                "interactions. Question types include multiple choice, true/false, fill-in-blank, "
                "drag-and-drop, hotspot, and sequence. Configure passing scores, attempt limits, "
                "and feedback layers. Use question banks to randomize questions and prevent cheating.",
                "template_type": "final-assessment",
            },
        ],
    },
    {
        "course_id": "SEED-COURSE-003",
        "title": "Learning Management System Administration",
        "description": (
            "Comprehensive guide to LMS administration including user management, course catalog "
            "organization, reporting and analytics, SCORM/xAPI compliance, and system integration. "
            "Covers Moodle, Canvas, and Blackboard administration best practices."
        ),
        "template_type": "tabs",
        "pages": [
            {
                "title": "User and Role Management",
                "content": "LMS user management involves creating user accounts, assigning roles "
                "(admin, instructor, student, manager), configuring permissions, and managing "
                "enrollments. Use bulk import tools for large user populations. Set up authentication "
                "via SSO, LDAP, or OAuth. Create organizational hierarchies with departments and groups.",
                "template_type": "text-content",
            },
            {
                "title": "Course Catalog Organization",
                "content": "Organize your course catalog using categories, tags, and learning paths. "
                "Create course templates with standardized settings for easy deployment. Configure "
                "enrollment methods: manual, self-enrollment, guest access, or payment gateway "
                "integration. Set up prerequisites and completion tracking for certification programs.",
                "template_type": "text-content",
            },
            {
                "title": "Analytics and Reporting",
                "content": "LMS analytics provide insights into learner engagement, course completion "
                "rates, assessment performance, and time-on-task. Built-in reports cover activity "
                "logs, grade reports, and competency tracking. Export data for external analysis "
                "or integrate with BI tools. Use learning analytics to identify at-risk learners "
                "and improve course content based on data.",
                "template_type": "accordion",
            },
        ],
    },
    {
        "course_id": "SEED-COURSE-004",
        "title": "Corporate Training and Compliance",
        "description": (
            "Design and deliver effective corporate training programs. Covers compliance training, "
            "onboarding, soft skills development, safety training, and DEI programs. Learn to "
            "measure training ROI and align L&D with business objectives."
        ),
        "pages": [
            {
                "title": "Compliance Training Essentials",
                "content": "Compliance training ensures employees understand laws, regulations, and "
                "company policies relevant to their roles. Key topics: workplace harassment prevention, "
                "data privacy (GDPR, CCPA), information security, anti-corruption, and industry-specific "
                "regulations. Effective compliance training uses scenario-based learning and real-world "
                "examples to make content relevant and memorable. Document completion for audit purposes.",
                "template_type": "text-content",
            },
            {
                "title": "Onboarding Program Design",
                "content": "A structured onboarding program accelerates new hire productivity and "
                "improves retention. Key components: company culture and values, role-specific training, "
                "tools and systems orientation, compliance requirements, and mentorship pairing. "
                "Create a 30-60-90 day plan with clear milestones. Use a blended approach combining "
                "self-paced e-learning, instructor-led sessions, and hands-on practice.",
                "template_type": "tabs",
            },
            {
                "title": "Measuring Training Effectiveness",
                "content": "Use Kirkpatrick's Four Levels to evaluate training: Level 1 (Reaction) - "
                "learner satisfaction surveys, Level 2 (Learning) - pre/post assessments, "
                "Level 3 (Behavior) - on-the-job observation and manager feedback, "
                "Level 4 (Results) - business metrics like productivity, quality, retention. "
                "Calculate ROI by comparing training costs to measurable performance improvements.",
                "template_type": "click-reveal",
            },
        ],
    },
    {
        "course_id": "SEED-COURSE-005",
        "title": "Accessible and Inclusive E-Learning Design",
        "description": (
            "Create e-learning content that is accessible to all learners including those with "
            "disabilities. Covers WCAG 2.1 guidelines, screen reader compatibility, keyboard "
            "navigation, color contrast, captioning, and inclusive language. Learn to use "
            "accessibility checkers and conduct usability testing with diverse audiences."
        ),
        "template_type": "accordion",
        "pages": [
            {
                "title": "WCAG 2.1 Guidelines Overview",
                "content": "The Web Content Accessibility Guidelines (WCAG) 2.1 define four principles "
                "of accessibility: Perceivable, Operable, Understandable, and Robust (POUR). "
                "Each principle has success criteria at three levels: A (minimum), AA (standard), "
                "AAA (enhanced). Most organizations target AA compliance. Key requirements include "
                "text alternatives for non-text content, captions for multimedia, sufficient color "
                "contrast, keyboard accessibility, and consistent navigation.",
                "template_type": "text-content",
            },
            {
                "title": "Screen Reader Compatibility",
                "content": "Screen readers like JAWS, NVDA, and VoiceOver convert on-screen content "
                "to speech or braille. Design for screen readers by: using semantic HTML headings "
                "(H1-H6), providing alt text for images, labeling form elements, using ARIA landmarks, "
                "ensuring proper reading order, and avoiding auto-playing content. Test with actual "
                "screen readers rather than relying solely on automated checkers.",
                "template_type": "text-content",
            },
            {
                "title": "Inclusive Language and Visual Design",
                "content": "Inclusive language avoids bias and makes all learners feel represented. "
                "Use gender-neutral terms, diverse names and scenarios in examples, and culturally "
                "inclusive imagery. For visual design: maintain 4.5:1 color contrast ratio minimum, "
                "use 12pt+ font sizes, avoid relying solely on color to convey meaning, provide "
                "transcripts for audio, and ensure responsive design works across devices.",
                "template_type": "text-content",
            },
        ],
    },
]


# ── Database Helpers ───────────────────────────────────────────


def _uuid_str() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.utcnow().isoformat()


# ── Backup/Restore ─────────────────────────────────────────────


async def backup_embeddings(backup_path: str) -> int:
    """Export all course_embeddings records to a JSON file."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    engine = create_async_engine(DB_URL)
    async with engine.connect() as conn:
        r = await conn.execute(text(
            "SELECT embedding_record_id, course_record_id, organization_id, "
            "content_hash, chunk_count, embedding_model, is_stale, "
            "created_at, updated_at, embedding::text "
            "FROM course_embeddings ORDER BY id"
        ))
        rows = []
        for row in r:
            rows.append({
                "embedding_record_id": row[0],
                "course_record_id": row[1],
                "organization_id": row[2],
                "content_hash": row[3],
                "chunk_count": row[4],
                "embedding_model": row[5],
                "is_stale": row[6],
                "created_at": str(row[7]) if row[7] else None,
                "updated_at": str(row[8]) if row[8] else None,
                "embedding": row[9],  # string representation
            })

    await engine.dispose()

    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "dimension": VECTOR_DIM, "records": rows, "count": len(rows)}, f, indent=2)

    logger.info("Backup saved: %s (%d records)", backup_path, len(rows))
    return len(rows)


async def restore_embeddings(backup_path: str) -> int:
    """Restore course_embeddings from a JSON backup file."""
    with open(backup_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    records = data.get("records", [])
    if not records:
        logger.warning("No records found in backup")
        return 0

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    engine = create_async_engine(DB_URL)
    async with engine.begin() as conn:
        for rec in records:
            # Parse vector from string representation
            vec_str = rec.get("embedding", "[]")
            await conn.execute(text(
                "INSERT INTO course_embeddings "
                "(embedding_record_id, course_record_id, organization_id, "
                "content_hash, chunk_count, embedding_model, is_stale, embedding) "
                "VALUES (:rid, :cid, :org, :hash, :chunk, :model, :stale, CAST(:vec AS vector))"
            ), {
                "rid": rec["embedding_record_id"],
                "cid": rec["course_record_id"],
                "org": rec.get("organization_id", "default"),
                "hash": rec.get("content_hash", ""),
                "chunk": rec.get("chunk_count", 1),
                "model": rec.get("embedding_model", EMBEDDING_MODEL),
                "stale": rec.get("is_stale", False),
                "vec": vec_str,
            })

    await engine.dispose()
    logger.info("Restored %d records from %s", len(records), backup_path)
    return len(records)


# ── Seeding ────────────────────────────────────────────────────


async def seed_courses_if_empty() -> int:
    """Insert sample courses if the DB has no courses besides demo ones."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    engine = create_async_engine(DB_URL)
    async with engine.begin() as conn:
        r = await conn.execute(text("SELECT COUNT(*) FROM courses"))
        count = r.scalar()
        if count >= len(SAMPLE_COURSES):
            logger.info("DB has %d courses — skipping course seeding", count)
            return 0

        inserted = 0
        for course in SAMPLE_COURSES:
            # Check if already exists
            r = await conn.execute(
                text("SELECT 1 FROM courses WHERE course_id = :cid"),
                {"cid": course["course_id"]},
            )
            if r.fetchone():
                continue

            # Insert course
            await conn.execute(text(
                "INSERT INTO courses (course_id, title, description, status, created_at, updated_at, json_data) "
                "VALUES (:cid, :title, :desc, 'published', NOW(), NOW(), '{}')"
            ), {
                "cid": course["course_id"],
                "title": course["title"],
                "desc": course["description"],
            })

            # Insert pages with string course_id reference
            for i, page in enumerate(course["pages"]):
                page_id = f"{course['course_id']}-PAGE-{i+1:02d}"
                # Insert page (course_id is string, not FK)
                await conn.execute(text(
                    "INSERT INTO pages (page_id, course_id, title, order_index, "
                    "layout, created_at, updated_at) "
                    "VALUES (:pid, :cid, :title, :order, :layout, NOW(), NOW())"
                ), {
                    "pid": page_id,
                    "cid": course["course_id"],
                    "title": page["title"],
                    "order": i + 1,
                    "layout": '{"template_type":"' + page["template_type"] + '"}',
                })
                # Insert component (page_id is string, not FK)
                await conn.execute(text(
                    "INSERT INTO components (component_id, page_id, component_type, "
                    "order_index, data, created_at, updated_at) "
                    "VALUES (:cmp_id, :pid, 'text-content', 1, :data, NOW(), NOW())"
                ), {
                    "cmp_id": f"{page_id}-CMP-01",
                    "pid": page_id,
                    "data": '{"text":"' + page["content"].replace('"', '\\"') + '"}',
                })

            inserted += 1
            logger.info("Seeded course: %s (%d pages)", course["course_id"], len(course["pages"]))

    await engine.dispose()
    return inserted


async def embed_courses() -> int:
    """Generate embeddings for all courses and store in course_embeddings."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text
    import httpx

    engine = create_async_engine(DB_URL)

    # Gather courses
    async with engine.connect() as conn:
        r = await conn.execute(text(
            "SELECT id, course_id, COALESCE(title,''), COALESCE(description,'') FROM courses ORDER BY id"
        ))
        courses = [(row[0], row[1], row[2], row[3]) for row in r]

    if not courses:
        logger.warning("No courses to embed")
        await engine.dispose()
        return 0

    embedded_count = 0
    dimension_verified = False

    async with httpx.AsyncClient(timeout=30.0) as http_client:
        for course_pk, course_id, title, description in courses:
            # Build embedding text from course content
            text_to_embed = f"{title}\n{description}"

            # Also append page content from components (link via string IDs)
            async with engine.connect() as conn:
                r = await conn.execute(text(
                    "SELECT p.title, COALESCE(c.data->>'text', p.layout->>'template_type', '') "
                    "FROM pages p "
                    "LEFT JOIN components c ON c.page_id = p.page_id "
                    "WHERE p.course_id = :cid ORDER BY p.order_index"
                ), {"cid": course_id})
                pages = [(row[0], row[1]) for row in r]

            for page_title, page_content in pages:
                if page_content:
                    text_to_embed += f"\n{page_title}\n{str(page_content)[:500]}"

            # Truncate to avoid token limit (~8191 chars for ada, more for nomic)
            text_to_embed = text_to_embed[:8000]

            # Generate embedding via Ollama
            try:
                resp = await http_client.post(
                    f"{OLLAMA_URL}/api/embed",
                    json={"model": EMBEDDING_MODEL, "input": text_to_embed},
                )
                resp.raise_for_status()
                data = resp.json()
                embedding = data.get("embeddings", [[]])[0]

                if not dimension_verified:
                    logger.info("Embedding dimension: %d (model: %s)", len(embedding), EMBEDDING_MODEL)
                    dimension_verified = True

                if len(embedding) != VECTOR_DIM:
                    logger.error(
                        "Dimension mismatch: got %d, expected %d. Check EMBEDDING_MODEL.",
                        len(embedding), VECTOR_DIM,
                    )
                    continue

            except Exception as e:
                logger.error("Failed to embed course %s: %s", course_id, e)
                continue

            # Compute content hash
            content_hash = hashlib.sha256(text_to_embed.encode("utf-8")).hexdigest()

            # Check if embedding already exists and is current
            async with engine.connect() as conn:
                r = await conn.execute(text(
                    "SELECT 1 FROM course_embeddings "
                    "WHERE course_record_id = :cid AND content_hash = :hash AND NOT is_stale"
                ), {"cid": course_pk, "hash": content_hash})
                if r.fetchone():
                    logger.debug("Course %s already embedded (hash match)", course_id)
                    continue

            # Upsert embedding
            vec_str = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
            record_id = _uuid_str()

            async with engine.begin() as conn:
                # Remove old embedding
                await conn.execute(text(
                    "DELETE FROM course_embeddings WHERE course_record_id = :cid"
                ), {"cid": course_pk})

                # Insert new embedding using pgvector cast
                await conn.execute(text(
                    "INSERT INTO course_embeddings "
                    "(embedding_record_id, course_record_id, organization_id, "
                    "content_hash, chunk_count, embedding_model, is_stale, "
                    "embedding, created_at, updated_at) "
                    "VALUES (:rid, :cid, 'default', :hash, :chunk, :model, false, "
                    "CAST(:vec AS vector), NOW(), NOW())"
                ), {
                    "rid": record_id,
                    "cid": course_pk,
                    "hash": content_hash,
                    "chunk": len(pages) + 1,
                    "model": EMBEDDING_MODEL,
                    "vec": vec_str,
                })

            embedded_count += 1
            logger.info(
                "Embedded course: %s (pk=%d, dim=%d, pages=%d)",
                course_id, course_pk, len(embedding), len(pages),
            )

    await engine.dispose()
    return embedded_count


# ── Validation ──────────────────────────────────────────────────


async def validate_rag() -> Dict[str, Any]:
    """Run test queries through the RAG pipeline and report results."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text
    import httpx

    engine = create_async_engine(DB_URL)

    # Get total embedded courses
    async with engine.connect() as conn:
        r = await conn.execute(text(
            "SELECT COUNT(*), COUNT(DISTINCT course_record_id) FROM course_embeddings WHERE NOT is_stale"
        ))
        total, unique = r.fetchone()
        logger.info("Vector DB: %d total, %d unique courses embedded", total, unique)

    # Test queries
    test_queries = [
        ("instructional design principles", "Should match SEED-COURSE-001"),
        ("e-learning authoring tools Storyline", "Should match SEED-COURSE-002"),
        ("LMS administration and reporting", "Should match SEED-COURSE-003"),
        ("corporate compliance training", "Should match SEED-COURSE-004"),
        ("accessible inclusive design WCAG", "Should match SEED-COURSE-005"),
        ("random query that should not match", "May return low-similarity results"),
    ]

    results = []
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        for query, expected in test_queries:
            # Generate query embedding
            resp = await http_client.post(
                f"{OLLAMA_URL}/api/embed",
                json={"model": EMBEDDING_MODEL, "input": query},
            )
            query_vec = resp.json().get("embeddings", [[]])[0]

            t0 = time.perf_counter()
            vec_str = "[" + ",".join(f"{v:.8f}" for v in query_vec) + "]"

            # Search vector DB
            async with engine.connect() as conn:
                try:
                    r = await conn.execute(text(
                        "SELECT ce.course_record_id, c.course_id, c.title, "
                        "1 - (ce.embedding <=> CAST(:qv AS vector)) AS similarity "
                        "FROM course_embeddings ce "
                        "JOIN courses c ON c.id = ce.course_record_id "
                        "WHERE NOT ce.is_stale "
                        "ORDER BY ce.embedding <=> CAST(:qv AS vector) "
                        "LIMIT 5"
                    ), {"qv": vec_str})
                    matches = [(row[0], row[1], row[2], round(float(row[3]), 4)) for row in r]
                except Exception as e:
                    logger.error("Vector search failed for '%s': %s", query, e)
                    matches = []

            latency_ms = (time.perf_counter() - t0) * 1000
            results.append({
                "query": query,
                "expected": expected,
                "matches": [{"course_id": m[1], "title": m[2], "score": m[3]} for m in matches],
                "latency_ms": round(latency_ms, 1),
                "passed": len(matches) > 0,
            })
            status = "PASS" if matches else "FAIL"
            logger.info("%s: '%s' → %d results (%.1fms)", status, query, len(matches), latency_ms)

    await engine.dispose()
    return {"total_embedded": total, "unique_courses": unique, "results": results}


# ── Main ───────────────────────────────────────────────────────


async def main():
    parser = argparse.ArgumentParser(description="Seed Vector Database")
    parser.add_argument("--backup-only", action="store_true", help="Only backup existing data")
    parser.add_argument("--restore", metavar="FILE", help="Restore from backup file")
    parser.add_argument("--force", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--skip-seed", action="store_true", help="Skip course seeding")
    parser.add_argument("--skip-validate", action="store_true", help="Skip validation")
    args = parser.parse_args()

    # Restore mode
    if args.restore:
        count = await restore_embeddings(args.restore)
        print(f"Restored {count} records from {args.restore}")
        return

    # Backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"seed_backup_{timestamp}.json")
    os.makedirs(BACKUP_DIR, exist_ok=True)

    backup_count = await backup_embeddings(backup_path)
    if args.backup_only:
        print(f"Backup complete: {backup_path} ({backup_count} records)")
        return

    # Confirmation
    if not args.force:
        print(f"\n{'='*60}")
        print(f"  Vector DB Seed Script")
        print(f"  Backup: {backup_path} ({backup_count} records)")
        print(f"  Model:  {EMBEDDING_MODEL} ({VECTOR_DIM}-dim)")
        print(f"  DB:     {DB_URL[:60]}...")
        print(f"  This will re-embed all courses.")
        print(f"{'='*60}")
        resp = input("\nProceed? [y/N]: ").strip().lower()
        if resp not in ("y", "yes"):
            print("Aborted.")
            return

    # Seed courses
    if not args.skip_seed:
        seeded = await seed_courses_if_empty()
        if seeded:
            print(f"Seeded {seeded} sample courses")
    else:
        print("Course seeding skipped (--skip-seed)")

    # Embed
    embedded = await embed_courses()
    print(f"\nEmbedded {embedded} courses")

    # Validate
    if not args.skip_validate and embedded > 0:
        print("\n--- Validation ---")
        validation = await validate_rag()
        passed = sum(1 for r in validation["results"] if r["passed"])
        total = len(validation["results"])
        print(f"\nValidation: {passed}/{total} queries returned results")
        for r in validation["results"]:
            status = "PASS" if r["passed"] else "FAIL"
            top = r["matches"][0]["title"] if r["matches"] else "no matches"
            print(f"  {status}: '{r['query'][:50]}' -> {top[:60]} ({r['latency_ms']:.0f}ms)")

    print(f"\nBackup saved: {backup_path}")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
