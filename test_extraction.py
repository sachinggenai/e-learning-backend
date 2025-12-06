#!/usr/bin/env python3
"""Direct test of _extract_zip and _discover_payloads"""

import asyncio
import sys
import json
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.services.import_service import ImportService
from app.db.config import SessionLocal


async def test_extraction():
    """Test the extraction and discovery pipeline"""
    
    print("Creating test SCORM package...")
    tmpdir = Path(tempfile.mkdtemp())
    
    course_data = {
        "courseId": "test-001",
        "title": "Test Course",
        "templates": [
            {"id": "1", "type": "welcome", "order": 0, "title": "Welcome", "data": {"content": "test"}}
        ]
    }
    
    course_data_js = f"""var courseData = {json.dumps(course_data, indent=2)};
"""
    
    (tmpdir / "course_data.js").write_text(course_data_js)
    (tmpdir / "imsmanifest.xml").write_text("<manifest></manifest>")
    
    # Create ZIP
    zip_path = tmpdir / "test.zip"
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(tmpdir / "course_data.js", "course_data.js")
        z.write(tmpdir / "imsmanifest.xml", "imsmanifest.xml")
    
    zip_data = zip_path.read_bytes()
    print(f"✓ Created ZIP: {len(zip_data)} bytes\n")
    
    # Now test the import service
    async with SessionLocal() as db_session:
        service = ImportService(db_session)
        
        print("Step 1: Extract ZIP...")
        import tempfile as tmp
        with tmp.TemporaryDirectory() as tmpdir2:
            zip_path2 = Path(tmpdir2) / "test.zip"
            zip_path2.write_bytes(zip_data)
            zip_contents = service._extract_zip(zip_path2)
        
        print(f"✓ Extracted {len(zip_contents)} files:")
        for file_path, content in zip_contents.items():
            print(f"  - {file_path}: {len(content)} bytes")
        
        print("\nStep 2: Discover payloads...")
        payloads = await service._discover_payloads(zip_contents)
        
        print(f"✓ Found {len(payloads)} payload(s)")
        for i, payload in enumerate(payloads):
            if isinstance(payload, dict):
                print(f"  [{i}] Dict: {list(payload.keys())}")
            else:
                print(f"  [{i}] {type(payload).__name__}")


if __name__ == "__main__":
    asyncio.run(test_extraction())
