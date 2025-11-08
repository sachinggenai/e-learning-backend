"""
Health endpoint tests
Test the health check functionality as specified in Phase 1 requirements
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch


class TestHealthEndpoints:
    """Test health check endpoints"""

    def test_health_check_success(self, test_client: TestClient):
        """Test basic health check endpoint returns success"""
        response = test_client.get("/api/v1/health")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify required fields
        assert "status" in data
        assert "timestamp" in data
        assert "uptime" in data
        assert data["status"] == "healthy"

    def test_health_check_response_format(self, test_client: TestClient):
        """Test health check response format compliance"""
        response = test_client.get("/api/v1/health")
        data = response.json()
        
        # Verify data types
        assert isinstance(data["status"], str)
        assert isinstance(data["timestamp"], str)
        assert isinstance(data["uptime"], (int, float))
        
        # Verify timestamp format (ISO 8601)
        import datetime
        try:
            datetime.datetime.fromisoformat(data["timestamp"].replace('Z', '+00:00'))
        except ValueError:
            pytest.fail("Timestamp is not in valid ISO format")

    def test_health_check_detailed_success(self, test_client: TestClient):
        """Test detailed health check endpoint"""
        response = test_client.get("/api/v1/health/detailed")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify detailed health information
        assert "status" in data
        assert "services" in data
        assert "version" in data
        assert "environment" in data

    def test_health_check_detailed_services(self, test_client: TestClient):
        """Test detailed health check includes service status"""
        response = test_client.get("/api/v1/health/detailed")
        data = response.json()
        
        services = data["services"]
        
        # Should include validation service status
        assert "validation" in services
        assert "status" in services["validation"]
        
        # Should include export service status
        assert "export" in services
        assert "status" in services["export"]

    @pytest.mark.slow
    def test_health_check_performance(self, test_client: TestClient):
        """Test health check endpoint performance"""
        import time
        
        start_time = time.time()
        response = test_client.get("/api/v1/health")
        end_time = time.time()
        
        # Health check should respond within 1 second
        assert (end_time - start_time) < 1.0
        assert response.status_code == 200

    def test_health_check_concurrent_requests(self, test_client: TestClient):
        """Test health check handles concurrent requests"""
        import threading
        import queue
        
        results = queue.Queue()
        
        def make_request():
            response = test_client.get("/api/v1/health")
            results.put(response.status_code)
        
        # Make 10 concurrent requests
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=make_request)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # All requests should succeed
        while not results.empty():
            status_code = results.get()
            assert status_code == 200

    def test_health_check_cors_headers(self, test_client: TestClient):
        """Test health check includes proper CORS headers"""
        response = test_client.get("/api/v1/health")
        
        # Should include CORS headers for frontend access
        headers = response.headers
        assert "access-control-allow-origin" in headers

    def test_health_check_error_handling(self, test_client: TestClient):
        """Test health check error handling"""
        with patch('app.routers.health.datetime') as mock_datetime:
            # Simulate error in health check
            mock_datetime.utcnow.side_effect = Exception("System error")
            
            response = test_client.get("/api/v1/health")
            
            # Should still return a response (graceful degradation)
            assert response.status_code in [200, 503]  # OK or Service Unavailable

    def test_health_check_uptime_calculation(self, test_client: TestClient):
        """Test uptime calculation in health check"""
        # Make two requests with a small delay
        response1 = test_client.get("/api/v1/health")
        
        import time
        time.sleep(0.1)
        
        response2 = test_client.get("/api/v1/health")
        
        data1 = response1.json()
        data2 = response2.json()
        
        # Uptime should increase between requests
        assert data2["uptime"] >= data1["uptime"]

    def test_health_check_version_info(self, test_client: TestClient):
        """Test health check includes version information"""
        response = test_client.get("/api/v1/health/detailed")
        data = response.json()
        
        assert "version" in data
        version_info = data["version"]
        
        assert "api" in version_info
        assert "phase" in version_info
        assert version_info["phase"] == "1"