#!/usr/bin/env python3
"""Test full import like the test does"""

import asyncio
import sys
import json
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.services.import_service import ImportService
from app.db.config import SessionLocal


async def create_minimal_scorm_package():
    """Create a minimal SCORM package with course data for testing - SAME AS test_phase1_final.py"""
    
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


async def test():
    print("Creating package like test_phase1_final...")
    zip_data, course_data = await create_minimal_scorm_package()
    print(f"✓ Created package: {len(zip_data)} bytes")
    
    async with SessionLocal() as db_session:
        service = ImportService(db_session)
        
        print("\nExtracting and discovering...")
        import tempfile as tmp
        with tmp.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "test.zip"
            zip_path.write_bytes(zip_data)
            zip_contents = service._extract_zip(zip_path)
        
        print(f"Files in ZIP:")
        for fname in zip_contents.keys():
            content_len = len(zip_contents[fname])
            print(f"  - {fname} ({content_len} bytes)")
        
        print("\nDiscovering payloads...")
        payloads = await service._discover_payloads(zip_contents)
        print(f"✓ Found {len(payloads)} payloads")
        
        if payloads:
            print("\n✓ SUCCESS - Payloads found!")
        else:
            print("\n✗ FAILURE - No payloads found!")
            print("\nDebugging - checking course_data.js content:")
            if 'course_data.js' in zip_contents:
                content = zip_contents['course_data.js'].decode('utf-8')
                print(f"  Length: {len(content)}")
                print(f"  Preview: {content[:300]}...")

asyncio.run(test())
