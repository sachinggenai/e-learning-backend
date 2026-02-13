"""Tests for Branching & Adaptive Navigation API.

Covers all 7 endpoints:
  GET   /courses/{courseId}/branches
  POST  /courses/{courseId}/branches
  GET   /courses/{courseId}/branches/{branchId}
  PATCH /courses/{courseId}/branches/{branchId}
  DELETE /courses/{courseId}/branches/{branchId}
  POST  /courses/{courseId}/branches/{branchId}/events
  GET   /courses/{courseId}/branches/{branchId}/events
"""
import pytest
from fastapi.testclient import TestClient

COURSE_ID = "branch-test-course"


def _ensure_course(client: TestClient, course_id: str = COURSE_ID):
    """Create a course if it doesn't already exist."""
    r = client.post(
        "/api/v1/courses",
        json={
            "courseId": course_id,
            "title": "Branch Test Course",
            "description": "For branching tests",
            "data": {"pages": []},
        },
    )
    assert r.status_code in (201, 400)  # 400 = already exists


class TestBranchRuleCRUD:
    """CRUD tests for branch rules."""

    def test_list_empty(self, test_client: TestClient):
        _ensure_course(test_client)
        r = test_client.get(f"/api/v1/courses/{COURSE_ID}/branches")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_branch_rule(self, test_client: TestClient):
        _ensure_course(test_client)
        payload = {
            "title": "Score-based branch",
            "description": "Route high scorers forward",
            "sourcePageId": "page-1",
            "conditions": [
                {
                    "field": "score",
                    "operator": ">=",
                    "value": 80,
                    "targetPageId": "page-3",
                }
            ],
            "defaultTargetPageId": "page-2",
            "priority": 1,
            "isActive": True,
        }
        r = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/branches", json=payload
        )
        assert r.status_code == 201
        data = r.json()
        assert data["title"] == "Score-based branch"
        assert data["courseId"] == COURSE_ID
        assert data["branchId"]  # UUID assigned
        assert len(data["conditions"]) == 1
        assert data["defaultTargetPageId"] == "page-2"
        assert data["isActive"] is True
        assert data["createdAt"] is not None

    def test_get_branch_rule(self, test_client: TestClient):
        _ensure_course(test_client)
        # Create first
        create_r = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/branches",
            json={"title": "Get test", "conditions": []},
        )
        branch_id = create_r.json()["branchId"]

        r = test_client.get(
            f"/api/v1/courses/{COURSE_ID}/branches/{branch_id}"
        )
        assert r.status_code == 200
        assert r.json()["branchId"] == branch_id
        assert r.json()["title"] == "Get test"

    def test_get_branch_rule_not_found(self, test_client: TestClient):
        _ensure_course(test_client)
        r = test_client.get(
            f"/api/v1/courses/{COURSE_ID}/branches/nonexistent-id"
        )
        assert r.status_code == 404

    def test_update_branch_rule(self, test_client: TestClient):
        _ensure_course(test_client)
        create_r = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/branches",
            json={"title": "Before update", "priority": 5, "conditions": []},
        )
        branch_id = create_r.json()["branchId"]

        r = test_client.patch(
            f"/api/v1/courses/{COURSE_ID}/branches/{branch_id}",
            json={"title": "After update", "priority": 10, "isActive": False},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["title"] == "After update"
        assert data["priority"] == 10
        assert data["isActive"] is False

    def test_delete_branch_rule(self, test_client: TestClient):
        _ensure_course(test_client)
        create_r = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/branches",
            json={"title": "To delete", "conditions": []},
        )
        branch_id = create_r.json()["branchId"]

        r = test_client.delete(
            f"/api/v1/courses/{COURSE_ID}/branches/{branch_id}"
        )
        assert r.status_code == 204

        # Confirm gone
        r2 = test_client.get(
            f"/api/v1/courses/{COURSE_ID}/branches/{branch_id}"
        )
        assert r2.status_code == 404

    def test_course_not_found(self, test_client: TestClient):
        r = test_client.get("/api/v1/courses/nonexistent-course/branches")
        assert r.status_code == 404


class TestBranchEvents:
    """Tests for branch event recording and listing."""

    def test_record_and_list_events(self, test_client: TestClient):
        _ensure_course(test_client)
        # Create a rule
        create_r = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/branches",
            json={"title": "Events rule", "conditions": []},
        )
        branch_id = create_r.json()["branchId"]

        # Record an event
        event_payload = {
            "learnerId": "learner-42",
            "matchedConditionIndex": 0,
            "targetPageId": "page-3",
            "contextSnapshot": {"score": 85},
        }
        r = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/branches/{branch_id}/events",
            json=event_payload,
        )
        assert r.status_code == 201
        data = r.json()
        assert data["eventId"]
        assert data["branchId"] == branch_id
        assert data["courseId"] == COURSE_ID
        assert data["learnerId"] == "learner-42"
        assert data["targetPageId"] == "page-3"
        assert data["contextSnapshot"] == {"score": 85}

        # List events
        r2 = test_client.get(
            f"/api/v1/courses/{COURSE_ID}/branches/{branch_id}/events"
        )
        assert r2.status_code == 200
        events = r2.json()
        assert len(events) >= 1
        assert any(e["learnerId"] == "learner-42" for e in events)

    def test_list_events_filter_by_learner(self, test_client: TestClient):
        _ensure_course(test_client)
        create_r = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/branches",
            json={"title": "Learner filter rule", "conditions": []},
        )
        branch_id = create_r.json()["branchId"]

        # Record events for two learners
        for lid in ["learner-A", "learner-B"]:
            test_client.post(
                f"/api/v1/courses/{COURSE_ID}/branches/{branch_id}/events",
                json={"learnerId": lid, "targetPageId": "p1"},
            )

        r = test_client.get(
            f"/api/v1/courses/{COURSE_ID}/branches/{branch_id}/events",
            params={"learnerId": "learner-A"},
        )
        assert r.status_code == 200
        events = r.json()
        assert all(e["learnerId"] == "learner-A" for e in events)

    def test_event_on_nonexistent_branch(self, test_client: TestClient):
        _ensure_course(test_client)
        r = test_client.post(
            f"/api/v1/courses/{COURSE_ID}/branches/no-such-branch/events",
            json={"targetPageId": "p1"},
        )
        assert r.status_code == 404
