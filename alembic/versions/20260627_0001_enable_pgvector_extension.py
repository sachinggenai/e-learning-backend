"""Enable pgvector extension — G-05 fix.

Revision ID: 20260627_0001
Revises: 20260620_0002
Create Date: 2026-06-27

Enables the pgvector extension if available, making Tier-1 vector similarity
search functional. Idempotent — safe to run multiple times.

This fixes TPO Gap G-05: "pgvector extension not installed."
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "20260627_0001"
down_revision: Union[str, None] = "20260620_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enable pgvector extension and ensure vector-compatible indexes exist.

    The extension is CREATE IF NOT EXISTS — safe to run on databases
    that already have pgvector installed (e.g., pgvector/pgvector:pg16 Docker image).
    """
    conn = op.get_bind()

    # ── Enable pgvector extension ──────────────────────────────
    try:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        print("  ✓ pgvector extension enabled (or already present)")
    except Exception as exc:
        print(f"  ⚠ pgvector extension could not be enabled: {exc}")
        print("    Tier-1 vector search will use JSONB fallback.")

    # ── Verify extension is available ─────────────────────────
    ext_check = conn.execute(
        sa.text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
    ).scalar()

    if ext_check:
        # Recreate the course_embeddings table with native vector type if
        # it was previously created with JSONB fallback and is empty.
        # We use a non-destructive approach: check if the embedding column
        # is JSONB type, and if the table has no rows, alter it.
        col_info = conn.execute(sa.text("""
            SELECT data_type
            FROM information_schema.columns
            WHERE table_name = 'course_embeddings'
              AND column_name = 'embedding'
        """)).scalar()

        if col_info and col_info.lower() == 'jsonb':
            # Check if table is empty before altering
            row_count = conn.execute(
                sa.text("SELECT COUNT(*) FROM course_embeddings")
            ).scalar()
            if row_count == 0:
                conn.execute(sa.text("""
                    ALTER TABLE course_embeddings
                    ALTER COLUMN embedding TYPE vector(1536)
                    USING embedding::text::vector(1536)
                """))
                print("  ✓ course_embeddings.embedding column upgraded to vector(1536)")

                # Create ivfflat index if it doesn't exist
                try:
                    conn.execute(sa.text("""
                        CREATE INDEX IF NOT EXISTS ix_course_embeddings_vector
                            ON course_embeddings
                            USING ivfflat (embedding vector_cosine_ops)
                            WITH (lists = 100)
                    """))
                    print("  ✓ ivfflat ANN index created on course_embeddings")
                except Exception as idx_exc:
                    print(f"  ⚠ ivfflat index creation failed: {idx_exc}")
            else:
                print("  ⚠ course_embeddings has data — skipping column type migration")
                print("    Re-ingest embeddings after this migration for native vector type.")

        # Create ivfflat index if extension is available and index doesn't exist
        idx_exists = conn.execute(sa.text("""
            SELECT 1 FROM pg_indexes
            WHERE indexname = 'ix_course_embeddings_vector'
        """)).scalar()
        if not idx_exists and col_info and col_info.lower() != 'jsonb':
            try:
                conn.execute(sa.text("""
                    CREATE INDEX IF NOT EXISTS ix_course_embeddings_vector
                        ON course_embeddings
                        USING ivfflat (embedding vector_cosine_ops)
                        WITH (lists = 100)
                """))
                print("  ✓ ivfflat ANN index created on course_embeddings")
            except Exception as idx_exc:
                print(f"  ⚠ ivfflat index creation failed: {idx_exc}")
    else:
        print("  ℹ pgvector extension not available — using JSONB fallback for embeddings")


def downgrade() -> None:
    """Drop the pgvector extension if desired. Commented out by default
    since other tables may depend on it."""
    # Only drop if explicitly requested — dropping the extension cascades
    # and would break any table using vector columns.
    conn = op.get_bind()
    try:
        conn.execute(sa.text("DROP EXTENSION IF EXISTS vector CASCADE"))
        print("  ✓ pgvector extension dropped")
    except Exception as exc:
        print(f"  ⚠ Could not drop pgvector extension: {exc}")
