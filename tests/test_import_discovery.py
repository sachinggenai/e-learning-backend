import io
import json
import zipfile

from fastapi.testclient import TestClient


def _build_import_zip(payload: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        payload_json = json.dumps(payload)
        zf.writestr("course.js", f"const courseData = {payload_json};")
    return buffer.getvalue()


def test_import_commit_persists_course_and_templates(
    test_client: TestClient,
):
    payload = {
        "courseId": "import-course-001",
        "title": "Imported Course",
        "description": "Imported through API",
        "templates": [
            {
                "id": "welcome-001",
                "type": "content-text",
                "title": "Welcome",
                "data": {"content": "Hello learners"},
            },
            {
                "id": "quiz-001",
                "type": "mcq",
                "title": "Knowledge Check",
                "data": {
                    "content": "Choose one answer",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "2 + 2 = ?",
                            "options": [
                                {
                                    "id": "a",
                                    "text": "4",
                                    "isCorrect": True,
                                },
                                {
                                    "id": "b",
                                    "text": "5",
                                    "isCorrect": False,
                                },
                            ],
                        }
                    ],
                },
            },
        ],
    }
    zip_bytes = _build_import_zip(payload)

    analyze_response = test_client.post(
        "/api/v1/imports/analyze",
        files={
            "file": (
                "import-course.zip",
                zip_bytes,
                "application/zip",
            )
        },
    )
    assert analyze_response.status_code == 200
    job_id = analyze_response.json()["job_id"]

    preview_response = test_client.get(f"/api/v1/imports/jobs/{job_id}/preview")
    assert preview_response.status_code == 200
    assert preview_response.json()["status"] == "analyzed"

    status_response_before_commit = test_client.get(f"/api/v1/imports/jobs/{job_id}")
    assert status_response_before_commit.status_code == 200
    assert status_response_before_commit.json()["status"] == "analyzed"

    commit_response = test_client.post(
        f"/api/v1/imports/jobs/{job_id}/commit"
    )
    assert commit_response.status_code == 200
    assert commit_response.json()["course_id"] == "import-course-001"

    course_response = test_client.get("/api/v1/courses/import-course-001")
    assert course_response.status_code == 200
    course_body = course_response.json()
    assert course_body["courseId"] == "import-course-001"
    assert course_body["title"] == "Imported Course"
    assert len(course_body["data"]["templates"]) == 2
    assert course_body["data"]["importMeta"]["jobId"] == job_id

    template_response = test_client.get(
        f"/api/v1/courses/{course_body['courseId']}/templates"
    )
    assert template_response.status_code == 200
    templates = template_response.json()
    assert len(templates) == 2
    assert templates[0]["templateId"] == "welcome-001"
    assert templates[1]["templateId"] == "quiz-001"

    status_response = test_client.get(f"/api/v1/imports/jobs/{job_id}")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "committed"


def test_import_commit_rejects_duplicate_course_id(test_client: TestClient):
    existing = test_client.post(
        "/api/v1/courses",
        json={
            "courseId": "existing-import-course",
            "title": "Existing",
            "description": "Already present",
            "data": {"templates": []},
        },
    )
    assert existing.status_code == 201

    zip_bytes = _build_import_zip(
        {
            "courseId": "existing-import-course",
            "title": "Conflicting Import",
            "templates": [],
        }
    )

    analyze_response = test_client.post(
        "/api/v1/imports/analyze",
        files={
            "file": (
                "conflicting-import.zip",
                zip_bytes,
                "application/zip",
            )
        },
    )
    assert analyze_response.status_code == 200
    job_id = analyze_response.json()["job_id"]

    commit_response = test_client.post(
        f"/api/v1/imports/jobs/{job_id}/commit"
    )
    assert commit_response.status_code == 400
    assert "already exists" in commit_response.json()["detail"]
