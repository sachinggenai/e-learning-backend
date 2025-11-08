"""Negative & edge case tests for Courses API (spec CRS-NEG-*)."""

from fastapi.testclient import TestClient


def create_course(client: TestClient, course_id: str = "neg-course-1"):
    return client.post(
        "/api/v1/courses",
        json={
            "courseId": course_id,
            "title": "Temp Title",
            "description": "Desc",
            "data": {"pages": []},
        },
    )


class TestCourseNegative:
    def test_duplicate_course_id(self, test_client: TestClient):
        r1 = create_course(test_client, "dup-001")
        assert r1.status_code == 201
        r2 = create_course(test_client, "dup-001")
        assert r2.status_code == 400
        assert "courseId already exists" in r2.text

    def test_missing_title(self, test_client: TestClient):
        resp = test_client.post(
            "/api/v1/courses",
            json={"courseId": "no-title", "description": "d", "data": {}},
        )
        assert resp.status_code == 422

    def test_invalid_status_update(self, test_client: TestClient):
        r = create_course(test_client, "status-invalid")
        cid = r.json()["id"]
        # not allowed pattern (invalid status value)
        upd = test_client.patch(f"/api/v1/courses/{cid}", json={"status": "archived"})
        assert upd.status_code == 422

    def test_get_missing_course(self, test_client: TestClient):
        resp = test_client.get("/api/v1/courses/999999")
        assert resp.status_code == 404

    def test_delete_missing_course(self, test_client: TestClient):
        resp = test_client.delete("/api/v1/courses/999999")
        assert resp.status_code == 404

    def test_description_too_long(self, test_client: TestClient):
        long_desc = "x" * 600
        resp = test_client.post(
            "/api/v1/courses",
            json={
                "courseId": "long-desc",
                "title": "Title",
                "description": long_desc,
                "data": {},
            },
        )
        assert resp.status_code == 422
