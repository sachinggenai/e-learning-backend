"""Negative scenarios for export endpoints (EXP-004/005)."""

import json

from fastapi.testclient import TestClient


class TestExportNegative:
    def test_export_invalid_json_structure(self, test_client: TestClient):
        # Missing required fields like courseId/title/templates
        payload = {"courseData": "{\"courseId\":\"\", \"templates\": []}"}
        resp = test_client.post("/api/v1/export", json=payload)
        assert resp.status_code in (400, 422)

    def test_validate_invalid_course(self, test_client: TestClient):
        payload = {"courseData": "{\"courseId\":\"bad\"}"}
        resp = test_client.post("/api/v1/export/validate", json=payload)
        assert resp.status_code in (400, 422)

    def test_export_non_sequential_order_error(self, test_client: TestClient):
        # Orders 0,2 (gap at 1) should trigger 400 under new enforcement
        course = {
            "courseId": "order-gap-001",
            "title": "Order Gap",
            "author": "Tester",
            "version": "1.0.0",
            "createdAt": "2025-01-01T00:00:00Z",
            "updatedAt": "2025-01-01T00:00:00Z",
            "templates": [
                {
                    "id": "t0",
                    "type": "content-text",
                    "title": "T0",
                    "order": 0,
                    "data": {"content": "A"},
                },
                {
                    "id": "t2",
                    "type": "content-text",
                    "title": "T2",
                    "order": 2,
                    "data": {"content": "B"},
                },
            ],
            "assets": [],
            "navigation": {
                "allowSkip": True,
                "showProgress": True,
                "lockProgression": False,
            },
        }
        resp = test_client.post(
            "/api/v1/export", json={"course": json.dumps(course)}
        )
        assert resp.status_code == 400
        detail = resp.json().get("detail", "")
        assert "contiguous" in detail.lower()
