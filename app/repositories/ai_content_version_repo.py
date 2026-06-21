"""Repository for AI content versions — US-PEND-029."""
from __future__ import annotations

import json
import uuid as _uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select, func, desc, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_content_version import AIContentVersion

MAX_VERSIONS_PER_RESOURCE = 50
MAX_DIFF_SIZE = 100_000  # 100KB — skip diff above this size


class AIContentVersionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_version(
        self, resource_type, resource_id, course_id, content,
        created_by_user_id, proposal_id=None, change_summary="",
    ) -> AIContentVersion:
        previous = await self.get_latest(resource_type, resource_id)
        diff = None
        if previous and previous.content_snapshot:
            cj = json.dumps(content, default=str)
            pj = json.dumps(previous.content_snapshot, default=str)
            if len(cj) < MAX_DIFF_SIZE and len(pj) < MAX_DIFF_SIZE:
                try:
                    from deepdiff import DeepDiff
                    diff = DeepDiff(previous.content_snapshot, content, verbose_level=2).to_dict()
                except Exception:
                    diff = None

        stmt = select(func.max(AIContentVersion.version_number)).where(
            AIContentVersion.resource_type == resource_type,
            AIContentVersion.resource_id == resource_id,
        )
        result = await self.session.execute(stmt)
        max_ver = result.scalar() or 0

        version = AIContentVersion(
            version_id=str(_uuid.uuid4()),
            resource_type=resource_type, resource_id=resource_id,
            course_id=course_id, version_number=max_ver + 1,
            content_snapshot=content, content_diff=diff,
            proposal_id=proposal_id, created_by_user_id=created_by_user_id,
            change_summary=change_summary,
        )
        self.session.add(version)
        await self.session.commit()
        await self._enforce_retention(resource_type, resource_id)
        return version

    async def get_latest(self, resource_type, resource_id) -> Optional[AIContentVersion]:
        stmt = (
            select(AIContentVersion)
            .where(AIContentVersion.resource_type == resource_type,
                   AIContentVersion.resource_id == resource_id)
            .order_by(desc(AIContentVersion.version_number)).limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_versions(self, resource_type, resource_id) -> List[AIContentVersion]:
        stmt = (
            select(AIContentVersion)
            .where(AIContentVersion.resource_type == resource_type,
                   AIContentVersion.resource_id == resource_id)
            .order_by(desc(AIContentVersion.version_number))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def rollback_to(self, resource_type, resource_id, version_number):
        stmt = select(AIContentVersion).where(
            AIContentVersion.resource_type == resource_type,
            AIContentVersion.resource_id == resource_id,
            AIContentVersion.version_number == version_number,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _enforce_retention(self, resource_type, resource_id):
        stmt = (
            select(AIContentVersion.id)
            .where(AIContentVersion.resource_type == resource_type,
                   AIContentVersion.resource_id == resource_id)
            .order_by(desc(AIContentVersion.version_number))
            .offset(MAX_VERSIONS_PER_RESOURCE)
        )
        result = await self.session.execute(stmt)
        old_ids = result.scalars().all()
        if old_ids:
            await self.session.execute(
                delete(AIContentVersion).where(AIContentVersion.id.in_(old_ids))
            )
            await self.session.commit()
