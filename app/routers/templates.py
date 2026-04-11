"""Templates router for normalized template/page entities.

All endpoints operate under a course scope: /courses/{courseId}/templates.
Public course IDs are resolved to the internal course PK before repository use.
"""
from __future__ import annotations
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.repositories.course_repo import CourseRepository, CourseNotFoundError
from app.repositories.template_repo import (
    TemplateRepository,
    TemplateNotFoundError,
    TemplateConflictError,
)

router = APIRouter(prefix="/courses/{courseId}/templates", tags=["Templates"])


class TemplateCreate(BaseModel):
    templateId: str = Field(..., min_length=1, max_length=100)
    type: str = Field(..., min_length=1, max_length=100)
    title: str = Field(..., min_length=1, max_length=200)
    data: dict = Field(default_factory=dict)
    order: Optional[int] = Field(None, ge=0)


class TemplateUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    type: Optional[str] = Field(None, max_length=100)
    data: Optional[dict] = None


class TemplateOut(BaseModel):
    id: int
    templateId: str
    type: str
    title: str
    order: int
    data: dict

    model_config = {"from_attributes": True}


class ReorderRequest(BaseModel):
    orderedIds: List[int] = Field(..., min_length=1)


async def _get_repo(
    session: AsyncSession = Depends(get_session),
) -> TemplateRepository:
    return TemplateRepository(session)


async def _get_course_pk(
    courseId: str,
    session: AsyncSession = Depends(get_session),
) -> int:
    course_repo = CourseRepository(session)
    try:
        course = await course_repo.get_by_course_id(courseId)
    except CourseNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Course not found",
        ) from exc
    return course.id


@router.get("", response_model=List[TemplateOut])
async def list_templates(
    course_pk: int = Depends(_get_course_pk),
    repo: TemplateRepository = Depends(_get_repo),
):
    templates = await repo.list(course_pk)
    return [t.to_dict() for t in templates]


@router.post(
    "", response_model=TemplateOut, status_code=status.HTTP_201_CREATED
)
async def create_template(
    payload: TemplateCreate,
    course_pk: int = Depends(_get_course_pk),
    repo: TemplateRepository = Depends(_get_repo),
):
    try:
        tmpl = await repo.create(
            course_id=course_pk,
            template_uid=payload.templateId,
            template_type=payload.type,
            title=payload.title,
            data=payload.data,
            order=payload.order,
        )
    except TemplateConflictError:
        raise HTTPException(status_code=400, detail="Template already exists")
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="Course not found")
    return tmpl.to_dict()


@router.get("/{template_id}", response_model=TemplateOut)
async def get_template(
    template_id: int,
    course_pk: int = Depends(_get_course_pk),
    repo: TemplateRepository = Depends(_get_repo),
):
    try:
        tmpl = await repo.get(course_pk, template_id)
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")
    return tmpl.to_dict()


@router.patch("/{template_id}", response_model=TemplateOut)
async def update_template(
    template_id: int,
    payload: TemplateUpdate,
    course_pk: int = Depends(_get_course_pk),
    repo: TemplateRepository = Depends(_get_repo),
):
    try:
        tmpl = await repo.update(
            course_pk,
            template_id,
            title=payload.title,
            data=payload.data,
            template_type=payload.type,
        )
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")
    return tmpl.to_dict()


@router.post("/reorder", response_model=List[TemplateOut])
async def reorder_templates(
    payload: ReorderRequest,
    course_pk: int = Depends(_get_course_pk),
    repo: TemplateRepository = Depends(_get_repo),
):
    try:
        ordered = await repo.reorder(course_pk, payload.orderedIds)
    except TemplateConflictError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="Course not found")
    return [t.to_dict() for t in ordered]


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: int,
    course_pk: int = Depends(_get_course_pk),
    repo: TemplateRepository = Depends(_get_repo),
):
    try:
        await repo.delete(course_pk, template_id)
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")
    return None
