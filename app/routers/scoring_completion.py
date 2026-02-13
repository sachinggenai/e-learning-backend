"""Scoring & Completion API.

Endpoints:
  GET/PATCH    /courses/{courseId}/scoring
  POST         /courses/{courseId}/scoring/validate
  POST         /courses/{courseId}/scoring/calculate
  GET          /courses/{courseId}/completion
  GET/POST     /courses/{courseId}/pages/{pageId}/completion
  POST         /courses/{courseId}/interactions
"""
from __future__ import annotations
from typing import Optional, List
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.repositories.scoring_repo import ScoringRepository
from app.repositories.course_repo import CourseRepository
from app.repositories.page_component_repo import PageRepository, ComponentRepository


# ── DTOs ─────────────────────────────────────

class QuestionResponseDTO(BaseModel):
    questionId: str
    selectedOptionIds: List[str] = Field(default_factory=list)


class ComponentAnswerDTO(BaseModel):
    componentId: str
    componentType: str
    responses: List[QuestionResponseDTO]


class ScoreCalculateDTO(BaseModel):
    answers: List[ComponentAnswerDTO]
    attemptNumber: int = 1


class ComponentStateDTO(BaseModel):
    componentId: str
    completed: bool
    interactionsCompleted: Optional[List[str]] = None
    audiosCompleted: Optional[List[str]] = None
    score: Optional[float] = None


class PageCompletionEventDTO(BaseModel):
    componentStates: List[ComponentStateDTO]


class InteractionDataDTO(BaseModel):
    interactionId: Optional[str] = None
    value: Optional[str] = None
    score: Optional[float] = None
    maxScore: Optional[float] = None
    isCorrect: Optional[bool] = None
    duration: Optional[float] = None


class InteractionEventDTO(BaseModel):
    pageId: str
    componentId: str
    interactionType: str
    data: Optional[InteractionDataDTO] = None
    completed: bool = False


router = APIRouter(tags=["Scoring", "Completion"])


# ── Scoring Endpoints ───────────────────────

@router.get("/courses/{courseId}/scoring")
async def get_scoring_config(
    courseId: str,
    session: AsyncSession = Depends(get_session),
):
    course_repo = CourseRepository(session)
    course = await course_repo.get_by_course_id(courseId)
    if not course:
        raise HTTPException(404, f"Course '{courseId}' not found")

    scoring_repo = ScoringRepository(session)
    record = await scoring_repo.get_by_course(courseId)
    if not record:
        # Return default scoring config
        return {
            "scoringId": None,
            "courseId": courseId,
            "config": {
                "passingScore": 70,
                "maxAttempts": None,
                "attemptScoring": "best",
                "showCorrectAnswers": True,
                "showScoreAfterQuestion": False,
                "showScoreAfterPage": False,
                "weightedScoring": False,
                "allowPartialCredit": True,
            },
            "componentScores": [],
            "scormReporting": {
                "enabled": True,
                "version": "1.2",
                "reportScore": True,
                "reportCompletion": True,
                "reportInteractions": True,
            },
        }
    return record.to_dict()


@router.patch("/courses/{courseId}/scoring")
async def update_scoring_config(
    courseId: str,
    body: dict,
    session: AsyncSession = Depends(get_session),
):
    course_repo = CourseRepository(session)
    course = await course_repo.get_by_course_id(courseId)
    if not course:
        raise HTTPException(404, f"Course '{courseId}' not found")

    scoring_repo = ScoringRepository(session)
    kwargs = {}
    if "config" in body:
        kwargs["config"] = body["config"]
    if "componentScores" in body:
        kwargs["component_scores"] = body["componentScores"]
    if "scormReporting" in body:
        kwargs["scorm_reporting"] = body["scormReporting"]

    record = await scoring_repo.upsert(courseId, **kwargs)
    return record.to_dict()


@router.post("/courses/{courseId}/scoring/validate")
async def validate_scoring_config(
    courseId: str,
    session: AsyncSession = Depends(get_session),
):
    course_repo = CourseRepository(session)
    course = await course_repo.get_by_course_id(courseId)
    if not course:
        raise HTTPException(404, f"Course '{courseId}' not found")

    scoring_repo = ScoringRepository(session)
    record = await scoring_repo.get_by_course(courseId)

    errors = []
    warnings = []

    if not record:
        return {"valid": True, "errors": [], "warnings": [{"field": "scoring", "message": "No scoring configuration found, defaults will be used"}]}

    config = record.config or {}
    component_scores = record.component_scores or []

    # Check passing score range
    ps = config.get("passingScore", 70)
    if not (0 <= ps <= 100):
        errors.append({"field": "config.passingScore", "message": f"Passing score must be 0-100, got {ps}"})

    # Check weights sum to 1.0 if weighted scoring is enabled
    if config.get("weightedScoring") and component_scores:
        total_weight = sum(cs.get("weight", 0) for cs in component_scores)
        if abs(total_weight - 1.0) > 0.01:
            errors.append({
                "field": "componentScores.weight",
                "message": f"Weights must sum to 1.0, got {total_weight:.4f}",
            })

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


