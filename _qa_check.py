"""Q&A: trace the Cybersecurity course upload flow."""
import asyncio, sys
sys.path.insert(0, ".")
from app.db.config import SessionLocal
from sqlalchemy import text


async def main():
    async with SessionLocal() as session:

        print("=" * 70)
        print("Q1: What course was created from the docx upload?")
        print("=" * 70)
        r = await session.execute(text("""
            SELECT id, course_id, title, description, status, created_at
            FROM courses
            WHERE course_id LIKE '%cyber%' OR title ILIKE '%cyber%'
            ORDER BY created_at DESC
        """))
        rows = r.fetchall()
        if rows:
            for row in rows:
                print(f"  id={row[0]}  course_id='{row[1]}'")
                print(f"  title='{row[2]}'")
                desc = (row[3] or "")[:150]
                print(f"  description='{desc}'")
                print(f"  status={row[4]}  created={row[5]}")
            course_pk = rows[0][0]
            course_id_val = rows[0][1]
        else:
            print("  No cybersecurity course found!")
            course_pk = None
            course_id_val = None
        print()

        if course_pk:
            print("=" * 70)
            print("Q2: Import job that created it")
            print("=" * 70)
            r = await session.execute(text("""
                SELECT id, status, filename, created_at
                FROM import_jobs
                ORDER BY created_at DESC
                LIMIT 5
            """))
            for row in r.fetchall():
                print(f"  id={row[0]}  status={row[1]}  file='{row[2]}'  created={row[3]}")
            print()

            print("=" * 70)
            print("Q3: Pages in the cybersecurity course")
            print("=" * 70)
            r = await session.execute(text("""
                SELECT title, "order", template_type
                FROM pages
                WHERE course_id = :cid
                ORDER BY "order"
            """), {"cid": course_pk})
            pages = r.fetchall()
            print(f"  Page count: {len(pages)}")
            for p in pages:
                print(f"    {p[1]}. '{p[0]}' ({p[2]})")
            print()

            print("=" * 70)
            print("Q4: Does this course have an embedding?")
            print("=" * 70)
            r = await session.execute(text("""
                SELECT embedding_record_id, embedding_model, is_stale,
                       content_hash, created_at
                FROM course_embeddings
                WHERE course_record_id = :cid
            """), {"cid": course_pk})
            emb = r.fetchone()
            if emb:
                print(f"  YES — id={emb[0]}  model={emb[1]}  stale={emb[2]}")
                print(f"  hash={emb[3][:40]}...  created={emb[4]}")
            else:
                print("  NO embedding exists → RAG won't find this course via Tier-1")
            print()

            print("=" * 70)
            print("Q5: Org-wide RAG numbers")
            print("=" * 70)
            r = await session.execute(text("SELECT COUNT(*) FROM courses"))
            total = r.scalar()
            r = await session.execute(text("SELECT COUNT(*) FROM course_embeddings"))
            emb_total = r.scalar()
            r = await session.execute(text("SELECT COUNT(*) FROM course_embeddings WHERE is_stale = false"))
            fresh = r.scalar()
            print(f"  Total courses: {total}")
            print(f"  With embeddings: {emb_total}")
            print(f"  Fresh (non-stale): {fresh}")
            print(f"  Missing (no RAG coverage): {total - emb_total}")
            print()

            print("=" * 70)
            print("Q6: Session used during testing")
            print("=" * 70)
            r = await session.execute(text("""
                SELECT session_id, course_id, status, created_at
                FROM ai_sessions
                ORDER BY created_at DESC
                LIMIT 5
            """))
            for row in r.fetchall():
                print(f"  session={row[0]}  course={row[1]}  status={row[2]}  created={row[3]}")

        print()
        print("Done.")

asyncio.run(main())
