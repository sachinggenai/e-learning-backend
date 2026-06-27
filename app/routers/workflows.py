"""REST endpoints for the durable workflow engine — US-BKND-AI-034.

6 endpoints:
    POST   /api/v1/workflows              Submit a workflow job (202)
    GET    /api/v1/workflows/{job_id}     Poll job status (200)
    POST   /api/v1/workflows/{job_id}/cancel   Cancel running job (200)
    POST   /api/v1/workflows/{job_id}/retry    Retry failed job (200)
    GET    /api/v1/workflows/{job_id}/events   Get event history (200)
    GET    /api/v1/workflows              List jobs with filters (200)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.dependencies.auth_dependencies import get_current_user
from app.models.user_context import UserContext
from app.repositories.workflow_repository import WorkflowRepository
from app.services.workflow.orchestrator import WorkflowOrchestrator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/workflows", tags=["Workflows"])


# ═══════════════════════════════════════════════════════════════════
# Pydantic Schemas
# ═══════════════════════════════════════════════════════════════════

class SubmitWorkflowRequest(BaseModel):
    workflow_type: str = Field(..., min_length=1, max_length=64)
    input: dict = Field(...)
    webhook_url: Optional[str] = Field(None, max_length=1024)
    priority: int = Field(default=0, ge=-10, le=10)


class SubmitWorkflowResponse(BaseModel):
    job_id: str
    workflow_type: str
    status: str
    created_at: str
    polling_url: str
    estimated_duration_seconds: Optional[int] = None


class JobStatusResponse(BaseModel):
    job_id: str
    workflow_type: str
    status: str
    current_state: Optional[str] = None
    progress: float
    checkpoint: Optional[dict] = None
    result: Optional[dict] = None
    error: Optional[dict] = None
    created_at: str
    started_at: Optional[str] = None
    updated_at: str
    completed_at: Optional[str] = None
    heartbeat_at: Optional[str] = None
    retry_count: int


class CancelJobResponse(BaseModel):
    job_id: str
    status: str
    previous_status: str
    cancelled_at: str


class RetryJobResponse(BaseModel):
    job_id: str
    status: str
    previous_status: str
    retry_count: int
    retried_at: str


class JobEventResponse(BaseModel):
    event_id: int
    state: str
    event_type: str
    timestamp: str
    payload: Optional[dict] = None


class JobEventListResponse(BaseModel):
    job_id: str
    events: List[JobEventResponse]


class JobListItem(BaseModel):
    job_id: str
    workflow_type: str
    status: str
    current_state: Optional[str] = None
    progress: float
    error: Optional[dict] = None
    created_at: str
    updated_at: str


class JobListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[JobListItem]


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _get_orchestrator() -> WorkflowOrchestrator:
    from app.main import app
    return app.state.workflow_orchestrator


async def _get_job_or_404(job_id: uuid.UUID):
    from app.db.config import SessionLocal
    async with SessionLocal() as session:
        repo = WorkflowRepository(session)
        job = await repo.get_job(job_id)
        if not job:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "WORKFLOW_NOT_FOUND",
                    "field": "job_id",
                    "message": f"No workflow job found with ID {job_id}",
                },
            )
        return job


def _sanitize_checkpoint(checkpoint: dict) -> dict:
    """Strip large page content from checkpoint for API responses."""
    sanitized = dict(checkpoint)
    pages_state = sanitized.get("pages_state")
    if pages_state and "results" in pages_state:
        results = pages_state["results"]
        last = results[-1] if results else {}
        sanitized["pages_state"] = {
            "total": pages_state.get("total", 0),
            "generated": len(results),
            "failed": pages_state.get("failed", 0),
            "current_page_title": last.get("title") if last else None,
            "current_page_index": last.get("page_index") if last else None,
        }
    return sanitized


# ═══════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════

@router.post("", response_model=SubmitWorkflowResponse, status_code=202)
async def submit_workflow(
    request: SubmitWorkflowRequest,
    user: UserContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Submit a new workflow job for asynchronous execution. Returns 202."""
    orchestrator = _get_orchestrator()

    repo = WorkflowRepository(session)
    type_def = await repo.get_type_definition(request.workflow_type)
    if not type_def:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "WORKFLOW_SCHEMA_ERROR",
                "field": "workflow_type",
                "message": f"Unregistered workflow type: '{request.workflow_type}'",
            },
        )

    import jsonschema
    try:
        jsonschema.validate(request.input, type_def.input_schema)
    except jsonschema.ValidationError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "WORKFLOW_VALIDATION_ERROR",
                "field": f"input.{'.'.join(str(p) for p in e.absolute_path)}",
                "message": e.message,
            },
        )

    job = await orchestrator.submit_job(
        workflow_type=request.workflow_type,
        input_data=request.input,
        session=session,
        webhook_url=request.webhook_url,
        priority=request.priority,
        created_by_user_id=user.user_id,
    )

    return SubmitWorkflowResponse(
        job_id=str(job.job_id),
        workflow_type=job.workflow_type,
        status=job.status,
        created_at=job.created_at.isoformat(),
        polling_url=f"/api/v1/workflows/{job.job_id}",
        estimated_duration_seconds=(
            type_def.max_duration_seconds
            if type_def.max_duration_seconds < 86400
            else None
        ),
    )


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_workflow_status(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Get the current status and progress of a workflow job."""
    repo = WorkflowRepository(session)
    job = await repo.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "WORKFLOW_NOT_FOUND",
                "field": "job_id",
                "message": f"No workflow job found with ID {job_id}",
            },
        )
    return JobStatusResponse(
        job_id=str(job.job_id),
        workflow_type=job.workflow_type,
        status=job.status,
        current_state=job.current_state,
        progress=job.progress,
        checkpoint=_sanitize_checkpoint(job.checkpoint_data or {}),
        result=job.result,
        error=job.error,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        updated_at=job.updated_at.isoformat(),
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        heartbeat_at=job.heartbeat_at.isoformat() if job.heartbeat_at else None,
        retry_count=job.retry_count,
    )


@router.post("/{job_id}/cancel", response_model=CancelJobResponse)
async def cancel_workflow(job_id: uuid.UUID):
    """Cancel a pending or running workflow job."""
    orchestrator = _get_orchestrator()
    job = await _get_job_or_404(job_id)

    if job.status not in ("pending", "running"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WORKFLOW_NOT_RUNNING",
                "field": "job_id",
                "message": f"Job is already in terminal state: {job.status}",
            },
        )

    success = await orchestrator.cancel_job(job_id)
    if not success:
        raise HTTPException(
            status_code=409,
            detail="Job cannot be cancelled. It may have already completed or been cancelled by another request."
        )

    return CancelJobResponse(
        job_id=str(job_id),
        status="cancelled",
        previous_status=job.status,
        cancelled_at=datetime.utcnow().isoformat(),
    )


@router.post("/{job_id}/retry", response_model=RetryJobResponse)
async def retry_workflow(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Retry a failed workflow job from its last checkpoint."""
    job = await _get_job_or_404(job_id)

    if job.status != "failed":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WORKFLOW_NOT_FAILED",
                "field": "job_id",
                "message": f"Job is in '{job.status}' state. Only 'failed' jobs can be retried.",
            },
        )

    repo = WorkflowRepository(session)
    updated = await repo.increment_retry(job_id)
    if not updated:
        raise HTTPException(
            status_code=409,
            detail="Job cannot be retried. It may no longer be in a failed state."
        )

    return RetryJobResponse(
        job_id=str(job_id),
        status=updated.status,
        previous_status="failed",
        retry_count=updated.retry_count,
        retried_at=datetime.utcnow().isoformat(),
    )


