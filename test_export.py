#!/usr/bin/env python3
"""
Quick test script to validate export functionality
"""
import sys
import os
import json
import asyncio
from pathlib import Path

# Add the backend directory to Python path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.services.scorm_export import SCORMExportService
from app.models.course import Course, Template, TemplateData

async def test_export_functionality():
    """Test the SCORM export functionality"""
    try:
        print("🧪 Testing SCORM Export Functionality...")
        
        # Create a test course
        test_course_data = {
            "courseId": "test-course-001",
            "title": "Sample Course for Export Test",
            "description": "A test course to validate export functionality",
            "author": "Test Author",
            "language": "en",
            "version": "1.0.0",
            "templates": [
                {
                    "id": "template-1",
                    "type": "content-text",
                    "title": "Introduction Template",
                    "order": 0,
                    "data": {
                        "content": "Welcome to this sample course! This is the introduction template."
                    }
                },
                {
                    "id": "template-2", 
                    "type": "content-text",
                    "title": "Advanced Topics Template",
                    "order": 1,
                    "data": {
                        "content": "This template covers advanced topics and concepts."
                    }
                }
            ]
        }
        
        # Create Course object
        course = Course(**test_course_data)
        print(f"✅ Created course: {course.title}")
        
        # Initialize SCORM export service
        export_service = SCORMExportService()
        print("✅ Initialized SCORM export service")
        
        # Validate course for export
        validation_result = export_service.validate_for_export(course)
        print(f"✅ Course validation: {validation_result}")
        
        # Estimate package size
        size_estimate = export_service.estimate_package_size(course)
        print(f"✅ Estimated package size: {size_estimate}")
        
        # Generate SCORM package
        print("🔄 Generating SCORM package...")
        zip_buffer = await export_service.generate_scorm_package(course)
        
        # Save to file for verification
        output_file = Path("/tmp/test_scorm_export.zip")
        with open(output_file, "wb") as f:
            f.write(zip_buffer.getvalue())
        
        file_size = output_file.stat().st_size
        print(f"✅ SCORM package generated successfully!")
        print(f"   📦 File: {output_file}")
        print(f"   📏 Size: {file_size:,} bytes")
        
        # Verify ZIP contents
        import zipfile
        with zipfile.ZipFile(output_file, 'r') as zip_file:
            file_list = zip_file.namelist()
            print(f"   📋 Contents: {len(file_list)} files")
            for file in sorted(file_list):
                print(f"      - {file}")
            
            # Critical Revalidation: Check file contents
            print("\n   🔍 Critical Content Validation:")
            
            # 1. Check imsmanifest.xml for single item structure
            if 'imsmanifest.xml' in file_list:
                with zip_file.open('imsmanifest.xml') as f:
                    manifest_content = f.read().decode('utf-8')
                    if '<item identifier="item_course_1"' in manifest_content:
                        print("      ✅ imsmanifest.xml: Single item structure confirmed")
                    else:
                        print("      ❌ imsmanifest.xml: Single item structure NOT found")
                        raise ValueError("imsmanifest.xml missing single item structure")
            else:
                raise ValueError("imsmanifest.xml missing from package")

            # 2. Check scorm_wrapper.js for terminate
            if 'scorm_wrapper.js' in file_list:
                with zip_file.open('scorm_wrapper.js') as f:
                    wrapper_content = f.read().decode('utf-8')
                    if 'SCORM.terminate()' in wrapper_content or 'terminate: function' in wrapper_content:
                        print("      ✅ scorm_wrapper.js: Terminate function confirmed")
                    else:
                        print("      ❌ scorm_wrapper.js: Terminate function NOT found")
                        raise ValueError("scorm_wrapper.js missing terminate function")
            else:
                raise ValueError("scorm_wrapper.js missing from package")

            # 3. Check index.html for finishCourse calling terminate
            if 'index.html' in file_list:
                with zip_file.open('index.html') as f:
                    html_content = f.read().decode('utf-8')
                    if 'SCORM.terminate()' in html_content:
                        print("      ✅ index.html: SCORM.terminate() call confirmed")
                    else:
                        print("      ❌ index.html: SCORM.terminate() call NOT found")
                        raise ValueError("index.html missing SCORM.terminate() call")
            else:
                raise ValueError("index.html missing from package")

        
        return True
        
    except Exception as e:
        print(f"❌ Error during export test: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_api_components():
    """Test individual API components"""
    try:
        print("\n🔧 Testing API Components...")
        
        # Test imports
        from app.routers.export import router
        from app.utils.validation import load_course_schema
        print("✅ All required modules imported successfully")
        
        # Test course validation utility
        schema = load_course_schema()
        print(f"✅ Course schema loaded: {bool(schema)}")
        
        # Test creating a simple course object
        test_course_dict = {
            "courseId": "test-001",
            "title": "Test Course", 
            "description": "Test description",
            "author": "Test Author",
            "language": "en",
            "templates": [],
            "version": "1.0.0"
        }
        
        test_course = Course(**test_course_dict)
        print(f"✅ Course object creation works: {test_course.title}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing API components: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    print("=" * 60)
    print("🚀 E-Learning Export Functionality Test")
    print("=" * 60)
    
    # Test API components first
    api_test_passed = test_api_components()
    
    # Test export functionality 
    export_test_passed = await test_export_functionality()
    
    print("\n" + "=" * 60)
    print("📊 Test Results Summary")
    print("=" * 60)
    print(f"API Components: {'✅ PASSED' if api_test_passed else '❌ FAILED'}")
    print(f"Export Functionality: {'✅ PASSED' if export_test_passed else '❌ FAILED'}")
    
    if api_test_passed and export_test_passed:
        print("\n🎉 ALL TESTS PASSED!")
        print("✅ Export functionality is working correctly")
        print("✅ ZIP format download capability confirmed")
    else:
        print("\n⚠️ Some tests failed - see output above")
        
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())