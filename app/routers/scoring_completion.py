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
from typing import Optional, List, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.models.interaction_event import InteractionEventRecord
from app.repositories.scoring_repo import ScoringRepository
from app.repositories.course_repo import CourseRepository, CourseNotFoundError
from app.repositories.interaction_event_repo import InteractionEventRepository
from app.repositories.page_component_repo import (
    PageRepository,
    ComponentRepository,
)
from app.utils.error_envelope import api_http_exception


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
    learnerId: Optional[str] = None
    data: Optional[InteractionDataDTO] = None
    completed: bool = False


router = APIRouter(tags=["Scoring", "Completion"])


async def _get_course_or_404(
    course_id: str,
    session: AsyncSession,
):
    course_repo = CourseRepository(session)
    try:
        return await course_repo.get_by_course_id(course_id)
    except CourseNotFoundError:
        raise api_http_exception(
            404,
            "NOT_FOUND",
            f"Course '{course_id}' not found",
            field="courseId",
        )


def _extract_question_definitions(component_data: dict) -> dict[str, dict]:
    questions = component_data.get("questions") or []
    if not isinstance(questions, list):
        return {}

    return {
        str(question.get("id")): question
        for question in questions
        if isinstance(question, dict) and question.get("id")
    }


def _get_correct_option_ids(question: dict) -> set[str]:
    option_ids = set()
    for option in question.get("options") or []:
        if option.get("isCorrect") or option.get("correct"):
            option_id = option.get("id")
            if option_id is not None:
                option_ids.add(str(option_id))
    return option_ids


async def _build_scorable_lookup(
    course_id: str,
    course,
    session: AsyncSession,
) -> dict[str, dict[str, Any]]:
    component_repo = ComponentRepository(session)
    components = await component_repo.list_by_course(course_id)
    lookup = {
        component.component_id: {
            "componentType": component.component_type,
            "data": component.data or {},
        }
        for component in components
    }
    if lookup:
        return lookup

    templates = (course.json_data or {}).get("templates") or []
    for template in templates:
        if not isinstance(template, dict) or not template.get("id"):
            continue
        lookup[str(template["id"])] = {
            "componentType": template.get("type"),
            "data": template.get("data") or {},
        }
    return lookup


async def _latest_events_by_component(
    course_id: str,
    session: AsyncSession,
    page_id: Optional[str] = None,
) -> dict[str, InteractionEventRecord]:
    repo = InteractionEventRepository(session)
    events = await repo.list_by_course(
        course_id,
        page_id=page_id,
        limit=1000,
    )
    latest = {}
    for event in events:
        if event.component_id not in latest:
            latest[event.component_id] = event
    return latest


def _is_component_completed(
    component,
    latest_event: Optional[InteractionEventRecord],
) -> bool:
    if not latest_event:
        return False

    criteria = component.completion_criteria or {}
    completion_type = criteria.get("type", "view")
    threshold = criteria.get("threshold")

    event_data = latest_event.data or {}
    event_score = latest_event.score
    if event_score is None:
        event_score = event_data.get("score")
    event_max = latest_event.max_score
    if event_max is None:
        event_max = event_data.get("maxScore")

    if completion_type in ("score", "scored-interaction"):
        if event_score is None:
            return bool(latest_event.completed)
        if event_max:
            required = threshold if threshold is not None else 100
            return (event_score / event_max * 100) >= required
        if threshold is not None:
            return event_score >= threshold
        return bool(latest_event.completed or event_score > 0)

    if completion_type == "interaction":
        return bool(latest_event.completed or latest_event.interaction_type)

    return bool(latest_event.completed)


def _evaluate_page_completion(
    strategy: str,
    component_statuses: list[dict],
    required_ids: Optional[list[str]],
    threshold: Optional[float],
) -> bool:
    if not component_statuses:
        return True

    completed_count = sum(
        1 for status in component_statuses if status["completed"]
    )
    total_count = len(component_statuses)

    if strategy == "all":
        return completed_count >= total_count
    if strategy == "any":
        return completed_count > 0
    if strategy == "percentage":
        percent = (completed_count / total_count * 100) if total_count else 100
        return percent >= (threshold if threshold is not None else 100)
    if strategy == "custom" and required_ids:
        completed_ids = {
            status["componentId"]
            for status in component_statuses
            if status["completed"]
        }
        return all(
            component_id in completed_ids for component_id in required_ids
        )
    return completed_count >= total_count


