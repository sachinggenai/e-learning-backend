"""Analytics & Reporting API.

Provides course-level performance summaries, skill mastery rollups,
and manager-facing views of learner progress.
"""
from __future__ import annotations
from typing import Optional
from datetime import datetime
from collections import Counter
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.repositories.course_repo import CourseRepository, CourseNotFoundError
from app.repositories.page_component_repo import PageRepository
from app.repositories.scoring_repo import ScoringRepository
from app.repositories.interaction_event_repo import InteractionEventRepository

logger = logging.getLogger(__name__)


async def _require_course(session: AsyncSession, course_id: str):
    repo = CourseRepository(session)
    try:
        return await repo.get_by_course_id(course_id)
    except CourseNotFoundError:
        raise HTTPException(404, f"Course '{course_id}' not found")
    except Exception as exc:
        logger.error("Failed to load course '%s': %s", course_id, exc, exc_info=True)
        raise HTTPException(500, "Failed to load course")


router = APIRouter(tags=["Analytics"])


@router.get("/courses/{courseId}/analytics/summary")
async def get_analytics_summary(
    courseId: str,
    learnerId: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
):
    """Course-level performance summary.

    Returns score distributions, completion rates, and mastery overview
    computed from persisted interaction events and scoring config.
    """
    course = await _require_course(session, courseId)

    # Gather structural data
    page_repo = PageRepository(session)
    pages = await page_repo.list_by_course(courseId)
    total_pages = len(pages)

    total_components = 0
    scoring_components = 0
    for page in pages:
        for comp in (page.components or []):
            total_components += 1
            criteria = comp.completion_criteria or {}
            if criteria.get("type") in ("score", "interaction", "scored-interaction"):
                scoring_components += 1

    # Scoring config
    scoring_repo = ScoringRepository(session)
    scoring_record = await scoring_repo.get_by_course(courseId)
    passing_score = 70
    if scoring_record and scoring_record.config:
        passing_score = scoring_record.config.get("passingScore", 70)

    # Interaction event stats
    event_repo = InteractionEventRepository(session)
    events = await event_repo.list_by_course(
        courseId,
        learner_id=learnerId,
        limit=10000,
    )
    total_events = len(events)
    distinct_learners = len({event.learner_id for event in events})
    completed_events = sum(1 for event in events if event.completed)
    scored_events = [float(event.score) for event in events if event.score is not None]
    average_score = (
        round(sum(scored_events) / len(scored_events), 2)
        if scored_events
        else None
    )

    by_type_counter = Counter(event.interaction_type for event in events)
    events_by_type = [
        {"interactionType": interaction_type, "count": count}
        for interaction_type, count in by_type_counter.most_common()
    ]

    return {
        "courseId": courseId,
        "title": course.title,
        "structure": {
            "totalPages": total_pages,
            "totalComponents": total_components,
            "scoringComponents": scoring_components,
        },
        "scoring": {
            "passingScore": passing_score,
            "weightedScoring": (scoring_record.config or {}).get("weightedScoring", False) if scoring_record else False,
        },
        "interactions": {
            "totalEvents": total_events,
            "byType": events_by_type,
            "filteredByLearnerId": learnerId,
            "distinctLearners": distinct_learners,
            "completedEvents": completed_events,
            "completionEventRate": (
                round((completed_events / total_events) * 100, 2)
                if total_events
                else 0.0
            ),
            "averageScore": average_score,
        },
        "generatedAt": datetime.utcnow().isoformat(),
    }


@router.get("/courses/{courseId}/analytics/skills")
async def get_skill_mastery(
    courseId: str,
    session: AsyncSession = Depends(get_session),
):
    """Skill mastery rollup — aggregated skill/tag performance.

    Groups components by their tags and computes mastery percentages
    based on scoring component weights.
    """
    await _require_course(session, courseId)

    page_repo = PageRepository(session)
    pages = await page_repo.list_by_course(courseId)

    # Build skill → component mapping from component tags
    # (tags are stored in component_type registry, but we approximate from data)
    skill_map: dict[str, dict] = {}
    for page in pages:
        for comp in (page.components or []):
            # Extract tags from component data or use component type as skill
            tags = (comp.data or {}).get("tags", [comp.component_type])
            if isinstance(tags, str):
                tags = [tags]
            for tag in tags:
                if tag not in skill_map:
                    skill_map[tag] = {"skill": tag, "componentCount": 0, "components": []}
                skill_map[tag]["componentCount"] += 1
                skill_map[tag]["components"].append({
                    "componentId": comp.component_id,
                    "componentType": comp.component_type,
                    "pageId": page.page_id,
                })

    skills = list(skill_map.values())
    skills.sort(key=lambda s: s["componentCount"], reverse=True)

    return {
        "courseId": courseId,
        "skills": skills,
        "totalSkills": len(skills),
        "generatedAt": datetime.utcnow().isoformat(),
    }


@router.get("/courses/{courseId}/analytics/manager-view")
async def get_manager_view(
    courseId: str,
    learnerId: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
):
    """Manager-facing view of learner progress.

    Provides a structural overview suitable for manager dashboards,
    including page-by-page breakdown, scoring configuration,
    and interaction volume.
    """
    course = await _require_course(session, courseId)

    page_repo = PageRepository(session)
    pages = await page_repo.list_by_course(courseId)

    scoring_repo = ScoringRepository(session)
    scoring_record = await scoring_repo.get_by_course(courseId)

    event_repo = InteractionEventRepository(session)
    events = await event_repo.list_by_course(
        courseId,
        learner_id=learnerId,
        limit=10000,
    )
    total_events = len(events)

    learner_stats_map = {}
    for event in events:
        learner_key = event.learner_id or "anonymous"
        if learner_key not in learner_stats_map:
            learner_stats_map[learner_key] = {
                "learnerId": learner_key,
                "eventCount": 0,
                "completedEvents": 0,
                "scoreTotal": 0.0,
                "scoreCount": 0,
            }
        bucket = learner_stats_map[learner_key]
        bucket["eventCount"] += 1
        if event.completed:
            bucket["completedEvents"] += 1
        if event.score is not None:
            bucket["scoreTotal"] += float(event.score)
            bucket["scoreCount"] += 1

    learner_stats = []
    for stats in learner_stats_map.values():
        score_count = stats.pop("scoreCount")
        score_total = stats.pop("scoreTotal")
        stats["averageScore"] = (
            round(score_total / score_count, 2)
            if score_count > 0
            else None
        )
        learner_stats.append(stats)

    learner_stats.sort(key=lambda row: row["eventCount"], reverse=True)

    page_details = []
    for page in pages:
        comp_count = len(page.components or [])
        page_details.append({
            "pageId": page.page_id,
            "title": page.title,
            "order": page.order_index,
            "componentCount": comp_count,
            "completionStrategy": (page.completion_config or {}).get("strategy", "all"),
        })

    return {
        "courseId": courseId,
        "courseTitle": course.title,
        "courseStatus": course.status,
        "pages": page_details,
        "totalPages": len(pages),
        "scoring": scoring_record.to_dict() if scoring_record else None,
        "totalInteractionEvents": total_events,
        "learnerStats": learner_stats,
        "filteredByLearnerId": learnerId,
        "generatedAt": datetime.utcnow().isoformat(),
    }
