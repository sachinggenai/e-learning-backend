"""Background worker for populating course embeddings — US-PEND-020.

Runs as an asyncio background task. Periodically scans for courses
missing embeddings and generates vectors via sentence-transformers
or the configured embedding provider.

Architecture:
    EmbeddingWorker (asyncio task)
      → SELECT courses WHERE embedding IS NULL
      → For each course: embedding_provider.embed(course_text)
      → similar_course_repo.upsert_embedding(course_id, vector)
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class EmbeddingWorker:
    """Background worker that populates course_embeddings table.

    Gracefully handles pgvector unavailability: logs a message and
    disables itself if the extension is not installed.

    Usage in app/main.py lifespan():
        worker = EmbeddingWorker(poll_interval_seconds=300)
        await worker.start()
        # ... app runs ...
        await worker.stop()
    """

    def __init__(
        self,
        poll_interval_seconds: float = 300.0,
        batch_size: int = 10,
    ):
        self.poll_interval = poll_interval_seconds
        self.batch_size = batch_size
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._model = None  # Lazy-loaded sentence-transformer model

    async def start(self) -> None:
        """Start the worker background task. Disables itself if pgvector unavailable."""
        if not self._is_pgvector_available():
            logger.info("EmbeddingWorker: pgvector not available — worker disabled")
            return

        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "EmbeddingWorker started (interval=%ds, batch=%d)",
            self.poll_interval, self.batch_size,
        )

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("EmbeddingWorker stopped")

    async def _loop(self) -> None:
        """Main poll loop: process pending courses, then sleep."""
        # Process immediately on first startup
        await self._process_batch()

        while self._running:
            try:
                await asyncio.sleep(self.poll_interval)
                await self._process_batch()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("EmbeddingWorker loop error — will retry")

    async def _process_batch(self) -> int:
        """Process one batch of courses that need embeddings."""
        from app.db.config import SessionLocal
        from app.repositories.similar_course_repo import SimilarCourseRepository
        import hashlib

        processed = 0
        try:
            async with SessionLocal() as session:
                repo = SimilarCourseRepository(session)

                pending = await repo.find_courses_without_embeddings(
                    limit=self.batch_size
                )
                if not pending:
                    return 0

                model = self._get_model()
                for record in pending:
                    try:
                        course_id = getattr(record, 'course_id', '')
                        org_id = getattr(record, 'organization_id', 'default')
                        course_pk = getattr(record, 'id', None)  # Integer PK
                        if course_pk is None:
                            continue

                        course_text = self._build_course_text(record)
                        # Use asyncio.to_thread for blocking encode()
                        vector = await asyncio.to_thread(
                            model.encode, course_text
                        )
                        content_hash = hashlib.sha256(
                            course_text.encode()
                        ).hexdigest()

                        await repo.upsert_embedding(
                            course_record_id=course_pk,
                            organization_id=org_id,
                            embedding=vector.tolist(),
                            content_hash=content_hash,
                            embedding_model=self._model_name(),
                        )
                        processed += 1
                    except Exception as exc:
                        logger.error(
                            "Failed to embed course %s: %s",
                            getattr(record, 'course_id', 'unknown'), exc,
                        )

                await session.commit()

            if processed:
                logger.info("EmbeddingWorker: processed %d courses", processed)
        except Exception:
            logger.exception("EmbeddingWorker batch failed")

        return processed

    def _get_model(self):
        """Lazy-load the sentence-transformer model (cached after first load).

        Uses asyncio.to_thread because model.encode() is CPU-bound.
        """
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            model_name = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
            logger.info("Loading embedding model: %s", model_name)
            self._model = SentenceTransformer(model_name)
        return self._model

    def _model_name(self) -> str:
        return os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    @staticmethod
    def _build_course_text(record) -> str:
        """Build a text representation of a course for embedding."""
        parts = [
            getattr(record, 'title', '') or '',
            getattr(record, 'description', '') or '',
        ]
        return ' '.join(filter(None, parts))

    @staticmethod
    def _is_pgvector_available() -> bool:
        """Check if pgvector extension is installed."""
        try:
            from app.repositories.similar_course_repo import _pgvector_available
            return _pgvector_available()
        except Exception:
            return False
