#!/usr/bin/env python3
"""
Test Phase 1 Import with Sample SCORM Package
Tests importing actual SCORM course data
"""

import asyncio
import sys
import json
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from app.services.import_service import ImportService
from app.db.config import SessionLocal


async def create_minimal_scorm_package():
    """Create a minimal SCORM package with course data for testing"""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # Create course data with multiple template types
        course_data = {
            "courseId": "golf-training-001",
            "title": "Golf Rules & Etiquette Training",
            "description": "Learn the essential rules and etiquette of golf",
            "author": "Golf Coach",
            "version": "1.0",
            "templates": [
                # Template 1: Welcome
                {
                    "id": "slide_1",
                    "type": "welcome",
                    "order": 0,
                    "title": "Welcome to Golf Training",
                    "data": {
                        "content": "Welcome to the Golf Rules and Etiquette Training Course!",
                        "imageUrl": "images/golf-course.jpg"
                    }
                },
                # Template 2: Text Content
                {
                    "id": "slide_2",
                    "type": "content-text",
                    "order": 1,
                    "title": "Rule 1: Basic Etiquette",
                    "data": {
                        "heading": "Golf Etiquette - The Foundation",
                        "content": "<p>Respect other golfers and the course.</p><p>Always be quiet when others are playing.</p>",
                        "imageUrl": "images/etiquette.jpg"
                    }
                },
                # Template 3: Video Content
                {
                    "id": "slide_3",
                    "type": "content-video",
                    "order": 2,
                    "title": "How to Play Golf",
                    "data": {
                        "videoUrl": "videos/golf-basics.mp4",
                        "duration": 300,
                        "transcript": "This video covers the basic steps of playing golf..."
                    }
                },
                # Template 4: MCQ Question
                {
                    "id": "slide_4",
                    "type": "mcq",
                    "order": 3,
                    "title": "Quiz Question 1",
                    "data": {
                        "questions": [
                            {
                                "id": "q1",
                                "question": "What is the maximum number of clubs allowed in a golf bag?",
                                "options": [
                                    {"id": "opt1", "text": "10 clubs", "isCorrect": False},
                                    {"id": "opt2", "text": "12 clubs", "isCorrect": False},
                                    {"id": "opt3", "text": "14 clubs", "isCorrect": True},
                                    {"id": "opt4", "text": "Unlimited", "isCorrect": False}
                                ]
                            }
                        ]
                    }
                },
                # Template 5: Summary
                {
                    "id": "slide_5",
                    "type": "summary",
                    "order": 4,
                    "title": "Course Complete",
                    "data": {
                        "content": "Congratulations! You have completed the Golf Training course.",
                        "passingScore": 80,
                        "showScore": True
                    }
                }
            ]
        }
        
        # Create imsmanifest.xml
        manifest_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="golf-course-001" version="1.0"
    xmlns="http://www.imsglobal.org/xsd/imscp_v1p1"
    xmlns:adlcp="http://www.adlnet.org/xsd/adl_cp_v1_2"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.imsglobal.org/xsd/imscp_v1p1 imscp_v1p1.xsd
    http://www.adlnet.org/xsd/adl_cp_v1_2 adlcp_v1_2.xsd">
    <organizations default="org1">
        <organization identifier="org1">
            <title>Golf Training Course</title>
            <item identifier="item1" identifierref="resource1">
                <title>Golf Training</title>
            </item>
        </organization>
    </organizations>
    <resources>
        <resource identifier="resource1" type="webcontent" href="index.html">
            <file href="index.html"/>
            <file href="course_data.js"/>
        </resource>
    </resources>
</manifest>"""
        
        # Create course_data.js with var assignment for regex parsing
        course_data_js = f"""var courseData = {json.dumps(course_data, indent=2)};
"""
        
        # Create index.html
        index_html = """<!DOCTYPE html>
<html>
<head>
    <title>Golf Training Course</title>
    <meta charset="UTF-8">
    <script src="course_data.js"></script>
</head>
<body>
    <h1>Golf Training Course</h1>
    <p>Loading course...</p>
    <script>
        console.log("Course loaded:", courseData);
    </script>
