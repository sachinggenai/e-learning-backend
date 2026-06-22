"""ORM model for course embedding vectors — US-BKND-AI-015.

Stores embedding vectors for similarity search across org-scoped courses.
Uses JSONB for pgvector-optional portability.

Table: course_embeddings
  - Dual-key pattern (int id + UUID string) matches existing AI models
  - embedding stored as {"dim": N, "vec": [...]} in JSONB
  - content_hash prevents wasted re-embedding when content unchanged
  - is_stale flag enables background re-indexing (future iteration)

Table: course_similarity_cache (deferred — table exists, code unused in MVP)
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, DateTime, Integer, Boolean, ForeignKey, Index, JSON,
)
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class CourseEmbeddingRecord(Base):
    """One embedding vector per course — recomputed when content changes."""

    __tablename__ = "course_embeddings"

    # ── Keys ─────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    embedding_record_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )

    # ── Foreign key to courses table ─────────────────────────
    course_record_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("courses.id", ondelete="CASCADE"),
        index=True,
    )

    # ── Tenant scope ─────────────────────────────────────────
    organization_id: Mapped[str] = mapped_column(
        String(64), default="default", index=True
    )

    # ── Vector data (pgvector native vector(1536)) ──
    embedding: Mapped[Optional[list]] = mapped_column(
        Vector(1536), nullable=True
    )

    # ── Staleness tracking ───────────────────────────────────
    content_hash: Mapped[str] = mapped_column(String(64))
    chunk_count: Mapped[int] = mapped_column(Integer, default=1)
    embedding_model: Mapped[str] = mapped_column(
        String(100), default="text-embedding-ada-002"
    )
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False)

    # ── Timestamps ───────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # ── Table-level constraints ──────────────────────────────
    __table_args__ = (
        Index(
            "ix_course_embeddings_org_stale",
            "organization_id",
            "is_stale",
            postgresql_where=(is_stale == False),  # noqa: E712
        ),
    )

    # ── Serialization (matches AI model camelCase convention) ─
    def to_dict(self) -> dict:
        return {
            "embeddingRecordId": self.embedding_record_id,
            "courseRecordId": self.course_record_id,
            "organizationId": self.organization_id,
            "contentHash": self.content_hash,
            "chunkCount": self.chunk_count,
            "embeddingModel": self.embedding_model,
            "isStale": self.is_stale,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }

    # ── Helpers ──────────────────────────────────────────────
    @staticmethod
    def compute_content_hash(title: str, description: str, template_text: str) -> str:
        """SHA-256 of concatenated content for staleness detection."""
        raw = f"{title}\n{description}\n{template_text}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def extract_vector(self) -> Optional[list[float]]:
        """Extract the embedding as a plain list of floats."""
        if self.embedding and "vec" in self.embedding:
            return self.embedding["vec"]
        return None


class CourseSimilarityCache(Base):
    """Optional cache for repeated similarity queries. DEFERRED — unused in MVP.

    Table exists for forward compatibility. No service or repository code
    reads/writes this table in the MVP implementation.
    """

    __tablename__ = "course_similarity_cache"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_course_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("courses.id", ondelete="CASCADE"),
    )
    similar_course_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("courses.id", ondelete="CASCADE"),
    )
    similarity_score: Mapped[float] = mapped_column()
    retrieval_tier: Mapped[str] = mapped_column(
        String(8), default="tier1"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_similarity_cache_expires", "expires_at"),
    )