def _build_page_completion_payload(
    page,
    latest_events: dict[str, InteractionEventRecord],
) -> dict:
    component_statuses = []
    for component in (page.components or []):
        criteria = component.completion_criteria or {}
        latest_event = latest_events.get(component.component_id)
        component_statuses.append(
            {
                "componentId": component.component_id,
                "completed": _is_component_completed(component, latest_event),
                "completionType": criteria.get("type", "view"),
                "threshold": criteria.get("threshold"),
            }
        )

    completion_config = page.completion_config or {}
    strategy = completion_config.get("strategy", "all")
    required_ids = completion_config.get("requiredComponents")
    threshold = completion_config.get("completionThreshold")
    page_completed = _evaluate_page_completion(
        strategy,
        component_statuses,
        required_ids,
        threshold,
    )

    return {
        "pageId": page.page_id,
        "title": page.title,
        "completed": page_completed,
        "strategy": strategy,
        "components": component_statuses,
    }


# ── Scoring Endpoints ───────────────────────

@router.get("/courses/{courseId}/scoring")
async def get_scoring_config(
    courseId: str,
    session: AsyncSession = Depends(get_session),
):
    await _get_course_or_404(courseId, session)

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
    await _get_course_or_404(courseId, session)

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
    await _get_course_or_404(courseId, session)

    scoring_repo = ScoringRepository(session)
    record = await scoring_repo.get_by_course(courseId)

    errors = []
    warnings = []

    if not record:
        return {
            "valid": True,
            "errors": [],
            "warnings": [
                {
                    "field": "scoring",
                    "message": (
                        "No scoring configuration found, defaults "
                        "will be used"
                    ),
                }
            ],
        }

    config = record.config or {}
    component_scores = record.component_scores or []

    # Check passing score range
    ps = config.get("passingScore", 70)
    if not (0 <= ps <= 100):
        errors.append(
            {
                "field": "config.passingScore",
                "message": f"Passing score must be 0-100, got {ps}",
            }
        )

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
    course = await _get_course_or_404(courseId, session)

    scoring_repo = ScoringRepository(session)
    record = await scoring_repo.get_by_course(courseId)
    config = (record.config if record else None) or {
        "passingScore": 70,
        "maxAttempts": None,
        "weightedScoring": False,
        "allowPartialCredit": True,
    }
    component_score_configs = (
        record.component_scores if record else None
    ) or []
    scorable_lookup = await _build_scorable_lookup(courseId, course, session)

    # Build lookup
    cs_lookup = {cs["componentId"]: cs for cs in component_score_configs}

    component_results = []
    total_score = 0.0
    total_max = 0.0

    for answer in body.answers:
        source_component = scorable_lookup.get(answer.componentId)
        if not source_component:
            raise api_http_exception(
                422,
                "VALIDATION_ERROR",
                "Component "
                f"'{answer.componentId}' not found for course "
                f"'{courseId}'",
                field="answers[].componentId",
                details={
                    "courseId": courseId,
                    "componentId": answer.componentId,
                },
            )

        question_lookup = _extract_question_definitions(
            source_component.get("data") or {}
        )
        if not question_lookup:
            raise api_http_exception(
                422,
                "VALIDATION_ERROR",
                f"Component '{answer.componentId}' has no scorable questions",
                field="answers[].responses",
                details={"componentId": answer.componentId},
            )

        comp_config = cs_lookup.get(answer.componentId, {})
        max_points = comp_config.get("maxPoints", 100)
        weight = comp_config.get("weight", 1.0)

        question_results = []
        comp_score = 0.0
        comp_max = 0.0

        for resp in answer.responses:
            question = question_lookup.get(resp.questionId)
            if not question:
                raise api_http_exception(
                    422,
                    "VALIDATION_ERROR",
                    "Question "
                    f"'{resp.questionId}' not found on component "
                    f"'{answer.componentId}'",
                    field="answers[].responses[].questionId",
                    details={
                        "componentId": answer.componentId,
                        "questionId": resp.questionId,
                    },
                )

            correct_option_ids = _get_correct_option_ids(question)
            if not correct_option_ids:
                raise api_http_exception(
                    422,
                    "VALIDATION_ERROR",
                    "Question "
                    f"'{resp.questionId}' has no correct options configured",
                    field="answers[].responses[].selectedOptionIds",
                    details={
                        "componentId": answer.componentId,
                        "questionId": resp.questionId,
                    },
                )

            selected_option_ids = {
                str(opt_id) for opt_id in resp.selectedOptionIds
            }
            q_max = max_points / max(len(answer.responses), 1)
            comp_max += q_max

            is_exact_match = selected_option_ids == correct_option_ids
            question_score = q_max if is_exact_match else 0.0
            partial_credit = False
            if (
                not is_exact_match
                and config.get("allowPartialCredit")
                and len(correct_option_ids) > 1
            ):
                correct_selected = len(
                    selected_option_ids & correct_option_ids
                )
                incorrect_selected = len(
                    selected_option_ids - correct_option_ids
                )
                fraction = (
                    (correct_selected - incorrect_selected)
                    / len(correct_option_ids)
                )
                fraction = max(0.0, fraction)
                question_score = round(q_max * fraction, 4)
                partial_credit = 0.0 < question_score < q_max

            comp_score += question_score
            question_results.append({
                "questionId": resp.questionId,
                "correct": is_exact_match,
                "score": round(question_score, 4),
                "maxScore": q_max,
                "partialCredit": partial_credit,
            })

        weighted_score = (
            comp_score * weight
            if config.get("weightedScoring")
            else comp_score
        )

        component_results.append({
            "componentId": answer.componentId,
            "componentType": source_component.get("componentType")
            or answer.componentType,
            "score": round(comp_score, 4),
            "maxScore": comp_max,
            "weight": weight,
            "weightedScore": round(weighted_score, 4),
            "questionResults": question_results,
        })

        total_score += weighted_score
        total_max += comp_max * (
            weight if config.get("weightedScoring") else 1.0
        )

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
        "remainingAttempts": (
            max_attempts - body.attemptNumber
        ) if max_attempts else None,
    }


