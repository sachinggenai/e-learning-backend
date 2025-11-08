"""
Export endpoint tests
Test SCORM export functionality as specified in Phase 1 requirements
"""

import pytest
import json
import io
import zipfile
from fastapi.testclient import TestClient
from unittest.mock import patch, Mock


class TestExportEndpoints:
    """Test SCORM export endpoints"""

    def test_export_course_success(self, test_client: TestClient, sample_course_json: str):
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
        
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "Invalid course JSON format" in data["detail"]

    def test_export_course_missing_fields(self, test_client: TestClient):
        """Test export with missing required fields"""
        invalid_course = {
            "courseId": "",  # Empty courseId
            "templates": []  # No templates
        }
        
        request_data = {"course": json.dumps(invalid_course)}
        
        response = test_client.post("/api/v1/export", json=request_data)
        
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data

    def test_export_course_zip_content(self, test_client: TestClient, sample_course_json: str):
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
            assert "course.json" in file_names
            
            # Verify manifest content
            manifest_content = zip_file.read("imsmanifest.xml").decode('utf-8')
            assert "manifest" in manifest_content
            assert "JSON Test Course" in manifest_content  # Course title
            
            # Verify course.json content
            course_content = zip_file.read("course.json").decode('utf-8')
            course_data = json.loads(course_content)
            assert course_data["courseId"] == "json-course-001"

    def test_export_course_filename_format(self, test_client: TestClient, sample_course_json: str):
        """Test exported file has correct filename format"""
        request_data = {"course": sample_course_json}
        
        response = test_client.post("/api/v1/export", json=request_data)
        
        content_disposition = response.headers["content-disposition"]
        
        # Should include course ID in filename
        assert "json-course-001" in content_disposition
        assert ".zip" in content_disposition

    @patch('app.services.scorm_export.SCORMExportService')
    def test_export_course_service_error(self, mock_service, test_client: TestClient, sample_course_json: str):
        """Test export handles service errors gracefully"""
        # Mock service to raise an error
        mock_instance = Mock()
        mock_service.return_value = mock_instance
        mock_instance.generate_scorm_package.side_effect = Exception("Export failed")
        
        request_data = {"course": sample_course_json}
        
        response = test_client.post("/api/v1/export", json=request_data)
        
        assert response.status_code == 500
        data = response.json()
        assert "Export failed" in data["detail"]

    def test_validate_course_for_export_success(self, test_client: TestClient, sample_course_json: str):
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
        
        assert response.status_code == 400

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
        
        assert data["success"] is True
        assert data["export_id"] == export_id
        assert data["status"] == "completed"  # Phase 1: always completed

    def test_export_course_large_content(self, test_client: TestClient):
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
    def test_export_course_performance(self, test_client: TestClient, sample_course_json: str):
        """Test export performance meets Phase 1 requirements (<5s for 10 slides)"""
        import time
        
        request_data = {"course": sample_course_json}
        
        start_time = time.time()
        response = test_client.post("/api/v1/export", json=request_data)
        end_time = time.time()
        
        # Should complete within 5 seconds for small course
        assert (end_time - start_time) < 5.0
        assert response.status_code == 200

    def test_export_course_security_validation(self, test_client: TestClient):
        """Test export validates against malicious content"""
        malicious_course = {
            "courseId": "<script>alert('xss')</script>",
            "title": "Normal Title",
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
            "navigation": {"allowSkip": True, "showProgress": True, "lockProgression": False}
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

    def test_export_course_concurrent_exports(self, test_client: TestClient, sample_course_json: str):
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