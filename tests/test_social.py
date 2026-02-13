"""Tests for Social & Collaborative API.

Covers 15 endpoints across:
  - Discussions (list, create, get+replies, add reply)
  - Peer Reviews (list, create submission, get+reviews, add review)
  - Polls (list, create, vote, results)
  - Teams (list, create, get, update, delete)
"""
import pytest
from fastapi.testclient import TestClient

COURSE_ID = "social-test-course"


def _ensure_course(client: TestClient, course_id: str = COURSE_ID):
    r = client.post(
        "/api/v1/courses",
        json={
            "courseId": course_id,
            "title": "Social Test Course",
            "description": "For social tests",
            "data": {"pages": []},
        },
    )
    assert r.status_code in (201, 400)


# ── Discussion Tests ──────────────────────────────────────────────────────────

class TestDiscussions:

    def test_list_empty(self, test_client: TestClient):
        _ensure_course(test_client)
        r = test_client.get(f"/api/v1/courses/{COURSE_ID}/discussions")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_discussion(self, test_client: TestClient):
        _ensure_course(test_client)
        r = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/discussions",
            json={
                "title": "First Thread",
                "body": "Discussion body text",
                "authorId": "user-1",
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert data["title"] == "First Thread"
        assert data["body"] == "Discussion body text"
        assert data["authorId"] == "user-1"
        assert data["courseId"] == COURSE_ID
        assert data["threadId"]
        assert data["isPinned"] is False
        assert data["isClosed"] is False

    def test_get_discussion_with_replies(self, test_client: TestClient):
        _ensure_course(test_client)
        # Create thread
        cr = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/discussions",
            json={"title": "Thread with replies", "body": "body"},
        )
        thread_id = cr.json()["threadId"]

        # Get thread — should have replies array
        r = test_client.get(
            f"/api/v1/courses/{COURSE_ID}/discussions/{thread_id}"
        )
        assert r.status_code == 200
        data = r.json()
        assert data["threadId"] == thread_id
        assert "replies" in data
        assert isinstance(data["replies"], list)

    def test_add_reply(self, test_client: TestClient):
        _ensure_course(test_client)
        cr = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/discussions",
            json={"title": "Reply target"},
        )
        thread_id = cr.json()["threadId"]

        r = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/discussions/{thread_id}/replies",
            json={"body": "Great point!", "authorId": "user-2"},
        )
        assert r.status_code == 201
        data = r.json()
        assert data["body"] == "Great point!"
        assert data["authorId"] == "user-2"
        assert data["threadId"] == thread_id

        # Verify reply appears in thread
        gr = test_client.get(
            f"/api/v1/courses/{COURSE_ID}/discussions/{thread_id}"
        )
        assert len(gr.json()["replies"]) >= 1

    def test_nested_reply(self, test_client: TestClient):
        _ensure_course(test_client)
        cr = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/discussions",
            json={"title": "Nested reply thread"},
        )
        thread_id = cr.json()["threadId"]

        # First reply
        r1 = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/discussions/{thread_id}/replies",
            json={"body": "Parent reply"},
        )
        parent_id = r1.json()["replyId"]

        # Nested reply
        r2 = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/discussions/{thread_id}/replies",
            json={"body": "Child reply", "parentReplyId": parent_id},
        )
        assert r2.status_code == 201
        assert r2.json()["parentReplyId"] == parent_id

    def test_thread_not_found(self, test_client: TestClient):
        _ensure_course(test_client)
        r = test_client.get(
            f"/api/v1/courses/{COURSE_ID}/discussions/no-such-thread"
        )
        assert r.status_code == 404


# ── Peer Review Tests ─────────────────────────────────────────────────────────

