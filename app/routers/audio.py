"""Audio Management API — upload, metadata, and narration overview.

Endpoints:
  POST         /assets/audio                  — Upload audio file
  GET/PATCH/DELETE /assets/audio/{audioId}     — Audio metadata CRUD
  GET          /courses/{courseId}/narration    — Course narration overview
"""
from __future__ import annotations
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.repositories.course_repo import CourseRepository
from app.repositories.page_component_repo import PageRepository

router = APIRouter(tags=["Audio"])


# In-memory audio registry (would be DB-persisted in production)
_audio_store: dict[str, dict] = {}

ALLOWED_AUDIO_TYPES = {"audio/mpeg", "audio/wav", "audio/ogg", "audio/aac", "audio/mp4", "audio/x-m4a"}
MAX_AUDIO_SIZE = 50 * 1024 * 1024  # 50MB


class AudioMetadataUpdateDTO(BaseModel):
    label: Optional[str] = None
    transcript: Optional[str] = None
    duration: Optional[float] = None


@router.post("/assets/audio", status_code=201)
async def upload_audio(
    file: UploadFile = File(...),
    courseId: Optional[str] = Form(None),
    label: Optional[str] = Form(None),
):
    if file.content_type and file.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(415, f"Unsupported audio format: {file.content_type}")

    content = await file.read()
    if len(content) > MAX_AUDIO_SIZE:
        raise HTTPException(413, "Audio file too large (max 50MB)")

    audio_id = str(uuid.uuid4())
    # In production, save to storage service
    audio_url = f"/api/v1/media/files/audio/{audio_id}_{file.filename}"

    entry = {
        "audioId": audio_id,
        "audioUrl": audio_url,
        "duration": None,
        "label": label or file.filename,
        "transcript": None,
        "mimeType": file.content_type,
        "fileSize": len(content),
        "courseId": courseId,
        "createdAt": __import__("datetime").datetime.utcnow().isoformat(),
    }
    _audio_store[audio_id] = entry
    return entry


@router.get("/assets/audio/{audioId}")
async def get_audio_metadata(audioId: str):
    entry = _audio_store.get(audioId)
    if not entry:
        raise HTTPException(404, f"Audio '{audioId}' not found")
    return entry


@router.patch("/assets/audio/{audioId}")
async def update_audio_metadata(
    audioId: str,
    body: AudioMetadataUpdateDTO,
):
    entry = _audio_store.get(audioId)
    if not entry:
        raise HTTPException(404, f"Audio '{audioId}' not found")

    if body.label is not None:
        entry["label"] = body.label
    if body.transcript is not None:
        entry["transcript"] = body.transcript
    if body.duration is not None:
        entry["duration"] = body.duration

    return entry


@router.delete("/assets/audio/{audioId}", status_code=204)
async def delete_audio(audioId: str):
    if audioId not in _audio_store:
        raise HTTPException(404, f"Audio '{audioId}' not found")
    del _audio_store[audioId]


@router.get("/courses/{courseId}/narration")
async def get_course_narration(
    courseId: str,
    session: AsyncSession = Depends(get_session),
):
    course_repo = CourseRepository(session)
    course = await course_repo.get_by_course_id(courseId)
    if not course:
        raise HTTPException(404, f"Course '{courseId}' not found")

    page_repo = PageRepository(session)
    pages = await page_repo.list_by_course(courseId)

    total_items = 0
    total_duration = 0.0
    page_narrations = []

    for page in pages:
        audio_items = []
        for comp in (page.components or []):
            ac = comp.audio_config or {}
            if not ac.get("enabled"):
                continue
            for item in ac.get("audioItems", []):
                audio_items.append({
                    "audioId": item.get("audioId"),
                    "componentId": comp.component_id,
                    "componentType": comp.component_type,
                    "targetInteractionId": item.get("targetInteractionId"),
                    "label": item.get("label"),
                    "audioUrl": item.get("audioUrl"),
                    "duration": item.get("duration", 0),
                    "requiredForCompletion": item.get("requiredForCompletion", False),
                })
                total_items += 1
                total_duration += item.get("duration", 0)

        if audio_items:
            page_narrations.append({
                "pageId": page.page_id,
                "pageTitle": page.title,
                "audioItems": audio_items,
            })

    return {
        "courseId": courseId,
        "totalAudioItems": total_items,
        "totalDuration": total_duration,
        "pages": page_narrations,
    }
