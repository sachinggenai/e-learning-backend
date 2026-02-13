"""Repositories for Social & Collaborative models.

Covers: DiscussionThread, DiscussionReply, PeerReviewSubmission,
PeerReview, Poll, PollVote, Team.
"""
from __future__ import annotations
from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.social import (
    DiscussionThread,
    DiscussionReply,
    PeerReviewSubmission,
    PeerReview,
    Poll,
    PollVote,
    Team,
)


# ── Discussion ───────────────────────────────────────────────────────────────

class DiscussionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_course(self, course_id: str) -> List[DiscussionThread]:
        q = (
            select(DiscussionThread)
            .where(DiscussionThread.course_id == course_id)
            .order_by(DiscussionThread.is_pinned.desc(), DiscussionThread.created_at.desc())
        )
        return list((await self.session.execute(q)).scalars().all())

    async def get(self, thread_id: str) -> Optional[DiscussionThread]:
        q = select(DiscussionThread).where(DiscussionThread.thread_id == thread_id)
        return (await self.session.execute(q)).scalar_one_or_none()

    async def create(self, thread: DiscussionThread) -> DiscussionThread:
        self.session.add(thread)
        await self.session.commit()
        await self.session.refresh(thread)
        return thread

    async def update(self, thread: DiscussionThread) -> DiscussionThread:
        await self.session.commit()
        await self.session.refresh(thread)
        return thread

    async def delete(self, thread: DiscussionThread) -> None:
        await self.session.delete(thread)
        await self.session.commit()


class DiscussionReplyRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_thread(self, thread_id: str) -> List[DiscussionReply]:
        q = (
            select(DiscussionReply)
            .where(DiscussionReply.thread_id == thread_id)
            .order_by(DiscussionReply.created_at)
        )
        return list((await self.session.execute(q)).scalars().all())

    async def create(self, reply: DiscussionReply) -> DiscussionReply:
        self.session.add(reply)
        await self.session.commit()
        await self.session.refresh(reply)
        return reply

    async def delete(self, reply: DiscussionReply) -> None:
        await self.session.delete(reply)
        await self.session.commit()


# ── Peer Review ──────────────────────────────────────────────────────────────

class PeerReviewSubmissionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_course(self, course_id: str) -> List[PeerReviewSubmission]:
        q = (
            select(PeerReviewSubmission)
            .where(PeerReviewSubmission.course_id == course_id)
            .order_by(PeerReviewSubmission.created_at.desc())
        )
        return list((await self.session.execute(q)).scalars().all())

    async def get(self, submission_id: str) -> Optional[PeerReviewSubmission]:
        q = select(PeerReviewSubmission).where(
            PeerReviewSubmission.submission_id == submission_id
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def create(self, sub: PeerReviewSubmission) -> PeerReviewSubmission:
        self.session.add(sub)
        await self.session.commit()
        await self.session.refresh(sub)
        return sub

    async def update(self, sub: PeerReviewSubmission) -> PeerReviewSubmission:
        await self.session.commit()
        await self.session.refresh(sub)
        return sub


class PeerReviewRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_submission(self, submission_id: str) -> List[PeerReview]:
        q = (
            select(PeerReview)
            .where(PeerReview.submission_id == submission_id)
            .order_by(PeerReview.created_at.desc())
        )
        return list((await self.session.execute(q)).scalars().all())

    async def create(self, review: PeerReview) -> PeerReview:
        self.session.add(review)
        await self.session.commit()
        await self.session.refresh(review)
        return review


# ── Poll ─────────────────────────────────────────────────────────────────────

class PollRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_course(self, course_id: str) -> List[Poll]:
        q = (
            select(Poll)
            .where(Poll.course_id == course_id)
            .order_by(Poll.created_at.desc())
        )
        return list((await self.session.execute(q)).scalars().all())

    async def get(self, poll_id: str) -> Optional[Poll]:
        q = select(Poll).where(Poll.poll_id == poll_id)
        return (await self.session.execute(q)).scalar_one_or_none()

    async def create(self, poll: Poll) -> Poll:
        self.session.add(poll)
        await self.session.commit()
        await self.session.refresh(poll)
        return poll

    async def update(self, poll: Poll) -> Poll:
        await self.session.commit()
        await self.session.refresh(poll)
        return poll


class PollVoteRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_poll(self, poll_id: str) -> List[PollVote]:
        q = (
            select(PollVote)
            .where(PollVote.poll_id == poll_id)
            .order_by(PollVote.created_at)
        )
        return list((await self.session.execute(q)).scalars().all())

    async def get_by_voter(self, poll_id: str, voter_id: str) -> Optional[PollVote]:
        q = select(PollVote).where(
            PollVote.poll_id == poll_id, PollVote.voter_id == voter_id
        )
        return (await self.session.execute(q)).scalar_one_or_none()

    async def create(self, vote: PollVote) -> PollVote:
        self.session.add(vote)
        await self.session.commit()
        await self.session.refresh(vote)
        return vote


# ── Team ─────────────────────────────────────────────────────────────────────

class TeamRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_course(self, course_id: str) -> List[Team]:
        q = (
            select(Team)
            .where(Team.course_id == course_id)
            .order_by(Team.name)
        )
        return list((await self.session.execute(q)).scalars().all())

    async def get(self, team_id: str) -> Optional[Team]:
        q = select(Team).where(Team.team_id == team_id)
        return (await self.session.execute(q)).scalar_one_or_none()

    async def create(self, team: Team) -> Team:
        self.session.add(team)
        await self.session.commit()
        await self.session.refresh(team)
        return team

    async def update(self, team: Team) -> Team:
        await self.session.commit()
        await self.session.refresh(team)
        return team

    async def delete(self, team: Team) -> None:
        await self.session.delete(team)
        await self.session.commit()
