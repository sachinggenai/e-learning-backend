"""
Test suite for template data conversion fix
Tests that the SCORM export service correctly handles various data types
"""

import pytest
import sys
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any, List

# Add backend to path
backend_path = Path(__file__).parent / "backend" / "app"
sys.path.insert(0, str(backend_path.parent))

from app.services.scorm_export import _ensure_dict, SCORMExportService


# Test fixtures and data classes
@dataclass
class SimpleDataClass:
    """Simple dataclass for testing"""
    content: str
    metadata: Dict[str, Any]


class SimpleObject:
    """Simple object with __dict__"""
    def __init__(self, content: str, metadata: Dict[str, Any]):
        self.content = content
        self.metadata = metadata


# Test cases
class TestEnsureDict:
    """Test the _ensure_dict helper function"""
    
    def test_dict_input(self):
        """Test that plain dicts are returned unchanged"""
        data = {"content": "Hello", "metadata": {}}
        result = _ensure_dict(data)
        assert result == data
        assert result is data  # Same reference
    
    def test_dataclass_input(self):
        """Test that dataclasses are converted to dicts"""
        data = SimpleDataClass(content="Hello", metadata={"key": "value"})
        result = _ensure_dict(data)
        assert isinstance(result, dict)
        assert result["content"] == "Hello"
        assert result["metadata"] == {"key": "value"}
    
    def test_object_with_dict(self):
        """Test that objects with __dict__ are converted"""
        data = SimpleObject(content="Hello", metadata={"key": "value"})
        result = _ensure_dict(data)
        assert isinstance(result, dict)
        assert result["content"] == "Hello"
        assert result["metadata"] == {"key": "value"}
    
    def test_invalid_input(self):
        """Test that invalid inputs raise ValueError"""
        with pytest.raises(ValueError):
            _ensure_dict("invalid string")
        
        with pytest.raises(ValueError):
            _ensure_dict(123)
    
    def test_list_input_error(self):
        """Test that lists raise ValueError"""
        with pytest.raises(ValueError):
            _ensure_dict([1, 2, 3])


class TestTemplateDataValidation:
    """Test the template data validation in SCORM export"""
    
    @pytest.fixture
    def scorm_service(self):
        """Create SCORM export service instance"""
        return SCORMExportService()
    
    def test_sanitize_data_with_dict(self, scorm_service):
        """Test _sanitize_data with plain dict"""
        data = {
            "content": "<p>Hello World</p>",
            "metadata": {"title": "Test Page"}
        }
        result = scorm_service._sanitize_data(data)
        assert isinstance(result, dict)
        assert "content" in result
        assert "metadata" in result
    
    def test_sanitize_data_with_dataclass(self, scorm_service):
        """Test _sanitize_data with dataclass input"""
        data = SimpleDataClass(
            content="<p>Hello World</p>",
            metadata={"title": "Test"}
        )
        result = scorm_service._sanitize_data(data)
        assert isinstance(result, dict)
        assert "content" in result
        assert "metadata" in result
    
    def test_sanitize_data_with_object(self, scorm_service):
        """Test _sanitize_data with plain object"""
        data = SimpleObject(
            content="<p>Hello World</p>",
            metadata={"title": "Test"}
        )
        result = scorm_service._sanitize_data(data)
        assert isinstance(result, dict)
        assert "content" in result
        assert "metadata" in result
    
    def test_sanitize_data_with_none(self, scorm_service):
        """Test _sanitize_data with None"""
        result = scorm_service._sanitize_data(None)
        assert result == {}
    
    def test_sanitize_data_with_nested_dicts(self, scorm_service):
        """Test _sanitize_data with nested structures"""
        data = {
            "content": "Text",
            "questions": [
                {"question": "Q1", "answer": "A1", "isCorrect": True},
                {"question": "Q2", "answer": "A2", "isCorrect": False}
            ]
        }
        result = scorm_service._sanitize_data(data)
        assert isinstance(result, dict)
        assert len(result.get("questions", [])) == 2


class TestMCQValidation:
    """Test MCQ-specific template validation"""
    
    @pytest.fixture
    def scorm_service(self):
        """Create SCORM export service instance"""
        return SCORMExportService()
    
    def test_mcq_data_as_dataclass(self, scorm_service):
        """Test MCQ questions with dataclass data"""
        @dataclass
        class MCQData:
            questions: List[Dict[str, Any]]
            type: str
        
        data = MCQData(
            questions=[
                {"question": "Q1", "options": ["A", "B"], "isCorrect": True},
                {"question": "Q2", "options": ["C", "D"], "isCorrect": False}
            ],
            type="assessment"
        )
        
        result = scorm_service._sanitize_data(data)
        assert isinstance(result, dict)
        assert "questions" in result
        assert len(result["questions"]) == 2
    
    def test_mcq_data_as_object(self, scorm_service):
        """Test MCQ questions with plain object"""
        class MCQData:
            def __init__(self):
                self.questions = [
                    {"question": "Q1", "options": ["A", "B"], "isCorrect": True}
                ]
                self.type = "assessment"
        
        data = MCQData()
        result = scorm_service._sanitize_data(data)
        assert isinstance(result, dict)
        assert "questions" in result


def run_tests():
    """Run all tests"""
    print("Running template data conversion tests...\n")
    
    # Run pytest
    exit_code = pytest.main([
        __file__,
        "-v",
        "--tb=short",
        "-x"  # Stop on first failure
    ])
    
    return exit_code


if __name__ == "__main__":
    exit_code = run_tests()
    sys.exit(exit_code)
