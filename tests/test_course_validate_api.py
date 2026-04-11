from datetime import datetime

from fastapi.testclient import TestClient


def test_validate_course_returns_dynamic_timestamp(test_client: TestClient):
    response = test_client.post(
        "/api/v1/courses/validate",
        json={
            "courseData": {
                "courseId": "page-validate-001",
                "title": "Page Validation",
                "pages": [
                    {
                        "id": "p1",
                        "title": "Welcome",
                        "templateType": "welcome",
                        "content": {"title": "Hello"},
                    }
                ],
            }
        },
    )
    assert response.status_code == 200
    timestamp = response.json()["timestamp"]
    # ISO string parse should succeed and should no longer be hardcoded.
    datetime.fromisoformat(timestamp)
    assert timestamp != "2024-01-01T00:00:00Z"


def test_validate_course_checks_export_model_compatibility(
    test_client: TestClient,
):
    response = test_client.post(
        "/api/v1/courses/validate",
        json={
            "courseData": {
                "courseId": "template-validate-001",
                "title": "Template Validation",
                "pages": [
                    {
                        "id": "p1",
                        "title": "Placeholder",
                        "templateType": "content-text",
                        "content": {"body": "Page based payload"},
                    }
                ],
                "templates": [
                    {
                        "id": "t1",
                        "type": "mcq",
                        "title": "Invalid MCQ",
                        "order": 0,
                        "data": {
                            "content": "No questions included"
                        },
                    }
                ],
            }
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert any(
        issue["id"].startswith("export-compat-")
        for issue in body["errors"]
    )