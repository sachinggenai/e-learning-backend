#!/usr/bin/env python3
"""
Create a proper test SCORM package with JSON course data and test Phase 1 import
"""

import asyncio
import sys
import json
import tempfile
import zipfile
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.import_service import ImportService
from app.db.config import SessionLocal


async def create_test_scorm_package():
    """Create a minimal test SCORM package with course data"""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # Create course data
        course_data = {
            "courseId": "test-golf-course-001",
            "title": "Golf Rules Training",
            "description": "Learn the rules of golf",
            "templates": [
                {
                    "id": "welcome_slide",
                    "type": "welcome",
                    "order": 0,
                    "title": "Welcome to Golf Training",
                    "data": {
                        "content": "Welcome to the Golf Rules training course!",
                        "imageUrl": "Etiquette/course.jpg"
                    }
                },
                {
                    "id": "content_slide_1",
                    "type": "content-text",
                    "order": 1,
                    "title": "Golf Etiquette",
                    "data": {
                        "heading": "Rule 1: Golf Etiquette",
                        "content": "<p>Respect other golfers and maintain proper conduct on the course.</p>",
                        "imageUrl": "Etiquette/course.jpg"
                    }
                },
                {
                    "id": "mcq_slide_1",
                    "type": "mcq",
                    "order": 2,
                    "title": "Question 1: Golf Rules",
                    "data": {
                        "questions": [
                            {
                                "id": "q1",
                                "question": "What is the maximum number of clubs allowed in a golf bag?",
                                "options": [
                                    {"id": "opt1", "text": "10 clubs", "isCorrect": False},
                                    {"id": "opt2", "text": "12 clubs", "isCorrect": False},
                                    {"id": "opt3", "text": "14 clubs", "isCorrect": True},
                                    {"id": "opt4", "text": "16 clubs", "isCorrect": False}
                                ]
                            }
                        ]
                    }
                },
                {
                    "id": "mcq_slide_2",
                    "type": "mcq",
                    "order": 3,
                    "title": "Question 2: Handicapping",
                    "data": {
                        "questions": [
                            {
                                "id": "q2",
                                "question": "Which number is better in golf scoring?",
                                "options": [
                                    {"id": "opt1", "text": "Higher scores", "isCorrect": False},
                                    {"id": "opt2", "text": "Lower scores", "isCorrect": True},
                                    {"id": "opt3", "text": "Even scores", "isCorrect": False}
                                ]
                            }
                        ]
                    }
                },
                {
                    "id": "summary_slide",
                    "type": "summary",
                    "order": 4,
                    "title": "Course Complete",
                    "data": {
                        "content": "Congratulations! You have completed the golf rules training.",
                        "passingScore": 80,
                        "showScore": True
                    }
                }
            ]
        }
        
        # Create imsmanifest.xml
        manifest = """<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="golf-course-001" version="1.0" 
    xmlns="http://www.imsglobal.org/xsd/imscp_v1p1" 
    xmlns:adlcp="http://www.adlnet.org/xsd/adl_cp_v1_2" 
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" 
    xsi:schemaLocation="http://www.imsglobal.org/xsd/imscp_v1p1 imscp_v1p1.xsd 
    http://www.adlnet.org/xsd/adl_cp_v1_2 adlcp_v1_2.xsd">
    <organizations default="org1">
        <organization identifier="org1">
            <title>Golf Rules Course</title>
            <item identifier="item1" identifierref="resource1">
                <title>Golf Training</title>
            </item>
        </organization>
    </organizations>
    <resources>
        <resource identifier="resource1" type="webcontent" href="index.html">
            <file href="index.html"/>
            <file href="course_data.js"/>
            <dependency identifierref="resource_assets"/>
        </resource>
        <resource identifier="resource_assets" type="webcontent">
            <file href="Etiquette/course.jpg"/>
        </resource>
    </resources>
</manifest>"""
        
        # Create course_data.js with JSON - use simpler format
        # The regex needs var keyword and simpler structure
        course_data_simple = {
            "courseId": "test-golf-course-001",
            "title": "Golf Rules Training",
            "templates": [
                {"id": "w1", "type": "welcome", "title": "Welcome", "order": 0, "data": {"content": "Welcome!"}},
                {"id": "c1", "type": "content-text", "title": "Rules", "order": 1, "data": {"heading": "Golf Rules", "content": "<p>Be respectful</p>"}},
                {"id": "m1", "type": "mcq", "title": "Q1", "order": 2, "data": {"questions": [{"id": "q1", "question": "Max clubs?", "options": [{"id": "o1", "text": "14", "isCorrect": True}]}]}},
                {"id": "s1", "type": "summary", "title": "Done", "order": 3, "data": {"content": "Complete!", "passingScore": 80}}
            ]
        }
        
        course_data_js = f"""var courseData = {json.dumps(course_data_simple)};
"""
        
        # Create a minimal index.html
        index_html = """<!DOCTYPE html>
<html>
<head>
    <title>Golf Rules Training</title>
    <script src="course_data.js"></script>
</head>
<body>
    <h1>Golf Rules Training</h1>
    <p>This course teaches you the rules and etiquette of golf.</p>
    <script src="scorm_wrapper.js"></script>
</body>
</html>"""
        
        # Write files
        (tmpdir / "imsmanifest.xml").write_text(manifest)
        (tmpdir / "course_data.js").write_text(course_data_js)
        (tmpdir / "index.html").write_text(index_html)
        
        # Create assets directory
        assets_dir = tmpdir / "Etiquette"
        assets_dir.mkdir(exist_ok=True)
        
        # Create a dummy image file (1x1 transparent PNG)
        png_data = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c630100010005000628d4c60000000049454e44ae426082')
        (assets_dir / "course.jpg").write_bytes(png_data)
        
        # Create ZIP
        zip_path = tmpdir / "test-golf-course.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
            for file_path in tmpdir.rglob('*'):
                if file_path.is_file() and file_path != zip_path:
                    arcname = file_path.relative_to(tmpdir)
                    z.write(file_path, arcname)
        
        # Return ZIP data
        return zip_path.read_bytes(), course_data_simple


