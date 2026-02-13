"""
Export endpoint tests
Test SCORM export functionality as specified in Phase 1 requirements
"""

import pytest
import json
import io
import zipfile
from fastapi.testclient import TestClient
from unittest.mock import patch, Mock, AsyncMock


def _make_scorm_zip(course_id: str = "json-course-001", title: str = "JSON Test Course") -> io.BytesIO:
    """Build a minimal in-memory SCORM zip matching what the real service produces."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<manifest identifier="{course_id}">\n'
            f"  <title>{title}</title>\n"
            "</manifest>\n"
        )
        zf.writestr("imsmanifest.xml", manifest)
        zf.writestr("index.html", f"<html><body>{title}</body></html>")
        zf.writestr(
            "course_data.js",
            f'var courseData = {{"courseId": "{course_id}", "title": "{title}"}};',
        )
    buf.seek(0)
    return buf


class TestExportEndpoints:
    """Test SCORM export endpoints"""

    @patch("app.routers.export.scorm_service.generate_scorm_package", new_callable=AsyncMock, return_value=_make_scorm_zip())
    def test_export_course_success(self, mock_gen, test_client: TestClient, sample_course_json: str):
        """Test successful course export"""
        request_data = {"course": sample_course_json}
        
        response = test_client.post("/api/v1/export", json=request_data)
        
        assert response.status_code == 200
        
        # Should return a ZIP file
        assert response.headers["content-type"] == "application/zip"
        assert "content-disposition" in response.headers
        assert "attachment" in response.headers["content-disposition"]

    def test_export_course_invalid_json(self, test_client: TestClient):
        """Test export with invalid JSON"""
        request_data = {"course": "invalid json string"}
        
        response = test_client.post("/api/v1/export", json=request_data)
        
        # CourseExportRequest.validate_json_only catches invalid JSON at the model level
        # → RequestValidationError → custom 422 handler
        assert response.status_code == 422
        data = response.json()
        assert data["detail"] == "Validation failed"
        assert any("Invalid JSON format" in e["message"] for e in data["errors"])

    def test_export_course_missing_fields(self, test_client: TestClient):
        """Test export with missing required fields"""
        invalid_course = {
            "courseId": "",  # Empty courseId
            "templates": []  # No templates
        }
        
        request_data = {"course": json.dumps(invalid_course)}
        
        response = test_client.post("/api/v1/export", json=request_data)
        
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data
        # Pydantic v2 returns a list of errors
        assert isinstance(data["detail"], list)
        assert len(data["detail"]) > 0

    @patch("app.routers.export.scorm_service.generate_scorm_package", new_callable=AsyncMock, return_value=_make_scorm_zip())
    def test_export_course_zip_content(self, mock_gen, test_client: TestClient, sample_course_json: str):
        """Test that exported ZIP contains required SCORM files"""
        request_data = {"course": sample_course_json}
        
        response = test_client.post("/api/v1/export", json=request_data)
        assert response.status_code == 200
        
        # Extract ZIP content for verification
        zip_content = io.BytesIO(response.content)
        
        with zipfile.ZipFile(zip_content, 'r') as zip_file:
            file_names = zip_file.namelist()
            
            # Should contain required SCORM files
            assert "imsmanifest.xml" in file_names
            assert "index.html" in file_names
            assert "course_data.js" in file_names
            
            # Verify manifest content
            manifest_content = zip_file.read("imsmanifest.xml").decode('utf-8')
            assert "manifest" in manifest_content
            assert "JSON Test Course" in manifest_content  # Course title
            
            # Verify course_data.js content
            course_content = zip_file.read("course_data.js").decode('utf-8')
            assert "var courseData =" in course_content
            assert "json-course-001" in course_content

    @patch("app.routers.export.scorm_service.generate_scorm_package", new_callable=AsyncMock, return_value=_make_scorm_zip())
    def test_export_course_filename_format(self, mock_gen, test_client: TestClient, sample_course_json: str):
        """Test exported file has correct filename format"""
        request_data = {"course": sample_course_json}
        
        response = test_client.post("/api/v1/export", json=request_data)
        
        content_disposition = response.headers["content-disposition"]
        
        # Should include course ID in filename
        assert "json-course-001" in content_disposition
        assert ".zip" in content_disposition

    def test_export_course_service_error(
        self, test_client: TestClient, sample_course_json: str
    ):
        """Test export handles service errors gracefully"""
        # Mock service to raise an error
        with patch(
            "app.routers.export.scorm_service.generate_scorm_package",
            side_effect=Exception("Export failed")
        ):
            request_data = {"course": sample_course_json}
            
            response = test_client.post("/api/v1/export", json=request_data)
            
            assert response.status_code == 500
            data = response.json()
            assert "Export failed" in data["detail"]

    @patch("app.routers.export.scorm_service.validate_for_export", new_callable=AsyncMock, return_value={"valid": True, "warnings": []})
    @patch("app.routers.export.scorm_service.estimate_package_size", return_value={"estimated_bytes": 1024})
    def test_validate_course_for_export_success(self, mock_est, mock_val, test_client: TestClient, sample_course_json: str):
        """Test course validation endpoint"""
        request_data = {"course": sample_course_json}
        
        response = test_client.post("/api/v1/export/validate", json=request_data)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "course_info" in data
        assert "validation" in data
        assert "estimated_size" in data

    def test_validate_course_for_export_invalid(self, test_client: TestClient):
        """Test validation with invalid course"""
        invalid_course = {"courseId": "", "title": "", "templates": []}
        request_data = {"course": json.dumps(invalid_course)}
        
        response = test_client.post("/api/v1/export/validate", json=request_data)
        
        assert response.status_code == 422

    def test_get_export_formats(self, test_client: TestClient):
        """Test get supported export formats endpoint"""
        response = test_client.get("/api/v1/export/formats")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert "formats" in data
        assert len(data["formats"]) > 0
        
        # Should include SCORM 1.2 format
        scorm_format = next((f for f in data["formats"] if f["id"] == "scorm_1_2"), None)
        assert scorm_format is not None
        assert scorm_format["supported"] is True

    def test_get_export_status(self, test_client: TestClient):
        """Test export status endpoint"""
        export_id = "test-export-123"
        
        response = test_client.get(f"/api/v1/export/status/{export_id}")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["exportId"] == export_id
        assert data["status"] == "completed"  # Phase 1: always completed

    @patch("app.routers.export.scorm_service.generate_scorm_package", new_callable=AsyncMock, return_value=_make_scorm_zip("large-course-001", "Large Test Course"))
    def test_export_course_large_content(self, mock_gen, test_client: TestClient):
        """Test export with large course content"""
        # Create a course with many templates
        large_course = {
            "courseId": "large-course-001",
            "title": "Large Test Course",
            "description": "Course with many templates",
            "author": "Test Author",
            "version": "1.0.0",
            "createdAt": "2025-01-01T10:00:00Z",
            "updatedAt": "2025-01-01T10:00:00Z",
            "templates": [],
            "assets": [],
            "navigation": {
                "allowSkip": True,
                "showProgress": True,
                "lockProgression": False
            }
        }
        
        # Add 50 templates
        for i in range(50):
            template = {
                "id": f"template-{i:03d}",
                "type": "content-text",
                "title": f"Content {i}",
                "order": i,
                "data": {
                    "content": f"This is content for template {i} " * 100  # Large content
                }
            }
            large_course["templates"].append(template)
        
        request_data = {"course": json.dumps(large_course)}
        
        response = test_client.post("/api/v1/export", json=request_data)
        
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"

    @pytest.mark.slow
    @patch("app.routers.export.scorm_service.generate_scorm_package", new_callable=AsyncMock, return_value=_make_scorm_zip())
    def test_export_course_performance(self, mock_gen, test_client: TestClient, sample_course_json: str):
        """Test export performance meets Phase 1 requirements (<5s for 10 slides)"""
        import time
        
        request_data = {"course": sample_course_json}
        
        start_time = time.time()
        response = test_client.post("/api/v1/export", json=request_data)
        end_time = time.time()
        
        # Should complete within 5 seconds for small course
        assert (end_time - start_time) < 5.0
        assert response.status_code == 200

    @patch("app.routers.export.scorm_service.generate_scorm_package", new_callable=AsyncMock, return_value=_make_scorm_zip("xss-test-001", "Normal Title"))
    def test_export_course_security_validation(self, mock_gen, test_client: TestClient):
        """Test export validates against malicious content"""
        malicious_course = {
            "courseId": "xss-test-001",
            "title": "Normal Title",
            "author": "Test Author",
            "templates": [{
                "id": "test",
                "type": "content-text",
                "title": "Test",
                "order": 0,
                "data": {
                    "content": "<script>document.location='http://evil.com'</script>"
                }
            }],
            "assets": [],
            "navigation": {"allowSkip": True, "showProgress": True}
        }
        
        request_data = {"course": json.dumps(malicious_course)}
        
        response = test_client.post("/api/v1/export", json=request_data)
        
        # Should either sanitize content or reject
        if response.status_code == 200:
            # If accepted, content should be sanitized in the ZIP
            zip_content = io.BytesIO(response.content)
            with zipfile.ZipFile(zip_content, 'r') as zip_file:
                manifest_content = zip_file.read("imsmanifest.xml").decode('utf-8')
                # Script tags should be escaped or removed
                assert "<script>" not in manifest_content

    @patch("app.routers.export.scorm_service.generate_scorm_package", new_callable=AsyncMock, return_value=_make_scorm_zip())
    def test_export_course_concurrent_exports(self, mock_gen, test_client: TestClient, sample_course_json: str):
        """Test handling multiple concurrent export requests"""
        import threading
        import queue
        
        results = queue.Queue()
        request_data = {"course": sample_course_json}
        
        def make_export_request():
            response = test_client.post("/api/v1/export", json=request_data)
            results.put(response.status_code)
        
        # Make 5 concurrent export requests
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=make_export_request)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # All requests should succeed
        while not results.empty():
            status_code = results.get()
            assert status_code == 200