from fastapi.testclient import TestClient
import uuid


def _create_course_with_mcq_component(
    test_client: TestClient,
) -> tuple[str, str, str]:
    course_id = f"score-course-{uuid.uuid4().hex[:8]}"
    course_response = test_client.post(
        "/api/v1/courses",
        json={
            "courseId": course_id,
            "title": "Scoring Course",
            "description": "Scoring test course",
            "data": {},
        },
    )
    assert course_response.status_code == 201

    page_response = test_client.post(
        f"/api/v1/courses/{course_id}/pages",
        json={
            "title": "Assessment Page",
        },
    )
    assert page_response.status_code == 201
    page_id = page_response.json()["pageId"]

    component_response = test_client.post(
        f"/api/v1/courses/{course_id}/pages/{page_id}/components",
        json={
            "componentType": "mcq",
            "data": {
                "questions": [
                    {
                        "id": "q1",
                        "question": "Capital of France?",
                        "options": [
                            {
                                "id": "paris",
                                "text": "Paris",
                                "isCorrect": True,
                            },
                            {
                                "id": "london",
                                "text": "London",
                                "isCorrect": False,
                            },
                        ],
                    }
                ]
            },
            "completionCriteria": {"type": "score", "threshold": 100},
        },
    )
    assert component_response.status_code == 201
    component_id = component_response.json()["componentId"]
    return course_id, page_id, component_id


def _create_course_with_completion_component(
    test_client: TestClient,
    *,
    component_type: str,
    component_data: dict,
    completion_criteria: dict,
) -> tuple[str, str, str]:
    course_id = f"completion-course-{uuid.uuid4().hex[:8]}"
    course_response = test_client.post(
        "/api/v1/courses",
        json={
            "courseId": course_id,
            "title": "Completion Course",
            "description": "Completion test course",
            "data": {},
        },
    )
    assert course_response.status_code == 201

    page_response = test_client.post(
        f"/api/v1/courses/{course_id}/pages",
        json={
            "title": "Completion Page",
            "pageCompletion": {"strategy": "all"},
        },
    )
    assert page_response.status_code == 201
    page_id = page_response.json()["pageId"]

    component_response = test_client.post(
        f"/api/v1/courses/{course_id}/pages/{page_id}/components",
        json={
            "componentType": component_type,
            "data": component_data,
            "completionCriteria": completion_criteria,
        },
    )
    assert component_response.status_code == 201
    return course_id, page_id, component_response.json()["componentId"]


def test_calculate_score_uses_persisted_mcq_answers(
    test_client: TestClient,
):
    course_id, _, component_id = _create_course_with_mcq_component(test_client)

    response = test_client.post(
        f"/api/v1/courses/{course_id}/scoring/calculate",
        json={
            "answers": [
                {
                    "componentId": component_id,
                    "componentType": "mcq",
                    "responses": [
                        {
                            "questionId": "q1",
                            "selectedOptionIds": ["paris"],
                        }
                    ],
                }
            ],
            "attemptNumber": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["totalScore"] == 100
    assert body["maxScore"] == 100
    assert body["percentage"] == 100
    assert body["passed"] is True
    assert body["componentResults"][0]["questionResults"][0]["correct"] is True


def test_calculate_score_returns_zero_for_incorrect_answer(
    test_client: TestClient,
):
    course_id, _, component_id = _create_course_with_mcq_component(test_client)

    response = test_client.post(
        f"/api/v1/courses/{course_id}/scoring/calculate",
        json={
            "answers": [
                {
                    "componentId": component_id,
                    "componentType": "mcq",
                    "responses": [
                        {
                            "questionId": "q1",
                            "selectedOptionIds": ["london"],
                        }
                    ],
                }
            ],
            "attemptNumber": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["totalScore"] == 0
    assert body["percentage"] == 0
    assert body["passed"] is False
    assert (
        body["componentResults"][0]["questionResults"][0]["correct"]
        is False
    )


def test_page_completion_submission_updates_read_models(
    test_client: TestClient,
):
    course_id, page_id, component_id = (
        _create_course_with_completion_component(
            test_client,
            component_type="content-text",
            component_data={"content": "Read this"},
            completion_criteria={"type": "interaction"},
        )
    )

    record_response = test_client.post(
        f"/api/v1/courses/{course_id}/pages/{page_id}/completion",
        json={
            "componentStates": [
                {
                    "componentId": component_id,
                    "completed": True,
                }
            ]
        },
    )
    assert record_response.status_code == 200
    assert record_response.json()["completed"] is True

    page_response = test_client.get(
        f"/api/v1/courses/{course_id}/pages/{page_id}/completion"
    )
    assert page_response.status_code == 200
    assert page_response.json()["completed"] is True
    assert page_response.json()["components"][0]["completed"] is True

    course_response = test_client.get(
        f"/api/v1/courses/{course_id}/completion"
    )
    assert course_response.status_code == 200
    assert course_response.json()["status"] == "completed"
    assert course_response.json()["overallProgress"] == 100.0


def test_interaction_score_updates_completion_threshold(
    test_client: TestClient,
):
    course_id, page_id, component_id = (
        _create_course_with_completion_component(
            test_client,
            component_type="mcq",
            component_data={
                "questions": [
                    {
                        "id": "q1",
                        "question": "Capital of Spain?",
                        "options": [
                            {
                                "id": "madrid",
                                "text": "Madrid",
                                "isCorrect": True,
                            },
                            {
                                "id": "rome",
                                "text": "Rome",
                                "isCorrect": False,
                            },
                        ],
                    }
                ]
            },
            completion_criteria={"type": "score", "threshold": 80},
        )
    )

    interaction_response = test_client.post(
        f"/api/v1/courses/{course_id}/interactions",
        json={
            "pageId": page_id,
            "componentId": component_id,
            "interactionType": "mcq-answer",
            "completed": True,
            "data": {
                "score": 90,
                "maxScore": 100,
                "isCorrect": True,
            },
        },
    )
    assert interaction_response.status_code == 201

    page_response = test_client.get(
        f"/api/v1/courses/{course_id}/pages/{page_id}/completion"
    )
    assert page_response.status_code == 200
    assert page_response.json()["completed"] is True
    assert page_response.json()["components"][0]["completed"] is True
