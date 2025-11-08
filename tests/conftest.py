"""
Pytest configuration and fixtures for backend testing
"""

import pytest
import os
import tempfile
import shutil
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import Mock, patch

# Set test environment
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["AUTO_MIGRATE"] = "true"

from app.main import app
from app.models.course import Course, Template


@pytest.fixture(scope="session")
def test_client():
    """Create a test client for FastAPI application"""
    with TestClient(app) as client:
        yield client


@pytest.fixture
def sample_course_data():
    """Sample course data for testing"""
    return {
        "courseId": "test-course-001",
        "title": "Test Course Title",
        "description": "This is a test course description",
        "author": "Test Author",
        "version": "1.0.0",
        "createdAt": "2025-01-01T10:00:00Z",
        "updatedAt": "2025-01-01T10:00:00Z",
        "templates": [
            {
                "id": "welcome-001",
                "type": "welcome",
                "title": "Welcome",
                "order": 0,
                "data": {
                    "content": "Welcome to the test course",
                    "subtitle": "Getting started"
                }
            },
            {
                "id": "content-001",
                "type": "content-text",
                "title": "Introduction",
                "order": 1,
                "data": {
                    "content": "This is the introduction content"
                }
            }
        ],
        "assets": [],
        "navigation": {
            "allowSkip": True,
            "showProgress": True,
            "lockProgression": False
        }
    }


@pytest.fixture
def sample_invalid_course_data():
    """Invalid course data for testing validation"""
    return {
        "courseId": "",  # Invalid: empty courseId
        "title": "",     # Invalid: empty title
        "templates": []  # Invalid: no templates
    }


@pytest.fixture
def sample_course_json():
    """Sample course data as JSON string"""
    return '''{
        "courseId": "json-course-001",
        "title": "JSON Test Course",
        "description": "Test course from JSON",
        "author": "JSON Author",
        "version": "1.0.0",
        "createdAt": "2025-01-01T10:00:00Z",
        "updatedAt": "2025-01-01T10:00:00Z",
        "templates": [
            {
                "id": "template-001",
                "type": "welcome",
                "title": "Welcome",
                "order": 0,
                "data": {
                    "content": "Welcome message"
                }
            }
        ],
        "assets": [],
        "navigation": {
            "allowSkip": true,
            "showProgress": true,
            "lockProgression": false
        }
    }'''


@pytest.fixture
def temp_directory():
    """Create a temporary directory for testing file operations"""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)


@pytest.fixture
def mock_scorm_service():
    """Mock SCORM export service for testing"""
    with patch('app.services.scorm_export.SCORMExportService') as mock:
        mock_instance = Mock()
        mock.return_value = mock_instance
        
        # Mock methods
        mock_instance.generate_scorm_package.return_value = Mock()
        mock_instance.estimate_package_size.return_value = {
            "total_estimated_bytes": 50000,
            "total_estimated_mb": 0.05
        }
        mock_instance.validate_for_export.return_value = {
            "valid": True,
            "errors": [],
            "warnings": []
        }
        
        yield mock_instance


@pytest.fixture
def mock_validation_service():
    """Mock validation service for testing"""
    with patch('app.utils.validation.validate_course_json') as mock:
        yield mock


class TestConfig:
    """Test configuration constants"""
    TEST_API_URL = "http://testserver"
    TEST_TIMEOUT = 30
    MAX_FILE_SIZE = 1024 * 1024  # 1MB for tests
    
    # Test user data
    TEST_USER = {
        "id": "test-user-001",
        "name": "Test User",
        "email": "test@example.com"
    }


def pytest_configure(config):
    """Configure pytest with custom markers"""
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "unit: marks tests as unit tests"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow running"
    )


def pytest_collection_modifyitems(config, items):
    """Add markers to tests based on their location"""
    for item in items:
        # Add integration marker to integration test files
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        
        # Add unit marker to unit test files
        if "unit" in str(item.fspath) or "test_" in str(item.fspath):
            item.add_marker(pytest.mark.unit)


@pytest.fixture(scope="function", autouse=True)
def reset_environment():
    """Reset environment for each test"""
    # Clear any cached modules or singletons
    yield
    # Cleanup after test


# Helper functions for tests
def assert_response_success(response, expected_status=200):
    """Assert that response is successful"""
    assert response.status_code == expected_status, f"Expected {expected_status}, got {response.status_code}: {response.text}"


def assert_response_error(response, expected_status=400):
    """Assert that response is an error"""
    assert response.status_code == expected_status, f"Expected error {expected_status}, got {response.status_code}"


def assert_valid_course_data(course_data):
    """Assert that course data structure is valid"""
    required_fields = ["courseId", "title", "templates"]
    for field in required_fields:
        assert field in course_data, f"Missing required field: {field}"
    
    assert isinstance(course_data["templates"], list), "Templates must be a list"
    assert len(course_data["templates"]) > 0, "Must have at least one template"


def create_test_zip_file(temp_dir: Path, filename: str = "test.zip") -> Path:
    """Create a test ZIP file for testing"""
    import zipfile
    
    zip_path = temp_dir / filename
    
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr("imsmanifest.xml", "<manifest></manifest>")
        zf.writestr("index.html", "<html><body>Test</body></html>")
        zf.writestr("course.json", '{"courseId": "test"}')
    
    return zip_path