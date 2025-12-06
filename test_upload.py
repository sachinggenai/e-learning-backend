import requests
import sys
import logging

logging.basicConfig(level=logging.DEBUG)

# Upload file
file_path = r"D:\projects\elearning_project\e-learning-backend\sample_course\RuntimeMinimumCalls_SCORM12.zip"

print(f"File exists: {__import__('os').path.exists(file_path)}")
print(f"File size: {__import__('os').path.getsize(file_path)} bytes")

with open(file_path, 'rb') as f:
    files = {'file': f}
    try:
        print("Sending request...")
        response = requests.post(
            "http://127.0.0.1:8000/api/v1/imports/analyze",
            files=files,
            timeout=60
        )
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        if response.status_code == 200:
            print(f"JSON: {response.json()}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
