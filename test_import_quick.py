#!/usr/bin/env python3
"""
Quick test script for SCORM import system.
Run: python test_import_quick.py
"""

import requests
import json
import time
import zipfile
import tempfile
from pathlib import Path

BASE_URL = "http://localhost:8000/api/v1/imports"


def create_test_zip() -> str:
    """Create a minimal test SCORM package."""
    print("📦 Creating test SCORM package...")
    
    # Create temporary directory
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        # Create test course data
        course_data = {
            "courseId": "test-course-001",
            "title": "Test Course",
            "description": "A quick test import",
            "templates": [
                {
                    "id": "slide_1",
                    "type": "welcome",
                    "title": "Welcome",
                    "order": 0,
                    "data": {
                        "content": "Welcome to the test course!"
                    }
                },
                {
                    "id": "slide_2",
                    "type": "mcq",
                    "title": "Question 1",
                    "order": 1,
                    "data": {
                        "question": "What is 2+2?",
                        "options": [
                            {"text": "3", "isCorrect": False},
                            {"text": "4", "isCorrect": True},
                            {"text": "5", "isCorrect": False}
                        ]
                    }
                }
            ]
        }
        
        # Write to JS file
        js_content = f"var courseData = {json.dumps(course_data)};"
        js_file = tmpdir / "course_data.js"
        js_file.write_text(js_content)
        
        # Create ZIP
        zip_path = tmpdir / "test_course.zip"
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.write(js_file, arcname="course_data.js")
        
        # Copy to current directory
        import shutil
        output_zip = Path("test_course.zip")
        shutil.copy(zip_path, output_zip)
        
        print(f"✅ Created: {output_zip}")
        return str(output_zip)


def upload_package(zip_file: str) -> str:
    """Upload and analyze package."""
    print(f"\n📤 Uploading {zip_file}...")
    
    try:
        with open(zip_file, "rb") as f:
            response = requests.post(
                f"{BASE_URL}/analyze",
                files={"file": f},
                timeout=30
            )
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        print("   ⚠️  Make sure server is running: ./run_dev.ps1")
        return None
    
    if response.status_code != 200:
        print(f"❌ Upload failed: {response.status_code}")
        print(response.text)
        return None
    
    data = response.json()
    job_id = data["job_id"]
    print(f"✅ Job created: {job_id}")
    
    return job_id


def poll_status(job_id: str) -> dict:
    """Poll until completion."""
    print(f"\n⏳ Polling status (max 30s)...")
    
    for attempt in range(60):
        try:
            response = requests.get(f"{BASE_URL}/jobs/{job_id}", timeout=10)
        except Exception as e:
            print(f"❌ Poll failed: {e}")
            return None
        
        if response.status_code != 200:
            print(f"❌ Status check failed: {response.status_code}")
            return None
        
        data = response.json()
        status = data["status"]
        progress = data["progress"]
        
        print(f"  Attempt {attempt+1}: {status} ({progress*100:.0f}%)", end="\r")
        
        if status in ("analyzed", "failed"):
            print()  # New line
            return data
        
        time.sleep(0.5)
    
    print("\n⏱️  Timeout!")
    return None


def commit_import(job_id: str) -> dict:
    """Commit the import."""
    print(f"\n💾 Committing import...")
    
    try:
        response = requests.post(f"{BASE_URL}/jobs/{job_id}/commit", timeout=10)
    except Exception as e:
        print(f"❌ Commit failed: {e}")
        return None
    
    if response.status_code != 200:
        print(f"❌ Commit failed: {response.status_code}")
        print(response.text)
        return None
    
    data = response.json()
    print(f"✅ {data['message']}")
    
    return data


def main():
    print("=" * 70)
    print("SCORM Import System - Quick Test")
    print("=" * 70)
    
    # Step 1: Create test ZIP
    zip_file = create_test_zip()
    if not zip_file:
        return False
    
    # Step 2: Upload
    job_id = upload_package(zip_file)
    if not job_id:
        return False
    
    # Step 3: Poll
    result = poll_status(job_id)
    if not result:
        return False
    
    # Display results
    print(f"\n📊 Analysis Results:")
    print(f"   Status: {result['status']}")
    print(f"   Progress: {result['progress']*100:.0f}%")
    
    if result.get("course_data"):
        course_data = result["course_data"]
        templates = course_data.get("templates", [])
        print(f"\n📋 Course Data:")
        print(f"   Course ID: {course_data.get('courseId')}")
        print(f"   Title: {course_data.get('title')}")
        print(f"   Templates: {len(templates)}")
        
        for tmpl in templates:
            print(f"      • {tmpl['order']}: {tmpl.get('type', 'unknown')} - {tmpl.get('title', 'Untitled')}")
        
        assets = course_data.get("assets", {})
        print(f"\n📦 Assets:")
        print(f"   Total: {assets.get('total', 0)}")
        print(f"   Ambiguous: {assets.get('ambiguous', 0)}")
    
    # Step 4: Commit
    if result["status"] == "analyzed":
        commit_result = commit_import(job_id)
        if not commit_result:
            return False
        
        print(f"\n✅ Final Status:")
        print(f"   Job ID: {commit_result['job_id']}")
        print(f"   Status: {commit_result['status']}")
        print(f"   Course ID: {commit_result.get('course_id')}")
    
    print("\n" + "=" * 70)
    print("✅ All tests passed!")
    print("=" * 70)
    print("\nNext steps:")
    print("  1. Check database: sqlite3 data/elearning.db \"SELECT * FROM import_jobs LIMIT 1;\"")
    print("  2. View in Swagger: http://localhost:8000/docs")
    print("  3. Read: TESTING_PHASE_1C_AND_2.md")
    
    return True


if __name__ == "__main__":
    import sys
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⏸️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
