"""Social & Collaborative ORM models.

Covers discussion threads/replies, peer reviews, polls, and team challenges
for multi-user e-learning templates.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, JSON, Text, Integer, Boolean, Float, ForeignKey

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


# ── Discussion ───────────────────────────────────────────────────────────────

class DiscussionThread(Base):
    """A discussion thread within a course."""

    __tablename__ = "discussion_threads"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    course_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("courses.course_id", ondelete="CASCADE"),
        index=True,
    )
    page_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    author_id: Mapped[str] = mapped_column(String(128), default="anonymous")
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "threadId": self.thread_id,
            "courseId": self.course_id,
            "pageId": self.page_id,
            "authorId": self.author_id,
            "title": self.title,
            "body": self.body,
            "isPinned": self.is_pinned,
            "isClosed": self.is_closed,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class DiscussionReply(Base):
    """A reply within a discussion thread."""

    __tablename__ = "discussion_replies"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    reply_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    thread_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("discussion_threads.thread_id", ondelete="CASCADE"),
        index=True,
    )
    author_id: Mapped[str] = mapped_column(String(128), default="anonymous")
    body: Mapped[str] = mapped_column(Text, default="")
    parent_reply_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "replyId": self.reply_id,
            "threadId": self.thread_id,
            "authorId": self.author_id,
            "body": self.body,
            "parentReplyId": self.parent_reply_id,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


# ── Peer Review ──────────────────────────────────────────────────────────────

class PeerReviewSubmission(Base):
    """A peer review submission (the work being reviewed)."""

    __tablename__ = "peer_review_submissions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    submission_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    course_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("courses.course_id", ondelete="CASCADE"),
        index=True,
    )
    page_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    author_id: Mapped[str] = mapped_column(String(128), default="anonymous")
    content: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="submitted")  # submitted | reviewed | closed

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "submissionId": self.submission_id,
            "courseId": self.course_id,
            "pageId": self.page_id,
            "authorId": self.author_id,
            "content": self.content,
            "status": self.status,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class PeerReview(Base):
    """A review left by a peer on a submission."""

    __tablename__ = "peer_reviews"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    review_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    submission_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("peer_review_submissions.submission_id", ondelete="CASCADE"),
        index=True,
    )
    reviewer_id: Mapped[str] = mapped_column(String(128), default="anonymous")
    feedback: Mapped[str] = mapped_column(Text, default="")
    rubric_scores: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    overall_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "reviewId": self.review_id,
            "submissionId": self.submission_id,
            "reviewerId": self.reviewer_id,
            "feedback": self.feedback,
            "rubricScores": self.rubric_scores,
            "overallScore": self.overall_score,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


# ── Polls ────────────────────────────────────────────────────────────────────

class Poll(Base):
    """A poll within a course (may be linked to a page component)."""

    __tablename__ = "polls"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    poll_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    course_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("courses.course_id", ondelete="CASCADE"),
        index=True,
    )
    question: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    allow_multiple: Mapped[bool] = mapped_column(Boolean, default=False)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=True)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "pollId": self.poll_id,
            "courseId": self.course_id,
            "question": self.question,
            "options": self.options,
            "allowMultiple": self.allow_multiple,
            "isAnonymous": self.is_anonymous,
            "isClosed": self.is_closed,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class PollVote(Base):
    """An individual vote on a poll."""

    __tablename__ = "poll_votes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    vote_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    poll_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("polls.poll_id", ondelete="CASCADE"),
        index=True,
    )
    voter_id: Mapped[str] = mapped_column(String(128), default="anonymous")
    selected_options: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "voteId": self.vote_id,
            "pollId": self.poll_id,
            "voterId": self.voter_id,
            "selectedOptions": self.selected_options,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


# ── Teams ────────────────────────────────────────────────────────────────────

class Team(Base):
    """A team (group) within a course for collaborative challenges."""

    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    team_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=_uuid
    )
    course_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("courses.course_id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200))
    members: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "teamId": self.team_id,
            "courseId": self.course_id,
            "name": self.name,
            "members": self.members,
            "score": self.score,
            "metadata": self.metadata_json,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