@router.post("/courses/{courseId}/scoring/calculate")
async def calculate_score(
    courseId: str,
    body: ScoreCalculateDTO,
    session: AsyncSession = Depends(get_session),
):
    course_repo = CourseRepository(session)
    course = await course_repo.get_by_course_id(courseId)
    if not course:
        raise HTTPException(404, f"Course '{courseId}' not found")

    scoring_repo = ScoringRepository(session)
    record = await scoring_repo.get_by_course(courseId)
    config = (record.config if record else None) or {
        "passingScore": 70,
        "maxAttempts": None,
        "weightedScoring": False,
        "allowPartialCredit": True,
    }
    component_score_configs = (record.component_scores if record else None) or []

    # Build lookup
    cs_lookup = {cs["componentId"]: cs for cs in component_score_configs}

    component_results = []
    total_score = 0.0
    total_max = 0.0

    for answer in body.answers:
        comp_config = cs_lookup.get(answer.componentId, {})
        max_points = comp_config.get("maxPoints", 100)
        weight = comp_config.get("weight", 1.0)

        question_results = []
        comp_score = 0.0
        comp_max = 0.0

        # Simple per-question scoring
        # Real implementation would look up correct answers from component data
        for resp in answer.responses:
            q_max = max_points / max(len(answer.responses), 1)
            comp_max += q_max
            # Placeholder: mark as needing actual answer validation
            question_results.append({
                "questionId": resp.questionId,
                "correct": False,
                "score": 0,
                "maxScore": q_max,
                "partialCredit": False,
            })

        weighted_score = comp_score * weight if config.get("weightedScoring") else comp_score

        component_results.append({
            "componentId": answer.componentId,
            "componentType": answer.componentType,
            "score": comp_score,
            "maxScore": comp_max,
            "weight": weight,
            "weightedScore": weighted_score,
            "questionResults": question_results,
        })

        total_score += weighted_score
        total_max += comp_max * (weight if config.get("weightedScoring") else 1.0)

    percentage = (total_score / total_max * 100) if total_max > 0 else 0
    passing_score = config.get("passingScore", 70)
    max_attempts = config.get("maxAttempts")

    return {
        "totalScore": total_score,
        "maxScore": total_max,
        "percentage": round(percentage, 2),
        "passed": percentage >= passing_score,
        "passingScore": passing_score,
        "componentResults": component_results,
        "attemptNumber": body.attemptNumber,
        "remainingAttempts": (max_attempts - body.attemptNumber) if max_attempts else None,
    }


# ── Completion Endpoints ─────────────────────

@router.get("/courses/{courseId}/completion")
async def get_course_completion(
    courseId: str,
    session: AsyncSession = Depends(get_session),
):
    course_repo = CourseRepository(session)
    course = await course_repo.get_by_course_id(courseId)
    if not course:
        raise HTTPException(404, f"Course '{courseId}' not found")

    page_repo = PageRepository(session)
    pages = await page_repo.list_by_course(courseId)

    page_results = []
    completed_pages = 0
    for page in pages:
        comp_statuses = []
        page_completed = True
        for comp in (page.components or []):
            criteria = comp.completion_criteria or {}
            comp_statuses.append({
                "componentId": comp.component_id,
                "completed": False,  # Default — real tracking via SCORM/interactions
                "completionType": criteria.get("type", "view"),
                "threshold": criteria.get("threshold"),
            })
            # A component needing completion means page is not yet automatically completed
            if criteria.get("type") and criteria["type"] != "view":
                page_completed = False

        page_results.append({
            "pageId": page.page_id,
            "title": page.title,
            "completed": page_completed,
            "strategy": (page.completion_config or {}).get("strategy", "all"),
            "components": comp_statuses,
        })
        if page_completed:
            completed_pages += 1

    total = len(pages)
    progress = (completed_pages / total * 100) if total > 0 else 0

    status = "not-started"
    if progress >= 100:
        status = "completed"
    elif progress > 0:
        status = "in-progress"

    return {
        "courseId": courseId,
        "status": status,
        "overallProgress": round(progress, 1),
        "pages": page_results,
    }


