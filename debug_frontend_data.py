#!/usr/bin/env python3
"""
Debug test to see what data the frontend is sending
"""
import sys
import json
import os

# Add the backend directory to Python path  
sys.path.insert(0, '/Users/aiwork/e-learning-editor/backend')

from app.models.course import Course, CourseExportRequest

def test_frontend_data():
    """Test with sample data that matches frontend structure"""
    
    # This is what I expect the frontend is sending based on the error logs
    frontend_course_data = {
        "courseId": "course_1759716087458",
        "title": "New Course", 
        "description": "Enter course description here",
        "author": "Author Name",
        "version": "1.0.0",
        "createdAt": "2025-10-06T02:01:27.458Z",
        "updatedAt": "2025-10-06T02:01:27.459Z", 
        "templates": [
            {
                "id": "template_1759716087459",
                "type": "welcome",
                "title": "Welcome",
                "order": 0,
                "data": {
                    "title": "Welcome to Your Course",
                    "subtitle": "Let's get started", 
                    "description": "This is an introduction to your eLearning course."
                }
            }
        ],
        "assets": [],
        "navigation": {
            "allowSkip": False,
            "showProgress": True,
            "lockProgression": False
        }
    }
    
    print("🧪 Testing Frontend Course Data Structure")
    print("=" * 50)
    
    # Test 1: Try to create Course object directly
    try:
        print("Test 1: Creating Course object directly...")
        course = Course(**frontend_course_data)
        print("✅ SUCCESS: Course object created")
    except Exception as e:
        print(f"❌ FAILED: {str(e)}")
        print(f"   Error type: {type(e).__name__}")
    
    # Test 2: Try CourseExportRequest format
    try:
        print("\nTest 2: Testing CourseExportRequest format...")
        export_request = CourseExportRequest(course=json.dumps(frontend_course_data))
        print("✅ SUCCESS: CourseExportRequest created")
    except Exception as e:
        print(f"❌ FAILED: {str(e)}")
        print(f"   Error type: {type(e).__name__}")
    
    # Test 3: Try with corrected backend structure (simulating transformation)
    try:
        print("\nTest 3: Testing with backend-expected structure...")
        backend_course_data = {
            **frontend_course_data,
            "templates": [
                {
                    "id": "template_1759716087459",
                    "type": "welcome", 
                    "title": "Welcome",
                    "order": 0,
                    "data": {
                        "content": "This is an introduction to your eLearning course.",  # Map description -> content
                        "subtitle": "Let's get started"
                    }
                }
            ],
            # Fix navigation field names
            "navigation": {
                "allowSkip": False,
                "showProgress": True,
                "linearProgression": False  # Map lockProgression -> linearProgression
            },
            # Add required settings
            "settings": {
                "theme": "default",
                "autoplay": False,
                "duration": None
            }
        }
        
        course = Course(**backend_course_data)
        print("✅ SUCCESS: Backend-structured course created")
        print(f"   Course ID: {course.courseId}")
        print(f"   Templates: {len(course.templates)}")
        print(f"   Navigation: {course.navigation}")
        print(f"   Settings: {course.settings}")
        
    except Exception as e:
        print(f"❌ FAILED: {str(e)}")
        print(f"   Error type: {type(e).__name__}")
        
    # Test 4: Test the full validation pipeline
    print("\nTest 4: Testing full validation pipeline...")
    from app.utils.validation import course_validator
    import asyncio
    
    async def test_validation():
        try:
            # Use the backend-structured course from Test 3
            course = Course(**backend_course_data)
            print("✅ Course object created successfully")
            
            # Test the validation pipeline that was failing
            validation_errors = await course_validator.validate_course(course)
            if validation_errors:
                print("❌ Validation errors found:")
                for error in validation_errors:
                    print(f"   - {error.field}: {error.message}")
                return False
            else:
                print("✅ Course passed all validation checks!")
                return True
                
        except Exception as e:
            print(f"❌ Validation pipeline failed: {str(e)}")
            return False
    
    # Run the async validation test
    validation_passed = asyncio.run(test_validation())

if __name__ == "__main__":
    test_frontend_data()