# ── Completion Endpoints ─────────────────────

@router.get("/courses/{courseId}/completion")
async def get_course_completion(
    courseId: str,
    session: AsyncSession = Depends(get_session),
):
    await _get_course_or_404(courseId, session)

    page_repo = PageRepository(session)
    pages = await page_repo.list_by_course(courseId)

    page_results = []
    completed_pages = 0
    for page in pages:
        latest_events = await _latest_events_by_component(
            courseId,
            session,
            page.page_id,
        )
        page_payload = _build_page_completion_payload(page, latest_events)
        page_results.append(page_payload)
        if page_payload["completed"]:
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
        raise api_http_exception(
            404,
            "NOT_FOUND",
            f"Page '{pageId}' not found",
            field="pageId",
            details={"courseId": courseId},
        )

    latest_events = await _latest_events_by_component(
        courseId,
        session,
        pageId,
    )
    return _build_page_completion_payload(page, latest_events)


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
        raise api_http_exception(
            404,
            "NOT_FOUND",
            f"Page '{pageId}' not found",
            field="pageId",
            details={"courseId": courseId},
        )

    event_repo = InteractionEventRepository(session)

    # Persist the latest reported state for each component so completion reads
    # are derived from stored evidence, not transient request data.
    for component_state in body.componentStates:
        event = InteractionEventRecord(
            course_id=courseId,
            page_id=pageId,
            component_id=component_state.componentId,
            interaction_type="page-completion-state",
            data={
                "interactionsCompleted": component_state.interactionsCompleted,
                "audiosCompleted": component_state.audiosCompleted,
                "score": component_state.score,
                "maxScore": 100 if component_state.score is not None else None,
            },
            completed=component_state.completed,
            score=component_state.score,
            max_score=100 if component_state.score is not None else None,
        )
        await event_repo.create(event)

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
    page_completed = _evaluate_page_completion(
        strategy,
        comp_statuses,
        required_ids,
        threshold,
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
    await _get_course_or_404(courseId, session)

    # Serialize data with Pydantic v1/v2 compat
    data_dict = None
    if body.data:
        data_dict = (
            body.data.model_dump()
            if hasattr(body.data, "model_dump")
            else body.data.dict()
        )

    event_repo = InteractionEventRepository(session)
    event = InteractionEventRecord(
        course_id=courseId,
        page_id=body.pageId,
        component_id=body.componentId,
        learner_id=body.learnerId or "anonymous",
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
    await _get_course_or_404(courseId, session)

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
