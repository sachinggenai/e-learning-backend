from fastapi.testclient import TestClient


def test_component_registry_endpoints(test_client: TestClient):
    list_response = test_client.get("/api/v1/components")
    assert list_response.status_code == 200
    list_body = list_response.json()
    assert "items" in list_body
    assert "schemaVersion" in list_body

    categories_response = test_client.get("/api/v1/components/categories")
    assert categories_response.status_code == 200
    categories_body = categories_response.json()
    assert "categories" in categories_body

    search_response = test_client.get(
        "/api/v1/components/search",
        params={"q": "mcq"},
    )
    assert search_response.status_code == 200
    search_body = search_response.json()
    assert "items" in search_body

    # If seeded data exists, validate detail + ETag behavior.
    if list_body["items"]:
        type_id = list_body["items"][0]["typeId"]
        detail_response = test_client.get(f"/api/v1/components/{type_id}")
        assert detail_response.status_code == 200
        assert "etag" in detail_response.json()

        etag = detail_response.headers.get("ETag")
        assert etag
        not_modified = test_client.get(
            f"/api/v1/components/{type_id}",
            headers={"If-None-Match": etag},
        )
        assert not_modified.status_code == 304

    missing_detail = test_client.get("/api/v1/components/non-existent-type")
    assert missing_detail.status_code == 404