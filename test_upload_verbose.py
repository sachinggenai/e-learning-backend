import requests
import sys
import time

# Upload file
file_path = r"D:\projects\elearning_project\e-learning-backend\sample_course\RuntimeMinimumCalls_SCORM12.zip"

print(f"File exists: {__import__('os').path.exists(file_path)}")
print(f"File size: {__import__('os').path.getsize(file_path)} bytes\n")

try:
    print("[1] Opening file...")
    with open(file_path, 'rb') as f:
        data = f.read()
        print(f"[2] Read {len(data)} bytes\n")
        
        print(f"[3] Preparing request...")
        headers = {}
        files = {'file': ('RuntimeMinimumCalls_SCORM12.zip', data)}
        
        print(f"[4] Sending POST to http://127.0.0.1:8000/api/v1/imports/analyze")
        start = time.time()
        response = requests.post(
            "http://127.0.0.1:8000/api/v1/imports/analyze",
            files=files,
            timeout=60
        )
        elapsed = time.time() - start
        print(f"[5] Got response in {elapsed:.2f}s")
        
        print(f"\nStatus Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        print(f"Response Body (first 500 chars):\n{response.text[:500]}")
        
        if response.status_code in [200, 201, 202]:
            try:
                data = response.json()
                print(f"\nJSON Response:\n{data}")
            except:
                print(f"\nCouldn't parse JSON")
                
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