@router.get("/{job_id}/events", response_model=JobEventListResponse)
async def get_workflow_events(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Get the event history for a workflow job (ordered by timestamp)."""
    await _get_job_or_404(job_id)
    repo = WorkflowRepository(session)
    events = await repo.get_events(job_id)
    return JobEventListResponse(
        job_id=str(job_id),
        events=[
            JobEventResponse(
                event_id=e.id,
                state=e.state,
                event_type=e.event_type,
                timestamp=e.timestamp.isoformat(),
                payload=e.payload,
            )
            for e in events
        ],
    )


@router.get("", response_model=JobListResponse)
async def list_workflows(
    status: Optional[str] = Query(None),
    workflow_type: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """List workflow jobs with optional filters and pagination."""
    repo = WorkflowRepository(session)
    jobs, total = await repo.list_jobs(
        status=status, workflow_type=workflow_type,
        limit=limit, offset=offset,
    )
    return JobListResponse(
        total=total, limit=limit, offset=offset,
        items=[
            JobListItem(
                job_id=str(j.job_id),
                workflow_type=j.workflow_type,
                status=j.status,
                current_state=j.current_state,
                progress=j.progress,
                error=j.error,
                created_at=j.created_at.isoformat(),
                updated_at=j.updated_at.isoformat(),
            )
            for j in jobs
        ],
    )


# ═══════════════════════════════════════════════════════════════════
# SSE Streaming Endpoint (Phase 1.5)
# ═══════════════════════════════════════════════════════════════════

@router.get("/{job_id}/stream")
async def stream_workflow_progress(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    """Stream real-time workflow progress via Server-Sent Events (Phase 1.5).

    Replaces polling (GET /{job_id} in a loop) with push-based progress updates.
    Client keeps the SSE connection open and receives events as the job progresses.

    Events emitted:
        - progress: {state, progress_pct, message}
        - checkpoint: {state, checkpoint_summary}
        - complete: {result}
        - error: {code, message}
        - heartbeat: {timestamp} (every 15s, keeps connection alive)

    The connection closes when the job reaches a terminal state (completed,
    failed, cancelled) or the client disconnects.
    """
    import asyncio
    import hashlib
    import json as _json
    from datetime import datetime, timezone

    def _sanitize_checkpoint_for_sse(checkpoint_data: dict) -> dict:
        """Strip large binary fields from checkpoint data for SSE transmission.

        Keeps summary fields: course title, page_count, manifest summary, asset count.
        Removes: raw file content, base64 assets, full page bodies.
        """
        sanitized: dict = {}
        for key, value in checkpoint_data.items():
            if isinstance(value, (str, int, float, bool, type(None))):
                sanitized[key] = value
            elif isinstance(value, dict):
                if key == "course":
                    sanitized[key] = {
                        k: v for k, v in value.items()
                        if k in ("course_id", "title", "page_count", "status")
                    }
                elif key == "manifest":
                    sanitized[key] = {
                        k: v for k, v in value.items()
                        if k in ("version", "title", "organization_count", "resource_count")
                    }
                elif key == "assets":
                    sanitized[key] = {
                        "count": value.get("count", 0),
                        "total_size_bytes": value.get("total_size_bytes", 0),
                    }
                else:
                    sanitized[key] = {
                        k: v for k, v in value.items()
                        if not isinstance(v, str) or len(v) < 1024
                    }
            elif isinstance(value, list):
                sanitized[key] = f"[{len(value)} items]"
        return sanitized

    async def event_generator():
        last_progress = -1
        last_checkpoint_hash: str | None = None
        heartbeat_count = 0

        while True:
            repo = WorkflowRepository(session)
            job = await repo.get_job(job_id)
            if job is None:
                not_found_payload = {
                    'code': 'NOT_FOUND',
                    'message': f'Job {job_id} not found',
                }
                yield f"event: error\ndata: {_json.dumps(not_found_payload)}\n\n"
                return

            current_progress = int(job.progress * 100)

            # ── Emit checkpoint events when checkpoint data changes ──
            if job.checkpoint_data:
                current_hash = hashlib.md5(
                    _json.dumps(job.checkpoint_data, sort_keys=True, default=str).encode()
                ).hexdigest()
                if current_hash != last_checkpoint_hash:
                    last_checkpoint_hash = current_hash
                    safe = _sanitize_checkpoint_for_sse(job.checkpoint_data)
                    checkpoint_payload = {
                        'state': job.current_state,
                        'checkpoint': safe,
                        'progress_pct': current_progress,
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                    }
                    yield f"event: checkpoint\ndata: {_json.dumps(checkpoint_payload)}\n\n"

            # ── Emit progress events when progress changes ──
            if current_progress != last_progress:
                last_progress = current_progress
                state_label = job.current_state or "initialising"
                msg_text = f"Phase: {state_label} ({current_progress}%)"
                progress_payload = {
                    'state': job.current_state,
                    'progress_pct': current_progress,
                    'status': job.status,
                    'message': msg_text,
                }
                yield f"event: progress\ndata: {_json.dumps(progress_payload)}\n\n"

            # ── Emit heartbeat every ~15s ──
            heartbeat_count += 1
            if heartbeat_count % 15 == 0:
                heartbeat_payload = {
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                }
                yield f"event: heartbeat\ndata: {_json.dumps(heartbeat_payload)}\n\n"

            # ── Check terminal states ──
            if job.status in ("completed", "failed", "cancelled"):
                if job.status == "completed":
                    complete_payload = {
                        'result': job.result or {},
                        'job_id': str(job_id),
                    }
                    yield f"event: complete\ndata: {_json.dumps(complete_payload)}\n\n"
                elif job.status == "failed":
                    error_msg = (
                        str(job.error.get('message', 'Unknown error'))
                        if job.error else 'Job failed'
                    )
                    error_payload = {
                        'code': 'JOB_FAILED',
                        'message': error_msg,
                        'job_id': str(job_id),
                    }
                    yield f"event: error\ndata: {_json.dumps(error_payload)}\n\n"
                elif job.status == "cancelled":
                    cancel_payload = {
                        'code': 'JOB_CANCELLED',
                        'message': 'Job was cancelled',
                        'job_id': str(job_id),
                    }
                    yield f"event: error\ndata: {_json.dumps(cancel_payload)}\n\n"
                return

            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "Access-Control-Allow-Origin": "*",
        },
    )