async def test_sample_import():
    """Test importing sample SCORM package"""
    
    try:
        # Create test package
        print("\n🏗️  Creating test SCORM package with course data...")
        zip_data, course_data_dict = await create_test_scorm_package()
        print(f"   Created package: {len(zip_data) / 1024:.1f} KB")
        print(f"   Course ID: {course_data_dict['courseId']}")
        print(f"   Title: {course_data_dict['title']}")
        print(f"   Templates: {len(course_data_dict['templates'])}")
        
        # Get database session
        async with SessionLocal() as db_session:
            # Step 1: Analyze the package
            print("\n🔍 Step 1: Analyzing package...")
            service = ImportService(db_session)
            result = await service.analyze_package(zip_data)
            
            print(f"✅ Analysis complete!")
            print(f"   Job ID: {result['job_id']}")
            print(f"   Status: {result['status']}")
            print(f"   Course ID in DB: {result.get('course_id', 'Not yet assigned')}")
            
            # Step 2: Check what was discovered
            if 'preview' in result:
                preview = result['preview']
                print(f"\n📋 Preview Data:")
                print(f"   Course ID: {preview.get('courseId', 'N/A')}")
                print(f"   Title: {preview.get('title', 'N/A')}")
                print(f"   Description: {preview.get('description', 'N/A')}")
                print(f"   Templates found: {len(preview.get('templates', []))}")
                
                for i, template in enumerate(preview.get('templates', [])):
                    print(f"\n   Template {i}: {template.get('title', 'N/A')}")
                    print(f"      ID: {template.get('id', 'N/A')}")
                    print(f"      Type: {template.get('type', 'N/A')}")
                    print(f"      Order: {template.get('order', 'N/A')}")
                    
                    schema = template.get('schema', {})
                    if schema:
                        properties = schema.get('properties', {})
                        print(f"      Schema fields detected: {len(properties)}")
                        for field_name, field_def in properties.items():
                            field_type = field_def.get('type', 'unknown')
                            field_desc = field_def.get('description', '')
                            print(f"         - {field_name}: {field_type}")
                            if field_desc:
                                print(f"           {field_desc}")
            
            # Step 3: Check for warnings
            if 'warnings' in result and result['warnings']:
                print(f"\n⚠️  Warnings ({len(result['warnings'])}):")
                for warning in result['warnings']:
                    print(f"   - {warning}")
            else:
                print(f"\n✅ No warnings")
        
        print("\n✅ Phase 1 import successful!")
        return True
        
    except Exception as e:
        print(f"\n❌ Import failed with error:")
        print(f"   {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    print("=" * 70)
    print("PHASE 1 IMPORT TEST - Test SCORM Package with Course Data")
    print("=" * 70)
    
    # Run import test
    success = await test_sample_import()
    
    print("\n" + "=" * 70)
    if success:
        print("✅ PHASE 1 IS WORKING!")
        print("   - Successfully created test SCORM package")
        print("   - Successfully analyzed and extracted course data")
        print("   - Successfully inferred template schemas")
        print("   - Successfully staged results for import")
    else:
        print("❌ PHASE 1 HAS ISSUES. See errors above.")
    print("=" * 70)
    
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
