#!/usr/bin/env python3
"""Debug Phase 1 parsing"""

import tempfile
import zipfile
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from app.services.heuristic_parser import HeuristicParser

# Create test ZIP
tmpdir = Path(tempfile.mkdtemp())
print(f"Working dir: {tmpdir}\n")

course_data = {
    "courseId": "golf-training-001",
    "title": "Golf Training",
    "templates": [{"id": "1", "type": "welcome", "data": {"content": "test"}}]
}

course_data_js = f"""var courseData = {json.dumps(course_data, indent=2)};
"""

(tmpdir / "course_data.js").write_text(course_data_js)
(tmpdir / "imsmanifest.xml").write_text("<manifest></manifest>")

# Create ZIP
zip_path = tmpdir / "test.zip"
with zipfile.ZipFile(zip_path, 'w') as z:
    z.write(tmpdir / "course_data.js", "course_data.js")
    z.write(tmpdir / "imsmanifest.xml", "imsmanifest.xml")

print("ZIP created with files:")
with zipfile.ZipFile(zip_path, 'r') as z:
    for info in z.filelist:
        print(f"  - {info.filename} ({info.file_size} bytes)")

# Extract like the import service does
print("\nExtracting ZIP contents...")
zip_contents = {}
with zipfile.ZipFile(zip_path, 'r') as z:
    for file_info in z.filelist:
        if not file_info.is_dir():
            zip_contents[file_info.filename] = z.read(file_info.filename)
            print(f"  ✓ {file_info.filename}")

# Try parsing
print("\nTesting HeuristicParser...")
parser = HeuristicParser()

for file_path, content in zip_contents.items():
    print(f"\n  File: {file_path}")
    if file_path.endswith((".js", ".json")):
        try:
            text = content.decode("utf-8", errors="ignore")
            print(f"    Content length: {len(text)} chars")
            print(f"    Content preview: {text[:200]}...")
            
            payloads = parser.extract_json_from_js(text)
            print(f"    ✓ Payloads found: {len(payloads)}")
            
            for i, payload in enumerate(payloads):
                if isinstance(payload, dict):
                    print(f"      [{i}] Dict with keys: {list(payload.keys())}")
                else:
                    print(f"      [{i}] {type(payload)}")
        except Exception as e:
            print(f"    ✗ Error: {e}")

print("\nDone!")
