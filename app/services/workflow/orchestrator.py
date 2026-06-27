"""Durable workflow engine orchestrator — US-BKND-AI-034.

Runs as a background asyncio task spawned in app.main.py's lifespan().
Picks up pending jobs, advances state machines, handles retries/timeouts,
and releases jobs on completion or failure.

Key design decisions:
    - Single-process asyncio (no separate worker process)
    - SELECT FOR UPDATE SKIP LOCKED for distributed concurrency
    - Heartbeat-based stall detection (no Redis)
    - Crash recovery on startup via _recover_stale_jobs()
    - Shared StepRegistry singleton for step function lookup (B1 fix)
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import SessionLocal
from app.repositories.workflow_repository import WorkflowRepository
from app.services.workflow.step_registry import get_default_registry
from app.services.workflow.types import StepResult
from app.models.workflow import WorkflowJob

logger = logging.getLogger(__name__)


def _get_hostname() -> str:
    """Cross-platform hostname helper (os.uname() doesn't exist on Windows)."""
    try:
        return os.uname().nodename
    except AttributeError:
        import platform
        return platform.node() or "unknown"


class WorkflowOrchestrator:
    """Background orchestrator that drives workflow jobs to completion.

    Usage in app.main.py lifespan():
        orchestrator = WorkflowOrchestrator(
            worker_id=os.getenv("WORKFLOW_WORKER_ID"),
            max_concurrency=int(os.getenv("WORKFLOW_MAX_CONCURRENCY", "4")),
        )
        await orchestrator.start()
        # ... app runs ...
        await orchestrator.stop()
    """

    def __init__(
        self,
        worker_id: str | None = None,
        poll_interval_seconds: float = 1.0,
        heartbeat_interval_seconds: float = 5.0,
        max_concurrency: int = 4,
        stale_threshold_seconds: int = 30,
    ):
        self.worker_id = worker_id or os.getenv(
            "WORKFLOW_WORKER_ID", f"worker-{_get_hostname()}"
        )
        self.poll_interval = poll_interval_seconds
        self.heartbeat_interval = heartbeat_interval_seconds
        self.max_concurrency = max_concurrency
        self.stale_threshold_seconds = stale_threshold_seconds
        self._active_jobs: Dict[uuid.UUID, asyncio.Task] = {}
        self._running = False
        # B1 FIX: Use shared singleton — NOT a new StepRegistry()
        self._step_registry = get_default_registry()

    # ═══════════════════════════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════════════════════════

    async def start(self) -> None:
        """Start the orchestrator. Called from app lifespan startup."""
        self._running = True
        logger.info(
            "WorkflowOrchestrator starting (worker=%s, max_concurrency=%d)",
            self.worker_id, self.max_concurrency,
        )
        # 1. Recover jobs orphaned by a previous worker crash
        recovered = await self._recover_stale_jobs()
        if recovered:
            logger.info("Recovered %d stale/expired jobs on startup", recovered)
        # 1b. Auto-reject HITL-expired jobs on startup (Fix-4)
        hitl_expired = await self._expire_stale_hitl_jobs()
        if hitl_expired:
            logger.info("Auto-rejected %d HITL-expired jobs on startup", hitl_expired)
        # 2. Seed workflow type definitions (idempotent)
        await self._seed_type_definitions()
        # 3. Start the poll loop as a background task
        asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Graceful shutdown. Called from app lifespan shutdown."""
        self._running = False
        logger.info(
            "WorkflowOrchestrator stopping (%d active jobs)", len(self._active_jobs)
        )
        if self._active_jobs:
            done, pending = await asyncio.wait(
                list(self._active_jobs.values()), timeout=10.0
            )
            if pending:
                logger.warning("Timed out waiting for %d active jobs", len(pending))

    async def submit_job(
        self,
        workflow_type: str,
        input_data: Dict[str, Any],
        session: AsyncSession,
        webhook_url: Optional[str] = None,
        priority: int = 0,
        created_by_user_id: Optional[str] = None,
    ) -> WorkflowJob:
        """Submit a new workflow job. Returns the created job with UUID."""
        repo = WorkflowRepository(session)
        type_def = await repo.get_type_definition(workflow_type)
        if not type_def:
            raise ValueError(f"Unknown workflow type: {workflow_type}")

        job = await repo.create_job(
            workflow_type=workflow_type,
            input_data=input_data,
            webhook_url=webhook_url,
            priority=priority,
            created_by_user_id=created_by_user_id,
            max_retries=type_def.state_machine.get("max_retries", 3),
            max_duration_seconds=type_def.max_duration_seconds,
        )
        return job

    async def cancel_job(self, job_id: uuid.UUID) -> bool:
        """Cancel a running or pending job. Returns True if cancelled."""
        async with SessionLocal() as session:
            repo = WorkflowRepository(session)
            job = await repo.get_job(job_id)
            if not job or job.status not in ("pending", "running"):
                return False

            await repo.transition(
                job_id=job_id,
                new_status="cancelled",
                new_state=job.current_state,
                previous_state=job.current_state,
            )
            await repo.append_event(
                job_id=job_id,
                state=job.current_state,
                event_type="cancelled",
                payload={"cancelled_by": self.worker_id},
            )

            task = self._active_jobs.pop(job_id, None)
            if task and not task.done():
                task.cancel()
            return True

    # ═══════════════════════════════════════════════════════════════
    # Internal: Poll Loop & Job Execution
    # ═══════════════════════════════════════════════════════════════

    async def _poll_loop(self) -> None:
        """Main loop: poll for pending jobs, execute state machines."""
        iteration = 0
        while self._running:
            try:
                if len(self._active_jobs) < self.max_concurrency:
                    job = await self._pick_and_lock()
                    if job:
                        task = asyncio.create_task(self._execute_job(job))
                        self._active_jobs[job.job_id] = task
                        task.add_done_callback(
                            lambda t, jid=job.job_id: self._active_jobs.pop(jid, None)
                        )

                stale = [jid for jid, t in self._active_jobs.items() if t.done()]
                for jid in stale:
                    self._active_jobs.pop(jid, None)

                # ── Periodic HITL expiry check (every 60 iterations ~60s) ──
                iteration += 1
                if iteration % 60 == 0:
                    try:
                        hitl_count = await self._expire_stale_hitl_jobs()
                        if hitl_count:
                            logger.info("HITL check: auto-rejected %d expired jobs", hitl_count)
                    except Exception:
                        pass  # Non-fatal — don't crash the poll loop

            except Exception:
                logger.exception("Error in orchestration poll loop")

            await asyncio.sleep(self.poll_interval)

    async def _pick_and_lock(self) -> Optional[WorkflowJob]:
        """Atomically claim a pending job from the database."""
        async with SessionLocal() as session:
            repo = WorkflowRepository(session)
            return await repo.try_lock_pending(self.worker_id)

    async def _execute_job(self, job: WorkflowJob) -> None:
        """Run a single job's state machine to completion."""
        job_logger = logging.getLogger(
            f"workflow.{job.workflow_type}.{job.job_id}"
        )
        job_logger.info("Starting execution")

        async with SessionLocal() as session:
            repo = WorkflowRepository(session)
            type_def = await repo.get_type_definition(job.workflow_type)
            if not type_def:
                await repo.transition(
                    job.job_id, "failed", job.current_state, job.current_state,
                    error={
                        "code": "TYPE_NOT_FOUND",
                        "message": f"Workflow type '{job.workflow_type}' not found",
                    },
                    completed_at=datetime.utcnow(),
                )
                return

            state_machine = type_def.state_machine
            checkpoint = dict(job.checkpoint_data or {})

            try:
                await self._run_state_machine(
                    repo, job, state_machine, checkpoint, job_logger
                )
            except asyncio.CancelledError:
                job_logger.warning("Job execution cancelled")
            except Exception as exc:
                job_logger.exception("Unhandled error in state machine")
                await repo.transition(
                    job.job_id, "failed", job.current_state, job.current_state,
                    error={"code": "UNHANDLED_ERROR", "message": str(exc)},
                    checkpoint_data=checkpoint,
                    completed_at=datetime.utcnow(),
                )
                await repo.append_event(
                    job.job_id, job.current_state, "error", {"error": str(exc)}
                )

    async def _run_state_machine(
        self,
        repo: WorkflowRepository,
        job: WorkflowJob,
        state_machine: Dict[str, Any],
        checkpoint: Dict[str, Any],
        job_logger: logging.Logger,
    ) -> None:
        """Advance the job through its state machine states until terminal."""
        current_state_name = job.current_state
        states = state_machine.get("states", [])
        state_configs: Dict[str, Any] = {s["name"]: s for s in states}

        while current_state_name not in ("complete", "failed", "cancelled"):
            state_config = state_configs.get(current_state_name)
            if not state_config:
                raise ValueError(
                    f"Unknown state '{current_state_name}' in state machine"
                )

            timeout_s = state_config.get("timeout_s", 300)
            max_retries_for_state = state_config.get("retry_count", 1)
            next_state_on_success = state_config.get("next", "complete")

            step_func = self._step_registry.get(job.workflow_type, current_state_name)
            if not step_func:
                raise ValueError(
                    f"No step registered for {job.workflow_type}.{current_state_name}"
                )

            await repo.append_event(job.job_id, current_state_name, "state_entered")

            try:
                step_result: StepResult = await asyncio.wait_for(
                    step_func(
                        job.job_id, job.input, checkpoint, job_logger, state_config
                    ),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                job_logger.error(
                    "State '%s' timed out after %ds", current_state_name, timeout_s
                )
                step_result = StepResult(
                    success=False,
                    checkpoint_data=checkpoint,
                    progress=job.progress,
                    error={
                        "code": "STEP_TIMEOUT",
                        "message": f"State '{current_state_name}' timed out after {timeout_s}s",
                    },
                )

            if step_result.success:
                if step_result.checkpoint_data:
                    checkpoint.update(step_result.checkpoint_data)
                progress = (
                    step_result.progress
                    if step_result.progress is not None
                    else job.progress
                )

                await repo.transition(
                    job.job_id,
                    new_status="running",
                    new_state=next_state_on_success,
                    previous_state=current_state_name,
                    progress=progress,
                    checkpoint_data=checkpoint,
                )
                await repo.append_event(
                    job.job_id, current_state_name, "step_completed",
                    {"next_state": next_state_on_success},
                )

                current_state_name = next_state_on_success
                job.progress = progress

            else:
                attempt = job.retry_count + 1
                job_max = job.max_retries

                if attempt <= max_retries_for_state and (
                    job_max == 0 or attempt <= job_max
                ):
                    job_logger.warning(
                        "State '%s' failed (attempt %d/%d). Retrying.",
                        current_state_name, attempt, max_retries_for_state,
                    )
                    await repo.append_event(
                        job.job_id, current_state_name, "retry",
                        {"attempt": attempt, "error": step_result.error},
                    )
                    # Persist partial progress so step resumes from last success
                    await repo.update_checkpoint(job.job_id, checkpoint)
                    await repo.increment_retry(job.job_id)
                    return  # Exit; poll loop re-locks on next cycle
                else:
                    job_logger.error(
                        "State '%s' failed permanently after %d attempts.",
                        current_state_name, attempt,
                    )
                    await repo.transition(
                        job.job_id,
                        new_status="failed",
                        new_state=current_state_name,
                        previous_state=current_state_name,
                        error=step_result.error or {
                            "code": "STEP_FAILED",
                            "message": "Step failed after max retries",
                        },
                        checkpoint_data=checkpoint,
                        completed_at=datetime.utcnow(),
                    )
                    await repo.append_event(
                        job.job_id, current_state_name, "step_failed",
                        {"error": step_result.error, "final_attempt": attempt},
                    )
                    self._enqueue_to_dlq(job, step_result.error)
                    return

        # Terminal: complete
        if current_state_name == "complete":
            await repo.transition(
                job.job_id,
                new_status="complete",
                new_state="complete",
                previous_state=current_state_name,
                progress=1.0,
                result=checkpoint.get("result"),
                checkpoint_data=checkpoint,
                completed_at=datetime.utcnow(),
            )
            await repo.append_event(job.job_id, "complete", "job_completed")
            await self._publish_completion_event(job, repo)
            if job.webhook_url:
                await self._fire_webhook(job, "complete")

    # ═══════════════════════════════════════════════════════════════
    # Internal: Recovery
    # ═══════════════════════════════════════════════════════════════

    async def _recover_stale_jobs(self) -> int:
        """Reclaim jobs orphaned by a previous worker process crash."""
        async with SessionLocal() as session:
            repo = WorkflowRepository(session)
            stale_threshold = self.stale_threshold_seconds

            stale = await repo.find_stale_running_jobs(stale_threshold)
            for job in stale:
                await repo.transition(
                    job.job_id,
                    new_status="pending",
                    new_state=job.current_state,
                    previous_state=job.current_state,
                    error={
                        "code": "WORKER_RECOVERY",
                        "message": f"Recovered after restart (stale >{stale_threshold}s)",
                    },
                )
                await repo.release_lock(job.job_id)

            expired = await repo.find_expired_jobs()
            for job in expired:
                await repo.transition(
                    job.job_id,
                    new_status="failed",
                    new_state=job.current_state,
                    previous_state=job.current_state,
                    error={
                        "code": "JOB_EXPIRED",
                        "message": f"Exceeded max duration",
                    },
                    completed_at=datetime.utcnow(),
                )

            logger.info("Recovered %d stale, expired %d jobs", len(stale), len(expired))
            return len(stale) + len(expired)

    async def _expire_stale_hitl_jobs(self) -> int:
        """Auto-reject jobs stuck in HITL state for > 72 hours.

        When a LangGraph graph hits interrupt() for human approval,
        the job's expires_at is set to now + 72h. If no human responds
        within that window, this method auto-rejects the job.
        """
        async with SessionLocal() as session:
            repo = WorkflowRepository(session)
            expired = await repo.find_expired_hitl_jobs()
            for job in expired:
                logger.warning(
                    "Auto-rejecting job %s — HITL timeout expired at %s",
                    job.job_id, job.expires_at,
                )
                await repo.transition(
                    job.job_id,
                    new_status="cancelled",
                    new_state=job.current_state,
                    previous_state=job.current_state,
                    error={
                        "code": "HITL_TIMEOUT",
                        "message": (
                            f"Human-in-the-loop approval timed out after 72h. "
                            f"Please re-submit the course generation job."
                        ),
                    },
                    completed_at=datetime.utcnow(),
                )
                # Emit outbox event for notification
                try:
                    from app.services.ai.outbox_service import AIOutboxService
                    outbox = AIOutboxService(session)
                    await outbox.publish(
                        event_type="workflow.hitl_timeout",
                        payload={
                            "job_id": str(job.job_id),
                            "workflow_type": job.workflow_type,
                            "expired_at": job.expires_at.isoformat() if job.expires_at else None,
                        },
                    )
                except Exception:
                    pass
            if expired:
                logger.info("Auto-rejected %d HITL-expired jobs", len(expired))
            return len(expired)

    # ═══════════════════════════════════════════════════════════════
    # Internal: Seed Type Definitions
    # ═══════════════════════════════════════════════════════════════

    async def _seed_type_definitions(self) -> None:
        """Register built-in workflow types. Idempotent (upsert)."""
        async with SessionLocal() as session:
            repo = WorkflowRepository(session)

            await repo.register_type_definition(
                workflow_type="course_generation",
                display_name="Course Generation",
                description="Generate full course content from an approved page plan",
                input_schema={
                    "type": "object",
                    "required": ["import_job_id"],
                    "properties": {
                        "import_job_id": {"type": "string"},
                        "course_id": {"type": "string"},
                        "generation_options": {
                            "type": "object",
                            "properties": {
                                "model": {"type": "string"},
                                "temperature": {"type": "number"},
                                "max_tokens_per_page": {"type": "integer"},
                                "retry_count": {"type": "integer"},
                                "language": {"type": "string"},
                            },
                        },
                    },
                },
                state_machine={
                    "states": [
                        {"name": "validate_input", "next": "generate_pages",
                         "retry_count": 1, "timeout_s": 30},
                        {"name": "generate_pages", "next": "validate_course",
                         "retry_count": 3, "timeout_s": 600},
                        {"name": "validate_course", "next": "create_batch_proposal",
                         "retry_count": 1, "timeout_s": 60},
                        {"name": "create_batch_proposal", "next": "complete",
                         "retry_count": 1, "timeout_s": 30},
                        {"name": "complete", "next": None},
                        {"name": "failed", "next": None},
                        {"name": "cancelled", "next": None},
                    ]
                },
            )

            await repo.register_type_definition(
                workflow_type="scorm_export",
                display_name="SCORM Export",
                description="Build a SCORM package for a persisted course",
                input_schema={
                    "type": "object",
                    "required": ["course_id"],
                    "properties": {
                        "course_id": {"type": "string"},
                        "export_options": {"type": "object"},
                    },
                },
                state_machine={
                    "states": [
                        {"name": "validate_course", "next": "generate_manifest",
                         "retry_count": 1, "timeout_s": 30},
                        {"name": "generate_manifest", "next": "package_assets",
                         "retry_count": 1, "timeout_s": 60},
                        {"name": "package_assets", "next": "create_zip",
                         "retry_count": 2, "timeout_s": 120},
                        {"name": "create_zip", "next": "complete",
                         "retry_count": 1, "timeout_s": 180},
                        {"name": "complete", "next": None},
                        {"name": "failed", "next": None},
                        {"name": "cancelled", "next": None},
                    ]
                },
            )

            logger.info("Workflow type definitions seeded")

    # ═══════════════════════════════════════════════════════════════
    # Internal: Integration Hooks
    # ═══════════════════════════════════════════════════════════════

    def _enqueue_to_dlq(
        self, job: WorkflowJob, error: Optional[Dict[str, Any]]
    ) -> None:
        """Route a permanently failed job to the Dead Letter Queue."""
        try:
            from app.services.ai.dead_letter_queue import get_dlq

            get_dlq().enqueue(
                job_id=str(job.job_id),
                job_type=job.workflow_type,
                session_id=str(job.session_id) if job.session_id else "",
                user_id=job.created_by_user_id or "",
                error_message=(
                    error.get("message", "Unknown error")
                    if error else "Unknown error"
                ),
                original_payload={
                    "job_id": str(job.job_id),
                    "input": job.input,
                },
                max_retries=job.max_retries,
            )
        except Exception:
            logger.exception("Failed to enqueue job %s to DLQ", job.job_id)

    async def _publish_completion_event(
        self, job: WorkflowJob, repo: WorkflowRepository
    ) -> None:
        """Emit a WorkflowCompleted event via the Outbox."""
        try:
            from app.services.ai.outbox_service import AIOutboxService

            outbox = AIOutboxService(repo.session)
            await outbox.publish(
                event_type="WorkflowCompleted",
                aggregate_type="workflow",
                aggregate_id=str(job.job_id),
                payload={
                    "workflow_type": job.workflow_type,
                    "status": job.status,
                    "result": job.result,
                    "duration_seconds": (
                        (job.completed_at - job.started_at).total_seconds()
                        if job.started_at and job.completed_at
                        else None
                    ),
                },
            )
        except Exception:
            logger.exception(
                "Failed to publish completion event for job %s", job.job_id
            )

    # ── LangGraph Fallback (Phase 2.9) ──────────────────────────

    def is_langgraph_available(self) -> bool:
        """Check if LangGraph is installed.

        When LangGraph is unavailable, the orchestrator automatically
        handles course generation sequentially (the existing behaviour).
        """
        try:
            from app.services.ai.langgraph.course_generation_graph import is_langgraph_available
            return is_langgraph_available()
        except ImportError:
            return False

    async def degrade_to_sequential(
        self, job: WorkflowJob, reason: str = ""
    ) -> None:
        """Degrade from LangGraph to sequential execution mode.

        Called when LangGraph fails or is unavailable. This ensures
        course generation continues via the durable workflow engine
        even without LangGraph.

        This is the existing behaviour — this method is a formal
        documentation of the fallback path.
        """
        logger.info(
            "Degrading job %s to sequential mode (reason: %s)",
            job.job_id, reason or "LangGraph unavailable",
        )
        async with SessionLocal() as session:
            repo = WorkflowRepository(session)
            await repo.append_event(
                job.job_id,
                job.current_state,
                "degraded_to_sequential",
                {"reason": reason or "LangGraph unavailable"},
            )
        # The job continues via the normal poll loop / state machine

    async def _fire_webhook(self, job: WorkflowJob, status: str) -> None:
        """POST job completion/failure to the configured webhook URL."""
        import httpx

        payload = {
            "job_id": str(job.job_id),
            "workflow_type": job.workflow_type,
            "status": status,
            "result": job.result,
            "error": job.error,
            "completed_at": datetime.utcnow().isoformat(),
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(job.webhook_url, json=payload)
                resp.raise_for_status()

            async with SessionLocal() as session:
                from sqlalchemy import update as sa_update

                await session.execute(
                    sa_update(WorkflowJob)
                    .where(WorkflowJob.job_id == job.job_id)
                    .values(webhook_sent_at=datetime.utcnow())
                )
                await session.commit()
        except Exception:
            logger.warning(
                "Webhook delivery failed for job %s (non-fatal)", job.job_id
            )
