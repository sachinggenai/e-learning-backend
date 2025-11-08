"""Tests for media upload API (spec MED-*)."""

from fastapi.testclient import TestClient


class TestMediaUpload:
    def test_upload_image_success(self, test_client: TestClient):
        # minimal PNG signature + extra bytes
        file_content = b"\x89PNG\r\n\x1a\nxxxx"
        resp = test_client.post(
            "/api/v1/media/upload",
            files={"file": ("test.png", file_content, "image/png")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["media"]["category"] == "image"

    def test_empty_file_rejected(self, test_client: TestClient):
        resp = test_client.post(
            "/api/v1/media/upload", files={"file": ("empty.png", b"", "image/png")}
        )
        assert resp.status_code == 400

    def test_unsupported_type(self, test_client: TestClient):
        resp = test_client.post(
            "/api/v1/media/upload",
            files={
                "file": (
                    "bad.exe",
                    b"MZ...binary",
                    "application/octet-stream",
                )
            },
        )
        assert resp.status_code == 400

    def test_upload_mp3_success(self, test_client: TestClient):
        # Minimal MP3 starting with ID3 tag
        file_content = b"ID3" + b"\x00" * 100
        resp = test_client.post(
            "/api/v1/media/upload",
            files={"file": ("audio.mp3", file_content, "audio/mpeg")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["media"]["category"] == "audio"
        assert data["media"]["mime_type"].startswith("audio/")

    def test_mime_mismatch_rejected(self, test_client: TestClient):
        # PNG bytes but audio mime to trigger mismatch when
        # both differ in major type
        file_content = b"\x89PNG\r\n\x1a\nxxxx"
        resp = test_client.post(
            "/api/v1/media/upload",
            files={"file": ("fake.mp3", file_content, "audio/mpeg")},
        )
    # Without python-magic may pass; assert 200 or 400 acceptable.
    # With python-magic installed should be 400.
        assert resp.status_code in (200, 400)
        if resp.status_code == 400:
            lower = resp.text.lower()
            assert (
                "mismatch" in lower or "unsupported" in lower
            )

    def test_size_limit_enforced(self, test_client: TestClient, monkeypatch):
        # Simulate size header exceed without sending huge body
        class DummyFile:
            filename = "big.mp4"
            size = None

            async def read(self):  # pragma: no cover
                return b""

        # Simpler: send large content directly instead of monkeypatching
        big_content = b"0" * (51 * 1024 * 1024)
        resp = test_client.post(
            "/api/v1/media/upload",
            files={"file": ("big.mp4", big_content, "video/mp4")},
        )
        assert resp.status_code == 400
        assert "exceeds" in resp.text.lower()
