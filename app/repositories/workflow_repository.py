"""Async repository for workflow jobs, type definitions, and events — US-BKND-AI-034.

Handles job persistence, atomic locking via SELECT FOR UPDATE SKIP LOCKED,
state transitions, heartbeat, event logging, and recovery queries.

Pattern: __init__(self, session: AsyncSession) — matches all existing repos.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, update, func, text, and_, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import WorkflowJob, WorkflowJobEvent, WorkflowTypeDefinition

logger = logging.getLogger(__name__)

LOCK_TIMEOUT_MS = 5000


class WorkflowRepository:
    """Handles durable workflow job persistence and atomic locking."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ═══════════════════════════════════════════════════════════════
    # Type Definitions
    # ═══════════════════════════════════════════════════════════════

    async def get_type_definition(
        self, workflow_type: str
    ) -> Optional[WorkflowTypeDefinition]:
        stmt = select(WorkflowTypeDefinition).where(
            WorkflowTypeDefinition.workflow_type == workflow_type,
            WorkflowTypeDefinition.is_active == True,  # noqa: E712
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def register_type_definition(
        self,
        workflow_type: str,
        display_name: str,
        description: str,
        input_schema: Dict[str, Any],
        state_machine: Dict[str, Any],
        output_schema: Optional[Dict[str, Any]] = None,
        max_duration_seconds: int = 86400,
    ) -> WorkflowTypeDefinition:
        stmt = pg_insert(WorkflowTypeDefinition).values(
            workflow_type=workflow_type,
            display_name=display_name,
            description=description,
            input_schema=input_schema,
            state_machine=state_machine,
            output_schema=output_schema,
            max_duration_seconds=max_duration_seconds,
        ).on_conflict_do_update(
            index_elements=["workflow_type"],
            set_=dict(
                display_name=display_name,
                description=description,
                input_schema=input_schema,
                state_machine=state_machine,
                output_schema=output_schema,
                max_duration_seconds=max_duration_seconds,
                updated_at=datetime.utcnow(),
            ),
        )
        await self.session.execute(stmt)
        await self.session.commit()
        return await self.get_type_definition(workflow_type)

    async def list_active_types(self) -> List[WorkflowTypeDefinition]:
        stmt = select(WorkflowTypeDefinition).where(
            WorkflowTypeDefinition.is_active == True  # noqa: E712
        ).order_by(WorkflowTypeDefinition.workflow_type)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ═══════════════════════════════════════════════════════════════
    # Job CRUD
    # ═══════════════════════════════════════════════════════════════

    async def create_job(
        self,
        workflow_type: str,
        input_data: Dict[str, Any],
        webhook_url: Optional[str] = None,
        priority: int = 0,
        created_by_user_id: Optional[str] = None,
        session_id: Optional[uuid.UUID] = None,
        max_retries: int = 3,
        max_duration_seconds: int = 86400,
    ) -> WorkflowJob:
        job = WorkflowJob(
            workflow_type=workflow_type,
            input=input_data,
            status="pending",
            current_state="validate_input",
            checkpoint_data={},
            progress=0.0,
            retry_count=0,
            max_retries=max_retries,
            webhook_url=webhook_url,
            priority=priority,
            created_by_user_id=created_by_user_id,
            session_id=session_id,
            expires_at=datetime.utcnow() + timedelta(seconds=max_duration_seconds),
        )
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        logger.info("Created workflow job %s (type=%s)", job.job_id, workflow_type)
        return job

    async def get_job(self, job_id: uuid.UUID) -> Optional[WorkflowJob]:
        stmt = select(WorkflowJob).where(WorkflowJob.job_id == job_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_jobs(
        self,
        status: Optional[str] = None,
        workflow_type: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[WorkflowJob], int]:
        conditions = []
        if status:
            conditions.append(WorkflowJob.status == status)
        if workflow_type:
            conditions.append(WorkflowJob.workflow_type == workflow_type)

        count_stmt = select(func.count(WorkflowJob.id))
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar_one()

        stmt = select(WorkflowJob).order_by(
            WorkflowJob.created_at.desc()
        ).limit(limit).offset(offset)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    # ═══════════════════════════════════════════════════════════════
    # Locking & Concurrency (CRITICAL — raw SQL with SKIP LOCKED)
    # ═══════════════════════════════════════════════════════════════

    async def try_lock_pending(self, worker_id: str) -> Optional[WorkflowJob]:
        """Atomically claim the next pending job (priority-ordered).

        Uses raw SQL because SQLAlchemy ORM does not support SKIP LOCKED.
        SET LOCAL lock_timeout scoped to this transaction only.
        """
        stmt = text("""
            SET LOCAL lock_timeout = :lock_timeout;
            SELECT job_id, workflow_type, input, checkpoint_data, current_state,
                   retry_count, max_retries, expires_at
            FROM workflow_jobs
            WHERE status = 'pending'
              AND expires_at > NOW()
              AND locked_by IS NULL
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """).bindparams(lock_timeout=f"{LOCK_TIMEOUT_MS}ms")

        try:
            result = await self.session.execute(stmt)
            row = result.mappings().one_or_none()
        except Exception:
            logger.debug("Lock acquisition timed out or no pending jobs available")
            return None

        if not row:
            return None

        job_id = row["job_id"]
        now = datetime.utcnow()
        await self.session.execute(
            update(WorkflowJob)
            .where(WorkflowJob.job_id == job_id)
            .values(
                status="running",
                locked_by=worker_id,
                started_at=now,
                heartbeat_at=now,
                updated_at=now,
            )
        )
        await self.session.commit()

        stmt2 = select(WorkflowJob).where(WorkflowJob.job_id == job_id)
        result2 = await self.session.execute(stmt2)
        job = result2.scalar_one_or_none()
        if job:
            logger.info("Worker %s locked job %s (type=%s, priority=%s)",
                         worker_id, job.job_id, job.workflow_type, job.priority)
        return job

    async def heartbeat(self, job_id: uuid.UUID) -> None:
        stmt = (
            update(WorkflowJob)
            .where(WorkflowJob.job_id == job_id)
            .values(heartbeat_at=datetime.utcnow(), updated_at=datetime.utcnow())
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def transition(
        self,
        job_id: uuid.UUID,
        new_status: str,
        new_state: str,
        previous_state: str,
        progress: Optional[float] = None,
        error: Optional[Dict[str, Any]] = None,
        result: Optional[Dict[str, Any]] = None,
        checkpoint_data: Optional[Dict[str, Any]] = None,
        completed_at: Optional[datetime] = None,
    ) -> Optional[WorkflowJob]:
        values: Dict[str, Any] = {
            "status": new_status,
            "current_state": new_state,
            "previous_state": previous_state,
            "updated_at": datetime.utcnow(),
        }
        if progress is not None:
            values["progress"] = progress
        if error is not None:
            values["error"] = error
        if result is not None:
            values["result"] = result
        if checkpoint_data is not None:
            values["checkpoint_data"] = checkpoint_data
        if new_status in ("complete", "failed", "cancelled"):
            values["locked_by"] = None
            values["completed_at"] = completed_at or datetime.utcnow()

        stmt = (
            update(WorkflowJob)
            .where(WorkflowJob.job_id == job_id)
            .values(**values)
            .returning(WorkflowJob)
        )
        result_set = await self.session.execute(stmt)
        await self.session.commit()
        job = result_set.scalar_one_or_none()
        if job:
            logger.info("Job %s transitioned to %s/%s", job_id, new_status, new_state)
        return job

    async def release_lock(self, job_id: uuid.UUID) -> None:
        stmt = (
            update(WorkflowJob)
            .where(WorkflowJob.job_id == job_id)
            .values(locked_by=None, updated_at=datetime.utcnow())
        )
        await self.session.execute(stmt)
        await self.session.commit()

    # ═══════════════════════════════════════════════════════════════
    # Recovery
    # ═══════════════════════════════════════════════════════════════

    async def find_stale_running_jobs(
        self, stale_threshold_seconds: int = 30
    ) -> List[WorkflowJob]:
        cutoff = datetime.utcnow() - timedelta(seconds=stale_threshold_seconds)
        stmt = select(WorkflowJob).where(
            WorkflowJob.status == "running",
            WorkflowJob.locked_by.isnot(None),
            or_(
                WorkflowJob.heartbeat_at.is_(None),
                WorkflowJob.heartbeat_at < cutoff,
            ),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_expired_jobs(self) -> List[WorkflowJob]:
        stmt = select(WorkflowJob).where(
            WorkflowJob.expires_at < datetime.utcnow(),
            WorkflowJob.status.in_(["pending", "running"]),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def increment_retry(self, job_id: uuid.UUID) -> Optional[WorkflowJob]:
        stmt = (
            update(WorkflowJob)
            .where(WorkflowJob.job_id == job_id)
            .values(
                retry_count=WorkflowJob.retry_count + 1,
                current_retry_state=WorkflowJob.current_state,
                status="pending",
                locked_by=None,
                updated_at=datetime.utcnow(),
            )
            .returning(WorkflowJob)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one_or_none()

    # ═══════════════════════════════════════════════════════════════
    # Events
    # ═══════════════════════════════════════════════════════════════

    async def append_event(
        self,
        job_id: uuid.UUID,
        state: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> WorkflowJobEvent:
        event = WorkflowJobEvent(
            job_id=job_id,
            state=state,
            event_type=event_type,
            payload=payload or {},
        )
        self.session.add(event)
        await self.session.commit()
        return event

    async def get_events(
        self, job_id: uuid.UUID, limit: int = 500
    ) -> List[WorkflowJobEvent]:
        stmt = (
            select(WorkflowJobEvent)
            .where(WorkflowJobEvent.job_id == job_id)
            .order_by(WorkflowJobEvent.timestamp.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
