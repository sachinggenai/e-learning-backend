"""Tests for Analytics & Reporting API.

Covers 3 endpoints:
  GET /courses/{courseId}/analytics/summary
  GET /courses/{courseId}/analytics/skills
  GET /courses/{courseId}/analytics/manager-view
"""
import pytest
from fastapi.testclient import TestClient

COURSE_ID = "analytics-test-course"


def _ensure_course(client: TestClient, course_id: str = COURSE_ID):
    r = client.post(
        "/api/v1/courses",
        json={
            "courseId": course_id,
            "title": "Analytics Test Course",
            "description": "For analytics tests",
            "data": {"pages": []},
        },
    )
    assert r.status_code in (201, 400)


class TestAnalyticsSummary:

    def test_summary_success(self, test_client: TestClient):
        _ensure_course(test_client)
        r = test_client.get(
            f"/api/v1/courses/{COURSE_ID}/analytics/summary"
        )
        assert r.status_code == 200
        data = r.json()
        assert data["courseId"] == COURSE_ID
        assert "title" in data
        assert "structure" in data
        assert "totalPages" in data["structure"]
        assert "totalComponents" in data["structure"]
        assert "scoringComponents" in data["structure"]
        assert "scoring" in data
        assert "passingScore" in data["scoring"]
        assert "interactions" in data
        assert "totalEvents" in data["interactions"]
        assert "byType" in data["interactions"]
        assert "generatedAt" in data

    def test_summary_course_not_found(self, test_client: TestClient):
        r = test_client.get(
            "/api/v1/courses/nonexistent-analytics/analytics/summary"
        )
        assert r.status_code == 404


class TestAnalyticsSkills:

    def test_skills_success(self, test_client: TestClient):
        _ensure_course(test_client)
        r = test_client.get(
            f"/api/v1/courses/{COURSE_ID}/analytics/skills"
        )
        assert r.status_code == 200
        data = r.json()
        assert data["courseId"] == COURSE_ID
        assert "skills" in data
        assert isinstance(data["skills"], list)
        assert "totalSkills" in data
        assert "generatedAt" in data

    def test_skills_course_not_found(self, test_client: TestClient):
        r = test_client.get(
            "/api/v1/courses/nonexistent-analytics/analytics/skills"
        )
        assert r.status_code == 404


class TestAnalyticsManagerView:

    def test_manager_view_success(self, test_client: TestClient):
        _ensure_course(test_client)
        r = test_client.get(
            f"/api/v1/courses/{COURSE_ID}/analytics/manager-view"
        )
        assert r.status_code == 200
        data = r.json()
        assert data["courseId"] == COURSE_ID
        assert "courseTitle" in data
        assert "courseStatus" in data
        assert "pages" in data
        assert isinstance(data["pages"], list)
        assert "totalPages" in data
        assert "totalInteractionEvents" in data
        assert "generatedAt" in data

    def test_manager_view_course_not_found(self, test_client: TestClient):
        r = test_client.get(
            "/api/v1/courses/nonexistent-analytics/analytics/manager-view"
        )
        assert r.status_code == 404
