import uuid

from fastapi.testclient import TestClient


def test_template_crud_and_reorder(test_client: TestClient):
    course_id = f"tpl-course-{uuid.uuid4().hex[:8]}"
    course_payload = {
        "courseId": course_id,
        "title": "Templates Course",
        "description": "With templates",
        "data": {"templates": []},
    }
    rc = test_client.post("/api/v1/courses", json=course_payload)
    assert rc.status_code == 201, rc.text

    t1 = {
        "templateId": "welcome1",
        "type": "welcome",
        "title": "Welcome 1",
        "data": {"content": "Hi"},
    }
    r1 = test_client.post(f"/api/v1/courses/{course_id}/templates", json=t1)
    assert r1.status_code == 201, r1.text

    t2 = {
        "templateId": "content1",
        "type": "content-text",
        "title": "Content 1",
        "data": {"content": "Body"},
    }
    r2 = test_client.post(f"/api/v1/courses/{course_id}/templates", json=t2)
    assert r2.status_code == 201, r2.text

    lst = test_client.get(f"/api/v1/courses/{course_id}/templates")
    assert lst.status_code == 200
    templates = lst.json()
    assert len(templates) == 2
    ids = [templates[0]["id"], templates[1]["id"]]

    reorder_payload = {"orderedIds": list(reversed(ids))}
    rr = test_client.post(
        f"/api/v1/courses/{course_id}/templates/reorder",
        json=reorder_payload,
    )
    assert rr.status_code == 200
    reordered = rr.json()
    assert reordered[0]["id"] == ids[1]
    assert reordered[1]["id"] == ids[0]

    upd = test_client.patch(
        f"/api/v1/courses/{course_id}/templates/{ids[0]}",
        json={"title": "Updated Title"},
    )
    assert upd.status_code == 200
    assert upd.json()["title"] == "Updated Title"

    rc2 = test_client.get(f"/api/v1/courses/{course_id}")
    assert rc2.status_code == 200
    course_after = rc2.json()
    snapshot = course_after["data"]["templates"]
    assert len(snapshot) == 2
    assert snapshot[0]["id"] in {"welcome1", "content1"}

    delr = test_client.delete(
        f"/api/v1/courses/{course_id}/templates/{ids[1]}"
    )
    assert delr.status_code == 204

    lst2 = test_client.get(f"/api/v1/courses/{course_id}/templates")
    assert lst2.status_code == 200
    assert len(lst2.json()) == 1

    rc3 = test_client.get(f"/api/v1/courses/{course_id}")
    assert rc3.status_code == 200
    assert len(rc3.json()["data"]["templates"]) == 1
