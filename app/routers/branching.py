"""Branching & Adaptive Navigation API.

Endpoints for defining branching rules, fetching them,
and recording learner branch-path decisions.
"""
from __future__ import annotations
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.db.config import get_session
from app.repositories.branching_repo import BranchRuleRepository, BranchEventRepository
from app.repositories.course_repo import CourseRepository, CourseNotFoundError
from app.models.branching import BranchRule, BranchEvent


logger = logging.getLogger(__name__)


# ── DTOs ─────────────────────────────────────────────────────────────────────

class BranchConditionDTO(BaseModel):
    """A single branching condition."""
    field: str = Field(..., description="Field to evaluate (e.g. 'score', 'interactionType')")
    operator: str = Field(..., description="Comparison operator (==, !=, >=, <=, >, <, in, contains)")
    value: object = Field(..., description="Value to compare against")
    targetPageId: str = Field(..., description="Page to navigate to when condition is met")


class BranchRuleCreateDTO(BaseModel):
    title: str = Field("", max_length=200)
    description: Optional[str] = None
    sourcePageId: Optional[str] = None
    sourceComponentId: Optional[str] = None
    conditions: List[BranchConditionDTO] = Field(default_factory=list)
    defaultTargetPageId: Optional[str] = None
    priority: int = 0
    isActive: bool = True


class BranchRuleUpdateDTO(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    sourcePageId: Optional[str] = None
    sourceComponentId: Optional[str] = None
    conditions: Optional[List[BranchConditionDTO]] = None
    defaultTargetPageId: Optional[str] = None
    priority: Optional[int] = None
    isActive: Optional[bool] = None


class BranchEventCreateDTO(BaseModel):
    learnerId: str = "anonymous"
    matchedConditionIndex: int = -1
    targetPageId: str
    contextSnapshot: Optional[dict] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _require_course(session: AsyncSession, course_id: str):
    repo = CourseRepository(session)
    try:
        return await repo.get_by_course_id(course_id)
    except CourseNotFoundError:
        raise HTTPException(404, f"Course '{course_id}' not found")
    except Exception as exc:
        logger.error("Failed to load course '%s': %s", course_id, exc, exc_info=True)
        raise HTTPException(500, "Failed to load course")


# ── Router ───────────────────────────────────────────────────────────────────

router = APIRouter(tags=["Branching"])


@router.get("/courses/{courseId}/branches")
async def list_branch_rules(
    courseId: str,
    session: AsyncSession = Depends(get_session),
):
    """Get all branching rules for a course."""
    await _require_course(session, courseId)
    repo = BranchRuleRepository(session)
    rules = await repo.list_by_course(courseId)
    return [r.to_dict() for r in rules]


@router.post("/courses/{courseId}/branches", status_code=201)
async def create_branch_rule(
    courseId: str,
    body: BranchRuleCreateDTO,
    session: AsyncSession = Depends(get_session),
):
    """Create a new branching rule for a course."""
    await _require_course(session, courseId)
    repo = BranchRuleRepository(session)

    conditions_raw = [c.model_dump() if hasattr(c, "model_dump") else c.dict() for c in body.conditions]

    rule = BranchRule(
        course_id=courseId,
        title=body.title,
        description=body.description,
        source_page_id=body.sourcePageId,
        source_component_id=body.sourceComponentId,
        conditions=conditions_raw,
        default_target_page_id=body.defaultTargetPageId,
        priority=body.priority,
        is_active=body.isActive,
    )
    rule = await repo.create(rule)
    return rule.to_dict()


@router.get("/courses/{courseId}/branches/{branchId}")
async def get_branch_rule(
    courseId: str,
    branchId: str,
    session: AsyncSession = Depends(get_session),
):
    """Get a specific branching rule."""
    await _require_course(session, courseId)
    repo = BranchRuleRepository(session)
    rule = await repo.get(branchId)
    if not rule or rule.course_id != courseId:
        raise HTTPException(404, f"Branch rule '{branchId}' not found")
    return rule.to_dict()


@router.patch("/courses/{courseId}/branches/{branchId}")
async def update_branch_rule(
    courseId: str,
    branchId: str,
    body: BranchRuleUpdateDTO,
    session: AsyncSession = Depends(get_session),
):
    """Update a branching rule."""
    await _require_course(session, courseId)
    repo = BranchRuleRepository(session)
    rule = await repo.get(branchId)
    if not rule or rule.course_id != courseId:
        raise HTTPException(404, f"Branch rule '{branchId}' not found")

    if body.title is not None:
        rule.title = body.title
    if body.description is not None:
        rule.description = body.description
    if body.sourcePageId is not None:
        rule.source_page_id = body.sourcePageId
    if body.sourceComponentId is not None:
        rule.source_component_id = body.sourceComponentId
    if body.conditions is not None:
        rule.conditions = [c.model_dump() if hasattr(c, "model_dump") else c.dict() for c in body.conditions]
    if body.defaultTargetPageId is not None:
        rule.default_target_page_id = body.defaultTargetPageId
    if body.priority is not None:
        rule.priority = body.priority
    if body.isActive is not None:
        rule.is_active = body.isActive

    rule = await repo.update(rule)
    return rule.to_dict()


@router.delete("/courses/{courseId}/branches/{branchId}", status_code=204)
async def delete_branch_rule(
    courseId: str,
    branchId: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete a branching rule."""
    await _require_course(session, courseId)
    repo = BranchRuleRepository(session)
    rule = await repo.get(branchId)
    if not rule or rule.course_id != courseId:
        raise HTTPException(404, f"Branch rule '{branchId}' not found")
    await repo.delete(rule)


# ── Branch Events (learner path tracking) ────────────────────────────────────

@router.post("/courses/{courseId}/branches/{branchId}/events", status_code=201)
async def record_branch_event(
    courseId: str,
    branchId: str,
    body: BranchEventCreateDTO,
    session: AsyncSession = Depends(get_session),
):
    """Record a branch decision made by a learner."""
    await _require_course(session, courseId)
    rule_repo = BranchRuleRepository(session)
    rule = await rule_repo.get(branchId)
    if not rule or rule.course_id != courseId:
        raise HTTPException(404, f"Branch rule '{branchId}' not found")

    event_repo = BranchEventRepository(session)
    event = BranchEvent(
        branch_id=branchId,
        course_id=courseId,
        learner_id=body.learnerId,
        matched_condition_index=body.matchedConditionIndex,
        target_page_id=body.targetPageId,
        context_snapshot=body.contextSnapshot,
    )
    event = await event_repo.create(event)
    return event.to_dict()


@router.get("/courses/{courseId}/branches/{branchId}/events")
async def list_branch_events(
    courseId: str,
    branchId: str,
    learnerId: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """List branch events for a given rule, optionally filtered by learner."""
    await _require_course(session, courseId)
    repo = BranchEventRepository(session)
    events = await repo.list_by_branch(branchId, learner_id=learnerId)
    return [e.to_dict() for e in events]