@router.get("/courses/{courseId}/pages/{pageId}/completion")
async def get_page_completion(
    courseId: str,
    pageId: str,
    session: AsyncSession = Depends(get_session),
):
    page_repo = PageRepository(session)
    page = await page_repo.get_by_course_and_page(courseId, pageId)
    if not page:
        raise HTTPException(404, f"Page '{pageId}' not found")

    comp_statuses = []
    for comp in (page.components or []):
        criteria = comp.completion_criteria or {}
        comp_statuses.append({
            "componentId": comp.component_id,
            "completed": False,
            "completionType": criteria.get("type", "view"),
            "threshold": criteria.get("threshold"),
        })

    return {
        "pageId": page.page_id,
        "title": page.title,
        "completed": False,
        "strategy": (page.completion_config or {}).get("strategy", "all"),
        "components": comp_statuses,
    }


@router.post("/courses/{courseId}/pages/{pageId}/completion")
async def record_page_completion(
    courseId: str,
    pageId: str,
    body: PageCompletionEventDTO,
    session: AsyncSession = Depends(get_session),
):
    page_repo = PageRepository(session)
    page = await page_repo.get_by_course_and_page(courseId, pageId)
    if not page:
        raise HTTPException(404, f"Page '{pageId}' not found")

    # Process completion states
    completion_config = page.completion_config or {}
    strategy = completion_config.get("strategy", "all")
    required_ids = completion_config.get("requiredComponents")
    threshold = completion_config.get("completionThreshold", 100)

    state_map = {s.componentId: s for s in body.componentStates}

    comp_statuses = []
    completed_count = 0
    total_count = 0

    for comp in (page.components or []):
        state = state_map.get(comp.component_id)
        is_completed = state.completed if state else False
        criteria = comp.completion_criteria or {}

        comp_statuses.append({
            "componentId": comp.component_id,
            "completed": is_completed,
            "completionType": criteria.get("type", "view"),
            "threshold": criteria.get("threshold"),
        })

        if criteria.get("type"):
            total_count += 1
            if is_completed:
                completed_count += 1

    # Evaluate page completion based on strategy
    page_completed = False
    if strategy == "all":
        page_completed = completed_count >= total_count if total_count > 0 else True
    elif strategy == "any":
        page_completed = completed_count > 0
    elif strategy == "percentage":
        pct = (completed_count / total_count * 100) if total_count > 0 else 100
        page_completed = pct >= threshold
    elif strategy == "custom" and required_ids:
        page_completed = all(
            state_map.get(rid, ComponentStateDTO(componentId=rid, completed=False)).completed
            for rid in required_ids
        )

    return {
        "pageId": page.page_id,
        "title": page.title,
        "completed": page_completed,
        "strategy": strategy,
        "components": comp_statuses,
    }


# ── Interaction Events ───────────────────────
# interactionType is an OPEN STRING — any value the frontend sends is accepted.
# Known types include: flip, reveal, drag-sort, text-input, rating,
# acknowledge, download, mcq-answer, match, drag-drop, etc.

@router.post("/courses/{courseId}/interactions", status_code=201)
async def record_interaction(
    courseId: str,
    body: InteractionEventDTO,
    session: AsyncSession = Depends(get_session),
):
    course_repo = CourseRepository(session)
    course = await course_repo.get_by_course_id(courseId)
    if not course:
        raise HTTPException(404, f"Course '{courseId}' not found")

    # Serialize data with Pydantic v1/v2 compat
    data_dict = None
    if body.data:
        data_dict = body.data.model_dump() if hasattr(body.data, "model_dump") else body.data.dict()

    # Persist the interaction event to DB
    from app.repositories.interaction_event_repo import InteractionEventRepository
    from app.models.interaction_event import InteractionEventRecord

    event_repo = InteractionEventRepository(session)
    event = InteractionEventRecord(
        course_id=courseId,
        page_id=body.pageId,
        component_id=body.componentId,
        interaction_type=body.interactionType,
        data=data_dict,
        completed=body.completed,
        score=body.data.score if body.data else None,
        max_score=body.data.maxScore if body.data else None,
        duration=body.data.duration if body.data else None,
    )
    event = await event_repo.create(event)
    return event.to_dict()


@router.get("/courses/{courseId}/interactions")
async def list_interactions(
    courseId: str,
    learnerId: str | None = None,
    interactionType: str | None = None,
    pageId: str | None = None,
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """List persisted interaction events for a course with optional filters."""
    course_repo = CourseRepository(session)
    course = await course_repo.get_by_course_id(courseId)
    if not course:
        raise HTTPException(404, f"Course '{courseId}' not found")

    from app.repositories.interaction_event_repo import InteractionEventRepository

    repo = InteractionEventRepository(session)
    events = await repo.list_by_course(
        courseId,
        learner_id=learnerId,
        interaction_type=interactionType,
        page_id=pageId,
        limit=limit,
        offset=offset,
    )
    return [e.to_dict() for e in events]
