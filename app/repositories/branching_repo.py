"""Repository for BranchRule and BranchEvent — branching CRUD."""
from __future__ import annotations
from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.branching import BranchRule, BranchEvent


class BranchRuleRepository:
    """DB access for branch_rules table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_course(self, course_id: str) -> List[BranchRule]:
        q = (
            select(BranchRule)
            .where(BranchRule.course_id == course_id)
            .order_by(BranchRule.priority, BranchRule.created_at)
        )
        return list((await self.session.execute(q)).scalars().all())

    async def get(self, branch_id: str) -> Optional[BranchRule]:
        q = select(BranchRule).where(BranchRule.branch_id == branch_id)
        return (await self.session.execute(q)).scalar_one_or_none()

    async def create(self, rule: BranchRule) -> BranchRule:
        self.session.add(rule)
        await self.session.commit()
        await self.session.refresh(rule)
        return rule

    async def update(self, rule: BranchRule) -> BranchRule:
        await self.session.commit()
        await self.session.refresh(rule)
        return rule

    async def delete(self, rule: BranchRule) -> None:
        await self.session.delete(rule)
        await self.session.commit()


class BranchEventRepository:
    """DB access for branch_events table."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_branch(
        self, branch_id: str, *, learner_id: Optional[str] = None
    ) -> List[BranchEvent]:
        q = select(BranchEvent).where(BranchEvent.branch_id == branch_id)
        if learner_id:
            q = q.where(BranchEvent.learner_id == learner_id)
        q = q.order_by(BranchEvent.created_at.desc())
        return list((await self.session.execute(q)).scalars().all())

    async def list_by_course(
        self, course_id: str, *, learner_id: Optional[str] = None
    ) -> List[BranchEvent]:
        q = select(BranchEvent).where(BranchEvent.course_id == course_id)
        if learner_id:
            q = q.where(BranchEvent.learner_id == learner_id)
        q = q.order_by(BranchEvent.created_at.desc())
        return list((await self.session.execute(q)).scalars().all())

    async def create(self, event: BranchEvent) -> BranchEvent:
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(event)
        return event
