"""Negative test coverage for Templates API (spec TPL-NEG-*)."""

from fastapi.testclient import TestClient


def make_course(client: TestClient):
    r = client.post(
        "/api/v1/courses",
        json={"courseId": "tpl-neg", "title": "Tpl Neg", "data": {}},
    )
    assert r.status_code == 201
    return r.json()["id"]


def create_template(client: TestClient, course_id: int, template_id="welcome"):
    return client.post(
        f"/api/v1/courses/{course_id}/templates",
        json={
            "templateId": template_id,
            "type": "welcome",
            "title": "Welcome",
            "data": {"content": "hi"},
        },
    )


class TestTemplateNegative:
    def test_duplicate_template_id(self, test_client: TestClient):
        cid = make_course(test_client)
        r1 = create_template(test_client, cid, "dup-temp")
        assert r1.status_code == 201
        r2 = create_template(test_client, cid, "dup-temp")
        assert r2.status_code == 400

    def test_invalid_title_length(self, test_client: TestClient):
        cid = make_course(test_client)
        long_title = "x" * 205
        resp = test_client.post(
            f"/api/v1/courses/{cid}/templates",
            json={
                "templateId": "t-long",
                "type": "welcome",
                "title": long_title,
                "data": {},
            },
        )
        assert resp.status_code == 422

    def test_get_missing_template(self, test_client: TestClient):
        cid = make_course(test_client)
        resp = test_client.get(f"/api/v1/courses/{cid}/templates/99999")
        assert resp.status_code == 404

    def test_update_missing_template(self, test_client: TestClient):
        cid = make_course(test_client)
        resp = test_client.patch(
            f"/api/v1/courses/{cid}/templates/99999", json={"title": "New"}
        )
        assert resp.status_code == 404

    def test_delete_missing_template(self, test_client: TestClient):
        cid = make_course(test_client)
        resp = test_client.delete(f"/api/v1/courses/{cid}/templates/99999")
        assert resp.status_code == 404