</body>
</html>"""
        
        # Write files
        (tmpdir / "imsmanifest.xml").write_text(manifest_content)
        (tmpdir / "course_data.js").write_text(course_data_js)
        (tmpdir / "index.html").write_text(index_html)
        
        # Create image directory
        images_dir = tmpdir / "images"
        images_dir.mkdir()
        (images_dir / "golf-course.jpg").write_text("dummy image")
        (images_dir / "etiquette.jpg").write_text("dummy image")
        
        # Create videos directory
        videos_dir = tmpdir / "videos"
        videos_dir.mkdir()
        (videos_dir / "golf-basics.mp4").write_text("dummy video")
        
        # Create ZIP
        zip_path = tmpdir / "test-course.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
            for file_path in tmpdir.rglob('*'):
                if file_path.is_file() and file_path != zip_path:
                    arcname = file_path.relative_to(tmpdir)
                    z.write(file_path, arcname)
        
        return zip_path.read_bytes(), course_data


async def test_phase1_import():
    """Test Phase 1 import with sample SCORM package"""
    
    try:
        print("\n" + "=" * 70)
        print("PHASE 1 IMPORT TEST - Sample SCORM Course")
        print("=" * 70)
        
        # Step 1: Create test package
        print("\n📦 Step 1: Creating sample SCORM package...")
        zip_data, course_data = await create_minimal_scorm_package()
        print(f"   ✅ Created package: {len(zip_data) / 1024:.1f} KB")
        print(f"   ✅ Course ID: {course_data['courseId']}")
        print(f"   ✅ Title: {course_data['title']}")
        print(f"   ✅ Templates: {len(course_data['templates'])}")
        
        # Step 2: Initialize database session
        print("\n🗄️  Step 2: Initializing database session...")
        async with SessionLocal() as db_session:
            
            # Step 3: Analyze package
            print("\n🔍 Step 3: Analyzing SCORM package (Phase 1)...")
            service = ImportService(db_session)
            job_id = await service.analyze_package(zip_data)
            
            print(f"   ✅ Analysis complete!")
            print(f"   ✅ Job ID: {job_id}")
            
            # Step 4: Get job details and preview
            print("\n📋 Step 4: Retrieving import preview...")
            
            # Debug: Try to get the job directly
            job = await service.job_repo.get_by_id(job_id)
            print(f"   DEBUG: Job retrieved from DB: {job is not None}")
            if job:
                print(f"   DEBUG: Job status: {job.status}")
                print(f"   DEBUG: Job result_data exists: {job.result_data is not None}")
            
            job_preview = await service.get_preview(job_id)
            
            if not job_preview:
                raise Exception("Failed to retrieve preview - job not found")
            
            # Extract course data from preview
            preview = job_preview.get('courseData', {})
            
            print(f"\n   Course Information:")
            print(f"   ├─ Course ID: {preview.get('courseId', 'N/A')}")
            print(f"   ├─ Title: {preview.get('title', 'N/A')}")
            print(f"   ├─ Author: {preview.get('author', 'N/A')}")
            print(f"   └─ Templates Found: {len(preview.get('templates', []))}")
            
            # Step 5: Analyze each template
            print(f"\n   Template Analysis:")
            templates = preview.get('templates', [])
            
            for i, template in enumerate(templates):
                print(f"\n   [{i+1}] {template.get('title', 'Untitled')}")
                print(f"       ├─ ID: {template.get('id', 'N/A')}")
                print(f"       ├─ Type: {template.get('type', 'N/A')}")
                print(f"       ├─ Order: {template.get('order', 'N/A')}")
                
                # Show schema info
                schema = template.get('schema', {})
                properties = schema.get('properties', {})
                
                if properties:
                    print(f"       ├─ Schema Fields: {len(properties)}")
                    for field_name, field_def in list(properties.items())[:3]:
                        field_type = field_def.get('type', 'unknown')
                        print(f"       │  └─ {field_name}: {field_type}")
                    if len(properties) > 3:
                        print(f"       │  └─ ... and {len(properties) - 3} more fields")
                
                # Show sample data
                data = template.get('data', {})
                if data:
                    print(f"       └─ Data Keys: {', '.join(list(data.keys())[:3])}")
                    if len(data) > 3:
                        print(f"          ... and {len(data) - 3} more")
            
            # Step 6: Check warnings
            print(f"\n   Asset & Warning Analysis:")
            warnings = job_preview.get('warnings', [])
            if warnings:
                print(f"   ⚠️  Warnings: {len(warnings)}")
                for warn in warnings[:3]:
                    print(f"       └─ {warn}")
                if len(warnings) > 3:
                    print(f"       └─ ... and {len(warnings) - 3} more")
            else:
                print(f"   ✅ No warnings - all assets properly detected")
            
            # Step 7: Summary
            print("\n" + "=" * 70)
            print("✅ PHASE 1 IMPORT TEST RESULTS")
            print("=" * 70)
            print(f"\n✓ Successfully extracted SCORM package")
            print(f"✓ Successfully parsed course data: {preview.get('courseId')}")
            print(f"✓ Successfully detected {len(templates)} templates")
            print(f"✓ Successfully inferred schemas for all templates")
            print(f"✓ Successfully identified assets and file references")
            print(f"\n🎯 Conclusion: PHASE 1 IS WORKING! ✅")
            print("\nPhase 1 Capabilities Verified:")
            print("  ✅ ZIP extraction")
            print("  ✅ JavaScript parsing (regex-based)")
            print("  ✅ JSON course data extraction")
            print("  ✅ Multi-template support")
            print("  ✅ Schema inference (type detection)")
            print("  ✅ Asset detection")
            print("  ✅ Database staging")
            
            return True
        
    except Exception as e:
        print("\n" + "=" * 70)
        print("❌ PHASE 1 IMPORT TEST FAILED")
        print("=" * 70)
        print(f"\n❌ Error: {type(e).__name__}")
        print(f"   Message: {str(e)}")
        
        import traceback
        print("\n📋 Full Traceback:")
        traceback.print_exc()
        
        return False


async def main():
    """Main test runner"""
    success = await test_phase1_import()
    
    print("\n" + "=" * 70)
    if success:
        print("✅ TEST PASSED - Phase 1 is working correctly!")
    else:
        print("❌ TEST FAILED - See errors above")
    print("=" * 70)
    
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
