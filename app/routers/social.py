"""Social & Collaborative API.

Endpoints for discussion threads/replies, peer reviews,
polls with vote submission/tally, and team challenges.
"""
from __future__ import annotations
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.config import get_session
from app.utils.error_responses import validation_error
from app.repositories.course_repo import CourseRepository
from app.repositories.social_repo import (
    DiscussionRepository,
    DiscussionReplyRepository,
    PeerReviewSubmissionRepository,
    PeerReviewRepository,
    PollRepository,
    PollVoteRepository,
    TeamRepository,
)
from app.models.social import (
    DiscussionThread,
    DiscussionReply,
    PeerReviewSubmission,
    PeerReview,
    Poll,
    PollVote,
    Team,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _require_course(session: AsyncSession, course_id: str):
    repo = CourseRepository(session)
    try:
        return await repo.get_by_course_id(course_id)
    except Exception:
        raise HTTPException(404, f"Course '{course_id}' not found")


# ── DTOs ─────────────────────────────────────────────────────────────────────

class DiscussionCreateDTO(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    body: str = ""
    authorId: str = "anonymous"
    pageId: Optional[str] = None


class DiscussionReplyCreateDTO(BaseModel):
    body: str = Field(..., min_length=1)
    authorId: str = "anonymous"
    parentReplyId: Optional[str] = None


class PeerReviewSubmissionCreateDTO(BaseModel):
    content: dict = Field(default_factory=dict)
    authorId: str = "anonymous"
    pageId: Optional[str] = None


class PeerReviewCreateDTO(BaseModel):
    reviewerId: str = "anonymous"
    feedback: str = ""
    rubricScores: Optional[dict] = None
    overallScore: Optional[float] = None


class PollCreateDTO(BaseModel):
    question: str = Field(..., min_length=1)
    options: List[str] = Field(..., min_length=2)
    allowMultiple: bool = False
    isAnonymous: bool = True


class PollVoteCreateDTO(BaseModel):
    voterId: str = "anonymous"
    selectedOptions: List[int] = Field(..., min_length=1, description="0-based option indices")


class TeamCreateDTO(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    members: List[str] = Field(default_factory=list)
    metadata: Optional[dict] = None


class TeamUpdateDTO(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    members: Optional[List[str]] = None
    score: Optional[float] = None
    metadata: Optional[dict] = None


# ── Router ───────────────────────────────────────────────────────────────────

router = APIRouter(tags=["Social"])


# ── Discussions ──────────────────────────────────────────────────────────────

@router.get("/courses/{courseId}/discussions")
async def list_discussions(
    courseId: str,
    session: AsyncSession = Depends(get_session),
):
    await _require_course(session, courseId)
    repo = DiscussionRepository(session)
    threads = await repo.list_by_course(courseId)
    return [t.to_dict() for t in threads]


@router.post("/courses/{courseId}/discussions", status_code=201)
async def create_discussion(
    courseId: str,
    body: DiscussionCreateDTO,
    session: AsyncSession = Depends(get_session),
):
    await _require_course(session, courseId)
    repo = DiscussionRepository(session)
    thread = DiscussionThread(
        course_id=courseId,
        title=body.title,
        body=body.body,
        author_id=body.authorId,
        page_id=body.pageId,
    )
    thread = await repo.create(thread)
    return thread.to_dict()


@router.get("/courses/{courseId}/discussions/{threadId}")
async def get_discussion(
    courseId: str,
    threadId: str,
    session: AsyncSession = Depends(get_session),
):
    await _require_course(session, courseId)
    repo = DiscussionRepository(session)
    thread = await repo.get(threadId)
    if not thread or thread.course_id != courseId:
        raise HTTPException(404, f"Discussion thread '{threadId}' not found")

    reply_repo = DiscussionReplyRepository(session)
    replies = await reply_repo.list_by_thread(threadId)
    result = thread.to_dict()
    result["replies"] = [r.to_dict() for r in replies]
    return result


@router.post("/courses/{courseId}/discussions/{threadId}/replies", status_code=201)
async def add_discussion_reply(
    courseId: str,
    threadId: str,
    body: DiscussionReplyCreateDTO,
    session: AsyncSession = Depends(get_session),
):
    await _require_course(session, courseId)
    thread_repo = DiscussionRepository(session)
    thread = await thread_repo.get(threadId)
    if not thread or thread.course_id != courseId:
        raise HTTPException(404, f"Discussion thread '{threadId}' not found")
    if thread.is_closed:
        return validation_error(
            "Validation failed",
            [{"field": "threadId", "message": "Thread is closed"}],
        )

    reply_repo = DiscussionReplyRepository(session)
    reply = DiscussionReply(
        thread_id=threadId,
        body=body.body,
        author_id=body.authorId,
        parent_reply_id=body.parentReplyId,
    )
    reply = await reply_repo.create(reply)
    return reply.to_dict()


# ── Peer Reviews ─────────────────────────────────────────────────────────────

@router.get("/courses/{courseId}/peer-reviews")
async def list_peer_review_submissions(
    courseId: str,
    session: AsyncSession = Depends(get_session),
):
    await _require_course(session, courseId)
    repo = PeerReviewSubmissionRepository(session)
    subs = await repo.list_by_course(courseId)
    return [s.to_dict() for s in subs]


@router.post("/courses/{courseId}/peer-reviews", status_code=201)
async def create_peer_review_submission(
    courseId: str,
    body: PeerReviewSubmissionCreateDTO,
    session: AsyncSession = Depends(get_session),
):
    await _require_course(session, courseId)
    repo = PeerReviewSubmissionRepository(session)
    sub = PeerReviewSubmission(
        course_id=courseId,
        content=body.content,
        author_id=body.authorId,
        page_id=body.pageId,
    )
    sub = await repo.create(sub)
    return sub.to_dict()


@router.get("/courses/{courseId}/peer-reviews/{submissionId}")
async def get_peer_review_submission(
    courseId: str,
    submissionId: str,
    session: AsyncSession = Depends(get_session),
):
    await _require_course(session, courseId)
    repo = PeerReviewSubmissionRepository(session)
    sub = await repo.get(submissionId)
    if not sub or sub.course_id != courseId:
        raise HTTPException(404, f"Submission '{submissionId}' not found")

    review_repo = PeerReviewRepository(session)
    reviews = await review_repo.list_by_submission(submissionId)
    result = sub.to_dict()
    result["reviews"] = [r.to_dict() for r in reviews]
    return result


@router.post("/courses/{courseId}/peer-reviews/{submissionId}/reviews", status_code=201)
async def add_peer_review(
    courseId: str,
    submissionId: str,
    body: PeerReviewCreateDTO,
    session: AsyncSession = Depends(get_session),
):
    await _require_course(session, courseId)
    sub_repo = PeerReviewSubmissionRepository(session)
    sub = await sub_repo.get(submissionId)
    if not sub or sub.course_id != courseId:
        raise HTTPException(404, f"Submission '{submissionId}' not found")

    review_repo = PeerReviewRepository(session)
    review = PeerReview(
        submission_id=submissionId,
        reviewer_id=body.reviewerId,
        feedback=body.feedback,
        rubric_scores=body.rubricScores,
        overall_score=body.overallScore,
    )
    review = await review_repo.create(review)

    # Update submission status
    sub.status = "reviewed"
    await sub_repo.update(sub)

    return review.to_dict()


# ── Polls ────────────────────────────────────────────────────────────────────

@router.get("/courses/{courseId}/polls")
async def list_polls(
    courseId: str,
    session: AsyncSession = Depends(get_session),
):
    await _require_course(session, courseId)
    repo = PollRepository(session)
    polls = await repo.list_by_course(courseId)
    return [p.to_dict() for p in polls]


@router.post("/courses/{courseId}/polls", status_code=201)
async def create_poll(
    courseId: str,
    body: PollCreateDTO,
    session: AsyncSession = Depends(get_session),
):
    await _require_course(session, courseId)
    repo = PollRepository(session)
    # Store options as list of dicts with text and index
    options = [{"index": i, "text": opt} for i, opt in enumerate(body.options)]
    poll = Poll(
        course_id=courseId,
        question=body.question,
        options=options,
        allow_multiple=body.allowMultiple,
        is_anonymous=body.isAnonymous,
    )
    poll = await repo.create(poll)
    return poll.to_dict()


@router.post("/courses/{courseId}/polls/{pollId}/votes", status_code=201)
async def submit_poll_vote(
    courseId: str,
    pollId: str,
    body: PollVoteCreateDTO,
    session: AsyncSession = Depends(get_session),
):
    await _require_course(session, courseId)
    poll_repo = PollRepository(session)
    poll = await poll_repo.get(pollId)
    if not poll or poll.course_id != courseId:
        raise HTTPException(404, f"Poll '{pollId}' not found")
    if poll.is_closed:
        return validation_error(
            "Validation failed",
            [{"field": "pollId", "message": "Poll is closed"}],
        )

    # Validate option indices
    max_index = len(poll.options) - 1
    for idx in body.selectedOptions:
        if idx < 0 or idx > max_index:
            return validation_error(
                "Validation failed",
                [{"field": "selectedOptions", "message": f"Option index {idx} out of range (0-{max_index})"}],
            )

    if not poll.allow_multiple and len(body.selectedOptions) > 1:
        return validation_error(
            "Validation failed",
            [{"field": "selectedOptions", "message": "This poll only allows a single selection"}],
        )

    vote_repo = PollVoteRepository(session)
    # Check for duplicate voter (non-anonymous polls)
    if not poll.is_anonymous:
        existing = await vote_repo.get_by_voter(pollId, body.voterId)
        if existing:
            raise HTTPException(409, "Voter has already voted on this poll")

    vote = PollVote(
        poll_id=pollId,
        voter_id=body.voterId,
        selected_options=body.selectedOptions,
    )
    vote = await vote_repo.create(vote)
    return vote.to_dict()


@router.get("/courses/{courseId}/polls/{pollId}/results")
async def get_poll_results(
    courseId: str,
    pollId: str,
    session: AsyncSession = Depends(get_session),
):
    """Get aggregated poll results (tallied votes per option)."""
    await _require_course(session, courseId)
    poll_repo = PollRepository(session)
    poll = await poll_repo.get(pollId)
    if not poll or poll.course_id != courseId:
        raise HTTPException(404, f"Poll '{pollId}' not found")

    vote_repo = PollVoteRepository(session)
    votes = await vote_repo.list_by_poll(pollId)

    # Tally
    tally = {i: 0 for i in range(len(poll.options))}
    for v in votes:
        for idx in v.selected_options:
            if idx in tally:
                tally[idx] += 1

    total_votes = len(votes)
    option_results = []
    for opt in poll.options:
        idx = opt["index"]
        count = tally.get(idx, 0)
        option_results.append({
            "index": idx,
            "text": opt["text"],
            "votes": count,
            "percentage": round(count / total_votes * 100, 1) if total_votes > 0 else 0,
        })

    return {
        "pollId": poll.poll_id,
        "question": poll.question,
        "totalVotes": total_votes,
        "options": option_results,
        "isClosed": poll.is_closed,
    }


# ── Teams ────────────────────────────────────────────────────────────────────

@router.get("/courses/{courseId}/teams")
async def list_teams(
    courseId: str,
    session: AsyncSession = Depends(get_session),
):
    await _require_course(session, courseId)
    repo = TeamRepository(session)
    teams = await repo.list_by_course(courseId)
    return [t.to_dict() for t in teams]


@router.post("/courses/{courseId}/teams", status_code=201)
async def create_team(
    courseId: str,
    body: TeamCreateDTO,
    session: AsyncSession = Depends(get_session),
):
    await _require_course(session, courseId)
    repo = TeamRepository(session)
    team = Team(
        course_id=courseId,
        name=body.name,
        members=body.members,
        metadata_json=body.metadata,
    )
    team = await repo.create(team)
    return team.to_dict()


@router.get("/courses/{courseId}/teams/{teamId}")
async def get_team(
    courseId: str,
    teamId: str,
    session: AsyncSession = Depends(get_session),
):
    await _require_course(session, courseId)
    repo = TeamRepository(session)
    team = await repo.get(teamId)
    if not team or team.course_id != courseId:
        raise HTTPException(404, f"Team '{teamId}' not found")
    return team.to_dict()


@router.patch("/courses/{courseId}/teams/{teamId}")
async def update_team(
    courseId: str,
    teamId: str,
    body: TeamUpdateDTO,
    session: AsyncSession = Depends(get_session),
):
    await _require_course(session, courseId)
    repo = TeamRepository(session)
    team = await repo.get(teamId)
    if not team or team.course_id != courseId:
        raise HTTPException(404, f"Team '{teamId}' not found")

    if body.name is not None:
        team.name = body.name
    if body.members is not None:
        team.members = body.members
    if body.score is not None:
        team.score = body.score
    if body.metadata is not None:
        team.metadata_json = body.metadata

    team = await repo.update(team)
    return team.to_dict()


@router.delete("/courses/{courseId}/teams/{teamId}", status_code=204)
async def delete_team(
    courseId: str,
    teamId: str,
    session: AsyncSession = Depends(get_session),
):
    await _require_course(session, courseId)
    repo = TeamRepository(session)
    team = await repo.get(teamId)
    if not team or team.course_id != courseId:
        raise HTTPException(404, f"Team '{teamId}' not found")
    await repo.delete(team)
