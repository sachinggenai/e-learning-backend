import uuid

from fastapi.testclient import TestClient


def _setup_course_with_component(test_client: TestClient):
    course_id = f"analytics-course-{uuid.uuid4().hex[:8]}"
    course_response = test_client.post(
        "/api/v1/courses",
        json={
            "courseId": course_id,
            "title": "Analytics Learner Course",
            "description": "Learner analytics tests",
            "data": {},
        },
    )
    assert course_response.status_code == 201

    page_response = test_client.post(
        f"/api/v1/courses/{course_id}/pages",
        json={"title": "Page 1"},
    )
    assert page_response.status_code == 201
    page_id = page_response.json()["pageId"]

    comp_response = test_client.post(
        f"/api/v1/courses/{course_id}/pages/{page_id}/components",
        json={
            "componentType": "content-text",
            "data": {"content": "Hello"},
            "completionCriteria": {"type": "interaction"},
        },
    )
    assert comp_response.status_code == 201
    component_id = comp_response.json()["componentId"]
    return course_id, page_id, component_id


def test_analytics_summary_can_filter_by_learner(test_client: TestClient):
    course_id, page_id, component_id = _setup_course_with_component(test_client)

    for learner_id in ("learner-a", "learner-b", "learner-a"):
        response = test_client.post(
            f"/api/v1/courses/{course_id}/interactions",
            json={
                "pageId": page_id,
                "componentId": component_id,
                "interactionType": "view",
                "learnerId": learner_id,
                "completed": True,
                "data": {"score": 100, "maxScore": 100},
            },
        )
        assert response.status_code == 201

    all_summary = test_client.get(
        f"/api/v1/courses/{course_id}/analytics/summary"
    )
    assert all_summary.status_code == 200
    assert all_summary.json()["interactions"]["totalEvents"] == 3

    filtered_summary = test_client.get(
        f"/api/v1/courses/{course_id}/analytics/summary",
        params={"learnerId": "learner-a"},
    )
    assert filtered_summary.status_code == 200
    body = filtered_summary.json()
    assert body["interactions"]["totalEvents"] == 2
    assert body["interactions"]["filteredByLearnerId"] == "learner-a"
    assert body["interactions"]["distinctLearners"] == 1
    assert body["interactions"]["averageScore"] == 100.0


def test_manager_view_returns_learner_stats(test_client: TestClient):
    course_id, page_id, component_id = _setup_course_with_component(test_client)

    interactions = [
        ("learner-a", True, 100),
        ("learner-a", False, 50),
        ("learner-b", True, 90),
    ]
    for learner_id, completed, score in interactions:
        response = test_client.post(
            f"/api/v1/courses/{course_id}/interactions",
            json={
                "pageId": page_id,
                "componentId": component_id,
                "interactionType": "mcq-answer",
                "learnerId": learner_id,
                "completed": completed,
                "data": {"score": score, "maxScore": 100},
            },
        )
        assert response.status_code == 201

    manager_view = test_client.get(
        f"/api/v1/courses/{course_id}/analytics/manager-view"
    )
    assert manager_view.status_code == 200
    learner_stats = manager_view.json()["learnerStats"]
    assert len(learner_stats) == 2

    learner_a = next(row for row in learner_stats if row["learnerId"] == "learner-a")
    assert learner_a["eventCount"] == 2
    assert learner_a["completedEvents"] == 1
    assert learner_a["averageScore"] == 75.0

    filtered_view = test_client.get(
        f"/api/v1/courses/{course_id}/analytics/manager-view",
        params={"learnerId": "learner-b"},
    )
    assert filtered_view.status_code == 200
    filtered_stats = filtered_view.json()["learnerStats"]
    assert len(filtered_stats) == 1
    assert filtered_stats[0]["learnerId"] == "learner-b"