class TestPeerReviews:

    def test_list_empty(self, test_client: TestClient):
        _ensure_course(test_client)
        r = test_client.get(f"/api/v1/courses/{COURSE_ID}/peer-reviews")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_submission(self, test_client: TestClient):
        _ensure_course(test_client)
        r = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/peer-reviews",
            json={
                "content": {"answer": "My essay response"},
                "authorId": "student-1",
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert data["content"] == {"answer": "My essay response"}
        assert data["authorId"] == "student-1"
        assert data["status"] == "submitted"
        assert data["submissionId"]

    def test_get_submission_with_reviews(self, test_client: TestClient):
        _ensure_course(test_client)
        cr = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/peer-reviews",
            json={"content": {"text": "Work for review"}},
        )
        sub_id = cr.json()["submissionId"]

        r = test_client.get(
            f"/api/v1/courses/{COURSE_ID}/peer-reviews/{sub_id}"
        )
        assert r.status_code == 200
        data = r.json()
        assert data["submissionId"] == sub_id
        assert "reviews" in data
        assert isinstance(data["reviews"], list)

    def test_add_review(self, test_client: TestClient):
        _ensure_course(test_client)
        cr = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/peer-reviews",
            json={"content": {"text": "Reviewable work"}},
        )
        sub_id = cr.json()["submissionId"]

        r = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/peer-reviews/{sub_id}/reviews",
            json={
                "reviewerId": "reviewer-1",
                "feedback": "Well-structured response",
                "rubricScores": {"clarity": 4, "depth": 3},
                "overallScore": 7.5,
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert data["reviewerId"] == "reviewer-1"
        assert data["feedback"] == "Well-structured response"
        assert data["overallScore"] == 7.5

        # Submission status should be updated
        sr = test_client.get(
            f"/api/v1/courses/{COURSE_ID}/peer-reviews/{sub_id}"
        )
        assert sr.json()["status"] == "reviewed"

    def test_submission_not_found(self, test_client: TestClient):
        _ensure_course(test_client)
        r = test_client.get(
            f"/api/v1/courses/{COURSE_ID}/peer-reviews/no-such-sub"
        )
        assert r.status_code == 404


# ── Poll Tests ────────────────────────────────────────────────────────────────

class TestPolls:

    def test_list_empty(self, test_client: TestClient):
        _ensure_course(test_client)
        r = test_client.get(f"/api/v1/courses/{COURSE_ID}/polls")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_poll(self, test_client: TestClient):
        _ensure_course(test_client)
        r = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/polls",
            json={
                "question": "Favorite language?",
                "options": ["Python", "JavaScript", "Rust"],
                "allowMultiple": False,
                "isAnonymous": True,
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert data["question"] == "Favorite language?"
        assert len(data["options"]) == 3
        assert data["allowMultiple"] is False
        assert data["pollId"]

    def test_submit_vote(self, test_client: TestClient):
        _ensure_course(test_client)
        cr = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/polls",
            json={"question": "Vote test?", "options": ["A", "B"]},
        )
        poll_id = cr.json()["pollId"]

        r = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/polls/{poll_id}/votes",
            json={"voterId": "voter-1", "selectedOptions": [0]},
        )
        assert r.status_code == 201
        data = r.json()
        assert data["selectedOptions"] == [0]
        assert data["voteId"]

    def test_vote_invalid_option_index(self, test_client: TestClient):
        _ensure_course(test_client)
        cr = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/polls",
            json={"question": "Invalid idx?", "options": ["A", "B"]},
        )
        poll_id = cr.json()["pollId"]

        r = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/polls/{poll_id}/votes",
            json={"voterId": "v1", "selectedOptions": [99]},
        )
        assert r.status_code == 422

    def test_single_select_rejects_multiple(self, test_client: TestClient):
        _ensure_course(test_client)
        cr = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/polls",
            json={
                "question": "Single only?",
                "options": ["X", "Y", "Z"],
                "allowMultiple": False,
            },
        )
        poll_id = cr.json()["pollId"]

        r = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/polls/{poll_id}/votes",
            json={"voterId": "v1", "selectedOptions": [0, 1]},
        )
        assert r.status_code == 422

    def test_poll_results(self, test_client: TestClient):
        _ensure_course(test_client)
        cr = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/polls",
            json={"question": "Results test?", "options": ["Yes", "No"]},
        )
        poll_id = cr.json()["pollId"]

        # Cast votes
        test_client.post(
            f"/api/v1/courses/{COURSE_ID}/polls/{poll_id}/votes",
            json={"voterId": "v1", "selectedOptions": [0]},
        )
        test_client.post(
            f"/api/v1/courses/{COURSE_ID}/polls/{poll_id}/votes",
            json={"voterId": "v2", "selectedOptions": [0]},
        )
        test_client.post(
            f"/api/v1/courses/{COURSE_ID}/polls/{poll_id}/votes",
            json={"voterId": "v3", "selectedOptions": [1]},
        )

        r = test_client.get(
            f"/api/v1/courses/{COURSE_ID}/polls/{poll_id}/results"
        )
        assert r.status_code == 200
        data = r.json()
        assert data["pollId"] == poll_id
        assert data["totalVotes"] == 3
        # "Yes" got 2 votes → ~66.7%
        yes_opt = next(o for o in data["options"] if o["text"] == "Yes")
        assert yes_opt["votes"] == 2
        assert yes_opt["percentage"] > 60

    def test_poll_not_found(self, test_client: TestClient):
        _ensure_course(test_client)
        r = test_client.get(
            f"/api/v1/courses/{COURSE_ID}/polls/no-such-poll/results"
        )
        assert r.status_code == 404


