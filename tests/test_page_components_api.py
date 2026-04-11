import uuid

from fastapi.testclient import TestClient


def test_page_component_crud_and_reorder(test_client: TestClient):
    course_id = f"pc-course-{uuid.uuid4().hex[:8]}"
    course_response = test_client.post(
        "/api/v1/courses",
        json={
            "courseId": course_id,
            "title": "Page Component Course",
            "description": "CRUD coverage",
            "data": {},
        },
    )
    assert course_response.status_code == 201

    page_response = test_client.post(
        f"/api/v1/courses/{course_id}/pages",
        json={
            "title": "Page A",
            "components": [
                {
                    "componentType": "content-text",
                    "data": {"content": "One"},
                    "completionCriteria": {"type": "interaction"},
                },
                {
                    "componentType": "content-text",
                    "data": {"content": "Two"},
                    "completionCriteria": {"type": "interaction"},
                },
            ],
            "pageCompletion": {"strategy": "all"},
            "layout": {"preset": "single-column"},
        },
    )
    assert page_response.status_code == 201
    page_id = page_response.json()["pageId"]

    list_pages = test_client.get(f"/api/v1/courses/{course_id}/pages")
    assert list_pages.status_code == 200
    assert len(list_pages.json()) == 1

    list_components = test_client.get(
        f"/api/v1/courses/{course_id}/pages/{page_id}/components"
    )
    assert list_components.status_code == 200
    components = list_components.json()
    assert len(components) == 2
    component_ids = [components[0]["componentId"], components[1]["componentId"]]

    reorder_components = test_client.post(
        f"/api/v1/courses/{course_id}/pages/{page_id}/components/reorder",
        json={"orderedIds": list(reversed(component_ids))},
    )
    assert reorder_components.status_code == 200
    reordered = reorder_components.json()
    assert reordered[0]["componentId"] == component_ids[1]

    update_page = test_client.patch(
        f"/api/v1/courses/{course_id}/pages/{page_id}",
        json={"title": "Page A Updated", "pageCompletion": {"strategy": "any"}},
    )
    assert update_page.status_code == 200
    assert update_page.json()["title"] == "Page A Updated"

    update_component = test_client.patch(
        f"/api/v1/courses/{course_id}/pages/{page_id}/components/{component_ids[0]}",
        json={"data": {"content": "Updated"}},
    )
    assert update_component.status_code == 200
    assert update_component.json()["data"]["content"] == "Updated"

    add_component = test_client.post(
        f"/api/v1/courses/{course_id}/pages/{page_id}/components",
        json={
            "componentType": "content-text",
            "data": {"content": "Three"},
            "completionCriteria": {"type": "view"},
        },
    )
    assert add_component.status_code == 201
    new_component_id = add_component.json()["componentId"]

    delete_component = test_client.delete(
        f"/api/v1/courses/{course_id}/pages/{page_id}/components/{new_component_id}"
    )
    assert delete_component.status_code == 204

    final_components = test_client.get(
        f"/api/v1/courses/{course_id}/pages/{page_id}/components"
    )
    assert final_components.status_code == 200
    assert len(final_components.json()) == 2

    delete_page = test_client.delete(f"/api/v1/courses/{course_id}/pages/{page_id}")
    assert delete_page.status_code == 204

    pages_after_delete = test_client.get(f"/api/v1/courses/{course_id}/pages")
    assert pages_after_delete.status_code == 200
    assert pages_after_delete.json() == []