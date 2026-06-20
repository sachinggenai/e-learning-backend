"""Add course_embeddings and course_similarity_cache tables — US-BKND-AI-015.

Revision ID: 20260620_0001
Revises: 20260412_0003
Create Date: 2026-06-20

Creates:
    - course_embeddings: JSONB-based embedding storage with optional pgvector index
    - course_similarity_cache: Forward-compatible cache table (unused in MVP)

Both tables are CREATE IF NOT EXISTS — idempotent, safe to re-run.
pgvector ivfflat index is conditional — only created if pgvector extension exists.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# Resolved: `alembic heads` → 20260412_0003 (as of 2026-06-20)
revision: str = "20260620_0001"
down_revision: Union[str, None] = "20260412_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── course_embeddings ─────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS course_embeddings (
            id                  SERIAL PRIMARY KEY,
            embedding_record_id VARCHAR(64) UNIQUE NOT NULL,
            course_record_id    INTEGER NOT NULL
                REFERENCES courses(id) ON DELETE CASCADE,
            organization_id     VARCHAR(64) NOT NULL DEFAULT 'default',
            embedding           JSONB,
            content_hash        VARCHAR(64) NOT NULL,
            chunk_count         INTEGER NOT NULL DEFAULT 1,
            embedding_model     VARCHAR(100) NOT NULL DEFAULT 'text-embedding-ada-002',
            is_stale            BOOLEAN NOT NULL DEFAULT FALSE,
            created_at          TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
            updated_at          TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_course_embeddings_embedding_record_id
            ON course_embeddings (embedding_record_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_course_embeddings_course_record_id
            ON course_embeddings (course_record_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_course_embeddings_org_id
            ON course_embeddings (organization_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_course_embeddings_org_stale
            ON course_embeddings (organization_id, is_stale)
            WHERE is_stale = FALSE
    """)

    # Conditional pgvector ANN index
    conn = op.get_bind()
    ext_check = conn.execute(
        sa.text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
    ).scalar()
    if ext_check:
        op.execute("""
            CREATE INDEX IF NOT EXISTS ix_course_embeddings_vector
                ON course_embeddings
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
        """)

    # ── course_similarity_cache ────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS course_similarity_cache (
            id                SERIAL PRIMARY KEY,
            source_course_id  INTEGER NOT NULL
                REFERENCES courses(id) ON DELETE CASCADE,
            similar_course_id INTEGER NOT NULL
                REFERENCES courses(id) ON DELETE CASCADE,
            similarity_score  FLOAT NOT NULL,
            retrieval_tier    VARCHAR(8) NOT NULL DEFAULT 'tier1',
            expires_at        TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            created_at        TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
            UNIQUE(source_course_id, similar_course_id)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_similarity_cache_expires
            ON course_similarity_cache (expires_at)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS course_similarity_cache CASCADE")
    op.execute("DROP INDEX IF EXISTS ix_course_embeddings_vector")
    op.execute("DROP INDEX IF EXISTS ix_course_embeddings_org_stale")
    op.execute("DROP INDEX IF EXISTS ix_course_embeddings_org_id")
    op.execute("DROP INDEX IF EXISTS ix_course_embeddings_course_record_id")
    op.execute("DROP INDEX IF EXISTS ix_course_embeddings_embedding_record_id")
    op.execute("DROP TABLE IF EXISTS course_embeddings CASCADE")