# ── Team Tests ────────────────────────────────────────────────────────────────

class TestTeams:

    def test_list_empty(self, test_client: TestClient):
        _ensure_course(test_client)
        r = test_client.get(f"/api/v1/courses/{COURSE_ID}/teams")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_team(self, test_client: TestClient):
        _ensure_course(test_client)
        r = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/teams",
            json={
                "name": "Alpha Squad",
                "members": ["user-1", "user-2", "user-3"],
                "metadata": {"color": "blue"},
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "Alpha Squad"
        assert data["members"] == ["user-1", "user-2", "user-3"]
        assert data["metadata"] == {"color": "blue"}
        assert data["score"] == 0.0
        assert data["teamId"]

    def test_get_team(self, test_client: TestClient):
        _ensure_course(test_client)
        cr = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/teams",
            json={"name": "Get Team"},
        )
        team_id = cr.json()["teamId"]

        r = test_client.get(
            f"/api/v1/courses/{COURSE_ID}/teams/{team_id}"
        )
        assert r.status_code == 200
        assert r.json()["teamId"] == team_id

    def test_update_team(self, test_client: TestClient):
        _ensure_course(test_client)
        cr = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/teams",
            json={"name": "Before"},
        )
        team_id = cr.json()["teamId"]

        r = test_client.patch(
            f"/api/v1/courses/{COURSE_ID}/teams/{team_id}",
            json={
                "name": "After",
                "score": 42.5,
                "members": ["a", "b"],
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "After"
        assert data["score"] == 42.5
        assert data["members"] == ["a", "b"]

    def test_delete_team(self, test_client: TestClient):
        _ensure_course(test_client)
        cr = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/teams",
            json={"name": "To remove"},
        )
        team_id = cr.json()["teamId"]

        r = test_client.delete(
            f"/api/v1/courses/{COURSE_ID}/teams/{team_id}"
        )
        assert r.status_code == 204

        r2 = test_client.get(
            f"/api/v1/courses/{COURSE_ID}/teams/{team_id}"
        )
        assert r2.status_code == 404

    def test_team_not_found(self, test_client: TestClient):
        _ensure_course(test_client)
        r = test_client.get(
            f"/api/v1/courses/{COURSE_ID}/teams/no-such-team"
        )
        assert r.status_code == 404
