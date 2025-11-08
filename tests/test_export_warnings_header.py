import json
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app as real_app


@pytest.mark.asyncio
async def test_export_warnings_header(monkeypatch):
    # Force feature flag
    monkeypatch.setenv('EXPORT_HEADERS', '1')

    transport = ASGITransport(app=real_app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        payload = {
            "course": {
                "courseId": "c_warn",
                "title": "Hi",  # Short title triggers warning
                "author": "Test",
                "templates": [],
                "assets": []
            }
        }
        r = await client.post('/api/v1/export', json=payload)
        assert r.status_code == 200, r.text
        # Validate headers
        assert 'X-Course-Hash' in r.headers
        if 'X-Export-Warnings' in r.headers:
            warnings = json.loads(r.headers['X-Export-Warnings'])
            assert any('short' in w.lower() for w in warnings)
        else:
            pytest.fail('Expected X-Export-Warnings header to be present')
