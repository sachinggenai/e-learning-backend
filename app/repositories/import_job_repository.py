"""
Repository for Import Jobs.

Handles CRUD operations for import_jobs table with async support.
"""

import uuid
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from app.models.persisted_course import ImportJob

logger = logging.getLogger(__name__)


class ImportJobRepository:
    """Async repository for import jobs."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        status: str = "pending",
        course_id: Optional[str] = None,
        source_file_path: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        job_id: Optional[str] = None
    ) -> ImportJob:
        """
        Create a new import job.

        Args:
            status: Initial status (default: "pending")
            course_id: Optional target course ID
            source_file_path: Path to uploaded SCORM zip
            metadata: Optional metadata
            job_id: Optional job ID (auto-generated if not provided)

        Returns:
            Created ImportJob record
        """
        if job_id is None:
            job_id = str(uuid.uuid4())

        job = ImportJob(
            job_id=job_id,
            status=status,
            progress=0.0,
            course_id=course_id,
            source_file_path=source_file_path or "",
            error_message=None,
            result_data=metadata or {}
        )

        self.session.add(job)
        await self.session.commit()

        logger.info(f"Created import job {job_id}")
        return job

    async def get_by_id(self, job_id: str) -> Optional[ImportJob]:
        """Get import job by ID."""
        stmt = select(ImportJob).where(ImportJob.job_id == job_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(
        self,
        job_id: str,
        status: str,
        progress: float = 0.0,
        error_message: Optional[str] = None
    ) -> Optional[ImportJob]:
        """Update import job status and progress."""
        stmt = (
            update(ImportJob)
            .where(ImportJob.job_id == job_id)
            .values(
                status=status,
                progress=progress,
                error_message=error_message,
                updated_at=datetime.utcnow()
            )
            .returning(ImportJob)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()

        job = result.scalar_one_or_none()
        if job:
            logger.info(f"Updated job {job_id} to status {status} ({progress*100:.0f}%)")
        return job

    async def update_result(
        self,
        job_id: str,
        result_data: Dict[str, Any]
    ) -> Optional[ImportJob]:
        """Update job result data (staged course data)."""
        stmt = (
            update(ImportJob)
            .where(ImportJob.job_id == job_id)
            .values(
                result_data=result_data,
                updated_at=datetime.utcnow()
            )
            .returning(ImportJob)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()

        job = result.scalar_one_or_none()
        if job:
            logger.debug(f"Updated job {job_id} result data")
        return job

    async def update_course_id(self, job_id: str, course_id: str) -> Optional[ImportJob]:
        """Link job to a course."""
        stmt = (
            update(ImportJob)
            .where(ImportJob.job_id == job_id)
            .values(
                course_id=course_id,
                updated_at=datetime.utcnow()
            )
            .returning(ImportJob)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one_or_none()

    async def list_by_status(self, status: str, limit: int = 50) -> List[ImportJob]:
        """List jobs by status."""
        stmt = (
            select(ImportJob)
            .where(ImportJob.status == status)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_all(self, limit: int = 50) -> List[ImportJob]:
        """List all import jobs."""
        stmt = select(ImportJob).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def delete(self, job_id: str) -> bool:
        """Delete an import job."""
        stmt = delete(ImportJob).where(ImportJob.job_id == job_id)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def cleanup_old_pending(self, hours: int = 24) -> int:
        """Clean up pending jobs older than specified hours."""
        from datetime import timedelta

        cutoff = datetime.utcnow() - timedelta(hours=hours)
        stmt = delete(ImportJob).where(
            (ImportJob.status == "pending") & (ImportJob.created_at < cutoff)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()

        deleted_count = result.rowcount
        logger.info(f"Cleaned up {deleted_count} old pending jobs")
        return deleted_count
